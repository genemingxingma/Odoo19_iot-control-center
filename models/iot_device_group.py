from odoo import api, fields, models


class IoTDeviceGroup(models.Model):
    _name = "iot.device.group"
    _description = "IoT Device Group"
    _order = "name"

    name = fields.Char(required=True)
    active = fields.Boolean(default=True)
    company_id = fields.Many2one("res.company", required=True, default=lambda self: self.env.company, index=True)
    department_id = fields.Many2one("iot.department", domain="[('company_id', '=', company_id)]")
    location_id = fields.Many2one("iot.location", domain="[('company_id', '=', company_id)]")

    device_ids = fields.Many2many(
        "iot.device",
        "iot_device_group_rel",
        "group_id",
        "device_id",
        string="Switches",
        domain="[('company_id', '=', company_id), ('active', '=', True)]",
    )
    schedule_ids = fields.One2many("iot.schedule", "group_id", string="Schedules")

    def action_turn_on(self):
        self.mapped("device_ids").action_turn_on()

    def action_turn_off(self):
        self.mapped("device_ids").action_turn_off()

    def action_sync_schedule(self):
        devices = self.mapped("device_ids")
        devices.mark_schedule_dirty(auto_sync=True)

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        records.mapped("device_ids").mark_schedule_dirty(auto_sync=True)
        return records

    def write(self, vals):
        before = self.mapped("device_ids")
        res = super().write(vals)
        if "device_ids" in vals:
            devices = before | self.mapped("device_ids")
            devices.mark_schedule_dirty(auto_sync=True)
        return res

    def unlink(self):
        devices = self.mapped("device_ids")
        res = super().unlink()
        devices.mark_schedule_dirty(auto_sync=True)
        return res
