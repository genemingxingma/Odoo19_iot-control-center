from odoo import _, api, fields, models
from odoo.exceptions import UserError


class IoTTHSensorBindWizard(models.TransientModel):
    _name = "iot.th.sensor.bind.wizard"
    _description = "Bind TH Node by ID"

    node_id = fields.Char(string="Node ID", required=True)
    probe_code = fields.Char(string="Probe Code (Optional)")
    validated = fields.Boolean(readonly=True, default=False)
    validated_node_id = fields.Char(readonly=True)
    validated_probe_code = fields.Char(readonly=True)
    candidate_sensor_ids = fields.Many2many("iot.th.sensor", string="Matched Sensors", readonly=True)
    candidate_count = fields.Integer(readonly=True)
    company_id = fields.Many2one(
        "res.company",
        required=True,
        default=lambda self: self.env.company,
        domain=lambda self: [("id", "in", self.env.companies.ids)],
    )
    location_id = fields.Many2one("iot.location", domain="[('company_id', '=', company_id)]")
    location_detail = fields.Char()

    @api.onchange("node_id", "probe_code", "company_id")
    def _onchange_reset_validation(self):
        self.validated = False
        self.validated_node_id = False
        self.validated_probe_code = False
        self.candidate_sensor_ids = [(5, 0, 0)]
        self.candidate_count = 0

    def action_validate_id(self):
        self.ensure_one()
        node_id = (self.node_id or "").strip()
        probe_code = (self.probe_code or "").strip()
        if self.company_id not in self.env.companies:
            raise UserError(_("You can only bind to companies you can access."))
        sensors = self.env["iot.th.sensor"].find_bind_candidates(node_id, probe_code=probe_code, require_online=True)
        conflict = sensors.filtered(lambda s: s.company_id and s.company_id != self.company_id)
        if conflict:
            raise UserError(_("This node is already bound to another company."))
        self.write(
            {
                "validated": True,
                "validated_node_id": node_id.lower(),
                "validated_probe_code": probe_code.upper(),
                "candidate_sensor_ids": [(6, 0, sensors.ids)],
                "candidate_count": len(sensors),
            }
        )
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Validate Node ID"),
                "message": _("Found %s sensor(s) ready for binding.") % len(sensors),
                "sticky": False,
                "type": "success",
            },
        }

    def action_bind(self):
        self.ensure_one()
        node_id = (self.node_id or "").strip()
        probe_code = (self.probe_code or "").strip()
        if self.company_id not in self.env.companies:
            raise UserError(_("You can only bind to companies you can access."))
        if (
            not self.validated
            or self.validated_node_id != node_id.lower()
            or (self.validated_probe_code or "") != probe_code.upper()
        ):
            raise UserError(_("Please validate the node ID first."))
        sensors = self.env["iot.th.sensor"].bind_by_node(
            node_id,
            probe_code=probe_code,
            company=self.company_id,
            location=self.location_id,
            location_detail=self.location_detail,
        )
        if not sensors:
            raise UserError(_("Failed to bind node."))
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Bind Node"),
                "message": _("Node %s is now bound to %s.") % (self.node_id, self.company_id.display_name),
                "sticky": False,
                "type": "success",
            },
        }
