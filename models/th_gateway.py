from datetime import timedelta

from odoo import api, fields, models

from ..services.tcp_service import ensure_running as ensure_tcp_running


class IoTTHGateway(models.Model):
    _name = "iot.th.gateway"
    _description = "Temperature/Humidity Gateway"

    name = fields.Char(required=True)
    serial = fields.Char(string="Gateway ID", required=True, index=True)
    active = fields.Boolean(default=True)

    company_id = fields.Many2one("res.company", index=True)
    department_id = fields.Many2one("iot.department", domain="[('company_id', '=', company_id)]")
    location_id = fields.Many2one("iot.location", domain="[('company_id', '=', company_id)]")

    tcp_token = fields.Char(help="Optional token for gateway payload authentication.")
    sampling_interval_min = fields.Integer(default=5, help="Recommended gateway upload interval in minutes.")
    statistics_window_hours = fields.Integer(default=24, help="Default analysis window in hours.")

    last_seen = fields.Datetime()
    online = fields.Boolean(compute="_compute_online", store=False)

    sensor_ids = fields.One2many("iot.th.sensor", "gateway_id")
    sensor_count = fields.Integer(compute="_compute_counts")
    alert_count = fields.Integer(compute="_compute_counts")

    @api.depends("sensor_ids")
    def _compute_counts(self):
        alert_model = self.env["iot.th.alert"]
        for rec in self:
            rec.sensor_count = len(rec.sensor_ids)
            rec.alert_count = alert_model.search_count([("gateway_id", "=", rec.id), ("state", "=", "open")])

    @api.depends("last_seen")
    def _compute_online(self):
        timeout = int(self.env["ir.config_parameter"].sudo().get_param("iot_control_center.th_online_timeout_sec", 300))
        now = fields.Datetime.now()
        for rec in self:
            rec.online = bool(rec.last_seen and (now - rec.last_seen) <= timedelta(seconds=timeout))

    @api.model
    def _cron_ensure_tcp_service(self):
        ensure_tcp_running(self.env)

    def action_open_sensors(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": "Sensors",
            "res_model": "iot.th.sensor",
            "view_mode": "list,form",
            "domain": [("gateway_id", "=", self.id)],
        }

    def action_open_alerts(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": "Alerts",
            "res_model": "iot.th.alert",
            "view_mode": "list,form",
            "domain": [("gateway_id", "=", self.id), ("state", "=", "open")],
        }
