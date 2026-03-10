import logging
import os
import subprocess
from pathlib import Path

from odoo import SUPERUSER_ID, api, fields, models
from odoo.tools import config as odoo_config

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
    iot_openwrt_ssh_private_key_path = fields.Char(
        config_parameter="iot_control_center.openwrt_ssh_private_key_path",
        readonly=True,
    )
    iot_openwrt_ssh_public_key = fields.Char(
        config_parameter="iot_control_center.openwrt_ssh_public_key",
        readonly=True,
    )
    iot_openwrt_online_timeout_sec = fields.Integer(
        config_parameter="iot_control_center.openwrt_online_timeout_sec",
        default=300,
    )
    iot_openwrt_heartbeat_interval_sec = fields.Integer(
        config_parameter="iot_control_center.openwrt_heartbeat_interval_sec",
        default=300,
    )
    iot_openwrt_full_probe_every = fields.Integer(
        config_parameter="iot_control_center.openwrt_full_probe_every",
        default=6,
    )
    iot_openwrt_offline_failure_threshold = fields.Integer(
        config_parameter="iot_control_center.openwrt_offline_failure_threshold",
        default=2,
    )

    def action_generate_openwrt_ssh_key(self):
        self.ensure_one()
        data_dir = (
            odoo_config.get("data_dir")
            or self.env["ir.config_parameter"].sudo().get_param("data_dir")
            or "/var/lib/odoo/.local/share/Odoo"
        )
        key_dir = Path(data_dir) / "iot_openwrt_ssh"
        key_dir.mkdir(parents=True, exist_ok=True)
        private_key = key_dir / "id_ed25519"
        public_key = key_dir / "id_ed25519.pub"
        if not private_key.exists():
            subprocess.run(
                [
                    "ssh-keygen",
                    "-t",
                    "ed25519",
                    "-N",
                    "",
                    "-C",
                    "iot_control_center_openwrt",
                    "-f",
                    str(private_key),
                ],
                check=True,
                capture_output=True,
                text=True,
            )
            os.chmod(private_key, 0o600)
        public_text = public_key.read_text(encoding="utf-8").strip() if public_key.exists() else ""
        self.env["ir.config_parameter"].sudo().set_param("iot_control_center.openwrt_ssh_private_key_path", str(private_key))
        self.env["ir.config_parameter"].sudo().set_param("iot_control_center.openwrt_ssh_public_key", public_text)
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": "OpenWrt SSH Key",
                "message": "OpenWrt SSH key generated or reused successfully.",
                "type": "success",
                "sticky": False,
            },
        }

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
