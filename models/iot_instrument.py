"""Heater and washer workspaces with device-scoped, acknowledged commands."""
import base64
import hashlib
import json
import secrets
import uuid
from datetime import datetime, timedelta, timezone

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError
from ..core import instruments as contract

HEATER_FAULT_SELECTION = [("none", "No Active Alarm"), ("sensor", "Temperature Sensor Fault"),
    ("no_rise", "Insufficient Temperature Rise"), ("over_temperature", "Overtemperature"),
    ("storage", "Device Storage Error"), ("loop_stalled", "Control Loop Stalled"), ("configuration", "Settings Required")]


class Instrument(models.Model):
    _name = "iot.instrument"
    _inherit = ["iot.access.mixin"]
    _description = "Laboratory Instrument"
    _check_company_auto = True

    name = fields.Char(required=True)
    uid = fields.Char(required=True, default=lambda self: uuid.uuid4().hex, readonly=True, copy=False, index=True)
    kind = fields.Selection([("heater", "Buffer Heater"), ("washer", "Array Washer")], required=True)
    company_id = fields.Many2one("res.company", required=True, default=lambda self: self.env.company, index=True)
    location_detail = fields.Char()
    active = fields.Boolean(default=True)
    token_hash = fields.Char(groups="base.group_system", copy=False)
    state = fields.Selection([(k, v) for k, v in [("idle", "Idle"), ("heating", "Heating"),
        ("running", "Running"), ("waiting", "Waiting for Operator"), ("fault", "Fault"),
        ("updating", "Updating"), ("uncommissioned", "Commissioning Required")]], default="uncommissioned", readonly=True)
    last_seen = fields.Datetime(readonly=True)
    status_sampled_at = fields.Datetime(readonly=True)
    firmware = fields.Char(readonly=True)
    hardware = fields.Char(readonly=True)
    boot_id = fields.Char(readonly=True)
    last_seq = fields.Integer(readonly=True)
    status_json = fields.Json(readonly=True)
    catalog_sync_enabled = fields.Boolean(compute="_compute_catalog_sync", string="Automatic Program Sync")
    online = fields.Boolean(compute="_compute_online")
    status_fresh = fields.Boolean(compute="_compute_online")
    temperature_a = fields.Float(readonly=True, digits=(5, 2), string="Liquid Temperature")
    valid_a = fields.Boolean(readonly=True, string="Temperature Available")
    target_a = fields.Float(default=37, digits=(5, 2), string="Requested Temperature")
    chip_id = fields.Char(readonly=True, string="Chip ID")
    device_ip = fields.Char(readonly=True, string="Device IP Address")
    heating_enabled = fields.Boolean(readonly=True, string="Heating Enabled")
    heater_output = fields.Boolean(readonly=True, string="Heater Output")
    dropped_observations = fields.Integer(readonly=True, string="Offline Samples Overwritten")
    rise_window_s = fields.Integer(default=600, string="Heating Observation Time (s)")
    minimum_rise_c = fields.Float(default=1, digits=(5, 3), string="Minimum Temperature Rise (C)")
    settings_ready = fields.Boolean(readonly=True, string="Settings Stored on Device")
    applied_target_a = fields.Float(readonly=True, string="Stored Temperature")
    applied_rise_window_s = fields.Integer(readonly=True, string="Stored Observation Time (s)")
    applied_minimum_rise_c = fields.Float(readonly=True, digits=(5, 3), string="Stored Minimum Rise (C)")
    settings_pending = fields.Boolean(compute="_compute_settings_pending", string="Settings Not Yet Applied")
    fault_a = fields.Selection(HEATER_FAULT_SELECTION, readonly=True, string="Heater Alarm")
    washer_temperature = fields.Float(readonly=True, string="Measured Liquid Temperature")
    washer_temperature_valid = fields.Boolean(readonly=True, string="Liquid Temperature Available")
    recipe_id = fields.Many2one("iot.instrument.recipe", check_company=True, domain="[('state','=','released')]")
    release_id = fields.Many2one("iot.instrument.release", check_company=True)
    command_ids = fields.One2many("iot.instrument.command", "instrument_id")
    _uid_unique = models.Constraint("UNIQUE(uid)", "Instrument identity must be unique.")

    @api.depends("kind", "status_json")
    def _compute_catalog_sync(self):
        for rec in self:
            rec.catalog_sync_enabled = rec.kind == "washer" and (rec.status_json or {}).get("catalog_sync") == 1

    @api.depends("last_seen", "status_sampled_at")
    def _compute_online(self):
        cutoff = fields.Datetime.now() - timedelta(seconds=120)
        for rec in self:
            rec.online = bool(rec.last_seen and rec.last_seen >= cutoff)
            rec.status_fresh = bool(rec.status_sampled_at and rec.status_sampled_at >= cutoff)

    @api.depends("settings_ready", "target_a", "applied_target_a", "rise_window_s", "applied_rise_window_s", "minimum_rise_c", "applied_minimum_rise_c")
    def _compute_settings_pending(self):
        for rec in self:
            rec.settings_pending = not rec.settings_ready or any(abs(a - b) > 0.0001 for a, b in (
                (rec.target_a, rec.applied_target_a), (rec.rise_window_s, rec.applied_rise_window_s),
                (rec.minimum_rise_c, rec.applied_minimum_rise_c)))

    @api.constrains("target_a")
    def _check_targets(self):
        for rec in self:
            try:
                contract.targets({"a": rec.target_a})
            except ValueError as exc:
                raise ValidationError(_("Set temperatures from 10 to 50 C in 0.25 C increments.")) from exc

    @api.constrains("rise_window_s", "minimum_rise_c")
    def _check_protection(self):
        for rec in self:
            try:
                contract.integer(rec.rise_window_s, 30, 3600)
                contract.number(rec.minimum_rise_c, 0.125, 5)
            except ValueError as exc:
                raise ValidationError(_("Set a heating observation time of 30 to 3600 seconds and a minimum rise of 0.125 to 5 C.")) from exc

    @api.model_create_multi
    def create(self, vals_list):
        if not self.env.su and not self.env.user.has_group("iot_control_center.group_iot_manager"):
            raise AccessError(_("Only IoT managers can register instruments."))
        for vals in vals_list:
            if not self.env.su and set(vals) - {"name", "kind", "company_id", "location_detail", "target_a", "rise_window_s", "minimum_rise_c", "active"}:
                raise AccessError(_("Device-reported fields cannot be changed manually."))
        return super().create(vals_list)

    def write(self, vals):
        if not self.env.su:
            self._check_iot_access(manage=bool(set(vals) - {"target_a", "recipe_id"}))
            if set(vals) - {"name", "active", "location_detail", "target_a", "rise_window_s", "minimum_rise_c", "recipe_id", "release_id"}:
                raise AccessError(_("Identity and device-reported fields cannot be changed manually."))
        return super().write(vals)

    def _enqueue(self, name, payload):
        self.ensure_one()
        self._check_iot_access(manage=name == "ota")
        if not self.active:
            raise UserError(_("This instrument is archived."))
        body = contract.command(self.kind, name, payload)
        self.env.cr.execute("SELECT id FROM iot_instrument WHERE id=%s FOR UPDATE", [self.id])
        commands = self.env["iot.instrument.command"].sudo()
        domain = [("instrument_id", "=", self.id), ("state", "in", ["queued", "sent"])]
        if name != "stop":
            domain += [("name", "=", name)]
        commands.search(domain).write({"state": "cancelled"})
        return commands.create({"instrument_id": self.id, "company_id": self.company_id.id,
            "name": name, "payload": body, "expires_at": fields.Datetime.now() + timedelta(minutes=2)})

    def _queued_notice(self):
        return {"type": "ir.actions.client", "tag": "display_notification", "params": {
            "title": _("Command queued"), "message": _("Waiting for device confirmation. Sending is not proof of execution."), "type": "info"}}

    def action_set_temperature(self):
        self.ensure_one()
        self._enqueue("set_temperature", {"a": self.target_a,
            "rise_window_s": self.rise_window_s, "minimum_rise_c": self.minimum_rise_c})
        return self._queued_notice()

    def action_stop(self):
        for rec in self:
            rec._enqueue("stop", {})
        return self._queued_notice()

    def action_send_recipe(self):
        self.ensure_one()
        self._check_iot_access()
        if self.catalog_sync_enabled:
            return {"type": "ir.actions.client", "tag": "display_notification", "params": {
                "title": _("Automatic program synchronization"),
                "message": _("This washer synchronizes all current released company programs while idle. Publish a revision or archive a program to update its local list."), "type": "info"}}
        self.recipe_id.check_access("read")
        if not self.recipe_id or self.recipe_id.state != "released" or self.recipe_id.company_id != self.company_id:
            raise UserError(_("Select a released program belonging to this company."))
        self._enqueue("load_recipe", dict(self.recipe_id.snapshot))
        return self._queued_notice()

    def _program_catalog(self):
        self.ensure_one()
        records = self.env["iot.instrument.recipe"].sudo().with_context(active_test=False).search([
            ("company_id", "=", self.company_id.id), ("state", "=", "released")], order="uid,revision desc,id desc")
        seen, programs = set(), []
        for program in records:
            if program.uid in seen:
                continue
            seen.add(program.uid)
            # Archiving the latest revision removes it; do not resurrect an older one.
            if program.active:
                programs.append(dict(program.snapshot))
        return contract.program_catalog(self.uid, programs)

    def action_ota(self):
        self.ensure_one()
        self._check_iot_access(manage=True)
        release = self.release_id
        release.check_access("read")
        if not release or release.company_id != self.company_id or release.kind != self.kind or release.hardware != self.hardware:
            raise UserError(_("Select firmware matching the company, device type and reported hardware profile."))
        if not self.online or not self.status_fresh or self.state != "idle" or (self.kind == "heater" and (self.heating_enabled or self.heater_output)):
            raise UserError(_("Firmware updates require a connected, idle instrument with all outputs off."))
        self._enqueue("ota", {"release": release.uid})
        return self._queued_notice()

    def action_credentials(self):
        self.ensure_one()
        self._check_iot_access(manage=True)
        return {"type": "ir.actions.act_window", "res_model": "iot.instrument.provision", "view_mode": "form", "target": "new",
                "context": {"default_instrument_id": self.id}}

    def action_history(self):
        self.ensure_one()
        self.check_access("read")
        model = "iot.instrument.reading" if self.kind == "heater" else "iot.instrument.run.log"
        return {"type": "ir.actions.act_window", "name": _("Temperature History") if self.kind == "heater" else _("Run Logs"),
            "res_model": model, "view_mode": "graph,pivot,list" if self.kind == "heater" else "list,form",
            "domain": [("instrument_id", "=", self.id)], "context": {"search_default_last_day": 1, "search_default_valid": 1} if self.kind == "heater" else {}}

    def action_alarms(self):
        self.ensure_one()
        self.check_access("read")
        return {"type": "ir.actions.act_window", "name": _("Heater Alarms"),
            "res_model": "iot.instrument.alarm", "view_mode": "list,form", "domain": [("instrument_id", "=", self.id)]}

    def _exchange(self, data):
        self.ensure_one()
        contract.event(data, self.kind)
        self.env.cr.execute("SELECT id FROM iot_instrument WHERE id=%s FOR UPDATE", [self.id])
        self.invalidate_recordset()
        now = fields.Datetime.now()
        key = contract.digest({"device": self.uid, "event": data["event_id"]})
        fresh = self.env["iot.ingest.event"]._claim(key, "instrument", contract.digest(data), now)
        sampled = datetime.fromtimestamp(data["sampled_at"], timezone.utc).replace(tzinfo=None) if data["sampled_at"] else False
        if sampled and sampled > now + timedelta(minutes=5):
            raise ValueError("future sample")
        if fresh:
            status = data["status"]
            current = bool(sampled and sampled >= now - timedelta(seconds=120)
                and (not self.status_sampled_at or sampled >= self.status_sampled_at)
                and (data["boot_id"] == self.boot_id and data["seq"] > self.last_seq
                     or data["boot_id"] != self.boot_id and (not self.status_sampled_at or sampled > self.status_sampled_at)))
            if current:
                values = dict(state=status["state"], firmware=status["firmware"], hardware=str(status.get("hardware", ""))[:64],
                    boot_id=data["boot_id"], last_seq=data["seq"], status_json=status, status_sampled_at=sampled)
                if self.kind == "heater":
                    values["settings_ready"] = status.get("settings_ready", False)
                    values.update(chip_id=status.get("chip_id", False), device_ip=status.get("ip", False),
                        dropped_observations=status.get("dropped_observations", 0),
                        heating_enabled=status.get("enabled", False), heater_output=status["a"]["output"],
                        applied_rise_window_s=status.get("rise_window_s", 0),
                        applied_minimum_rise_c=status.get("minimum_rise_c", 0))
                    for channel in ("a",):
                        values["valid_" + channel] = status[channel]["valid"]
                        values["temperature_" + channel] = status[channel].get("temperature", 0) if status[channel]["valid"] else 0
                        values["applied_target_" + channel] = status[channel]["target"]
                        values["fault_" + channel] = status[channel].get("fault", "none")
                else:
                    values["washer_temperature_valid"] = status.get("temperature_valid", False)
                    values["washer_temperature"] = status.get("temperature", 0) if values["washer_temperature_valid"] else 0
                self.write(values)
            if self.kind == "heater" and data.get("observation") is True:
                for channel in ("a",):
                    probe = status[channel]
                    self.env["iot.instrument.reading"].create({"instrument_id": self.id, "company_id": self.company_id.id,
                        "channel": channel, "sampled_at": sampled, "received_at": now, "event_id": key,
                        "valid": probe["valid"], "temperature": probe.get("temperature", 0) if probe["valid"] else 0,
                        "target": probe["target"], "output": probe["output"], "fault": probe.get("fault", "none")})
            if self.kind == "heater" and data.get("alarm") is True:
                for channel in ("a",):
                    fault = status[channel].get("fault", "none")
                    if fault != "none":
                        self.env["iot.instrument.alarm"].create({"instrument_id": self.id, "company_id": self.company_id.id,
                            "event_id": key, "channel": channel, "fault": fault, "sampled_at": sampled, "received_at": now})
            if data.get("log"):
                log = data["log"]
                self.env["iot.instrument.run.log"].create({"instrument_id": self.id, "company_id": self.company_id.id,
                    "event_id": key, "sampled_at": sampled, "received_at": now, "run_id": log["run_id"],
                    "recipe_uid": log["recipe_id"], "revision": log["revision"], "step": log["step"],
                    "event": log["event"], "message": log.get("message", ""), "temperature_valid": status.get("temperature_valid", False),
                    "temperature": status.get("temperature", 0) if status.get("temperature_valid") else 0})
            if data.get("ack"):
                ack = data["ack"]
                pending = self.env["iot.instrument.command"].search([("instrument_id", "=", self.id),
                    ("uid", "=", ack["id"]), ("state", "in", ["queued", "sent", "expired"])], limit=1)
                if pending:
                    pending.write({"state": ack["result"], "acknowledged_at": now})
        self.last_seen = now
        queue = self.env["iot.instrument.command"]
        queue.search([("instrument_id", "=", self.id), ("state", "in", ["queued", "sent"]), ("expires_at", "<=", now)]).write({"state": "expired"})
        pending = queue.search([("instrument_id", "=", self.id), ("state", "in", ["queued", "sent"]),
            ("expires_at", ">", now)], order="id", limit=1)
        result = {"ok": True, "event_id": data["event_id"], "server_time": int(now.replace(tzinfo=timezone.utc).timestamp()), "command": None}
        if pending:
            pending.write({"state": "sent", "attempts": pending.attempts + 1})
            result["command"] = {"id": pending.uid, "seq": pending.id, "name": pending.name, "payload": pending.payload or {},
                "boot_id": data["boot_id"], "expires_at": int(pending.expires_at.replace(tzinfo=timezone.utc).timestamp())}
        return result


