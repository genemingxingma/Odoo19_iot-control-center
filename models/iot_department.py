from odoo import fields, models


class IoTDepartment(models.Model):
    _name = "iot.department"
    _description = "IoT Department"

    name = fields.Char(required=True)
    company_id = fields.Many2one("res.company", required=True, default=lambda self: self.env.company)
    active = fields.Boolean(default=True)

    _company_name_uniq = models.Constraint(
        "UNIQUE(name, company_id)",
        "Department name must be unique per company.",
    )
