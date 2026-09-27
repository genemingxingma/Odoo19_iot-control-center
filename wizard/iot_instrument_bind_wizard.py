from odoo import _, api, fields, models
from odoo.exceptions import UserError

from ..core import instruments as contract


class IoTInstrumentBindWizard(models.TransientModel):
    _name = "iot.instrument.bind.wizard"
    _description = "Add Instrument by Device ID"

    device_id = fields.Char(required=True, string="Device ID")
    validated = fields.Boolean(readonly=True, default=False)
    kind = fields.Selection([("heater", "Buffer Heater"), ("washer", "Array Washer")], readonly=True)
    status_message = fields.Char(readonly=True)
    existing_instrument_id = fields.Many2one("iot.instrument", readonly=True)
    name = fields.Char(string="Instrument Name")
    company_id = fields.Many2one("res.company", required=True, default=lambda self: self.env.company,
        domain=lambda self: [("id", "in", self.env.companies.ids)])
    location_detail = fields.Char()

    @api.onchange("device_id", "company_id")
    def _onchange_reset_validation(self):
        self.validated = False
        self.kind = False
        self.status_message = False
        self.existing_instrument_id = False

    def _reopen(self):
        self.ensure_one()
        return {"type": "ir.actions.act_window", "name": _("Add Instrument by Device ID"),
            "res_model": self._name, "view_mode": "form", "res_id": self.id, "target": "new"}

    def _normalized(self):
        value = (self.device_id or "").strip().upper()
        contract.device_identity(value)
        return value

    def action_search_id(self):
        self.ensure_one()
        if self.company_id not in self.env.companies:
            raise UserError(_("You can only add instruments to companies you can access."))
        try:
            device_id = self._normalized()
        except ValueError as exc:
            self.write({"validated": False, "kind": False, "existing_instrument_id": False,
                "status_message": _("Enter the exact Device ID shown on the instrument, such as HTR-C82B962D09D7.")})
            return self._reopen()
        existing = self.env["iot.instrument"].sudo().search([("device_id", "=", device_id)], limit=1)
        if existing:
            accessible = existing.company_id in self.env.companies
            message = (_("This Device ID is already registered as %s in %s.") %
                (existing.display_name, existing.company_id.display_name)) if accessible else _("This Device ID is already registered to another company.")
            self.write({"device_id": device_id, "validated": False, "kind": existing.kind,
                "existing_instrument_id": existing.id if accessible else False, "status_message": message})
            return self._reopen()
        kind = contract.device_kind(device_id)
        default_name = _("Buffer Heater %s") % device_id[-6:] if kind == "heater" else _("Array Washer %s") % device_id[-6:]
        self.write({"device_id": device_id, "validated": True, "kind": kind,
            "existing_instrument_id": False, "name": self.name or default_name,
            "status_message": _("Device ID is available. Confirm the company and location, then add it.")})
        return self._reopen()

    def action_confirm_bind(self):
        self.ensure_one()
        if self.company_id not in self.env.companies:
            raise UserError(_("You can only add instruments to companies you can access."))
        try:
            device_id = self._normalized()
        except ValueError as exc:
            raise UserError(_("Enter a valid Device ID shown on the instrument.")) from exc
        kind = contract.device_kind(device_id)
        # Serialize concurrent attempts for this visible identity before the
        # uniqueness constraint provides the final database-level guard.
        self.env.cr.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", [device_id])
        existing = self.env["iot.instrument"].sudo().search([("device_id", "=", device_id)], limit=1)
        if existing:
            raise UserError(_("This Device ID is already registered."))
        if not self.validated or self.kind != kind or not (self.name or "").strip():
            raise UserError(_("Search the Device ID and enter an instrument name before confirming."))
        instrument = self.env["iot.instrument"].sudo().create({
            "name": self.name.strip(), "uid": device_id, "device_id": device_id,
            "kind": kind, "company_id": self.company_id.id,
            "location_detail": (self.location_detail or "").strip() or False,
        })
        return {"type": "ir.actions.act_window", "name": instrument.display_name,
            "res_model": "iot.instrument", "view_mode": "form", "res_id": instrument.id, "target": "current"}
