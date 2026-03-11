from odoo import api, fields, models
from odoo.exceptions import ValidationError


class IoTAttendanceUser(models.Model):
    _name = "iot.attendance.user"
    _description = "IoT Attendance User Mapping"
    _order = "device_id, device_user_id, id"

    name = fields.Char(compute="_compute_name", store=True)
    active = fields.Boolean(default=True)
    device_id = fields.Many2one("iot.attendance.device", required=True, ondelete="cascade")
    employee_id = fields.Many2one("hr.employee", required=True, ondelete="cascade")
    device_user_id = fields.Char(required=True, help="Enroll/PIN code used by the attendance device.")
    device_uid = fields.Char(help="Optional internal UID returned by the device.")
    company_id = fields.Many2one(related="device_id.company_id", store=True, readonly=True)
    last_seen_at = fields.Datetime(readonly=True, copy=False)

    _sql_constraints = [
        ("iot_attendance_user_unique", "unique(device_id, device_user_id)", "The device user ID must be unique per device."),
    ]

    @api.depends("device_id.name", "employee_id.name", "device_user_id")
    def _compute_name(self):
        for rec in self:
            rec.name = " / ".join([p for p in [rec.device_id.name, rec.employee_id.name, rec.device_user_id] if p])

    @api.constrains("device_user_id")
    def _check_device_user_id(self):
        for rec in self:
            if rec.device_user_id and not rec.device_user_id.strip():
                raise ValidationError("Device User ID cannot be empty.")
