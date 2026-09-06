from odoo import api, fields, models

class IoTIngestEvent(models.Model):
    _name = "iot.ingest.event"
    _description = "Committed IoT Event Receipt"
    event_id = fields.Char(required=True, index=True)
    route = fields.Char(required=True)
    digest = fields.Char(required=True)
    received_at = fields.Datetime(required=True, index=True)
    _event_identity = models.Constraint("UNIQUE(event_id)", "Event identity must be unique.")

    @api.model
    def _claim(self, event_id, route, digest, received_at):
        self.env.cr.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", [event_id])
        existing = self.search([("event_id", "=", event_id)], limit=1)
        if existing:
            if existing.route != route or existing.digest != digest:
                raise ValueError("event identity reused with a different payload")
            return False
        self.create(dict(event_id=event_id, route=route, digest=digest, received_at=received_at))
        return True