class InstrumentCommand(models.Model):
    _name = "iot.instrument.command"
    _description = "Instrument Command Delivery"
    _order = "id desc"
    instrument_id = fields.Many2one("iot.instrument", required=True, ondelete="restrict", index=True)
    company_id = fields.Many2one("res.company", required=True, index=True)
    uid = fields.Char(default=lambda self: uuid.uuid4().hex, required=True, index=True)
    name = fields.Char(required=True)
    payload = fields.Json()
    state = fields.Selection([(x, x.title()) for x in ("queued", "sent", "applied", "rejected", "expired", "cancelled")], default="queued", required=True)
    expires_at = fields.Datetime(required=True)
    acknowledged_at = fields.Datetime()
    attempts = fields.Integer()
    _uid_unique = models.Constraint("UNIQUE(uid)", "Command identity must be unique.")


class InstrumentReading(models.Model):
    _name = "iot.instrument.reading"
    _description = "Buffer Temperature Observation"
    _order = "sampled_at desc, id desc"
    instrument_id = fields.Many2one("iot.instrument", required=True, ondelete="restrict", index=True)
    company_id = fields.Many2one("res.company", required=True, index=True)
    event_id = fields.Char(required=True)
    sampled_at = fields.Datetime(index=True)
    received_at = fields.Datetime(required=True, index=True)
    channel = fields.Selection([("a", "Liquid Temperature")], required=True, default="a")
    valid = fields.Boolean()
    temperature = fields.Float(digits=(5, 2), aggregator="avg")
    target = fields.Float(digits=(5, 2), aggregator="avg")
    output = fields.Boolean()
    fault = fields.Selection(HEATER_FAULT_SELECTION)
    _sample_unique = models.Constraint("UNIQUE(event_id,channel)", "Sample already received.")

    @api.model
    def _read_group(self, domain, groupby=(), aggregates=(), having=(), offset=0, limit=None, order=None):
        # Missing sensors and unsynchronised clocks must never become zero-degree samples.
        domain = list(domain) + [("valid", "=", True), ("sampled_at", "!=", False)]
        return super()._read_group(domain, groupby, aggregates, having, offset, limit, order)


