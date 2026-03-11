import logging
import secrets
from datetime import datetime

import pytz

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class IoTAttendanceDevice(models.Model):
    _name = "iot.attendance.device"
    _description = "IoT Attendance Device"
    _inherit = ["mail.thread", "mail.activity.mixin"]
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
    timezone = fields.Selection(selection=lambda self: [(tz, tz) for tz in pytz.common_timezones], default=lambda self: self.env.user.tz or "UTC", required=True)
    punch_direction_mode = fields.Selection([("device", "Use Device Direction"), ("auto", "Auto Alternate In/Out")], default="device", required=True)
    auto_clear_after_sync = fields.Boolean(string="Clear Device Logs After Sync")
    sync_enabled = fields.Boolean(default=True, tracking=True)
    webhook_token = fields.Char(copy=False, default=lambda self: secrets.token_urlsafe(24))
    webhook_url = fields.Char(compute="_compute_urls")
    adms_http_url = fields.Char(compute="_compute_urls")
    adms_https_url = fields.Char(compute="_compute_urls")
    adms_last_seen_at = fields.Datetime(readonly=True, copy=False)
    adms_last_payload = fields.Text(readonly=True, copy=False)
    last_sync_at = fields.Datetime(readonly=True, copy=False)
    last_sync_message = fields.Char(readonly=True, copy=False)
    user_mapping_ids = fields.One2many("iot.attendance.user", "device_id", string="Employee Mapping")
    punch_ids = fields.One2many("iot.attendance.punch", "device_id", string="Punches")
    request_ids = fields.One2many("iot.attendance.request", "device_id", string="Request Logs")
    punch_count = fields.Integer(compute="_compute_counts")
    user_count = fields.Integer(compute="_compute_counts")
    request_count = fields.Integer(compute="_compute_counts")

    _sql_constraints = [
        ("iot_attendance_device_serial_unique", "unique(serial_number)", "Serial number must be unique."),
    ]

    def _get_base_url(self):
        self.ensure_one()
        return self.env["ir.config_parameter"].sudo().get_param("web.base.url", "")

    @api.depends("webhook_token", "serial_number", "protocol")
    def _compute_urls(self):
        for rec in self:
            base_url = rec._get_base_url().rstrip("/")
            if not base_url:
                rec.webhook_url = False
                rec.adms_http_url = False
                rec.adms_https_url = False
                continue
            host_part = base_url.split("://", 1)[1] if "://" in base_url else base_url
            rec.webhook_url = f"{base_url}/iot_attendance/push/{rec.id}" if rec.id else False
            rec.adms_http_url = f"http://{host_part}/iclock/"
            rec.adms_https_url = f"https://{host_part}/iclock/"

    @api.depends("punch_ids", "user_mapping_ids", "request_ids")
    def _compute_counts(self):
        punch_counts = self.env["iot.attendance.punch"].read_group([("device_id", "in", self.ids)], ["device_id"], ["device_id"])
        user_counts = self.env["iot.attendance.user"].read_group([("device_id", "in", self.ids)], ["device_id"], ["device_id"])
        request_counts = self.env["iot.attendance.request"].read_group([("device_id", "in", self.ids)], ["device_id"], ["device_id"])
        punch_map = {item["device_id"][0]: item["device_id_count"] for item in punch_counts}
        user_map = {item["device_id"][0]: item["device_id_count"] for item in user_counts}
        req_map = {item["device_id"][0]: item["device_id_count"] for item in request_counts}
        for rec in self:
            rec.punch_count = punch_map.get(rec.id, 0)
            rec.user_count = user_map.get(rec.id, 0)
            rec.request_count = req_map.get(rec.id, 0)

    def action_generate_token(self):
        for rec in self:
            rec.webhook_token = secrets.token_urlsafe(24)

    def action_test_connection(self):
        self.ensure_one()
        if self.protocol == "adms_http":
            raise UserError(_("ADMS devices do not support pull-based connection tests. Point the device to the ADMS URL instead."))
        if self.protocol == "http_push":
            raise UserError(_("Webhook devices do not require a live socket connection test."))
        imported = self._fetch_zk_punches(limit=1)
        message = _("Connection successful. Sample records fetched: %s") % len(imported)
        self.write({"last_sync_message": message})
        return {"type": "ir.actions.client", "tag": "display_notification", "params": {"title": _("Connection test"), "message": message, "type": "success"}}

    def action_sync_now(self):
        self.ensure_one()
        created = self._sync_device()
        return {"type": "ir.actions.client", "tag": "display_notification", "params": {"title": _("Synchronization complete"), "message": _("Imported %s punch(es).", created), "type": "success"}}

    def _validate_webhook_token(self, token):
        self.ensure_one()
        return bool(self.webhook_token) and secrets.compare_digest((token or "").strip(), self.webhook_token.strip())

    def _normalize_direction(self, raw_direction, raw_status):
        self.ensure_one()
        mapping = {"0": "in", "1": "out", "2": "out", "3": "in", "4": "in", "5": "out", "in": "in", "check_in": "in", "out": "out", "check_out": "out"}
        normalized = mapping.get(str(raw_direction).lower()) if raw_direction is not None else None
        if not normalized and raw_status is not None:
            normalized = mapping.get(str(raw_status).lower())
        if not normalized or self.punch_direction_mode == "auto":
            return "auto"
        return normalized

    def _parse_device_datetime(self, value):
        self.ensure_one()
        if isinstance(value, datetime):
            local_dt = value
        elif isinstance(value, str):
            local_dt = fields.Datetime.to_datetime(value.strip().replace("T", " "))
        else:
            raise UserError(_("Unsupported punch timestamp: %s") % value)
        if not local_dt:
            raise UserError(_("Unable to parse punch timestamp."))
        if local_dt.tzinfo:
            return local_dt.astimezone(pytz.UTC).replace(tzinfo=None)
        tz = pytz.timezone(self.timezone or "UTC")
        return tz.localize(local_dt).astimezone(pytz.UTC).replace(tzinfo=None)

    def _resolve_employee(self, device_user_id, device_uid=None):
        self.ensure_one()
        device_user_id = (device_user_id or "").strip()
        device_uid = (device_uid or "").strip()
        if device_user_id:
            mapping = self.env["iot.attendance.user"].search([("device_id", "=", self.id), ("device_user_id", "=", device_user_id)], limit=1)
            if mapping:
                return mapping.employee_id
        if device_uid:
            mapping = self.env["iot.attendance.user"].search([("device_id", "=", self.id), ("device_uid", "=", device_uid)], limit=1)
            if mapping:
                return mapping.employee_id
        if device_user_id:
            employee = self.env["hr.employee"].search([("biometric_code", "=", device_user_id)], limit=1)
            if employee:
                return employee
            employee = self.env["hr.employee"].search([("barcode", "=", device_user_id)], limit=1)
            if employee:
                return employee
        return self.env["hr.employee"]

    def _prepare_punch_vals(self, payload, source):
        self.ensure_one()
        device_user_id = str(payload.get("device_user_id") or payload.get("user_id") or payload.get("pin") or payload.get("badge_id") or "").strip()
        device_uid = str(payload.get("device_uid") or payload.get("uid") or "").strip()
        if not device_user_id:
            raise UserError(_("Missing device user ID in payload %s") % payload)
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
            "raw_payload": payload,
        }

    def ingest_webhook_payload(self, punches):
        self.ensure_one()
        Punch = self.env["iot.attendance.punch"].sudo()
        created = 0
        for payload in punches:
            vals = self._prepare_punch_vals(payload, "webhook")
            vals["unique_hash"] = Punch._build_unique_hash(vals)
            if Punch.search_count([("unique_hash", "=", vals["unique_hash"])]):
                continue
            Punch.create(vals)
            created += 1
        self.write({"last_sync_at": fields.Datetime.now(), "last_sync_message": _("Webhook imported %s punch(es).") % created})
        return created

    @api.model
    def _find_adms_device(self, serial_number, remote_ip=None):
        serial_number = (serial_number or "").strip()
        domain = [("protocol", "=", "adms_http")]
        if serial_number:
            device = self.search(domain + [("serial_number", "=", serial_number)], limit=1)
            if device:
                return device
        if remote_ip:
            device = self.search(domain + [("host", "=", remote_ip)], limit=1)
            if device:
                return device
        devices = self.search(domain + [("active", "=", True), ("sync_enabled", "=", True)], limit=2)
        if len(devices) == 1:
            return devices
        return self.env["iot.attendance.device"]

    def ingest_adms_payload(self, payload_text, table=None, serial_number=None, remote_ip=None, query_params=None):
        self.ensure_one()
        Punch = self.env["iot.attendance.punch"].sudo()
        created = 0
        lines = [line.strip() for line in (payload_text or "").replace("\r", "\n").split("\n") if line.strip()]
        normalized_table = (table or "").upper()
        for line in lines:
            parsed = self._parse_adms_line(line, normalized_table)
            if not parsed:
                continue
            vals = self._prepare_punch_vals(parsed, "adms")
            vals["unique_hash"] = Punch._build_unique_hash(vals)
            if Punch.search_count([("unique_hash", "=", vals["unique_hash"])]):
                continue
            Punch.create(vals)
            created += 1
        self.write({"adms_last_seen_at": fields.Datetime.now(), "adms_last_payload": (payload_text or "")[:10000], "last_sync_message": _("ADMS received %s punch(es).") % created})
        return created

    def _parse_adms_line(self, line, table_name):
        self.ensure_one()
        parts = [part for part in line.split("\t") if part]
        kv = {}
        for part in parts:
            if "=" in part:
                key, value = part.split("=", 1)
                kv[key.strip()] = value.strip()
        if kv:
            device_user_id = kv.get("PIN") or kv.get("UserID") or kv.get("EnrollNumber")
            timestamp = kv.get("DateTime") or kv.get("time") or kv.get("Time_second")
            status = kv.get("Status") or kv.get("status")
            verify = kv.get("Verify") or kv.get("verify")
            if device_user_id and timestamp:
                return {"device_user_id": device_user_id, "timestamp": timestamp, "status": status, "direction": verify, "raw_line": line}
        if table_name == "ATTLOG" and len(parts) >= 2:
            return {
                "device_user_id": parts[0].strip(),
                "timestamp": parts[1].strip(),
                "status": parts[2].strip() if len(parts) > 2 else None,
                "direction": parts[3].strip() if len(parts) > 3 else None,
                "raw_line": line,
            }
        return None

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
                        "direction": getattr(record, "punch", None),
                    }
                )
            if self.auto_clear_after_sync and payloads and not limit:
                conn.clear_attendance()
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
        Punch = self.env["iot.attendance.punch"].sudo()
        created = 0
        for payload in self._fetch_zk_punches():
            vals = self._prepare_punch_vals(payload, "device_pull")
            vals["unique_hash"] = Punch._build_unique_hash(vals)
            if Punch.search_count([("unique_hash", "=", vals["unique_hash"])]):
                continue
            Punch.create(vals)
            created += 1
        self.write({"last_sync_at": fields.Datetime.now(), "last_sync_message": _("Imported %s punch(es).") % created})
        return created

    @api.model
    def cron_reprocess_pending_punches(self):
        self.env["iot.attendance.punch"].sudo().cron_reprocess_pending()
