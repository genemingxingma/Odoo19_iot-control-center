from odoo import fields, models


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