class InstrumentAlarm(models.Model):
    _name = "iot.instrument.alarm"
    _description = "Heater Alarm Event"
    _order = "id desc"
    instrument_id = fields.Many2one("iot.instrument", required=True, ondelete="restrict", index=True)
    company_id = fields.Many2one("res.company", required=True, index=True)
    event_id = fields.Char(required=True)
    sampled_at = fields.Datetime()
    received_at = fields.Datetime(required=True)
    channel = fields.Selection([("a", "Liquid Temperature")], required=True, default="a")
    fault = fields.Selection(HEATER_FAULT_SELECTION, required=True)
    _event_unique = models.Constraint("UNIQUE(event_id,channel)", "Alarm already received.")


class InstrumentRunLog(models.Model):
    _name = "iot.instrument.run.log"
    _description = "Washer Run Event"
    _order = "id desc"
    instrument_id = fields.Many2one("iot.instrument", required=True, ondelete="restrict", index=True)
    company_id = fields.Many2one("res.company", required=True, index=True)
    event_id = fields.Char(required=True)
    sampled_at = fields.Datetime(index=True)
    received_at = fields.Datetime(required=True)
    run_id = fields.Char(required=True, index=True)
    recipe_uid = fields.Char(required=True)
    revision = fields.Integer(required=True)
    step = fields.Integer()
    event = fields.Char(required=True)
    message = fields.Char()
    temperature = fields.Float(string="Measured Liquid Temperature")
    temperature_valid = fields.Boolean(string="Liquid Temperature Available")
    _event_unique = models.Constraint("UNIQUE(event_id)", "Run event already received.")


