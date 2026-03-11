from odoo import fields, models


class HrEmployee(models.Model):
    _inherit = "hr.employee"

    biometric_code = fields.Char(
        string="Biometric Code",
        help="Primary employee code used by attendance devices.",
        index=True,
        copy=False,
    )
    iot_attendance_user_ids = fields.One2many(
        "iot.attendance.user",
        "employee_id",
        string="IoT Attendance Users",
    )
