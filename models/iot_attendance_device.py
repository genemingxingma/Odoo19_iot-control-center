import logging
import re
import secrets
from urllib.parse import urlsplit

import pytz

from odoo import _, api, fields, models
from odoo.exceptions import UserError

from ..core.attendance import first_value, normalize_direction, parse_adms_line, parse_timestamp

_logger = logging.getLogger(__name__)


class IoTAttendanceDevice(models.Model):
    _name = "iot.attendance.device"
    _description = "IoT Attendance Device"
    _inherit = ["mail.thread", "mail.activity.mixin", "iot.access.mixin"]
    _order = "name, id"

    name = fields.Char(required=True, tracking=True)
    active = fields.Boolean(default=True)
    company_id = fields.Many2one("res.company", required=True, default=lambda self: self.env.company, tracking=True, index=True)
    protocol = fields.Selection(
        [("zk_tcp", "ZKTeco TCP"), ("adms_http", "ZKTeco ADMS HTTP"), ("http_push", "HTTP Push")],
        required=True,
        default="adms_http",
        tracking=True,
    )
    host = fields.Char(tracking=True)
    port = fields.Integer(default=4370, tracking=True)
    password = fields.Char(help="Communication password for devices that require it.")
    serial_number = fields.Char(string="Serial Number", tracking=True, help="Device serial number used by ADMS/PUSH requests.")
    timezone = fields.Char(string="Company Timezone", compute="_compute_timezone", readonly=True)
    punch_direction_mode = fields.Selection([("device", "Use Device Direction"), ("auto", "Auto Alternate In/Out")], default="device", required=True)
    auto_clear_after_sync = fields.Boolean(string="Clear Device Logs After Sync")
    sync_enabled = fields.Boolean(default=True, tracking=True)
    webhook_token = fields.Char(copy=False, default=lambda self: secrets.token_urlsafe(24))
    webhook_url = fields.Char(string="Webhook URL", compute="_compute_urls")
    adms_http_url = fields.Char(string="ADMS HTTP URL", compute="_compute_urls")
    adms_https_url = fields.Char(string="ADMS HTTPS URL", compute="_compute_urls")
    adms_last_seen_at = fields.Datetime(string="ADMS Last Seen", readonly=True, copy=False)
    adms_last_payload = fields.Text(string="ADMS Last Payload", readonly=True, copy=False)
    last_sync_at = fields.Datetime(readonly=True, copy=False)
    last_sync_message = fields.Char(readonly=True, copy=False)
    display_last_sync_message = fields.Char(compute="_compute_sync_message", string="Last Sync Message")
    user_mapping_ids = fields.One2many("iot.attendance.user", "device_id", string="Employee Mapping")
    punch_ids = fields.One2many("iot.attendance.punch", "device_id", string="Punches")
    request_ids = fields.One2many("iot.attendance.request", "device_id", string="Request Logs")
    punch_count = fields.Integer(compute="_compute_counts")
    user_count = fields.Integer(compute="_compute_counts")
    request_count = fields.Integer(compute="_compute_counts")
    pending_count = fields.Integer(compute="_compute_counts", string="Needs Review")
    connection_state = fields.Selection([
        ("disabled", "Paused"), ("unknown", "No Contact Yet"),
        ("online", "Connected"), ("offline", "No Recent Contact")],
        compute="_compute_connection_state", string="Connection")

    @api.depends("last_sync_message")
    @api.depends_context("lang")
    def _compute_sync_message(self):
        for rec in self:
            message = rec.last_sync_message or ""
            match = re.fullmatch(r"ADMS received (\d+) punch\(es\)\.", message)
            if match:
                rec.display_last_sync_message = _("ADMS received %s punch(es).", int(match[1]))
                continue
            match = re.fullmatch(r"Webhook imported (\d+) punch\(es\)\.", message)
            if match:
                rec.display_last_sync_message = _("Webhook imported %s punch(es).", int(match[1]))
                continue
            match = re.fullmatch(r"Imported (\d+) punch\(es\)\.", message)
            if match:
                rec.display_last_sync_message = _("Imported %s punch(es).", int(match[1]))
                continue
            match = re.fullmatch(r"Connection successful\. Sample records fetched: (\d+)", message)
            rec.display_last_sync_message = (_("Connection successful. Sample records fetched: %s", int(match[1]))
                                            if match else message)

    @api.depends("active", "sync_enabled", "adms_last_seen_at", "last_sync_at", "protocol")
    def _compute_connection_state(self):
        now = fields.Datetime.now()
        for rec in self:
            last_seen = rec.adms_last_seen_at if rec.protocol == "adms_http" else rec.last_sync_at
            rec.connection_state = ("disabled" if not rec.active or not rec.sync_enabled else
                "unknown" if not last_seen else "online" if (now - last_seen).total_seconds() <= 600 else "offline")

    _serial_unique = models.Constraint(
        "UNIQUE(serial_number)",
        "Serial number must be unique.",
    )

    @api.depends("company_id.country_id", "company_id.partner_id.country_id", "company_id.partner_id.tz")
    def _compute_timezone(self):
        for rec in self:
            rec.timezone = (rec.company_id or rec.env.company).get_iot_timezone()

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            vals.pop("timezone", None)
        return super().create(vals_list)

    def write(self, vals):
        if "timezone" in vals:
            vals = dict(vals)
            vals.pop("timezone", None)
        return super().write(vals)

    def _get_base_url(self):
        self.ensure_one()
        internal_url = self.company_id.get_iot_internal_odoo_base_url()
        if internal_url:
            return internal_url
        return self.env["ir.config_parameter"].sudo().get_param("web.base.url", "")

    @api.depends("webhook_token", "serial_number", "protocol", "company_id.iot_prefer_internal_network",
                 "company_id.iot_internal_host", "company_id.iot_internal_odoo_port")
    def _compute_urls(self):
        for rec in self:
            base_url = rec._get_base_url().rstrip("/")
            if not base_url:
                rec.webhook_url = False
                rec.adms_http_url = False
                rec.adms_https_url = False
                continue
            parsed = urlsplit(base_url if "://" in base_url else f"http://{base_url}")
            host_part = parsed.hostname or ""
            if ":" in host_part:
                host_part = f"[{host_part}]"
            adms_port_raw = rec.env["ir.config_parameter"].sudo().get_param("iot_control_center.attendance_adms_port", 8069)
            try:
                adms_port = int(adms_port_raw)
            except (TypeError, ValueError):
                adms_port = 8069
            if not 1 <= adms_port <= 65535:
                adms_port = 8069
            rec.webhook_url = f"{base_url}/iot_attendance/push/{rec.id}" if rec.id else False
            rec.adms_http_url = base_url if parsed.scheme == "http" else f"http://{host_part}:{adms_port}"
            # Do not manufacture HTTPS on an HTTP-only Odoo port.
            rec.adms_https_url = base_url if parsed.scheme == "https" else False

    @api.depends("punch_ids", "punch_ids.state", "user_mapping_ids", "request_ids")
    def _compute_counts(self):
        punch_counts = self.env["iot.attendance.punch"].read_group([("device_id", "in", self.ids)], ["device_id"], ["device_id"])
        user_counts = self.env["iot.attendance.user"].read_group([("device_id", "in", self.ids)], ["device_id"], ["device_id"])
        request_counts = self.env["iot.attendance.request"].read_group([("device_id", "in", self.ids)], ["device_id"], ["device_id"])
        punch_map = {item["device_id"][0]: item["device_id_count"] for item in punch_counts}
        user_map = {item["device_id"][0]: item["device_id_count"] for item in user_counts}
        req_map = {item["device_id"][0]: item["device_id_count"] for item in request_counts}
        pending = self.env["iot.attendance.punch"].read_group(
            [("device_id", "in", self.ids), ("state", "in", ["new", "error"])], ["device_id"], ["device_id"])
        pending_map = {item["device_id"][0]: item["device_id_count"] for item in pending}
        for rec in self:
            rec.punch_count = punch_map.get(rec.id, 0)
            rec.user_count = user_map.get(rec.id, 0)
            rec.request_count = req_map.get(rec.id, 0)
            rec.pending_count = pending_map.get(rec.id, 0)

    def action_review_punches(self):
        self.ensure_one()
        self.check_access("read")
        action = self.env["ir.actions.actions"]._for_xml_id("iot_control_center.action_iot_attendance_punch")
        action["domain"] = [("device_id", "=", self.id), ("state", "in", ["new", "error"])]
        return action

    def action_generate_token(self):
        self._check_iot_access(manage=True)
        for rec in self:
            rec.webhook_token = secrets.token_urlsafe(24)

    def action_test_connection(self):
        self._check_iot_access(manage=True)
        self.ensure_one()
        if self.protocol == "adms_http":
            raise UserError(_("ADMS devices do not support pull-based connection tests. Point the device to the ADMS URL instead."))
        if self.protocol == "http_push":
            raise UserError(_("Webhook devices do not require a live socket connection test."))
        imported = self._fetch_zk_punches(limit=1)
        message = _("Connection successful. Sample records fetched: %s") % len(imported)
        self.write({"last_sync_message": "Connection successful. Sample records fetched: %s" % len(imported)})
        return {"type": "ir.actions.client", "tag": "display_notification", "params": {"title": _("Connection test"), "message": message, "type": "success"}}

    def action_sync_now(self):
        self._check_iot_access(manage=True)
        self.ensure_one()
        created = self._sync_device()
        return {"type": "ir.actions.client", "tag": "display_notification", "params": {"title": _("Synchronization complete"), "message": _("Imported %s punch(es).", created), "type": "success"}}

    def _validate_webhook_token(self, token):
        self.ensure_one()
        return bool(self.webhook_token) and secrets.compare_digest((token or "").strip(), self.webhook_token.strip())

    def _normalize_direction(self, raw_direction, raw_status):
        self.ensure_one()
        return normalize_direction(raw_direction, raw_status, self.punch_direction_mode)

    def _parse_device_datetime(self, value):
        self.ensure_one()
        try:
            local_dt = parse_timestamp(value)
        except (ValueError, TypeError) as exc:
            raise UserError(_("Invalid punch timestamp. Check the terminal date and time.")) from exc
        if local_dt.tzinfo:
            return local_dt.astimezone(pytz.UTC).replace(tzinfo=None)
        tz = pytz.timezone(self.company_id.get_iot_timezone())
        try:
            return tz.localize(local_dt, is_dst=None).astimezone(pytz.UTC).replace(tzinfo=None)
        except (pytz.AmbiguousTimeError, pytz.NonExistentTimeError) as exc:
            raise UserError(_("The punch time is ambiguous in the company timezone.")) from exc

    def _resolve_employee(self, device_user_id, device_uid=None):
        self.ensure_one()
        device_user_id = (device_user_id or "").strip()
        device_uid = (device_uid or "").strip()
        if device_user_id:
            mapping = self.env["iot.attendance.user"].search([("device_id", "=", self.id), ("device_user_id", "=", device_user_id)], limit=1)
            if mapping and mapping.employee_id.company_id == self.company_id:
                return mapping.employee_id
        if device_uid:
            mapping = self.env["iot.attendance.user"].search([("device_id", "=", self.id), ("device_uid", "=", device_uid)], limit=1)
            if mapping and mapping.employee_id.company_id == self.company_id:
                return mapping.employee_id
        if device_user_id:
            employee = self.env["hr.employee"].search([("company_id", "=", self.company_id.id), ("biometric_code", "=", device_user_id)], limit=2)
            if len(employee) == 1:
                return employee
            if employee:
                return self.env["hr.employee"]
            employee = self.env["hr.employee"].search([("company_id", "=", self.company_id.id), ("barcode", "=", device_user_id)], limit=2)
            if len(employee) == 1:
                return employee
        return self.env["hr.employee"]

    def _prepare_punch_vals(self, payload, source):
        self.ensure_one()
        if not isinstance(payload, dict):
            raise UserError(_("Each punch must be a record with a user ID and timestamp."))
        user_value = first_value(payload, "device_user_id", "user_id", "pin", "badge_id")
        device_user_id = str(user_value if user_value is not None else "").strip()
        device_uid = str(payload.get("device_uid") or payload.get("uid") or "").strip()
        if not device_user_id:
            raise UserError(_("Missing device user ID in attendance record."))
        employee = self._resolve_employee(device_user_id, device_uid=device_uid)
        mapping = self.env["iot.attendance.user"].search([("device_id", "=", self.id), ("device_user_id", "=", device_user_id)], limit=1)
        if mapping:
            mapping.last_seen_at = fields.Datetime.now()
        return {
            "device_id": self.id,
            "employee_id": employee.id or False,
            "device_user_id": device_user_id,
            "device_uid": device_uid or False,
            "punch_time": self._parse_device_datetime(payload.get("punch_time") or payload.get("timestamp") or payload.get("datetime")),
            "direction": self._normalize_direction(payload.get("direction"), payload.get("status")),
            "source": source,
            "raw_payload": False,
        }

    def _ingest_webhook_payload(self, punches):
        self.ensure_one()
        if not self.sync_enabled:
            raise UserError(_("Attendance synchronization is paused for this device."))
        if not isinstance(punches, list):
            raise UserError(_("Punches must be a list of records."))
        values = [self._prepare_punch_vals(payload, "webhook") for payload in punches]
        created = self._create_punch_batch(values)
        self.write({"last_sync_at": fields.Datetime.now(), "last_sync_message": "Webhook imported %s punch(es)." % created})
        return created

    def _create_punch_batch(self, values):
        Punch = self.env["iot.attendance.punch"].with_context(iot_attendance_ingest=True).sudo()
        new_values, seen = [], set()
        for vals in sorted(values, key=lambda item: item["punch_time"]):
            vals["unique_hash"] = Punch._build_unique_hash(vals)
            if vals["unique_hash"] not in seen and not Punch.search_count([("unique_hash", "=", vals["unique_hash"])]):
                new_values.append(vals)
                seen.add(vals["unique_hash"])
        if new_values:
            Punch.create(new_values)
        return len(new_values)

    @api.model
    def _find_adms_device(self, serial_number, remote_ip=None):
        serial_number = (serial_number or "").strip()
        domain = [("protocol", "=", "adms_http")]
        if serial_number:
            device = self.search(domain + [("serial_number", "=", serial_number)], limit=1)
            if device:
                return device
            # A conflicting serial must never fall back to a shared VPN/NAT IP.
            return self.env["iot.attendance.device"]
        if remote_ip:
            device = self.search(domain + [("host", "=", remote_ip), ("serial_number", "=", False)], limit=2)
            if len(device) == 1:
                return device
        return self.env["iot.attendance.device"]

    def _ingest_adms_payload(self, payload_text, table=None, serial_number=None, remote_ip=None, query_params=None):
        self.ensure_one()
        if not self.sync_enabled:
            raise UserError(_("Attendance synchronization is paused for this device."))
        values = []
        lines = [line.strip() for line in (payload_text or "").replace("\r", "\n").split("\n") if line.strip()]
        normalized_table = (table or "").upper()
        for line in lines:
            parsed = self._parse_adms_line(line, normalized_table)
            if not parsed:
                continue
            values.append(self._prepare_punch_vals(parsed, "adms"))
        created = self._create_punch_batch(values)
        self.write({"adms_last_seen_at": fields.Datetime.now(), "last_sync_at": fields.Datetime.now(),
                    "last_sync_message": "ADMS received %s punch(es)." % created})
        return created

    def _parse_adms_line(self, line, table_name):
        self.ensure_one()
        try:
            return parse_adms_line(line, table_name)
        except ValueError as exc:
            raise UserError(_("Invalid attendance row. Check the terminal upload format and clock.")) from exc

    def _fetch_zk_punches(self, limit=None):
        self.ensure_one()
        try:
            from zk import ZK
        except ImportError as exc:
            raise UserError(_("Missing Python dependency `pyzk`. Install it in the Odoo runtime first.")) from exc
        if not self.host:
            raise UserError(_("Host is required for ZKTeco devices."))
        zk = ZK(self.host, port=self.port or 4370, timeout=15, password=int(self.password or 0), force_udp=False, ommit_ping=True)
        conn = None
        try:
            conn = zk.connect()
            conn.disable_device()
            records = conn.get_attendance() or []
            if limit:
                records = records[:limit]
            payloads = []
            for record in records:
                payloads.append(
                    {
                        "device_user_id": getattr(record, "user_id", None),
                        "device_uid": getattr(record, "uid", None),
                        "punch_time": getattr(record, "timestamp", None),
                        "status": getattr(record, "status", None),
                        "direction": getattr(record, "punch", None) if getattr(record, "punch", None) is not None else "auto",
                    }
                )
            # Never erase the terminal before imported records are committed.
            # Device-side deletion is deliberately not part of synchronization.
            return payloads
        except Exception as exc:
            _logger.exception("Failed to sync IoT attendance device %s: %s", self.display_name, exc)
            raise UserError(_("Unable to read device logs: %s") % exc) from exc
        finally:
            if conn:
                try:
                    conn.enable_device()
                except Exception:
                    pass
                try:
                    conn.disconnect()
                except Exception:
                    pass

    def _sync_device(self):
        self.ensure_one()
        if self.protocol in ("adms_http", "http_push"):
            raise UserError(_("Push devices are passive. Point the device to the ADMS/Webhook URL instead."))
        if not self.sync_enabled:
            raise UserError(_("Attendance synchronization is paused for this device."))
        values = [self._prepare_punch_vals(payload, "device_pull") for payload in self._fetch_zk_punches()]
        created = self._create_punch_batch(values)
        self.write({"last_sync_at": fields.Datetime.now(), "last_sync_message": "Imported %s punch(es)." % created})
        return created

    @api.model
    def cron_reprocess_pending_punches(self):
        self.env["iot.attendance.punch"].sudo().cron_reprocess_pending()