class InstrumentRecipe(models.Model):
    _name = "iot.instrument.recipe"
    _inherit = ["iot.access.mixin"]
    _description = "Washer Program Version"
    _check_company_auto = True
    name = fields.Char(required=True)
    active = fields.Boolean(default=True)
    device_label = fields.Char(required=True, default="Array wash", string="Screen Label",
        help="A short Latin-character label for the GB2312 instrument screen. The program name in Odoo may use any language.")
    uid = fields.Char(required=True, default=lambda self: uuid.uuid4().hex, copy=False)
    revision = fields.Integer(default=1, required=True)
    company_id = fields.Many2one("res.company", required=True, default=lambda self: self.env.company)
    state = fields.Selection([("draft", "Draft"), ("released", "Released")], default="draft", readonly=True, copy=False)
    step_ids = fields.One2many("iot.instrument.recipe.step", "recipe_id", copy=True)
    snapshot = fields.Json(readonly=True, copy=False)
    checksum = fields.Char(readonly=True, copy=False)
    _revision_unique = models.Constraint("UNIQUE(company_id,uid,revision)", "Program revision already exists.")

    @api.model_create_multi
    def create(self, vals_list):
        if not self.env.su and any(set(v) & {"state", "snapshot", "checksum"} for v in vals_list):
            raise AccessError(_("Use Release Program to publish a validated version."))
        return super().create(vals_list)

    def _lock_draft(self):
        for rec in self:
            self.env.cr.execute("SELECT state FROM iot_instrument_recipe WHERE id=%s FOR UPDATE", [rec.id])
            if self.env.cr.fetchone()[0] != "draft":
                raise UserError(_("Released programs are immutable. Duplicate the program to make changes."))

    def write(self, vals):
        if set(vals) == {"active"}:
            self._check_iot_access(manage=True)
            return super().write(vals)
        self._lock_draft()
        if not self.env.su and set(vals) & {"state", "snapshot", "checksum"}:
            raise AccessError(_("Use Release Program to publish a validated version."))
        return super().write(vals)

    def unlink(self):
        self._lock_draft()
        return super().unlink()

    def action_new_revision(self):
        self.ensure_one()
        self._check_iot_access(manage=True)
        latest = self.with_context(active_test=False).search([
            ("uid", "=", self.uid), ("company_id", "=", self.company_id.id)], order="revision desc", limit=1)
        draft = self.copy({"uid": self.uid, "revision": latest.revision + 1, "active": True})
        return {"type": "ir.actions.act_window", "res_model": self._name, "res_id": draft.id, "view_mode": "form", "target": "current"}

    def action_release(self):
        self._check_iot_access(manage=True)
        for rec in self:
            rec._lock_draft()
            try:
                body = contract.recipe({"schema": 1, "id": rec.uid, "label": rec.device_label, "revision": rec.revision,
                    "steps": [{"kind": s.kind, "duration_s": s.duration_s, "rps": s.rps, "reverse_s": s.reverse_s, "cycles": s.cycles}
                        for s in rec.step_ids.sorted("sequence")]})
            except (ValueError, TypeError, AttributeError) as exc:
                raise ValidationError(_("Invalid program: %s", str(exc))) from exc
            rec.sudo().write({"state": "released", "snapshot": body, "checksum": contract.digest(body)})

