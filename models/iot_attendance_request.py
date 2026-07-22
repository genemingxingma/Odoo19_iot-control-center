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
    remote_ip = fields.Char(string="Remote IP", index=True)
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
    def _heartbeat_sample_seconds(self):
        raw_value = self.env["ir.config_parameter"].sudo().get_param(
            "iot_control_center.attendance_heartbeat_log_interval_seconds",
            "600",
        )
        try:
            return max(int(raw_value or 600), 0)
        except (TypeError, ValueError):
            return 600

    @api.model
    def create_sampled(self, vals, sample_seconds=0):
        """Create one request row per source and sampling window."""
        try:
            sample_seconds = max(int(sample_seconds or 0), 0)
        except (TypeError, ValueError):
            sample_seconds = 0
        request_model = self.sudo()
        if not sample_seconds:
            return request_model.create(vals)

        identity = "|".join(
            str(vals.get(field_name) or "")
            for field_name in (
                "endpoint",
                "method",
                "device_id",
                "serial_number",
                "remote_ip",
                "status",
                "note",
            )
        )
        self.env.cr.execute(
            "SELECT pg_advisory_xact_lock(hashtext(%s))",
            [f"iot.attendance.request:{identity}"],
        )
        cutoff = fields.Datetime.now() - timedelta(seconds=sample_seconds)
        domain = [
            ("create_date", ">=", cutoff),
            ("endpoint", "=", vals.get("endpoint")),
            ("method", "=", vals.get("method")),
            ("status", "=", vals.get("status")),
            ("note", "=", vals.get("note") or False),
        ]
        for field_name in ("device_id", "serial_number", "remote_ip"):
            domain.append((field_name, "=", vals.get(field_name) or False))
        existing = request_model.search(domain, order="create_date desc, id desc", limit=1)
        return existing or request_model.create(vals)

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
        self._compact_sampled_heartbeats(batch_size=batch_size)

    @api.model
    def _compact_sampled_heartbeats(self, batch_size=10000):
        sample_seconds = self._heartbeat_sample_seconds()
        if not sample_seconds:
            return 0

        deleted = 0
        while True:
            self.env.cr.execute(
                """
                WITH ranked AS (
                    SELECT
                        id,
                        ROW_NUMBER() OVER (
                            PARTITION BY
                                COALESCE(device_id, 0),
                                COALESCE(serial_number, ''),
                                COALESCE(remote_ip, ''),
                                endpoint,
                                status,
                                FLOOR(EXTRACT(EPOCH FROM create_date) / %s)
                            ORDER BY create_date DESC, id DESC
                        ) AS row_number
                    FROM iot_attendance_request
                    WHERE endpoint IN ('/getrequest', '/iclock', '/iclock/getrequest')
                      AND status = 'matched'
                      AND note = 'Heartbeat / getrequest'
                ),
                doomed AS (
                    SELECT id
                    FROM ranked
                    WHERE row_number > 1
                    ORDER BY id
                    LIMIT %s
                )
                DELETE FROM iot_attendance_request request
                USING doomed
                WHERE request.id = doomed.id
                """,
                [sample_seconds, int(batch_size)],
            )
            count = self.env.cr.rowcount
            deleted += count
            if count < int(batch_size):
                break
        return deleted
