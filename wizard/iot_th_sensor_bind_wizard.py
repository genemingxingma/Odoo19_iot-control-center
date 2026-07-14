from odoo import _, api, fields, models
from odoo.exceptions import UserError


class IoTTHSensorBindWizard(models.TransientModel):
    _name = "iot.th.sensor.bind.wizard"
    _description = "Bind TH Node/Sensor Channel by ID"

    node_id = fields.Char(string="Node ID", required=True)
    probe_code = fields.Char(string="Sensor Channel (Optional)")
    validated = fields.Boolean(readonly=True, default=False)
    validated_node_id = fields.Char(readonly=True)
    validated_probe_code = fields.Char(readonly=True)
    candidate_summary = fields.Char(string="Matched Sensors", readonly=True)
    candidate_count = fields.Integer(readonly=True)
    company_id = fields.Many2one(
        "res.company",
        default=lambda self: self.env.company,
        domain=lambda self: [("id", "in", self.env.companies.ids)],
    )
    location_id = fields.Many2one("stock.location", domain="['|', ('company_id', '=', False), ('company_id', '=', company_id)]")
    location_detail = fields.Char()

    @api.onchange("node_id", "probe_code", "company_id")
    def _onchange_reset_validation(self):
        self.validated = False
        self.validated_node_id = False
        self.validated_probe_code = False
        self.candidate_summary = False
        self.candidate_count = 0

    def _resolve_company(self):
        self.ensure_one()
        company = self.company_id or self.env.company
        if not company:
            raise UserError(_("No available company for binding."))
        if company not in self.env.companies:
            raise UserError(_("You can only bind to companies you can access."))
        if self.company_id != company:
            self.company_id = company.id
        return company

    def _reopen_self_action(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Bind Node by ID"),
            "res_model": "iot.th.sensor.bind.wizard",
            "view_mode": "form",
            "res_id": self.id,
            "target": "new",
        }

    def action_validate_id(self):
        self.ensure_one()
        node_id = (self.node_id or "").strip()
        probe_code = (self.probe_code or "").strip()
        if not node_id:
            raise UserError(_("Please input Node ID first."))
        company = self._resolve_company()
        sensors = self.env["iot.th.sensor"].find_bind_candidates(node_id, probe_code=probe_code, require_online=True)
        conflict = sensors.filtered(lambda s: s.company_id and s.company_id != company)
        if conflict:
            raise UserError(_("This node is already bound to another company."))
        self.write(
            {
                "node_id": node_id,
                "probe_code": probe_code,
                "validated": True,
                "validated_node_id": node_id,
                "validated_probe_code": probe_code.upper(),
                "candidate_summary": ", ".join(["%s-%s" % (s.node_id, s.probe_code) for s in sensors]),
                "candidate_count": len(sensors),
            }
        )
        return self._reopen_self_action()

    def action_search_id(self):
        # Backward compatibility with switch bind wizard button naming.
        return self.action_validate_id()

    def action_confirm_bind(self):
        self.ensure_one()
        node_id = (self.node_id or "").strip()
        probe_code = (self.probe_code or "").strip()
        if not node_id:
            node_id = (self.validated_node_id or "").strip()
        if not probe_code and self.validated_probe_code:
            probe_code = (self.validated_probe_code or "").strip()
        if not node_id:
            raise UserError(_("Please input Node ID first."))
        company = self._resolve_company()
        sensors = self.env["iot.th.sensor"].bind_by_node(
            node_id,
            probe_code=probe_code,
            company=company,
            location=self.location_id,
            location_detail=self.location_detail,
        )
        if not sensors:
            raise UserError(_("Failed to bind node."))
        self.write(
            {
                "validated": False,
                "validated_node_id": False,
                "validated_probe_code": False,
                "candidate_summary": False,
                "candidate_count": 0,
            }
        )
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Bind Node"),
                "message": _("Node %s is now bound to %s. You can bind next one now.") % (node_id, company.display_name),
                "sticky": False,
                "type": "success",
            },
        }

    def action_bind(self):
        # Backward compatibility for old button binding.
        return self.action_confirm_bind()
