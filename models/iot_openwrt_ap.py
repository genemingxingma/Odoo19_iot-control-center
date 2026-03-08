import json
import uuid
from urllib import error as urlerror
from urllib import request as urlrequest

from odoo import _, api, fields, models
from odoo.exceptions import UserError


class IoTOpenwrtAP(models.Model):
    _name = "iot.openwrt.ap"
    _description = "OpenWrt Access Point"
    _inherit = ["mail.thread"]

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

    def action_upgrade_firmware(self):
        base_url = (self.env["ir.config_parameter"].sudo().get_param("web.base.url") or "").strip().rstrip("/")
        if not base_url:
            raise UserError(_("web.base.url is empty."))
        for rec in self:
            firmware = rec.upgrade_firmware_id
            if not firmware:
                raise UserError(_("Please select a firmware package first."))
            if rec.model and firmware.model_pattern and firmware.model_pattern.lower() not in rec.model.lower():
                raise UserError(_("Selected firmware does not match the AP model."))
            payload = rec._base_payload()
            payload["firmware_url"] = f"{base_url}/iot_control_center/openwrt/firmware/{firmware.id}/download"
            payload["filename"] = firmware.filename
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
