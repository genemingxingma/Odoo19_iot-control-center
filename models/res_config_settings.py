import logging

from odoo import SUPERUSER_ID, api, fields, models

from ..services.tcp_service import ensure_running as ensure_tcp_running

_logger = logging.getLogger(__name__)


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    iot_mqtt_host = fields.Char(config_parameter="iot_control_center.mqtt_host", default="iot.imytest.com")
    iot_mqtt_port = fields.Integer(config_parameter="iot_control_center.mqtt_port", default=1883)
    iot_mqtt_username = fields.Char(config_parameter="iot_control_center.mqtt_username", default="imytest")
    iot_mqtt_password = fields.Char(config_parameter="iot_control_center.mqtt_password", default="imytest")
    iot_mqtt_topic_root = fields.Char(config_parameter="iot_control_center.mqtt_topic_root", default="iot/relay")
    iot_mqtt_keepalive = fields.Integer(config_parameter="iot_control_center.mqtt_keepalive", default=60)
    iot_mqtt_message_retention_days = fields.Integer(
        config_parameter="iot_control_center.mqtt_message_retention_days",
        default=7,
    )
    iot_device_retention_days = fields.Integer(
        config_parameter="iot_control_center.device_retention_days",
        default=30,
    )
    iot_online_timeout_sec = fields.Integer(config_parameter="iot_control_center.online_timeout_sec", default=300)
    iot_firmware_base_url = fields.Char(
        config_parameter="iot_control_center.firmware_base_url",
        default="iot.imytest.com",
    )
    iot_th_tcp_host = fields.Char(config_parameter="iot_control_center.th_tcp_host", default="0.0.0.0")
    iot_th_tcp_port = fields.Integer(config_parameter="iot_control_center.th_tcp_port", default=9910)
    iot_th_online_timeout_sec = fields.Integer(config_parameter="iot_control_center.th_online_timeout_sec", default=300)
    iot_middleware_enabled = fields.Boolean(config_parameter="iot_control_center.middleware_enabled", default=False)
    iot_middleware_base_url = fields.Char(config_parameter="iot_control_center.middleware_base_url", default="http://127.0.0.1:8099")
    iot_middleware_token = fields.Char(config_parameter="iot_control_center.middleware_token", default="imytest-middleware-token")

    def _run_iot_services_after_commit(self):
        dbname = self.env.cr.dbname
        registry = self.env.registry
        context = dict(self.env.context)

        def _runner():
            with registry.cursor() as cr:
                env = api.Environment(cr, SUPERUSER_ID, context)
                try:
                    middleware_enabled = str(env["ir.config_parameter"].sudo().get_param("iot_control_center.middleware_enabled", "False")).lower() in ("1", "true", "yes")
                    if not middleware_enabled:
                        env["iot.device"]._cron_ensure_mqtt_service()
                        env["iot.th.gateway"]._cron_ensure_tcp_service()
                        ensure_tcp_running(env)
                    cr.commit()
                except Exception:
                    cr.rollback()
                    _logger.exception("Deferred IoT service ensure failed after settings save (db=%s)", dbname)

        self.env.cr.postcommit.add(_runner)

    def set_values(self):
        res = super().set_values()
        self._run_iot_services_after_commit()
        return res
