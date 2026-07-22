import logging
from datetime import timedelta

from odoo import _, api, fields, models


_logger = logging.getLogger(__name__)


class IoTControlBoard(models.Model):
    _name = "iot.control.board"
    _description = "IoT Control Board Card"
    _order = "sequence, id"

    name = fields.Char(required=True, translate=True)
    key = fields.Selection(
        [
            ("relay", "Relay"),
            ("th", "Temperature/Humidity"),
            ("attendance", "Attendance"),
            ("openwrt", "OpenWrt AC"),
            ("other", "Other"),
        ],
        required=True,
        default="other",
    )
    description = fields.Text(translate=True)
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

    @api.model
    def _cleanup_legacy_records(self):
        legacy_xmlids = [
            "iot_control_center.cron_iot_run_schedules",
            "iot_control_center.menu_iot_th_raw_packet",
            "iot_control_center.action_iot_th_raw_packet",
            "iot_control_center.view_iot_th_raw_packet_list",
            "iot_control_center.view_iot_th_raw_packet_form",
            "iot_control_center.view_iot_th_raw_packet_search",
            "iot_control_center.rule_iot_th_raw_packet_company",
            "iot_control_center.access_iot_th_raw_packet_manager",
            "iot_control_center.access_iot_th_raw_packet_user",
            "iot_control_center.access_iot_th_raw_packet_admin",
        ]
        IrModelData = self.env["ir.model.data"].sudo()
        for xmlid in legacy_xmlids:
            module, name = xmlid.split(".", 1)
            data = IrModelData.search([("module", "=", module), ("name", "=", name)], limit=1)
            if not data:
                continue
            try:
                with self.env.cr.savepoint():
                    if data.model in self.env:
                        record = self.env[data.model].sudo().browse(data.res_id)
                        if record.exists():
                            record.unlink()
                    if data.exists():
                        data.unlink()
            except Exception:
                _logger.debug("Skipped legacy cleanup for XMLID %s", xmlid, exc_info=True)
        with self.env.cr.savepoint():
            self.env.cr.execute("DROP TABLE IF EXISTS iot_th_raw_packet CASCADE")

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
        # Force canonical views from view_mode, so stale DB view tuples do not hide switch buttons.
        modes = [m.strip() for m in action["view_mode"].split(",") if m.strip()]
        action["views"] = [(False, mode) for mode in modes]
        action.setdefault("target", "current")
        action.pop("id", None)
        return action

    def _compute_metrics(self):
        Device = self.env["iot.device"]
        Gateway = self.env["iot.th.gateway"]
        Sensor = self.env["iot.th.sensor"]
        Alert = self.env["iot.th.alert"]
        OpenwrtAP = self.env["iot.openwrt.ap"]
        AttendanceDevice = self.env["iot.attendance.device"]
        AttendancePunch = self.env["iot.attendance.punch"]
        company_domain = [("company_id", "in", self.env.companies.ids)]

        for rec in self:
            if rec.key == "relay":
                timeout = int(self.env["ir.config_parameter"].sudo().get_param("iot_control_center.online_timeout_sec", 300))
                cutoff = fields.Datetime.now() - timedelta(seconds=max(timeout, 1))
                rec.metric_1_label = _("Devices")
                rec.metric_1_value = Device.search_count(company_domain)
                rec.metric_2_label = _("Online")
                rec.metric_2_value = Device.search_count(company_domain + [("last_seen", ">=", cutoff)])
            elif rec.key == "th":
                rec.metric_1_label = _("Sensors")
                rec.metric_1_value = Sensor.search_count(company_domain)
                rec.metric_2_label = _("Open Alerts")
                rec.metric_2_value = Alert.search_count(company_domain + [("state", "=", "open")])
            elif rec.key == "openwrt":
                rec.metric_1_label = _("APs")
                rec.metric_1_value = OpenwrtAP.search_count(company_domain + [("active", "=", True)])
                rec.metric_2_label = _("Online")
                rec.metric_2_value = OpenwrtAP.search_count(
                    company_domain
                    + [
                        ("active", "=", True),
                        ("status", "=", "online"),
                    ]
                )
            elif rec.key == "attendance":
                rec.metric_1_label = _("Devices")
                rec.metric_1_value = AttendanceDevice.search_count(company_domain + [("active", "=", True)])
                rec.metric_2_label = _("Punches")
                rec.metric_2_value = AttendancePunch.search_count(company_domain)
            else:
                rec.metric_1_label = _("Items")
                rec.metric_1_value = Gateway.search_count(company_domain)
                rec.metric_2_label = _("Open Alerts")
                rec.metric_2_value = Alert.search_count(company_domain + [("state", "=", "open")])

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
                "iot_control_center.action_iot_th_reading",
                "Monitoring & Analysis",
                "iot.th.reading",
                default_view_mode="graph,list,pivot",
            )
        if self.key == "openwrt":
            return self._safe_window_action(
                "iot_control_center.action_iot_openwrt_ap",
                "OpenWrt APs",
                "iot.openwrt.ap",
                default_view_mode="list,form",
            )
        if self.key == "attendance":
            return self._safe_window_action(
                "iot_control_center.action_iot_attendance_device",
                "Attendance Devices",
                "iot.attendance.device",
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
