from odoo import fields, models


class IoTControlBoard(models.Model):
    _name = "iot.control.board"
    _description = "IoT Control Board Card"
    _order = "sequence, id"

    name = fields.Char(required=True)
    key = fields.Selection(
        [
            ("relay", "Relay"),
            ("th", "Temperature/Humidity"),
            ("other", "Other"),
        ],
        required=True,
        default="other",
    )
    description = fields.Text()
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)

    icon_class = fields.Char(default="fa fa-cube")
    color = fields.Selection(
        [
            ("blue", "Blue"),
            ("green", "Green"),
            ("orange", "Orange"),
            ("gray", "Gray"),
        ],
        default="blue",
    )

    action_id = fields.Many2one("ir.actions.actions", required=True, ondelete="restrict")

    metric_1_label = fields.Char(compute="_compute_metrics")
    metric_1_value = fields.Integer(compute="_compute_metrics")
    metric_2_label = fields.Char(compute="_compute_metrics")
    metric_2_value = fields.Integer(compute="_compute_metrics")

    def _safe_window_action(self, xmlid, default_name, default_model, default_view_mode="list,kanban,form"):
        action = {}
        try:
            action = self.env["ir.actions.actions"]._for_xml_id(xmlid) or {}
        except Exception:
            action = {}

        if not action:
            action = {
                "type": "ir.actions.act_window",
                "name": default_name,
                "res_model": default_model,
                "view_mode": default_view_mode,
                "target": "current",
            }

        if not action.get("type"):
            action["type"] = "ir.actions.act_window"
        if not action.get("name"):
            action["name"] = default_name
        if not action.get("res_model"):
            action["res_model"] = default_model
        if not action.get("view_mode"):
            action["view_mode"] = default_view_mode
        if not action.get("views"):
            modes = [m.strip() for m in action["view_mode"].split(",") if m.strip()]
            action["views"] = [(False, mode) for mode in modes]
        action.setdefault("target", "current")
        action.pop("id", None)
        return action

    def _compute_metrics(self):
        Device = self.env["iot.device"].sudo()
        Gateway = self.env["iot.th.gateway"].sudo()
        Sensor = self.env["iot.th.sensor"].sudo()
        Alert = self.env["iot.th.alert"].sudo()

        for rec in self:
            if rec.key == "relay":
                rec.metric_1_label = "Devices"
                rec.metric_1_value = Device.search_count([("company_id", "!=", False)])
                rec.metric_2_label = "Online"
                rec.metric_2_value = Device.search_count([("company_id", "!=", False), ("last_seen", "!=", False)])
            elif rec.key == "th":
                rec.metric_1_label = "Sensors"
                rec.metric_1_value = Sensor.search_count([("company_id", "!=", False)])
                rec.metric_2_label = "Open Alerts"
                rec.metric_2_value = Alert.search_count([("state", "=", "open")])
            else:
                rec.metric_1_label = "Items"
                rec.metric_1_value = Gateway.search_count([])
                rec.metric_2_label = "Open Alerts"
                rec.metric_2_value = Alert.search_count([("state", "=", "open")])

    def action_open_module(self):
        self.ensure_one()
        if self.key == "relay":
            return self._safe_window_action(
                "iot_control_center.action_iot_device",
                "Switches",
                "iot.device",
                default_view_mode="list,kanban,form",
            )
        if self.key == "th":
            return self._safe_window_action(
                "iot_control_center.action_iot_th_sensor",
                "Sensors",
                "iot.th.sensor",
                default_view_mode="list,form",
            )
        if self.action_id and self.action_id.type == "ir.actions.act_window":
            action = self.action_id.sudo().read()[0]
            if not action.get("view_mode"):
                action["view_mode"] = "list,form"
            if not action.get("views"):
                modes = [m.strip() for m in action["view_mode"].split(",") if m.strip()]
                action["views"] = [(False, mode) for mode in modes]
            action.pop("id", None)
            return action
        return False
