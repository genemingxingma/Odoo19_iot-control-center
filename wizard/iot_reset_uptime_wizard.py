from odoo import _, fields, models
from odoo.exceptions import UserError


class IoTResetUptimeWizard(models.TransientModel):
    _name = "iot.reset.uptime.wizard"
    _description = "Reset Accumulated Time Wizard"

    device_id = fields.Many2one("iot.device", string="Switch", required=True, readonly=True)
    current_total_hours = fields.Float(string="Current Accumulated Hours", readonly=True)
    reason = fields.Text(string="Reset Reason", required=True)

    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        device_id = res.get("device_id") or self.env.context.get("default_device_id")
        if device_id:
            device = self.env["iot.device"].browse(device_id)
            res["current_total_hours"] = device.total_on_hours
        return res

    def action_confirm_reset(self):
        self.ensure_one()
        reason = (self.reason or "").strip()
        if not reason:
            raise UserError(_("Reset reason is required."))
        self.device_id.action_reset_uptime_with_reason(reason)
        return {"type": "ir.actions.act_window_close"}
