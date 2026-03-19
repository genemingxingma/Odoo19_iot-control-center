from datetime import timedelta

from odoo import api, fields, models


class IoTFirmwareUpgradeLog(models.Model):
    _name = "iot.firmware.upgrade.log"
    _description = "IoT Firmware Upgrade Log"
    _order = "requested_at desc, id desc"

    device_id = fields.Many2one("iot.device", required=True, ondelete="cascade", index=True)
    firmware_id = fields.Many2one("iot.firmware", ondelete="set null", index=True)
    company_id = fields.Many2one(related="device_id.company_id", store=True, index=True)

    target_version = fields.Char(required=True, index=True)
    reported_version = fields.Char(index=True)
    state = fields.Selection(
        [("pending", "Pending"), ("success", "Success"), ("mismatch", "Mismatch"), ("failed", "Failed")],
        default="pending",
        required=True,
        index=True,
    )
    requested_at = fields.Datetime(default=fields.Datetime.now, required=True, index=True)
    completed_at = fields.Datetime(index=True)
    command_payload = fields.Text()
    note = fields.Char()

    @api.model
    def init(self):
        self.env.cr.execute(
            """
            CREATE INDEX IF NOT EXISTS iot_firmware_upgrade_log_state_requested_idx
            ON iot_firmware_upgrade_log (state, requested_at DESC, id DESC)
            """
        )

    @api.model
    def _cron_trim_old_payloads(self, batch_size=5000):
        icp = self.env["ir.config_parameter"].sudo()
        retention_days_raw = icp.get_param("iot_control_center.firmware_log_payload_retention_days", "7")
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
                    FROM iot_firmware_upgrade_log
                    WHERE command_payload IS NOT NULL
                      AND state <> 'pending'
                      AND requested_at < %s
                    ORDER BY id
                    LIMIT %s
                )
                UPDATE iot_firmware_upgrade_log log
                SET command_payload = NULL
                FROM doomed
                WHERE log.id = doomed.id
                """,
                [cutoff, int(batch_size)],
            )
            if self.env.cr.rowcount < int(batch_size):
                break

    @api.model
    def _cron_purge_old_logs(self, batch_size=5000):
        icp = self.env["ir.config_parameter"].sudo()
        retention_days_raw = icp.get_param("iot_control_center.firmware_log_retention_days", "90")
        try:
            retention_days = max(int(retention_days_raw or 90), 1)
        except Exception:
            retention_days = 90

        cutoff = fields.Datetime.now() - timedelta(days=retention_days)
        while True:
            self.env.cr.execute(
                """
                WITH doomed AS (
                    SELECT id
                    FROM iot_firmware_upgrade_log
                    WHERE state <> 'pending'
                      AND requested_at < %s
                    ORDER BY id
                    LIMIT %s
                )
                DELETE FROM iot_firmware_upgrade_log log
                USING doomed
                WHERE log.id = doomed.id
                """,
                [cutoff, int(batch_size)],
            )
            if self.env.cr.rowcount < int(batch_size):
                break
