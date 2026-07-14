import json
import logging
import time
import uuid
from urllib import error as urlerror
from urllib import parse as urlparse
from urllib import request as urlrequest
from datetime import datetime
from datetime import timedelta

import psycopg2
import pytz
from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

from ..services.mqtt_service import ensure_running, publish_once

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

    company_id = fields.Many2one(
        "res.company",
        index=True,
        default=lambda self: False if self.env.context.get("iot_auto_discovery") else self.env.company,
    )
    department_id = fields.Many2one("hr.department", domain="['|', ('company_id', '=', False), ('company_id', '=', company_id)]", tracking=True)
    location_id = fields.Many2one(
        "stock.location",
        domain="['|', ('company_id', '=', False), ('company_id', '=', company_id)]",
        tracking=True,
    )
    location_detail = fields.Char(string="Location Detail", tracking=True, translate=True)
    group_ids = fields.Many2many("iot.device.group", "iot_device_group_rel", "device_id", "group_id", string="Groups")

    relay_state = fields.Selection(
        [("unknown", "Unknown"), ("off", "Off"), ("on", "On")],
        default="unknown",
        required=True,
        tracking=True,
    )
    desired_relay_state = fields.Selection(
        [("unknown", "Unknown"), ("off", "Off"), ("on", "On")],
        default="unknown",
        required=True,
        readonly=True,
    )
    relay_command_state = fields.Selection(
        [("idle", "Idle"), ("pending", "Pending"), ("confirmed", "Confirmed"), ("timeout", "Timed Out")],
        default="idle",
        required=True,
        readonly=True,
    )
    last_command_id = fields.Char(readonly=True, index=True)
    last_command_confirmed_at = fields.Datetime(readonly=True)
    max_continuous_on_minutes = fields.Integer(
        string="Maximum Continuous ON (Minutes)",
        default=0,
        help="Device-side safety cutoff. Set to 0 to disable. UV lamps should always have a finite limit.",
    )
    last_seen = fields.Datetime(tracking=True)
    online = fields.Boolean(compute="_compute_online", store=False)

    firmware_version = fields.Char(tracking=True)
    firmware_hardware_profile = fields.Char(readonly=True)
    flash_real_size_bytes = fields.Integer(readonly=True)
    free_heap_bytes = fields.Integer(readonly=True)
    mqtt_active_host = fields.Char(readonly=True)
    mqtt_route = fields.Selection(
        [("unknown", "Unknown"), ("primary", "Internal / Primary"), ("fallback", "Public / Fallback")],
        default="unknown",
        readonly=True,
    )
    network_config_dirty = fields.Boolean(default=True, readonly=True)
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
    schedule_timezone_name = fields.Char(readonly=True)
    schedule_timezone_offset_min = fields.Integer(readonly=True)
    schedule_sync_state = fields.Selection(
        [("pending", "Pending"), ("in_sync", "In Sync"), ("outdated", "Outdated")],
        compute="_compute_schedule_sync_state",
        store=False,
    )

    message_ids = fields.One2many("iot.mqtt.message", "device_id")

    _serial_uniq = models.Constraint(
        "UNIQUE(serial)",
        "Serial must be unique.",
    )

    @api.model
    def init(self):
        self._archive_duplicate_identity_rows()
        self.env.cr.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS iot_device_active_module_id_lower_uniq
            ON iot_device (lower(module_id))
            WHERE active IS TRUE
              AND module_id IS NOT NULL
              AND btrim(module_id) <> ''
            """
        )

    @api.model
    def _archive_duplicate_identity_rows(self):
        self.env.cr.execute(
            """
            WITH ranked AS (
                SELECT
                    id,
                    ROW_NUMBER() OVER (
                        PARTITION BY lower(module_id)
                        ORDER BY
                            CASE WHEN company_id IS NULL THEN 1 ELSE 0 END,
                            last_seen DESC NULLS LAST,
                            write_date DESC NULLS LAST,
                            id DESC
                    ) AS rn
                FROM iot_device
                WHERE active IS TRUE
                  AND module_id IS NOT NULL
                  AND btrim(module_id) <> ''
            )
            UPDATE iot_device d
               SET active = FALSE,
                   company_id = NULL,
                   write_date = NOW()
              FROM ranked r
             WHERE d.id = r.id
               AND r.rn > 1
            """
        )

    @api.model
    def _runtime_no_track_fields(self):
        return {
            "relay_state",
            "desired_relay_state",
            "relay_command_state",
            "last_command_id",
            "last_command_confirmed_at",
            "last_seen",
            "firmware_version",
            "firmware_hardware_profile",
            "flash_real_size_bytes",
            "free_heap_bytes",
            "mqtt_active_host",
            "mqtt_route",
            "network_config_dirty",
            "firmware_target_version",
            "firmware_upgrade_requested_at",
            "firmware_upgrade_completed_at",
            "firmware_upgrade_state",
            "on_since",
            "total_on_minutes",
            "delay_duration_minutes",
            "delay_active",
            "delay_started_at",
            "delay_end_at",
            "manual_override",
            "last_command_at",
            "last_command_payload",
            "schedule_dirty",
            "schedule_version",
            "schedule_applied_version",
            "schedule_last_push_at",
            "schedule_last_sync_at",
            "schedule_timezone_name",
            "schedule_timezone_offset_min",
            "module_id",
        }

    @api.model
    def _system_no_track_context(self):
        # System background updates should not create chatter/tracking history.
        return {
            "tracking_disable": True,
            "mail_notrack": True,
            "mail_create_nolog": True,
        }

    @api.model
    def _run_with_serialization_retry(self, func, retries=3, sleep_sec=0.05):
        for attempt in range(retries):
            try:
                with self.env.cr.savepoint():
                    return func()
            except psycopg2.errors.SerializationFailure:
                if attempt >= retries - 1:
                    raise
                time.sleep(sleep_sec * (attempt + 1))
        return None

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

    def _command_identity(self):
        self.ensure_one()
        return (self.module_id or self.serial or "").strip()

    def _max_on_seconds(self):
        self.ensure_one()
        return max(int(self.max_continuous_on_minutes or 0), 0) * 60

    @api.constrains("max_continuous_on_minutes")
    def _check_max_continuous_on_minutes(self):
        for rec in self:
            if rec.max_continuous_on_minutes < 0:
                raise ValidationError(_("Maximum continuous ON time cannot be negative."))

    @api.model
    def _relay_command_metadata(self, command, payload, body, command_at):
        vals = {
            "last_command_at": command_at,
            "last_command_payload": json.dumps(body, ensure_ascii=False),
        }
        target_state = payload.get("state") if command == "relay" else None
        command_id = payload.get("command_id")
        if target_state in ("on", "off") and command_id:
            vals.update(
                {
                    "desired_relay_state": target_state,
                    "relay_command_state": "pending",
                    "last_command_id": command_id,
                    "last_command_confirmed_at": False,
                }
            )
        return vals

    @api.model
    def find_bind_candidate(self, serial_or_id, require_online=False):
        key = (serial_or_id or "").strip()
        if not key:
            raise UserError(_("Switch ID/Serial is required."))
        rec = self.sudo().search(
            [("active", "=", True), "|", ("serial", "=ilike", key), ("module_id", "=ilike", key)],
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
        return rec.sudo()

    @api.model
    def bind_by_serial(self, serial, company=None, department=None, location=None, location_detail=None):
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
        if location_detail is not None:
            vals["location_detail"] = location_detail
        rec.write(vals)
        rec.mark_schedule_dirty(auto_sync=True)
        return rec.with_env(self.env)

    def action_unbind(self):
        for rec in self:
            rec.write(
                {
                    "company_id": False,
                    "department_id": False,
                    "location_id": False,
                    "location_detail": False,
                    "group_ids": [(5, 0, 0)],
                    "schedule_dirty": True,
                }
            )
            rec._force_schedule_clear()

    def _delay_locked_devices(self):
        now = fields.Datetime.now()
        return self.filtered(lambda d: d.delay_active and (not d.delay_end_at or d.delay_end_at > now))

    def _ensure_not_delay_locked(self):
        locked = self._delay_locked_devices()
        if locked:
            names = ", ".join(locked.mapped("display_name"))
            raise UserError(_("Delay mode is active. This action is blocked for: %s") % names)

    def _publish_command(self, command, payload=None, raise_on_fail=True, retain=False, return_details=False):
        icp = self.env["ir.config_parameter"].sudo()
        middleware_enabled = str(icp.get_param("iot_control_center.middleware_enabled", "False")).lower() in ("1", "true", "yes")
        if middleware_enabled:
            return self._publish_command_via_middleware(
                command,
                payload=payload,
                raise_on_fail=raise_on_fail,
                retain=retain,
                return_details=return_details,
            )

        mqtt_host = self.env["ir.config_parameter"].sudo().get_param("iot_control_center.mqtt_host")
        if not mqtt_host or str(mqtt_host).strip().lower() in ("false", ""):
            if raise_on_fail:
                raise UserError(_("MQTT is not configured. Please set broker settings first."))
            return False
        payload = payload or {}
        all_ok = True
        succeeded = self.browse()
        for rec in self:
            command_id = rec._command_identity()
            topic = f"{self._mqtt_topic_root()}/{command_id}/command"
            command_payload = dict(payload)
            if command == "relay" and command_payload.get("state") in ("on", "off"):
                command_payload["command_id"] = uuid.uuid4().hex
            body = {"command": command, **command_payload}
            ok = publish_once(self.env, topic, json.dumps(body, separators=(",", ":")), retain=retain)
            if not ok:
                all_ok = False
                if raise_on_fail:
                    raise UserError(_("Failed to publish MQTT command for %s") % rec.display_name)
                continue
            succeeded |= rec
            command_at = fields.Datetime.now()
            # Metadata write should never block command success.
            # Under concurrent MQTT/status updates, this row can be hot.
            try:
                self._run_with_serialization_retry(
                    lambda: rec.with_context(**self._system_no_track_context()).write(
                        self._relay_command_metadata(command, command_payload, body, command_at)
                    )
                )
            except Exception as exc:
                _logger.warning("Skip command metadata write for %s due to contention: %s", rec.display_name, exc)
        if return_details:
            return all_ok, succeeded
        return all_ok

    def _publish_command_via_middleware(self, command, payload=None, raise_on_fail=True, retain=False, return_details=False):
        icp = self.env["ir.config_parameter"].sudo()
        base_url = (icp.get_param("iot_control_center.middleware_base_url") or "").strip().rstrip("/")
        token = (icp.get_param("iot_control_center.middleware_token") or "").strip()
        if not base_url:
            if raise_on_fail:
                raise UserError(_("Middleware is enabled but Middleware Base URL is empty."))
            return False
        payload = payload or {}
        headers = {"Content-Type": "application/json"}
        if token:
            headers["X-IoT-Middleware-Token"] = token

        all_ok = True
        succeeded = self.browse()
        for rec in self:
            command_id = rec._command_identity()
            endpoint = f"{base_url}/v1/switch/{urlparse.quote(command_id, safe='')}/command"
            command_payload = dict(payload)
            if command == "relay" and command_payload.get("state") in ("on", "off"):
                command_payload["command_id"] = uuid.uuid4().hex
            body = {"command": command, "payload": command_payload, "retain": bool(retain)}
            req = urlrequest.Request(
                endpoint,
                data=json.dumps(body, separators=(",", ":")).encode("utf-8"),
                headers=headers,
                method="POST",
            )
            ok = True
            try:
                with urlrequest.urlopen(req, timeout=8) as resp:
                    code = getattr(resp, "status", 200)
                    if code < 200 or code >= 300:
                        ok = False
            except (urlerror.URLError, urlerror.HTTPError, TimeoutError) as exc:
                _logger.warning("Middleware command publish failed for %s via %s: %s", rec.serial, endpoint, exc)
                ok = False

            if not ok:
                all_ok = False
                if raise_on_fail:
                    raise UserError(_("Failed to publish MQTT command for %s") % rec.display_name)
                continue
            succeeded |= rec
            command_at = fields.Datetime.now()

            try:
                self._run_with_serialization_retry(
                    lambda: rec.with_context(**self._system_no_track_context()).write(
                        self._relay_command_metadata(command, command_payload, body, command_at)
                    )
                )
            except Exception as exc:
                _logger.warning("Skip command metadata write for %s due to contention: %s", rec.display_name, exc)

        if return_details:
            return all_ok, succeeded
        return all_ok

    def _network_config_payload(self):
        self.ensure_one()
        icp = self.env["ir.config_parameter"].sudo()
        public_host = (icp.get_param("iot_control_center.mqtt_host") or "").strip()
        try:
            public_port = int(icp.get_param("iot_control_center.mqtt_port", 1883) or 1883)
        except (TypeError, ValueError):
            public_port = 1883
        internal_endpoint = self.company_id.get_iot_internal_mqtt_endpoint() if self.company_id else False
        if internal_endpoint:
            primary_host, primary_port = internal_endpoint
            fallback_host = public_host if public_host and public_host != primary_host else ""
            fallback_port = public_port
        else:
            primary_host, primary_port = public_host, public_port
            fallback_host, fallback_port = "", public_port
        ota_base_url = self.company_id.get_iot_internal_ota_base_url() if self.company_id else False
        ota_base_url = ota_base_url or icp.get_param("iot_control_center.firmware_base_url") or ""
        return {
            "mqtt_primary_host": primary_host,
            "mqtt_primary_port": primary_port,
            "mqtt_fallback_host": fallback_host,
            "mqtt_fallback_port": fallback_port,
            "ota_base_url": ota_base_url,
        }

    @api.model
    def _firmware_supports_network_config(self, version):
        try:
            parts = tuple(int(part) for part in str(version or "").split(".")[:3])
        except (TypeError, ValueError):
            return False
        return parts >= (1, 8, 10)

    def _sync_network_config(self, raise_on_error=False):
        all_ok = True
        for rec in self:
            payload = rec._network_config_payload()
            if not payload["mqtt_primary_host"]:
                all_ok = False
                if raise_on_error:
                    raise UserError(_("No MQTT endpoint is configured for %s") % rec.display_name)
                continue
            ok = rec._publish_command("network_set", payload, raise_on_fail=raise_on_error)
            all_ok = all_ok and ok
        return all_ok

    def action_sync_network_config(self):
        self._sync_network_config(raise_on_error=True)
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Network configuration"),
                "message": _("Company internal network settings were sent to the selected controller(s)."),
                "type": "success",
                "sticky": False,
            },
        }

    def action_turn_on(self):
        self._ensure_not_delay_locked()
        devices = self.sudo()
        all_ok = True
        for rec in devices:
            ok = rec._publish_command(
                "relay",
                {"state": "on", "max_on_sec": rec._max_on_seconds()},
                raise_on_fail=False,
            )
            all_ok = all_ok and ok
        if all_ok:
            return {
                "type": "ir.actions.client",
                "tag": "display_notification",
                "params": {
                    "title": _("Switch command"),
                    "message": _("Turn on command sent; waiting for device confirmation."),
                    "sticky": False,
                    "type": "success",
                },
            }
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
        devices = self.sudo()
        all_ok = True
        for rec in devices:
            ok = rec._publish_command(
                "relay",
                {"state": "off", "max_on_sec": rec._max_on_seconds()},
                raise_on_fail=False,
            )
            all_ok = all_ok and ok
        if all_ok:
            return {
                "type": "ir.actions.client",
                "tag": "display_notification",
                "params": {
                    "title": _("Switch command"),
                    "message": _("Turn off command sent; waiting for device confirmation."),
                    "sticky": False,
                    "type": "success",
                },
            }
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
        all_ok = True
        for rec in self.sudo():
            duration_min = max(int(rec.delay_duration_minutes or 0), 1)
            ok = rec._publish_command(
                "delay_toggle",
                {"duration_sec": duration_min * 60, "max_on_sec": rec._max_on_seconds()},
                raise_on_fail=False,
            )
            all_ok = all_ok and ok

        if all_ok:
            return {
                "type": "ir.actions.client",
                "tag": "display_notification",
                "params": {
                    "title": _("Delay switch"),
                    "message": _("Delay command sent."),
                    "sticky": False,
                    "type": "success",
                },
            }
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
            tz = pytz.timezone(rec.get_company_timezone())
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

    def _schedule_timezone_snapshot(self):
        self.ensure_one()
        company = self.company_id or self.env.company
        timezone_name = company.get_iot_timezone()
        timezone = pytz.timezone(timezone_name)
        offset_min = int((datetime.now(timezone).utcoffset() or timedelta()).total_seconds() // 60)
        return timezone_name, offset_min

    def _sync_schedule_payload(self, raise_on_error=False):
        for rec in self:
            next_version = rec.schedule_version + 1
            try:
                timezone_name, offset_min = rec._schedule_timezone_snapshot()
                entries = rec._iter_schedule_entries()
                ok = False
                if entries:
                    ok = rec._publish_command(
                        "schedule_set",
                        {
                            "version": next_version,
                            "entries": entries,
                            "max_on_sec": rec._max_on_seconds(),
                        },
                        raise_on_fail=raise_on_error,
                        retain=True,
                    )
                else:
                    ok = rec._publish_command(
                        "schedule_clear",
                        {"version": next_version, "max_on_sec": rec._max_on_seconds()},
                        raise_on_fail=raise_on_error,
                        retain=True,
                    )
                if not ok:
                    rec.schedule_dirty = True
                    if raise_on_error:
                        raise UserError(_("Failed to publish MQTT command for %s") % rec.display_name)
                    continue
                rec.schedule_version = next_version
                rec.schedule_last_push_at = fields.Datetime.now()
                rec.schedule_timezone_name = timezone_name
                rec.schedule_timezone_offset_min = offset_min
                rec.schedule_dirty = False
            except Exception as exc:
                rec.schedule_dirty = True
                if raise_on_error:
                    raise
                _logger.warning("Auto schedule sync failed for %s: %s", rec.display_name, exc)

    def _force_schedule_clear(self, raise_on_error=False):
        for rec in self:
            next_version = rec.schedule_version + 1
            try:
                ok = rec._publish_command(
                    "schedule_clear",
                    {"version": next_version, "max_on_sec": rec._max_on_seconds()},
                    raise_on_fail=raise_on_error,
                    retain=True,
                )
                if not ok:
                    rec.schedule_dirty = True
                    if raise_on_error:
                        raise UserError(_("Failed to publish MQTT command for %s") % rec.display_name)
                    continue
                rec.schedule_version = next_version
                rec.schedule_last_push_at = fields.Datetime.now()
                rec.schedule_dirty = False
            except Exception as exc:
                rec.schedule_dirty = True
                if raise_on_error:
                    raise
                _logger.warning("Schedule clear failed for %s: %s", rec.display_name, exc)

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
            if rec.last_seen and at < rec.last_seen:
                continue
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

    def apply_command_ack(self, payload, reported_at=None):
        if not isinstance(payload, dict):
            return
        command_id = str(payload.get("last_command_id") or payload.get("command_id") or "").strip()
        state = payload.get("state")
        if not command_id:
            return
        at = reported_at or fields.Datetime.now()
        for rec in self:
            if command_id != (rec.last_command_id or ""):
                continue
            if rec.desired_relay_state in ("on", "off") and state == rec.desired_relay_state:
                rec.relay_command_state = "confirmed"
                rec.last_command_confirmed_at = at

    def apply_schedule_report(self, payload, reported_at=None):
        at = reported_at or fields.Datetime.now()
        for rec in self:
            version = payload.get("schedule_version") if isinstance(payload, dict) else None
            try:
                version = int(version) if version is not None else None
            except Exception:
                version = None
            if version is not None and version >= rec.schedule_applied_version:
                rec.schedule_applied_version = version
                rec.schedule_last_sync_at = at
            if not rec.last_seen or at >= rec.last_seen:
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
                owner = self.sudo().search(
                    [
                        ("id", "!=", rec.id),
                        ("active", "=", True),
                        ("module_id", "=ilike", module_id),
                    ],
                    limit=1,
                )
                if owner:
                    _logger.warning(
                        "Ignore conflicting module identity %s for %s; already owned by %s",
                        module_id,
                        rec.display_name,
                        owner.display_name,
                    )
                    continue
                rec.module_id = module_id
            if not rec.last_seen or at >= rec.last_seen:
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
            if prev_version and reported_version and prev_version != reported_version:
                rec.network_config_dirty = True
                rec._sync_network_config(raise_on_error=False)

    def apply_runtime_report(self, payload, reported_at=None):
        if not isinstance(payload, dict):
            return
        at = reported_at or fields.Datetime.now()
        for rec in self:
            vals = {}
            if payload.get("hardware_profile"):
                vals["firmware_hardware_profile"] = str(payload["hardware_profile"])
            for payload_key, field_name in (
                ("flash_real_size", "flash_real_size_bytes"),
                ("free_heap", "free_heap_bytes"),
            ):
                if payload.get(payload_key) is not None:
                    try:
                        vals[field_name] = int(payload[payload_key])
                    except (TypeError, ValueError):
                        pass
            active_host = str(payload.get("mqtt_host") or "").strip()
            route = str(payload.get("mqtt_route") or "").strip()
            if active_host:
                vals["mqtt_active_host"] = active_host
            if route in ("primary", "fallback"):
                vals["mqtt_route"] = route
            if active_host and rec._firmware_supports_network_config(rec.firmware_version):
                desired = rec._network_config_payload()
                primary_match = route == "primary" and active_host == desired["mqtt_primary_host"]
                fallback_match = route == "fallback" and active_host == desired["mqtt_fallback_host"]
                if primary_match or fallback_match:
                    vals["network_config_dirty"] = False
            if not rec.last_seen or at >= rec.last_seen:
                vals["last_seen"] = at
            if vals:
                rec.write(vals)

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
        if self:
            target = self.with_context(**self._system_no_track_context())
            self._run_with_serialization_retry(lambda: target.write({"schedule_dirty": True}))
        if auto_sync and self:
            self._sync_schedule_payload(raise_on_error=False)

    def write(self, vals):
        needs_auto_sync = bool({"group_ids", "max_continuous_on_minutes"} & set(vals))
        runtime_only = bool(vals) and set(vals).issubset(self._runtime_no_track_fields())
        if runtime_only:
            res = super(IoTDevice, self.with_context(**self._system_no_track_context())).write(vals)
        else:
            res = super().write(vals)
        if needs_auto_sync:
            self.mark_schedule_dirty(auto_sync=True)
        return res

    @api.model
    def _cron_ensure_mqtt_service(self):
        icp = self.env["ir.config_parameter"].sudo()
        middleware_enabled = str(icp.get_param("iot_control_center.middleware_enabled", "False")).lower() in ("1", "true", "yes")
        if not middleware_enabled:
            ensure_running(self.env)
        now = fields.Datetime.now()
        expired = self.with_context(**self._system_no_track_context()).search(
            [("delay_active", "=", True), ("delay_end_at", "!=", False), ("delay_end_at", "<=", now)]
        )
        if expired:
            self._run_with_serialization_retry(
                lambda: expired.write({"delay_active": False, "delay_started_at": False, "delay_end_at": False})
            )
        command_timeout = now - timedelta(minutes=2)
        timed_out = self.with_context(**self._system_no_track_context()).search(
            [
                ("relay_command_state", "=", "pending"),
                ("last_command_at", "!=", False),
                ("last_command_at", "<=", command_timeout),
            ]
        )
        if timed_out:
            timed_out.write({"relay_command_state": "timeout"})
        self._cron_retry_dirty_schedule_sync()
        self._cron_retry_network_config_sync()

    @api.model
    def _cron_retry_dirty_schedule_sync(self):
        """Retry schedule sync for online devices when previous push failed/offline."""
        timeout = int(self.env["ir.config_parameter"].sudo().get_param("iot_control_center.online_timeout_sec", 300))
        recent_cutoff = fields.Datetime.now() - timedelta(seconds=max(timeout, 60) * 2)
        dirty_devices = self.with_context(**self._system_no_track_context()).search(
            [
                ("schedule_dirty", "=", True),
                "|",
                ("company_id", "!=", False),
                ("schedule_version", ">", 0),
                ("last_seen", ">=", recent_cutoff),
            ],
            limit=200,
        )
        if not dirty_devices:
            return
        self._run_with_serialization_retry(lambda: dirty_devices._sync_schedule_payload(raise_on_error=False))

    @api.model
    def _cron_refresh_company_timezone_offsets(self):
        """Resend local schedules when a company timezone offset changes."""
        schedules = self.env["iot.schedule"].sudo().search([("active", "=", True)])
        devices = (schedules.mapped("device_id") | schedules.mapped("group_id.device_ids")).filtered(
            lambda device: device.active and device.company_id
        )
        changed = self.browse()
        for device in devices:
            try:
                timezone_name, offset_min = device._schedule_timezone_snapshot()
            except Exception as exc:
                _logger.warning("Unable to resolve company timezone for %s: %s", device.display_name, exc)
                continue
            if (
                device.schedule_timezone_name != timezone_name
                or device.schedule_timezone_offset_min != offset_min
            ):
                changed |= device
        if changed:
            changed.with_context(**self._system_no_track_context()).write({"schedule_dirty": True})
        self._cron_retry_dirty_schedule_sync()

    @api.model
    def _cron_retry_network_config_sync(self):
        timeout = int(self.env["ir.config_parameter"].sudo().get_param("iot_control_center.online_timeout_sec", 300))
        cutoff = fields.Datetime.now() - timedelta(seconds=max(timeout, 60) * 2)
        devices = self.with_context(**self._system_no_track_context()).search(
            [
                ("network_config_dirty", "=", True),
                ("last_seen", ">=", cutoff),
                ("company_id", "!=", False),
            ],
            limit=200,
        )
        supported = devices.filtered(lambda device: self._firmware_supports_network_config(device.firmware_version))
        if supported:
            supported._sync_network_config(raise_on_error=False)

    @api.model
    def _cron_update_live_uptime(self):
        def _do_update():
            devices = self.with_context(**self._system_no_track_context()).search(
                [("relay_state", "=", "on"), ("on_since", "!=", False)]
            )
            if devices:
                now = fields.Datetime.now()
                devices._accumulate_on_minutes_until(now)

        self._run_with_serialization_retry(_do_update)

    @api.model
    def _cron_dedupe_devices(self):
        # Keep the latest active row for each identity. Archive duplicates instead
        # of deleting rows so related history remains auditable.
        self.env.cr.execute(
            """
            WITH ranked AS (
                SELECT
                    id,
                    ROW_NUMBER() OVER (
                        PARTITION BY lower(serial)
                        ORDER BY
                            CASE WHEN company_id IS NULL THEN 1 ELSE 0 END,
                            last_seen DESC NULLS LAST,
                            write_date DESC NULLS LAST,
                            id DESC
                    ) AS rn
                FROM iot_device
                WHERE active IS TRUE
                  AND serial IS NOT NULL
                  AND btrim(serial) <> ''
            )
            UPDATE iot_device d
               SET active = FALSE,
                   company_id = NULL,
                   write_date = NOW()
              FROM ranked r
             WHERE d.id = r.id
               AND r.rn > 1
            """
        )
        self._archive_duplicate_identity_rows()

    @api.model
    def _cron_purge_stale_devices(self):
        icp = self.env["ir.config_parameter"].sudo()
        retention_days_raw = icp.get_param("iot_control_center.device_retention_days", "30")
        try:
            retention_days = max(int(retention_days_raw or 30), 1)
        except Exception:
            retention_days = 30
        cutoff = fields.Datetime.now() - timedelta(days=retention_days)
        # Keep bound devices; purge only unbound stale rows to prevent table bloat.
        self.env.cr.execute(
            """
            DELETE FROM iot_device
            WHERE (company_id IS NULL)
              AND (last_seen IS NULL OR last_seen < %s)
              AND (firmware_upgrade_state IS NULL OR firmware_upgrade_state <> 'pending')
            """,
            [cutoff],
        )
