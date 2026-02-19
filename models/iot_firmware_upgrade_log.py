from odoo import fields, models


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
