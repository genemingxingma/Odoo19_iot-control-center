from odoo import fields, models


class IoTAttendanceRequest(models.Model):
    _name = "iot.attendance.request"
    _description = "IoT Attendance Request Log"
    _order = "create_date desc, id desc"

    create_date = fields.Datetime(readonly=True)
    device_id = fields.Many2one("iot.attendance.device", ondelete="set null", index=True)
    company_id = fields.Many2one(related="device_id.company_id", store=True, readonly=True)
    endpoint = fields.Char(required=True, index=True)
    method = fields.Char(required=True, index=True)
    serial_number = fields.Char(index=True)
    remote_ip = fields.Char(index=True)
    query_params = fields.Text()
    headers = fields.Text()
    payload_text = fields.Text()
    status = fields.Selection(
        [("received", "Received"), ("matched", "Matched"), ("parsed", "Parsed"), ("ignored", "Ignored"), ("error", "Error")],
        required=True,
        default="received",
        index=True,
    )
    note = fields.Char()