class InstrumentRecipeStep(models.Model):
    _name = "iot.instrument.recipe.step"
    _description = "Washer Program Step"
    _order = "sequence,id"
    recipe_id = fields.Many2one("iot.instrument.recipe", required=True, ondelete="cascade")
    company_id = fields.Many2one(related="recipe_id.company_id", store=True, index=True)
    sequence = fields.Integer(default=10)
    kind = fields.Selection([("home", "Home Rotor"), ("fill_a", "Fill Buffer A"), ("fill_b", "Fill Buffer B"),
        ("wash", "Wash"), ("drain", "Drain"), ("dry", "Spin Dry"), ("wait", "Wait for Operator")], required=True)
    duration_s = fields.Integer(default=30, required=True)
    rps = fields.Float(string="Speed (rev/s)")
    reverse_s = fields.Integer(default=5, string="Reverse Every (s)")
    cycles = fields.Integer(default=0, string="Wash Cycles", help="One cycle is forward plus reverse. Zero keeps timed washing; otherwise duration is cycles x 2 x reverse interval.")

    @api.onchange("kind")
    def _onchange_kind_speed(self):
        for step in self:
            step.rps = contract.washer_speed_default(step.kind)

    @api.model_create_multi
    def create(self, vals_list):
        vals_list = [dict(vals) for vals in vals_list]
        for vals in vals_list:
            vals.setdefault("rps", contract.washer_speed_default(vals.get("kind")))
        parents = self.env["iot.instrument.recipe"].browse([v["recipe_id"] for v in vals_list])
        parents.check_access("write")
        parents._lock_draft()
        return super().create(vals_list)

    def write(self, vals):
        self.recipe_id._lock_draft()
        if "kind" in vals and "rps" not in vals:
            vals = dict(vals, rps=contract.washer_speed_default(vals["kind"]))
        if "recipe_id" in vals:
            parent = self.env["iot.instrument.recipe"].browse(vals["recipe_id"])
            parent.check_access("write")
            parent._lock_draft()
        return super().write(vals)

    def unlink(self):
        self.recipe_id._lock_draft()
        return super().unlink()


