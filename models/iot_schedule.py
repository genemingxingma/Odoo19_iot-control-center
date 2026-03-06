import math

import pytz

from odoo import api, fields, models
from odoo.exceptions import ValidationError


class IoTSchedule(models.Model):
    _name = "iot.schedule"
    _description = "IoT Relay Schedule"

    name = fields.Char(required=True)
    active = fields.Boolean(default=True)

    device_id = fields.Many2one("iot.device", ondelete="cascade")
    group_id = fields.Many2one("iot.device.group", ondelete="cascade")
    company_id = fields.Many2one("res.company", compute="_compute_company_id", store=True, index=True)

    command = fields.Selection([("on", "Turn On"), ("off", "Turn Off")], required=True, default="on")
    timezone = fields.Selection(selection=lambda self: [(tz, tz) for tz in pytz.all_timezones], default="UTC", required=True)
    hour = fields.Integer(default=8, required=True)
    minute = fields.Integer(default=0, required=True)
    time_float = fields.Float(
        string="Time",
        compute="_compute_time_float",
        inverse="_inverse_time_float",
        store=False,
    )

    monday = fields.Boolean(default=True)
    tuesday = fields.Boolean(default=True)
    wednesday = fields.Boolean(default=True)
    thursday = fields.Boolean(default=True)
    friday = fields.Boolean(default=True)
    saturday = fields.Boolean(default=False)
    sunday = fields.Boolean(default=False)

    def get_enabled_weekdays(self):
        self.ensure_one()
        out = []
        if self.monday:
            out.append(0)
        if self.tuesday:
            out.append(1)
        if self.wednesday:
            out.append(2)
        if self.thursday:
            out.append(3)
        if self.friday:
            out.append(4)
        if self.saturday:
            out.append(5)
        if self.sunday:
            out.append(6)
        return out

    @api.depends("device_id.company_id", "group_id.company_id")
    def _compute_company_id(self):
        for rec in self:
            rec.company_id = rec.device_id.company_id or rec.group_id.company_id

    @api.depends("hour", "minute")
    def _compute_time_float(self):
        for rec in self:
            h = rec.hour if isinstance(rec.hour, int) else 0
            m = rec.minute if isinstance(rec.minute, int) else 0
            rec.time_float = float(h) + (float(m) / 60.0)

    def _inverse_time_float(self):
        for rec in self:
            v = rec.time_float
            if v is None:
                raise ValidationError("Time is required.")
            try:
                fv = float(v)
            except Exception:
                raise ValidationError("Invalid time format. Please use HH:MM.")
            if math.isnan(fv) or math.isinf(fv):
                raise ValidationError("Invalid time format. Please use HH:MM.")
            if fv < 0.0 or fv >= 24.0:
                raise ValidationError("Time must be between 00:00 and 23:59.")

            total_minutes = int(round(fv * 60.0))
            if total_minutes >= 24 * 60:
                total_minutes = (24 * 60) - 1
            if total_minutes < 0:
                total_minutes = 0
            rec.hour = total_minutes // 60
            rec.minute = total_minutes % 60

    def _mark_related_devices_dirty(self):
        devices = self.mapped("device_id") | self.mapped("group_id.device_ids")
        # Avoid blocking schedule save under high-frequency telemetry writes.
        # Dirty mark is enough; cron will retry push asynchronously.
        devices.mark_schedule_dirty(auto_sync=False)

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        records._mark_related_devices_dirty()
        return records

    def write(self, vals):
        old_devices = self.env["iot.device"].browse()
        if "device_id" in vals or "group_id" in vals:
            old_devices = self.mapped("device_id") | self.mapped("group_id.device_ids")
        res = super().write(vals)
        devices = old_devices | self.mapped("device_id") | self.mapped("group_id.device_ids")
        devices.mark_schedule_dirty(auto_sync=False)
        return res

    def unlink(self):
        devices = self.mapped("device_id") | self.mapped("group_id.device_ids")
        res = super().unlink()
        devices.mark_schedule_dirty(auto_sync=False)
        return res

    @api.constrains("hour", "minute")
    def _check_time(self):
        for rec in self:
            if rec.hour < 0 or rec.hour > 23:
                raise ValidationError("Hour must be between 0 and 23.")
            if rec.minute < 0 or rec.minute > 59:
                raise ValidationError("Minute must be between 0 and 59.")

    @api.constrains("device_id", "group_id")
    def _check_target(self):
        for rec in self:
            if bool(rec.device_id) == bool(rec.group_id):
                raise ValidationError("Schedule must be linked to exactly one target: Device or Group.")

    @api.model
    def _cron_run_schedules(self):
        # Legacy compatibility: schedule execution moved to device local runtime.
        return True
