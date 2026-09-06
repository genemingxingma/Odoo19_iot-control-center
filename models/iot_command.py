"""Transactional command outbox; retries reuse one device-visible identity."""
import uuid
from datetime import timedelta, timezone

from odoo import SUPERUSER_ID, api, fields, models

class IoTCommand(models.Model):
    _name = "iot.command"
    _description = "IoT Command Delivery"
    _order = "id desc"

    device_id = fields.Many2one("iot.device", required=True, ondelete="restrict", index=True)
    company_id = fields.Many2one("res.company", index=True, readonly=True)
    command_id = fields.Char(required=True, default=lambda self: uuid.uuid4().hex, index=True)
    command = fields.Char(required=True)
    payload = fields.Json(required=True)
    state = fields.Selection([("queued", "Queued"), ("sent", "Sent"), ("confirmed", "Confirmed"),
                              ("expired", "Expired"), ("cancelled", "Cancelled")], default="queued", index=True)
    attempts = fields.Integer(default=0)
    expires_at = fields.Datetime(required=True)
    sent_at = fields.Datetime()
    _command_unique = models.Constraint("UNIQUE(command_id)", "Command identity must be unique.")

    @api.model
    def _enqueue(self, device, command, payload):
        now = fields.Datetime.now()
        # A newer intent supersedes pending intent of the same kind. In particular,
        # an OFF must never be followed by an old queued ON or delay_start.
        controls = ("relay", "delay_start", "delay_cancel")
        superseded = list(controls) if command in controls else [command]
        self.search([("device_id", "=", device.id), ("command", "in", superseded),
                     ("state", "=", "queued")]).write({"state": "cancelled"})
        rec = self.create({"device_id": device.id, "company_id": device.company_id.id,
                           "command": command, "payload": dict(payload), "expires_at": now + timedelta(minutes=2)})
        body = {**payload, "command_id": rec.command_id, "command_seq": rec.id,
                "expires_at": int(rec.expires_at.replace(tzinfo=timezone.utc).timestamp())}
        rec.payload = body
        device.with_context(**device._system_no_track_context()).write(
            device._relay_command_metadata(command, body, {"command": command, **body}, now))
        registry = self.env.registry
        def after_commit():
            with registry.cursor() as cr:
                env = api.Environment(cr, SUPERUSER_ID, {})
                env["iot.command"]._cron_dispatch()
                cr.commit()
        self.env.cr.postcommit.add(after_commit)
        return rec

    @api.model
    def _cron_dispatch(self):
        now = fields.Datetime.now()
        self.search([("state", "in", ["queued", "sent"]), ("expires_at", "<=", now)]).write({"state": "expired"})
        self.env.cr.execute("SELECT id FROM iot_command WHERE state = 'queued' ORDER BY id LIMIT 20 FOR UPDATE SKIP LOCKED")
        for rec in self.browse([row[0] for row in self.env.cr.fetchall()]):
            if not rec.device_id.active or not rec.company_id or rec.company_id != rec.device_id.company_id:
                rec.state = "cancelled"
                continue
            rec.attempts += 1
            if rec.device_id._publish_command_via_middleware(rec.command, dict(rec.payload), raise_on_fail=False):
                rec.write({"state": "sent", "sent_at": fields.Datetime.now()})

    def action_open_device(self):
        self.ensure_one()
        self.check_access("read")
        return {"type": "ir.actions.act_window", "res_model": "iot.device", "res_id": self.device_id.id, "view_mode": "form"}
