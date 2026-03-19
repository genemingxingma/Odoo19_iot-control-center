from datetime import timedelta

from odoo import api, fields, models


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

    @api.model
    def init(self):
        self.env.cr.execute(
            """
            CREATE INDEX IF NOT EXISTS iot_attendance_request_create_date_id_idx
            ON iot_attendance_request (create_date DESC, id DESC)
            """
        )
        self.env.cr.execute(
            """
            CREATE INDEX IF NOT EXISTS iot_attendance_request_device_create_idx
            ON iot_attendance_request (device_id, create_date DESC, id DESC)
            """
        )
        self.env.cr.execute(
            """
            CREATE INDEX IF NOT EXISTS iot_attendance_request_serial_create_idx
            ON iot_attendance_request (serial_number, create_date DESC, id DESC)
            """
        )

    @api.model
    def _cron_purge_old_requests(self, batch_size=10000):
        icp = self.env["ir.config_parameter"].sudo()
        retention_days_raw = icp.get_param("iot_control_center.attendance_request_retention_days", "7")
        try:
            retention_days = max(int(retention_days_raw or 7), 1)
        except Exception:
            retention_days = 7

        cutoff = fields.Datetime.now() - timedelta(days=retention_days)
        while True:
            self.env.cr.execute(
                """
                WITH doomed AS (
                    SELECT id
                    FROM iot_attendance_request
                    WHERE create_date < %s
                    ORDER BY id
                    LIMIT %s
                )
                DELETE FROM iot_attendance_request req
                USING doomed
                WHERE req.id = doomed.id
                """,
                [cutoff, int(batch_size)],
            )
            if self.env.cr.rowcount < int(batch_size):
                break
