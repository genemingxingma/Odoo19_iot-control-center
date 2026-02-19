from odoo import fields, models


class IoTLocation(models.Model):
    _name = "iot.location"
    _description = "IoT Location"

    name = fields.Char(required=True)
    company_id = fields.Many2one("res.company", required=True, default=lambda self: self.env.company)
    department_id = fields.Many2one("iot.department", domain="[('company_id', '=', company_id)]")
    active = fields.Boolean(default=True)

    _sql_constraints = [
        ("iot_location_company_name_uniq", "unique(name, company_id)", "Location name must be unique per company."),
    ]
