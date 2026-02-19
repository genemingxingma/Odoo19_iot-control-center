from odoo import _, api, fields, models
from odoo.exceptions import UserError


class IoTDeviceBindWizard(models.TransientModel):
    _name = "iot.device.bind.wizard"
    _description = "Bind Switch by ID"

    serial = fields.Char(string="Switch ID/Serial", required=True)
    validated = fields.Boolean(readonly=True, default=False)
    validated_key = fields.Char(readonly=True)
    candidate_device_id = fields.Many2one("iot.device", string="Matched Switch", readonly=True)
    candidate_switch_id = fields.Char(string="Matched Switch ID", readonly=True)
    candidate_last_seen = fields.Datetime(string="Last Seen", readonly=True)
    company_id = fields.Many2one(
        "res.company",
        required=True,
        default=lambda self: self.env.company,
        domain=lambda self: [("id", "in", self.env.companies.ids)],
    )
    department_id = fields.Many2one("iot.department", domain="[('company_id', '=', company_id)]")
    location_id = fields.Many2one("iot.location", domain="[('company_id', '=', company_id)]")

    @api.onchange("serial", "company_id")
    def _onchange_reset_validation(self):
        self.validated = False
        self.validated_key = False
        self.candidate_device_id = False
        self.candidate_switch_id = False
        self.candidate_last_seen = False

    def action_search_id(self):
        self.ensure_one()
        key = (self.serial or "").strip()
        if not key:
            return {
                "type": "ir.actions.client",
                "tag": "display_notification",
                "params": {
                    "title": _("Search Switch ID"),
                    "message": _("Please input Switch ID first."),
                    "sticky": False,
                    "type": "warning",
                },
            }
        normalized_key = key.lower()
        if self.company_id not in self.env.companies:
            return {
                "type": "ir.actions.client",
                "tag": "display_notification",
                "params": {
                    "title": _("Search Switch ID"),
                    "message": _("You can only bind to companies you can access."),
                    "sticky": False,
                    "type": "danger",
                },
            }
        try:
            rec = self.env["iot.device"].find_bind_candidate(key, require_online=False)
            if rec.company_id and rec.company_id != self.company_id:
                raise UserError(_("This switch is already bound to company: %s") % rec.company_id.display_name)
        except UserError as err:
            self._reset_validation()
            return {
                "type": "ir.actions.client",
                "tag": "display_notification",
                "params": {
                    "title": _("Search Switch ID"),
                    "message": str(err),
                    "sticky": False,
                    "type": "warning",
                },
            }
        self.write(
            {
                "validated": True,
                "validated_key": normalized_key,
                "candidate_device_id": rec.id,
                "candidate_switch_id": rec.module_id or rec.serial or "",
                "candidate_last_seen": rec.last_seen,
            }
        )
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Search Switch ID"),
                "message": _("Found switch %s. Click Confirm Bind to continue.") % (rec.module_id or rec.serial),
                "sticky": False,
                "type": "success",
            },
        }

    def action_validate_id(self):
        # Backward compatibility for old button binding.
        return self.action_search_id()

    def _reset_validation(self):
        self.write(
            {
                "validated": False,
                "validated_key": False,
                "candidate_device_id": False,
                "candidate_switch_id": False,
                "candidate_last_seen": False,
            }
        )

    def action_confirm_bind(self):
        self.ensure_one()
        key = (self.serial or "").strip()
        if not key:
            raise UserError(_("Please input Switch ID first."))
        if self.company_id not in self.env.companies:
            raise UserError(_("You can only bind to companies you can access."))

        # Allow one-click bind: if user did not validate first, confirm will
        # perform the same search/validation logic and continue.
        try:
            rec_candidate = self.env["iot.device"].find_bind_candidate(key, require_online=False)
            if rec_candidate.company_id and rec_candidate.company_id != self.company_id:
                raise UserError(_("This switch is already bound to company: %s") % rec_candidate.company_id.display_name)
        except UserError as err:
            self._reset_validation()
            return {
                "type": "ir.actions.client",
                "tag": "display_notification",
                "params": {
                    "title": _("Bind Switch"),
                    "message": str(err),
                    "sticky": False,
                    "type": "warning",
                },
            }

        rec = self.env["iot.device"].bind_by_serial(
            key,
            company=self.company_id,
            department=self.department_id,
            location=self.location_id,
        )
        if not rec:
            raise UserError(_("Failed to bind switch."))
        bound_id = rec.module_id or rec.serial
        self._reset_validation()
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Bind Success"),
                "message": _("Switch %s bound successfully. You can bind next one now.") % bound_id,
                "sticky": False,
                "type": "success",
            },
        }

    def action_bind(self):
        # Backward compatibility for old button binding.
        return self.action_confirm_bind()
