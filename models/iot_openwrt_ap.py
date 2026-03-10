import json
import uuid
from html import escape
from urllib import error as urlerror
from urllib import request as urlrequest

from odoo import _, api, fields, models
from odoo.exceptions import UserError


class IoTOpenwrtAP(models.Model):
    _name = "iot.openwrt.ap"
    _description = "OpenWrt Access Point"
    _inherit = ["mail.thread"]

    _LIVE_TELEMETRY_FIELDS = {
        "client_count_total",
        "client_count_24g",
        "client_count_5g",
        "upload_rate_mbps",
        "download_rate_mbps",
        "upload_bytes_total",
        "download_bytes_total",
        "upload_rate_display",
        "download_rate_display",
        "upload_total_display",
        "download_total_display",
        "live_clients_html",
    }

    name = fields.Char(required=True, tracking=True)
    active = fields.Boolean(default=True)
    host = fields.Char(required=True, tracking=True)
    ssh_port = fields.Integer(default=22, required=True, tracking=True)
    ssh_user = fields.Char(default="root", required=True, tracking=True)
    auth_token = fields.Char(required=True, default=lambda self: uuid.uuid4().hex)

    company_id = fields.Many2one("res.company", index=True, tracking=True)
    department_id = fields.Many2one(
        "hr.department",
        domain="['|', ('company_id', '=', False), ('company_id', '=', company_id)]",
        tracking=True,
    )
    location_id = fields.Many2one(
        "stock.location",
        domain="['|', ('company_id', '=', False), ('company_id', '=', company_id)]",
        tracking=True,
    )
    location_detail = fields.Char(translate=True, tracking=True)

    template_id = fields.Many2one("iot.openwrt.template", tracking=True)
    upgrade_firmware_id = fields.Many2one("iot.openwrt.firmware", string="Upgrade Firmware")

    board_name = fields.Char(readonly=True, tracking=True)
    model = fields.Char(readonly=True, tracking=True)
    target = fields.Char(readonly=True, tracking=True)
    openwrt_version = fields.Char(readonly=True, tracking=True)
    current_hostname = fields.Char(readonly=True, tracking=True)
    client_count_total = fields.Integer(readonly=True, compute="_compute_live_telemetry", store=False)
    client_count_24g = fields.Integer(string="2.4G Clients", readonly=True, compute="_compute_live_telemetry", store=False)
    client_count_5g = fields.Integer(string="5G Clients", readonly=True, compute="_compute_live_telemetry", store=False)
    upload_rate_mbps = fields.Float(string="Upload Rate (Mbps)", readonly=True, digits=(16, 2), compute="_compute_live_telemetry", store=False)
    download_rate_mbps = fields.Float(string="Download Rate (Mbps)", readonly=True, digits=(16, 2), compute="_compute_live_telemetry", store=False)
    upload_bytes_total = fields.Float(string="Uploaded Bytes", readonly=True, digits=(16, 0), compute="_compute_live_telemetry", store=False)
    download_bytes_total = fields.Float(string="Downloaded Bytes", readonly=True, digits=(16, 0), compute="_compute_live_telemetry", store=False)
    upload_rate_display = fields.Char(string="Upload", readonly=True, compute="_compute_live_telemetry", store=False)
    download_rate_display = fields.Char(string="Download", readonly=True, compute="_compute_live_telemetry", store=False)
    upload_total_display = fields.Char(string="Uploaded", readonly=True, compute="_compute_live_telemetry", store=False)
    download_total_display = fields.Char(string="Downloaded", readonly=True, compute="_compute_live_telemetry", store=False)
    live_clients_html = fields.Html(string="Connected Clients", readonly=True, sanitize=False, compute="_compute_live_telemetry", store=False)

    status = fields.Selection(
        [
            ("unknown", "Unknown"),
            ("online", "Online"),
            ("offline", "Offline"),
            ("error", "Error"),
        ],
        default="unknown",
        tracking=True,
    )
    last_seen = fields.Datetime(readonly=True, tracking=True)
    last_probe_at = fields.Datetime(readonly=True, tracking=True)
    last_apply_at = fields.Datetime(readonly=True, tracking=True)
    last_upgrade_at = fields.Datetime(readonly=True, tracking=True)
    last_locate_at = fields.Datetime(readonly=True, tracking=True)
    locate_until = fields.Datetime(readonly=True, tracking=True)
    locate_active = fields.Boolean(readonly=True, tracking=True)
    last_error = fields.Text(readonly=True)
    online = fields.Boolean(compute="_compute_online", store=False)

    job_ids = fields.One2many("iot.openwrt.job", "ap_id")
    job_count = fields.Integer(compute="_compute_job_count")

    _sql_constraints = [
        ("iot_openwrt_ap_host_port_uniq", "unique(host, ssh_port)", "AP host + SSH port must be unique."),
    ]

    @api.depends("last_seen")
    def _compute_online(self):
        timeout = int(self.env["ir.config_parameter"].sudo().get_param("iot_control_center.openwrt_online_timeout_sec", 300))
        now = fields.Datetime.now()
        for rec in self:
            rec.online = bool(rec.last_seen and (now - rec.last_seen).total_seconds() <= timeout)

    @api.depends("job_ids")
    def _compute_job_count(self):
        for rec in self:
            rec.job_count = len(rec.job_ids)

    def _compute_live_telemetry(self):
        cache = self.env.context.get("iot_openwrt_live_cache") if isinstance(self.env.context.get("iot_openwrt_live_cache"), dict) else {}
        for rec in self:
            data = cache.get(rec.id) or {}
            rec.client_count_total = int(data.get("client_count_total") or 0)
            rec.client_count_24g = int(data.get("client_count_24g") or 0)
            rec.client_count_5g = int(data.get("client_count_5g") or 0)
            rec.upload_rate_mbps = float(data.get("upload_rate_mbps") or 0.0)
            rec.download_rate_mbps = float(data.get("download_rate_mbps") or 0.0)
            rec.upload_bytes_total = float(data.get("upload_bytes_total") or 0.0)
            rec.download_bytes_total = float(data.get("download_bytes_total") or 0.0)
            rec.upload_rate_display = data.get("upload_rate_display") or self._fmt_rate(0.0)
            rec.download_rate_display = data.get("download_rate_display") or self._fmt_rate(0.0)
            rec.upload_total_display = data.get("upload_total_display") or self._fmt_total(0.0)
            rec.download_total_display = data.get("download_total_display") or self._fmt_total(0.0)
            rec.live_clients_html = data.get("live_clients_html") or self._empty_clients_html()

    def _middleware_base_url(self):
        base_url = (self.env["ir.config_parameter"].sudo().get_param("iot_control_center.middleware_base_url") or "").strip().rstrip("/")
        if not base_url:
            raise UserError(_("Middleware Base URL is empty."))
        return base_url

    def _middleware_token(self):
        return (self.env["ir.config_parameter"].sudo().get_param("iot_control_center.middleware_token") or "").strip()

    def _middleware_private_key_path(self):
        return (self.env["ir.config_parameter"].sudo().get_param("iot_control_center.openwrt_ssh_private_key_path") or "").strip()

    def _call_middleware(self, endpoint, payload):
        headers = {"Content-Type": "application/json"}
        token = self._middleware_token()
        if token:
            headers["X-IoT-Middleware-Token"] = token
        req = urlrequest.Request(
            f"{self._middleware_base_url()}{endpoint}",
            data=json.dumps(payload, separators=(",", ":")).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        try:
            with urlrequest.urlopen(req, timeout=60) as resp:
                body = resp.read().decode("utf-8")
                return json.loads(body or "{}")
        except urlerror.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="ignore")
            raise UserError(_("Middleware HTTP error: %s") % (detail or exc.reason))
        except urlerror.URLError as exc:
            raise UserError(_("Middleware connection failed: %s") % exc.reason)

    def _base_payload(self):
        self.ensure_one()
        return {
            "host": (self.host or "").strip(),
            "port": int(self.ssh_port or 22),
            "username": (self.ssh_user or "").strip() or "root",
            "key_path": self._middleware_private_key_path() or None,
        }

    def _create_job(self, job_type, payload):
        self.ensure_one()
        return self.env["iot.openwrt.job"].create(
            {
                "name": f"{self.name} - {job_type}",
                "ap_id": self.id,
                "job_type": job_type,
                "request_payload": json.dumps(payload, ensure_ascii=False, indent=2),
            }
        )

    def _write_job_result(self, job, response, success=True, note=None):
        job.write(
            {
                "state": "success" if success else "failed",
                "completed_at": fields.Datetime.now(),
                "response_payload": json.dumps(response, ensure_ascii=False, indent=2),
                "note": note or "",
            }
        )

    def _extract_live_telemetry(self, response):
        summary = response.get("summary") or {}
        clients = response.get("clients") or []
        upload_rate = float(summary.get("upload_rate_mbps") or 0.0)
        download_rate = float(summary.get("download_rate_mbps") or 0.0)
        upload_total = float(summary.get("upload_bytes_total") or 0.0)
        download_total = float(summary.get("download_bytes_total") or 0.0)
        return {
            "client_count_total": int(summary.get("client_count_total") or len(clients)),
            "client_count_24g": int(summary.get("client_count_24g") or 0),
            "client_count_5g": int(summary.get("client_count_5g") or 0),
            "upload_rate_mbps": upload_rate,
            "download_rate_mbps": download_rate,
            "upload_bytes_total": upload_total,
            "download_bytes_total": download_total,
            "upload_rate_display": self._fmt_rate(upload_rate),
            "download_rate_display": self._fmt_rate(download_rate),
            "upload_total_display": self._fmt_total(upload_total),
            "download_total_display": self._fmt_total(download_total),
            "live_clients_html": self._build_clients_html(clients),
        }

    def _get_live_telemetry_map(self, force=False):
        cache = self.env.context.get("iot_openwrt_live_cache") if not force else None
        if isinstance(cache, dict):
            return cache
        data_map = {}
        for rec in self:
            try:
                response = rec._call_middleware("/v1/openwrt/probe", rec._base_payload())
                facts = response.get("facts") or {}
                release = facts.get("release") or {}
                now = fields.Datetime.now()
                rec.sudo().write(
                    {
                        "board_name": facts.get("board_name") or False,
                        "model": facts.get("model") or False,
                        "target": facts.get("target") or False,
                        "openwrt_version": release.get("description") or release.get("version") or False,
                        "current_hostname": facts.get("hostname") or False,
                        "status": "online",
                        "last_seen": now,
                        "last_probe_at": now,
                        "last_error": False,
                    }
                )
                data_map[rec.id] = rec._extract_live_telemetry(response)
            except Exception as exc:
                now = fields.Datetime.now()
                rec.sudo().write({"status": "error", "last_error": str(exc), "last_probe_at": now})
                data_map[rec.id] = {
                    "client_count_total": 0,
                    "client_count_24g": 0,
                    "client_count_5g": 0,
                    "upload_rate_mbps": 0.0,
                    "download_rate_mbps": 0.0,
                    "upload_bytes_total": 0.0,
                    "download_bytes_total": 0.0,
                    "upload_rate_display": self._fmt_rate(0.0),
                    "download_rate_display": self._fmt_rate(0.0),
                    "upload_total_display": self._fmt_total(0.0),
                    "download_total_display": self._fmt_total(0.0),
                    "live_clients_html": self._error_clients_html(str(exc)),
                }
        return data_map

    def _inject_live_telemetry_into_rows(self, rows, field_names):
        if not rows:
            return rows
        requested = set(field_names or [])
        if field_names is None:
            requested = self._LIVE_TELEMETRY_FIELDS
        if not (requested & self._LIVE_TELEMETRY_FIELDS):
            return rows
        record_ids = [row.get("id") for row in rows if row.get("id")]
        data_map = self.browse(record_ids)._get_live_telemetry_map()
        for row in rows:
            data = data_map.get(row.get("id")) or {}
            for field_name in requested & self._LIVE_TELEMETRY_FIELDS:
                row[field_name] = data.get(field_name)
        return rows

    def _read_format(self, fnames=None, load='_classic_read'):
        rows = super()._read_format(fnames=fnames, load=load)
        return self._inject_live_telemetry_into_rows(rows, fnames)

    @api.model
    def search_read(self, domain=None, fields=None, offset=0, limit=None, order=None):
        rows = super().search_read(domain=domain, fields=fields, offset=offset, limit=limit, order=order)
        return self._inject_live_telemetry_into_rows(rows, fields)

    @api.model
    def web_search_read(self, domain=None, specification=None, offset=0, limit=None, order=None, count_limit=None):
        result = super().web_search_read(
            domain=domain,
            specification=specification,
            offset=offset,
            limit=limit,
            order=order,
            count_limit=count_limit,
        )
        requested = set((specification or {}).keys())
        self._inject_live_telemetry_into_rows(result.get("records") or [], requested)
        return result

    def _build_clients_html(self, clients):
        rows = []
        for item in clients:
            rows.append(
                "<tr>"
                f"<td>{escape(item.get('hostname') or '')}</td>"
                f"<td>{escape(item.get('ip') or '')}</td>"
                f"<td>{escape((item.get('mac') or '').upper())}</td>"
                f"<td>{escape(item.get('band') or '')}</td>"
                f"<td>{self._fmt_int(item.get('signal_dbm'))}</td>"
                f"<td>{self._fmt_rate(item.get('upload_rate_mbps'))}</td>"
                f"<td>{self._fmt_rate(item.get('download_rate_mbps'))}</td>"
                f"<td>{self._fmt_bytes(item.get('upload_bytes_total'))}</td>"
                f"<td>{self._fmt_bytes(item.get('download_bytes_total'))}</td>"
                f"<td>{self._fmt_duration(item.get('connected_seconds'))}</td>"
                "</tr>"
            )
        if not rows:
            return self._empty_clients_html()
        return (
            '<div class="o_iot_openwrt_clients_table">'
            '<table class="table table-sm table-hover">'
            "<thead><tr>"
            f"<th>{escape(_('Hostname'))}</th>"
            f"<th>{escape(_('IP'))}</th>"
            f"<th>{escape(_('MAC'))}</th>"
            f"<th>{escape(_('Band'))}</th>"
            f"<th>{escape(_('Signal'))}</th>"
            f"<th>{escape(_('Upload Rate'))}</th>"
            f"<th>{escape(_('Download Rate'))}</th>"
            f"<th>{escape(_('Uploaded'))}</th>"
            f"<th>{escape(_('Downloaded'))}</th>"
            f"<th>{escape(_('Connected'))}</th>"
            "</tr></thead>"
            f"<tbody>{''.join(rows)}</tbody>"
            "</table></div>"
        )

    def _empty_clients_html(self):
        return '<div class="text-muted">%s</div>' % escape(_("No connected clients."))

    def _error_clients_html(self, message):
        return '<div class="text-danger">%s</div>' % escape(message or _("Probe failed."))

    def _fmt_rate(self, value):
        return "%.1f Mbps" % float(value or 0.0)

    def _fmt_total(self, value):
        value = float(value or 0.0)
        tb = 1024.0 ** 4
        gb = 1024.0 ** 3
        if value >= tb:
            return "%.1f TB" % (value / tb)
        return "%.1f GB" % (value / gb if gb else 0.0)

    def _fmt_bytes(self, value):
        return self._fmt_total(value)

    def _fmt_duration(self, seconds):
        seconds = int(seconds or 0)
        hours, remainder = divmod(seconds, 3600)
        minutes, secs = divmod(remainder, 60)
        if hours:
            return "%02d:%02d:%02d" % (hours, minutes, secs)
        return "%02d:%02d" % (minutes, secs)

    def _fmt_int(self, value):
        if value in (None, False):
            return ""
        return str(int(value))

    def action_probe(self):
        for rec in self:
            payload = rec._base_payload()
            job = rec._create_job("probe", payload)
            try:
                response = rec._call_middleware("/v1/openwrt/probe", payload)
                facts = response.get("facts") or {}
                release = facts.get("release") or {}
                rec.write(
                    {
                        "board_name": facts.get("board_name") or False,
                        "model": facts.get("model") or False,
                        "target": facts.get("target") or False,
                        "openwrt_version": release.get("description") or release.get("version") or False,
                        "current_hostname": facts.get("hostname") or False,
                        "status": "online",
                        "last_seen": fields.Datetime.now(),
                        "last_probe_at": fields.Datetime.now(),
                        "last_error": False,
                    }
                )
                rec._write_job_result(job, response, success=True)
            except Exception as exc:
                rec.write({"status": "error", "last_error": str(exc), "last_probe_at": fields.Datetime.now()})
                rec._write_job_result(job, {"ok": False}, success=False, note=str(exc))
                raise
        return True

    def action_apply_template(self):
        for rec in self:
            if not rec.template_id:
                raise UserError(_("Please select a template first."))
            payload = rec._base_payload()
            payload["template"] = rec.template_id.to_middleware_payload()
            job = rec._create_job("apply_template", payload)
            try:
                response = rec._call_middleware("/v1/openwrt/apply_template", payload)
                rec.write(
                    {
                        "status": "online",
                        "last_seen": fields.Datetime.now(),
                        "last_apply_at": fields.Datetime.now(),
                        "last_error": False,
                    }
                )
                rec._write_job_result(job, response, success=True)
            except Exception as exc:
                rec.write({"status": "error", "last_error": str(exc)})
                rec._write_job_result(job, {"ok": False}, success=False, note=str(exc))
                raise
        return True

    def action_reboot(self):
        for rec in self:
            payload = rec._base_payload()
            job = rec._create_job("reboot", payload)
            try:
                response = rec._call_middleware("/v1/openwrt/reboot", payload)
                rec.write({"last_seen": fields.Datetime.now(), "status": "online", "last_error": False})
                rec._write_job_result(job, response, success=True)
            except Exception as exc:
                rec.write({"status": "error", "last_error": str(exc)})
                rec._write_job_result(job, {"ok": False}, success=False, note=str(exc))
                raise
        return True

    def action_start_locate(self):
        duration_sec = 300
        for rec in self:
            payload = rec._base_payload()
            payload.update({"enable": True, "duration_sec": duration_sec})
            job = rec._create_job("locate_start", payload)
            try:
                response = rec._call_middleware("/v1/openwrt/locate", payload)
                now = fields.Datetime.now()
                rec.write(
                    {
                        "status": "online",
                        "last_seen": now,
                        "last_locate_at": now,
                        "locate_until": fields.Datetime.add(now, seconds=duration_sec),
                        "locate_active": True,
                        "last_error": False,
                    }
                )
                rec._write_job_result(job, response, success=True)
            except Exception as exc:
                rec.write({"status": "error", "last_error": str(exc), "last_locate_at": fields.Datetime.now()})
                rec._write_job_result(job, {"ok": False}, success=False, note=str(exc))
                raise
        return True

    def action_stop_locate(self):
        for rec in self:
            payload = rec._base_payload()
            payload.update({"enable": False})
            job = rec._create_job("locate_stop", payload)
            try:
                response = rec._call_middleware("/v1/openwrt/locate", payload)
                rec.write(
                    {
                        "status": "online",
                        "last_seen": fields.Datetime.now(),
                        "last_locate_at": fields.Datetime.now(),
                        "locate_until": False,
                        "locate_active": False,
                        "last_error": False,
                    }
                )
                rec._write_job_result(job, response, success=True)
            except Exception as exc:
                rec.write({"status": "error", "last_error": str(exc), "last_locate_at": fields.Datetime.now()})
                rec._write_job_result(job, {"ok": False}, success=False, note=str(exc))
                raise
        return True

    def action_upgrade_firmware(self):
        for rec in self:
            firmware = rec.upgrade_firmware_id
            if not firmware:
                raise UserError(_("Please select a firmware package first."))
            if rec.model and firmware.model_pattern and firmware.model_pattern.lower() not in rec.model.lower():
                raise UserError(_("Selected firmware does not match the AP model."))
            payload = rec._base_payload()
            payload["firmware_id"] = firmware.id
            payload["filename"] = firmware.filename
            payload["checksum_sha256"] = firmware.checksum_sha256 or ""
            job = rec._create_job("upgrade", payload)
            try:
                response = rec._call_middleware("/v1/openwrt/upgrade", payload)
                rec.write(
                    {
                        "last_seen": fields.Datetime.now(),
                        "status": "online",
                        "last_upgrade_at": fields.Datetime.now(),
                        "last_error": False,
                    }
                )
                rec._write_job_result(job, response, success=True)
            except Exception as exc:
                rec.write({"status": "error", "last_error": str(exc)})
                rec._write_job_result(job, {"ok": False}, success=False, note=str(exc))
                raise
        return True

    def action_open_jobs(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("OpenWrt Jobs"),
            "res_model": "iot.openwrt.job",
            "view_mode": "list,form",
            "domain": [("ap_id", "=", self.id)],
        }
