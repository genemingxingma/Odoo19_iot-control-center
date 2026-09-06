from odoo import _, models
from odoo.exceptions import AccessError

class IoTAccess(models.AbstractModel):
    _name = "iot.access.mixin"
    _description = "IoT Operation Authorization"

    def _check_iot_access(self, manage=False):
        group = "iot_control_center.group_iot_manager" if manage else "iot_control_center.group_iot_operator"
        if not self.env.su and not self.env.user.has_group(group):
            raise AccessError(_("You are not authorized to control these IoT devices."))
        self.check_access("read")
        if not self.env.su and any(record.company_id not in self.env.companies for record in self):
            raise AccessError(_("The device belongs to another company."))
