import json
import logging
import uuid
from datetime import datetime
from datetime import timedelta

import pytz
from odoo import _, api, fields, models
from odoo.exceptions import UserError

from ..services.mqtt_service import ensure_running

_logger = logging.getLogger(__name__)


class IoTDevice(models.Model):
    _name = "iot.device"
    _description = "IoT Relay Device"
    _inherit = ["mail.thread"]

    name = fields.Char(required=True, tracking=True)
    serial = fields.Char(required=True, tracking=True)
    module_id = fields.Char(tracking=True, index=True)
    switch_id_display = fields.Char(compute="_compute_switch_id_display", store=False)
    active = fields.Boolean(default=True)

    company_id = fields.Many2one("res.company", index=True)
    department_id = fields.Many2one("iot.department", domain="[('company_id', '=', company_id)]", tracking=True)
    location_id = fields.Many2one("iot.location", domain="[('company_id', '=', company_id)]", tracking=True)
    group_ids = fields.Many2many("iot.device.group", "iot_device_group_rel", "device_id", "group_id", string="Groups")

    relay_state = fields.Selection(
        [("unknown", "Unknown"), ("off", "Off"), ("on", "On")],
        default="unknown",
        required=True,
        tracking=True,
    )
    last_seen = fields.Datetime(tracking=True)
    online = fields.Boolean(compute="_compute_online", store=False)

    firmware_version = fields.Char(tracking=True)
    firmware_target_version = fields.Char(tracking=True)
    firmware_upgrade_requested_at = fields.Datetime(tracking=True)
    firmware_upgrade_completed_at = fields.Datetime(tracking=True)
    firmware_upgrade_state = fields.Selection(
        [("none", "None"), ("pending", "Pending"), ("success", "Success"), ("mismatch", "Mismatch"), ("failed", "Failed")],
        default="none",
        tracking=True,
    )
    auth_token = fields.Char(required=True, default=lambda self: uuid.uuid4().hex)

    on_since = fields.Datetime()
    total_on_minutes = fields.Integer(default=0, tracking=True)
    total_on_hours = fields.Float(compute="_compute_total_on_hours", digits=(16, 2), store=False)
    delay_duration_minutes = fields.Integer(default=30, tracking=True)
    delay_active = fields.Boolean(default=False, tracking=True)
    delay_started_at = fields.Datetime(tracking=True)
    delay_end_at = fields.Datetime(tracking=True)
    delay_remaining_minutes = fields.Float(compute="_compute_delay_remaining_minutes", digits=(16, 2), store=False)
    manual_override = fields.Boolean(default=False, tracking=True)

    last_command_at = fields.Datetime()
    last_command_payload = fields.Text()
    schedule_dirty = fields.Boolean(default=True, tracking=True)
    schedule_version = fields.Integer(default=0, tracking=True)
    schedule_applied_version = fields.Integer(default=0, tracking=True)
    schedule_last_push_at = fields.Datetime(tracking=True)
    schedule_last_sync_at = fields.Datetime(tracking=True)
    schedule_sync_state = fields.Selection(
        [("pending", "Pending"), ("in_sync", "In Sync"), ("outdated", "Outdated")],
        compute="_compute_schedule_sync_state",
        store=False,
    )

    message_ids = fields.One2many("iot.mqtt.message", "device_id")

    _sql_constraints = [
        ("iot_device_serial_uniq", "unique(serial)", "Serial must be unique."),
    ]

    @api.model
    def _system_no_track_context(self):
        # System background updates should not create chatter/tracking history.
        return {
            "tracking_disable": True,
            "mail_notrack": True,
            "mail_create_nolog": True,
        }

    @api.depends("last_seen")
    def _compute_online(self):
        timeout = int(self.env["ir.config_parameter"].sudo().get_param("iot_control_center.online_timeout_sec", 300))
        now = fields.Datetime.now()
        for rec in self:
            rec.online = bool(rec.last_seen and (now - rec.last_seen) <= timedelta(seconds=timeout))

    @api.depends("total_on_minutes", "relay_state", "on_since")
    def _compute_total_on_hours(self):
        now = fields.Datetime.now()
        for rec in self:
            total = rec.total_on_minutes
            if rec.relay_state == "on" and rec.on_since:
                diff = now - rec.on_since
                extra = max(int(diff.total_seconds() // 60), 0)
                total += extra
            rec.total_on_hours = round(total / 60.0, 2)

    @api.depends("schedule_dirty", "schedule_version", "schedule_applied_version")
    def _compute_schedule_sync_state(self):
        for rec in self:
            if rec.schedule_dirty:
                rec.schedule_sync_state = "pending"
            elif rec.schedule_applied_version >= rec.schedule_version:
                rec.schedule_sync_state = "in_sync"
            else:
                rec.schedule_sync_state = "outdated"

    @api.depends("module_id", "serial")
    def _compute_switch_id_display(self):
        for rec in self:
            rec.switch_id_display = rec.module_id or rec.serial or ""

    @api.depends("delay_active", "delay_end_at")
    def _compute_delay_remaining_minutes(self):
        now = fields.Datetime.now()
        for rec in self:
            if not rec.delay_active or not rec.delay_end_at:
                rec.delay_remaining_minutes = 0.0
                continue
            remaining = (rec.delay_end_at - now).total_seconds()
            rec.delay_remaining_minutes = round(max(remaining, 0.0) / 60.0, 2)

    def _accumulate_on_minutes_until(self, until_dt):
        for rec in self:
            if rec.relay_state == "on" and rec.on_since and until_dt > rec.on_since:
                diff = until_dt - rec.on_since
                delta_min = int(diff.total_seconds() // 60)
                if delta_min > 0:
                    rec.total_on_minutes += delta_min
                    rec.on_since = rec.on_since + timedelta(minutes=delta_min)

    def _mqtt_topic_root(self):
        return self.env["ir.config_parameter"].sudo().get_param("iot_control_center.mqtt_topic_root", "iot/relay")

    @api.model
    def find_bind_candidate(self, serial_or_id, require_online=False):
        key = (serial_or_id or "").strip()
        if not key:
            raise UserError(_("Switch ID/Serial is required."))
        rec = self.sudo().search(
            ["|", ("serial", "=ilike", key), ("module_id", "=ilike", key)],
            order="last_seen desc, id desc",
            limit=1,
        )
        if not rec:
            raise UserError(_("No switch found for ID: %s") % key)
        if require_online:
            timeout = int(self.env["ir.config_parameter"].sudo().get_param("iot_control_center.online_timeout_sec", 300))
            now = fields.Datetime.now()
            if not rec.last_seen or (now - rec.last_seen) > timedelta(seconds=timeout):
                raise UserError(_("Switch %s is offline. Please power it on first.") % (rec.module_id or rec.serial))
        return rec.with_env(self.env)

    @api.model
    def bind_by_serial(self, serial, company=None, department=None, location=None):
        serial_or_id = (serial or "").strip()
        rec = self.find_bind_candidate(serial_or_id, require_online=False)
        target_company = company or self.env.company
        if rec.company_id and rec.company_id != target_company:
            raise UserError(_("This switch is already bound to company: %s") % rec.company_id.display_name)
        vals = {"company_id": target_company.id}
        if department:
            vals["department_id"] = department.id
        if location:
            vals["location_id"] = location.id
        rec.write(vals)
        return rec.with_env(self.env)

    def action_unbind(self):
        for rec in self:
            rec.write(
                {
                    "company_id": False,
                    "department_id": False,
                    "location_id": False,
                    "group_ids": [(5, 0, 0)],
                    "schedule_dirty": True,
                }
            )

    def _delay_locked_devices(self):
        now = fields.Datetime.now()
        return self.filtered(lambda d: d.delay_active and (not d.delay_end_at or d.delay_end_at > now))

    def _ensure_not_delay_locked(self):
        locked = self._delay_locked_devices()
        if locked:
            names = ", ".join(locked.mapped("display_name"))
            raise UserError(_("Delay mode is active. This action is blocked for: %s") % names)

    def _publish_command(self, command, payload=None, raise_on_fail=True):
        service = ensure_running(self.env)
        if not service:
            if raise_on_fail:
                raise UserError(_("MQTT is not configured. Please set broker settings first."))
            return False
        payload = payload or {}
        all_ok = True
        for rec in self:
            topic = f"{self._mqtt_topic_root()}/{rec.serial}/command"
            body = {"command": command, **payload}
            ok = service.publish(topic, json.dumps(body))
            if not ok:
                all_ok = False
                if raise_on_fail:
                    raise UserError(_("Failed to publish MQTT command for %s") % rec.display_name)
                continue
            rec.last_command_at = fields.Datetime.now()
            rec.last_command_payload = json.dumps(body, ensure_ascii=False)
        return all_ok

    def action_turn_on(self):
        self._ensure_not_delay_locked()
        ok = self._publish_command("relay", {"state": "on"}, raise_on_fail=False)
        self.apply_state_report("on", reported_at=fields.Datetime.now())
        if ok:
            return {"type": "ir.actions.client", "tag": "reload"}
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Switch command"),
                "message": _("MQTT publish failed for some devices, please retry."),
                "sticky": False,
                "type": "warning",
            },
        }

    def action_turn_off(self):
        self._ensure_not_delay_locked()
        ok = self._publish_command("relay", {"state": "off"}, raise_on_fail=False)
        self.apply_state_report("off", reported_at=fields.Datetime.now())
        if ok:
            return {"type": "ir.actions.client", "tag": "reload"}
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Switch command"),
                "message": _("MQTT publish failed for some devices, please retry."),
                "sticky": False,
                "type": "warning",
            },
        }

    def action_toggle(self):
        return False

    def action_delay_toggle(self):
        now = fields.Datetime.now()
        all_ok = True
        for rec in self:
            duration_min = max(int(rec.delay_duration_minutes or 0), 1)
            ok = rec._publish_command("delay_toggle", {"duration_sec": duration_min * 60}, raise_on_fail=False)
            all_ok = all_ok and ok

            if rec.delay_active and (not rec.delay_end_at or rec.delay_end_at > now):
                rec._accumulate_on_minutes_until(now)
                rec.delay_active = False
                rec.delay_started_at = False
                rec.delay_end_at = False
                rec.on_since = False
                rec.relay_state = "off"
                rec.last_seen = now
            else:
                rec.apply_state_report("on", reported_at=now)
                rec.delay_active = True
                rec.delay_started_at = now
                rec.delay_end_at = now + timedelta(minutes=duration_min)

        if all_ok:
            return {"type": "ir.actions.client", "tag": "reload"}
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Delay switch"),
                "message": _("MQTT publish failed for some devices, please retry."),
                "sticky": False,
                "type": "warning",
            },
        }

    def _iter_schedule_entries(self):
        self.ensure_one()
        schedules = self.env["iot.schedule"].search(
            [
                ("active", "=", True),
                "|",
                ("device_id", "=", self.id),
                ("group_id", "in", self.group_ids.ids),
            ],
            order="id asc",
        )
        entries = []
        for rec in schedules:
            tz = pytz.timezone(rec.timezone or "UTC")
            offset = int((datetime.now(tz).utcoffset() or timedelta()).total_seconds() // 60)
            for weekday in rec.get_enabled_weekdays():
                entries.append(
                    {
                        "weekday": weekday,  # Monday=0 .. Sunday=6
                        "hour": rec.hour,
                        "minute": rec.minute,
                        "action": rec.command,
                        "offset_min": offset,
                    }
                )
        return entries

    def _sync_schedule_payload(self, raise_on_error=False):
        for rec in self:
            next_version = rec.schedule_version + 1
            entries = rec._iter_schedule_entries()
            try:
                if entries:
                    rec._publish_command("schedule_set", {"version": next_version, "entries": entries}, raise_on_fail=raise_on_error)
                else:
                    rec._publish_command("schedule_clear", {"version": next_version}, raise_on_fail=raise_on_error)
                rec.schedule_version = next_version
                rec.schedule_last_push_at = fields.Datetime.now()
                rec.schedule_dirty = False
            except Exception as exc:
                rec.schedule_dirty = True
                if raise_on_error:
                    raise
                _logger.warning("Auto schedule sync failed for %s: %s", rec.display_name, exc)

    def action_sync_schedule(self):
        self._sync_schedule_payload(raise_on_error=True)

    def action_reset_uptime(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Reset Accumulated Time"),
            "res_model": "iot.reset.uptime.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {
                "default_device_id": self.id,
            },
        }

    def action_reset_uptime_with_reason(self, reason):
        reason = (reason or "").strip()
        if not reason:
            raise UserError(_("Reset reason is required."))
        now = fields.Datetime.now()
        for rec in self:
            before_minutes = rec.total_on_minutes
            rec.total_on_minutes = 0
            rec.on_since = now if rec.relay_state == "on" else False
            rec.message_post(
                body=_(
                    "Accumulated ON time reset by %s. Reason: %s. Previous total: %.2f hours."
                )
                % (self.env.user.display_name, reason, round(before_minutes / 60.0, 2))
            )

    def apply_state_report(self, state, reported_at=None):
        state = state if state in ("on", "off") else "unknown"
        at = reported_at or fields.Datetime.now()
        for rec in self:
            old_state = rec.relay_state
            if old_state == "on" and state != "on":
                rec._accumulate_on_minutes_until(at)
                rec.on_since = False
            elif old_state != "on" and state == "on":
                rec.on_since = at

            rec.relay_state = state
            rec.last_seen = at
            if state != "on" and rec.delay_active:
                rec.delay_active = False
                rec.delay_started_at = False
                rec.delay_end_at = False

    def apply_schedule_report(self, payload, reported_at=None):
        at = reported_at or fields.Datetime.now()
        for rec in self:
            version = payload.get("schedule_version") if isinstance(payload, dict) else None
            try:
                version = int(version) if version is not None else None
            except Exception:
                version = None
            if version is not None:
                rec.schedule_applied_version = version
                rec.schedule_last_sync_at = at
            rec.last_seen = at

    def apply_delay_report(self, payload, reported_at=None):
        at = reported_at or fields.Datetime.now()
        if not isinstance(payload, dict):
            return
        active = payload.get("delay_active")
        remaining_sec = payload.get("delay_remaining_sec")
        for rec in self:
            rec.last_seen = at
            if active is None:
                continue
            is_active = bool(active)
            rec.delay_active = is_active
            if is_active:
                try:
                    remaining = max(int(remaining_sec or 0), 0)
                except Exception:
                    remaining = 0
                if remaining > 0:
                    rec.delay_end_at = at + timedelta(seconds=remaining)
                if not rec.delay_started_at:
                    rec.delay_started_at = at
            else:
                rec.delay_started_at = False
                rec.delay_end_at = False

    def apply_manual_override_report(self, payload, reported_at=None):
        at = reported_at or fields.Datetime.now()
        if not isinstance(payload, dict):
            return
        override = payload.get("manual_override")
        if override is None:
            return
        for rec in self:
            rec.manual_override = bool(override)
            rec.last_seen = at

    def apply_identity_report(self, module_id, reported_at=None):
        at = reported_at or fields.Datetime.now()
        for rec in self:
            if module_id and rec.module_id != module_id:
                rec.module_id = module_id
            rec.last_seen = at

    def apply_firmware_report(self, reported_version, reported_at=None, ota_state=None):
        at = reported_at or fields.Datetime.now()
        log_model = self.env["iot.firmware.upgrade.log"]
        for rec in self:
            prev_version = rec.firmware_version
            rec.firmware_version = reported_version
            rec.last_seen = at

            log = log_model.search(
                [("device_id", "=", rec.id), ("state", "=", "pending")],
                order="requested_at desc, id desc",
                limit=1,
            )
            if log:
                # Do not mark success only by periodic telemetry with same version.
                confirmed = ota_state == "ok" or (
                    prev_version
                    and (prev_version != reported_version)
                )
                if confirmed:
                    state = "success" if (log.target_version or "") == (reported_version or "") else "mismatch"
                    log.write(
                        {
                            "reported_version": reported_version,
                            "state": state,
                            "completed_at": at,
                        }
                    )
                    rec.firmware_upgrade_completed_at = at
                    rec.firmware_upgrade_state = state
            elif rec.firmware_target_version and rec.firmware_upgrade_state == "pending":
                confirmed = ota_state == "ok" or (
                    prev_version
                    and (prev_version != reported_version)
                )
                if confirmed:
                    rec.firmware_upgrade_completed_at = at
                    if rec.firmware_target_version == reported_version:
                        rec.firmware_upgrade_state = "success"
                    elif rec.firmware_upgrade_state != "failed":
                        rec.firmware_upgrade_state = "mismatch"

    def apply_firmware_upgrade_feedback(self, ota_state, note=None, reported_at=None):
        at = reported_at or fields.Datetime.now()
        log_model = self.env["iot.firmware.upgrade.log"]
        for rec in self:
            rec.last_seen = at
            if ota_state not in ("failed", "no_update"):
                continue

            log = log_model.search(
                [("device_id", "=", rec.id), ("state", "=", "pending")],
                order="requested_at desc, id desc",
                limit=1,
            )
            if log:
                log.write(
                    {
                        "state": "failed",
                        "completed_at": at,
                        "note": (note or "")[:255],
                    }
                )
            rec.firmware_upgrade_state = "failed"
            rec.firmware_upgrade_completed_at = at

    def mark_schedule_dirty(self, auto_sync=False):
        for rec in self:
            rec.schedule_dirty = True
        if auto_sync and self:
            self._sync_schedule_payload(raise_on_error=False)

    def write(self, vals):
        needs_auto_sync = "group_ids" in vals
        res = super().write(vals)
        if needs_auto_sync:
            self.mark_schedule_dirty(auto_sync=True)
        return res

    @api.model
    def _cron_ensure_mqtt_service(self):
        ensure_running(self.env)
        now = fields.Datetime.now()
        expired = self.with_context(**self._system_no_track_context()).search(
            [("delay_active", "=", True), ("delay_end_at", "!=", False), ("delay_end_at", "<=", now)]
        )
        if expired:
            expired.write({"delay_active": False, "delay_started_at": False, "delay_end_at": False})

    @api.model
    def _cron_update_live_uptime(self):
        devices = self.with_context(**self._system_no_track_context()).search([("relay_state", "=", "on"), ("on_since", "!=", False)])
        now = fields.Datetime.now()
        devices._accumulate_on_minutes_until(now)
