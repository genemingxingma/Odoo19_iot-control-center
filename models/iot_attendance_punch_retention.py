from datetime import timedelta

from odoo import api, fields, models


class IoTAttendancePunchRetention(models.Model):
    _inherit = "iot.attendance.punch"

    @api.model
    def _cron_purge_old_raw_payloads(self, batch_size=10000):
        icp = self.env["ir.config_parameter"].sudo()
        retention_days_raw = icp.get_param("iot_control_center.attendance_punch_raw_retention_days", "7")
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
                    FROM iot_attendance_punch
                    WHERE raw_payload IS NOT NULL
                      AND state IN ('processed', 'ignored')
                      AND punch_time < %s
                    ORDER BY id
                    LIMIT %s
                )
                UPDATE iot_attendance_punch punch
                SET raw_payload = NULL
                FROM doomed
                WHERE punch.id = doomed.id
                """,
                [cutoff, int(batch_size)],
            )
            if self.env.cr.rowcount < int(batch_size):
                break
