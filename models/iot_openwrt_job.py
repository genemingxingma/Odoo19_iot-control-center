from datetime import timedelta

from odoo import api, fields, models


class IoTOpenwrtJob(models.Model):
    _name = "iot.openwrt.job"
    _description = "OpenWrt AP Job"
    _order = "requested_at desc, id desc"

    name = fields.Char(required=True)
    ap_id = fields.Many2one("iot.openwrt.ap", required=True, ondelete="cascade", index=True)
    company_id = fields.Many2one(related="ap_id.company_id", store=True, index=True)
    job_type = fields.Selection(
        [
            ("probe", "Probe"),
            ("apply_template", "Apply Template"),
            ("locate_start", "Start Locate"),
            ("locate_stop", "Stop Locate"),
            ("reboot", "Reboot"),
            ("upgrade", "Upgrade"),
        ],
        required=True,
        index=True,
    )
    state = fields.Selection(
        [
            ("pending", "Pending"),
            ("success", "Success"),
            ("failed", "Failed"),
        ],
        default="pending",
        required=True,
        index=True,
    )
    requested_at = fields.Datetime(default=fields.Datetime.now, required=True)
    completed_at = fields.Datetime()
    request_payload = fields.Text()
    response_payload = fields.Text()
    note = fields.Text()

    @api.model
    def init(self):
        self.env.cr.execute(
            """
            CREATE INDEX IF NOT EXISTS iot_openwrt_job_state_requested_idx
            ON iot_openwrt_job (state, requested_at DESC, id DESC)
            """
        )

    @api.model
    def _cron_trim_old_payloads(self, batch_size=5000):
        icp = self.env["ir.config_parameter"].sudo()
        retention_days_raw = icp.get_param("iot_control_center.openwrt_job_payload_retention_days", "7")
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
                    FROM iot_openwrt_job
                    WHERE (request_payload IS NOT NULL OR response_payload IS NOT NULL)
                      AND state <> 'pending'
                      AND requested_at < %s
                    ORDER BY id
                    LIMIT %s
                )
                UPDATE iot_openwrt_job job
                SET request_payload = NULL,
                    response_payload = NULL
                FROM doomed
                WHERE job.id = doomed.id
                """,
                [cutoff, int(batch_size)],
            )
            if self.env.cr.rowcount < int(batch_size):
                break

    @api.model
    def _cron_purge_old_jobs(self, batch_size=5000):
        icp = self.env["ir.config_parameter"].sudo()
        retention_days_raw = icp.get_param("iot_control_center.openwrt_job_retention_days", "30")
        try:
            retention_days = max(int(retention_days_raw or 30), 1)
        except Exception:
            retention_days = 30

        cutoff = fields.Datetime.now() - timedelta(days=retention_days)
        while True:
            self.env.cr.execute(
                """
                WITH doomed AS (
                    SELECT id
                    FROM iot_openwrt_job
                    WHERE state <> 'pending'
                      AND requested_at < %s
                    ORDER BY id
                    LIMIT %s
                )
                DELETE FROM iot_openwrt_job job
                USING doomed
                WHERE job.id = doomed.id
                """,
                [cutoff, int(batch_size)],
            )
            if self.env.cr.rowcount < int(batch_size):
                break
