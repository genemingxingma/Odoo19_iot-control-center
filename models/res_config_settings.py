from odoo import fields, models

from ..services.tcp_service import ensure_running as ensure_tcp_running


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    iot_mqtt_host = fields.Char(config_parameter="iot_control_center.mqtt_host", default="iot.imytest.com")
    iot_mqtt_port = fields.Integer(config_parameter="iot_control_center.mqtt_port", default=1883)
    iot_mqtt_username = fields.Char(config_parameter="iot_control_center.mqtt_username", default="imytest")
    iot_mqtt_password = fields.Char(config_parameter="iot_control_center.mqtt_password", default="imytest")
    iot_mqtt_topic_root = fields.Char(config_parameter="iot_control_center.mqtt_topic_root", default="iot/relay")
    iot_mqtt_keepalive = fields.Integer(config_parameter="iot_control_center.mqtt_keepalive", default=60)
    iot_online_timeout_sec = fields.Integer(config_parameter="iot_control_center.online_timeout_sec", default=300)
    iot_firmware_base_url = fields.Char(
        config_parameter="iot_control_center.firmware_base_url",
        default="iot.imytest.com",
    )
    iot_th_tcp_host = fields.Char(config_parameter="iot_control_center.th_tcp_host", default="0.0.0.0")
    iot_th_tcp_port = fields.Integer(config_parameter="iot_control_center.th_tcp_port", default=9910)
    iot_th_online_timeout_sec = fields.Integer(config_parameter="iot_control_center.th_online_timeout_sec", default=300)

    def set_values(self):
        res = super().set_values()
        self.env["iot.device"]._cron_ensure_mqtt_service()
        self.env["iot.th.gateway"]._cron_ensure_tcp_service()
        ensure_tcp_running(self.env)
        return res