class InstrumentProvision(models.TransientModel):
    _name = "iot.instrument.provision"
    _description = "Instrument Credential Registration"
    instrument_id = fields.Many2one("iot.instrument", required=True)
    token = fields.Char(required=True)

    def action_apply(self):
        self.ensure_one()
        self.instrument_id._check_iot_access(manage=True)
        if not secrets.compare_digest(self.token.strip(), self.token) or len(self.token) < 32 or len(self.token) > 128:
            raise ValidationError(_("Use a random device token of 32 to 128 characters without surrounding spaces."))
        self.instrument_id.sudo().write({"token_hash": hashlib.sha256(self.token.encode()).hexdigest()})
        self.unlink()
        return {"type": "ir.actions.act_window_close"}


class InstrumentRelease(models.Model):
    _name = "iot.instrument.release"
    _description = "Signed Instrument Firmware Package"
    name = fields.Char(required=True)
    uid = fields.Char(required=True, default=lambda self: uuid.uuid4().hex, readonly=True, copy=False, index=True)
    company_id = fields.Many2one("res.company", required=True, default=lambda self: self.env.company)
    kind = fields.Selection([("heater", "Buffer Heater"), ("washer", "Array Washer")], required=True)
    hardware = fields.Char(required=True)
    manifest = fields.Text(required=True)
    binary = fields.Binary(required=True, attachment=True)
    filename = fields.Char(default="firmware.bin")
    _uid_unique = models.Constraint("UNIQUE(uid)", "Firmware identity must be unique.")

    @api.constrains("manifest", "binary", "kind", "hardware")
    def _check_package(self):
        for rec in self:
            try:
                info = json.loads(rec.manifest)
                raw = base64.b64decode(rec.binary, validate=True)
                expected = contract.HEATER_HARDWARE if rec.kind == "heater" else "washer-esp32-4m-v1"
                if rec.hardware != expected:
                    raise ValueError("withdrawn or unsupported hardware profile")
                if info.get("schema") != 1 or info["kind"] != rec.kind or info["hardware"] != rec.hardware or info["size"] != len(raw):
                    raise ValueError("target mismatch")
                contract.integer(info["version"], 1, 2147483647)
                if len(raw) > (0x1B0000 if rec.kind == "washer" else 1000000) or len(raw) < 32 or raw[0] != 0xE9:
                    raise ValueError("invalid application image")
                if info["sha256"] != hashlib.sha256(raw).hexdigest() or len(base64.b64decode(info["signature"], validate=True)) != 256:
                    raise ValueError("digest or RSA signature format invalid")
            except (ValueError, KeyError, TypeError) as exc:
                raise ValidationError(_("The signed firmware package is invalid or targets another board.")) from exc

    def write(self, vals):
        if set(vals) - {"name"}:
            raise UserError(_("Firmware packages are immutable. Create a new release."))
        return super().write(vals)
