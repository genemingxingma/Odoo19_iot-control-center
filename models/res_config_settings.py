import logging
import os
import secrets
import subprocess
from pathlib import Path

from odoo import SUPERUSER_ID, api, fields, models
from odoo.tools import config as odoo_config


_logger = logging.getLogger(__name__)


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"
    iot_ota_tls_fingerprint = fields.Char(related="company_id.iot_ota_tls_fingerprint", readonly=False)

    iot_prefer_internal_network = fields.Boolean(
        related="company_id.iot_prefer_internal_network",
        string="Prefer Company Internal Network",
        readonly=False,
    )
    iot_internal_host = fields.Char(
        related="company_id.iot_internal_host", string="Internal Server Host", readonly=False
    )
    iot_internal_odoo_port = fields.Integer(
        related="company_id.iot_internal_odoo_port", string="Internal Odoo Port", readonly=False
    )
    iot_internal_mqtt_port = fields.Integer(
        related="company_id.iot_internal_mqtt_port", string="Internal MQTT Port", readonly=False
    )
    iot_internal_ota_port = fields.Integer(
        related="company_id.iot_internal_ota_port", string="Internal OTA HTTPS Port", readonly=False
    )

    iot_mqtt_host = fields.Char(
        string="MQTT Host", config_parameter="iot_control_center.mqtt_host", default="iot.imytest.com"
    )
    iot_mqtt_port = fields.Integer(string="MQTT Port", config_parameter="iot_control_center.mqtt_port", default=1883)
    iot_mqtt_username = fields.Char(
        string="MQTT Username", config_parameter="iot_control_center.mqtt_username", default="imytest"
    )
    iot_mqtt_password = fields.Char(
        string="MQTT Password", config_parameter="iot_control_center.mqtt_password", default="imytest"
    )
    iot_mqtt_topic_root = fields.Char(
        string="Topic Root", config_parameter="iot_control_center.mqtt_topic_root", default="iot/relay"
    )
    iot_mqtt_keepalive = fields.Integer(
        string="MQTT Keepalive (sec)", config_parameter="iot_control_center.mqtt_keepalive", default=60
    )
    iot_mqtt_message_retention_days = fields.Integer(
        string="MQTT Message Retention (days)",
        config_parameter="iot_control_center.mqtt_message_retention_days",
        default=7,
    )
    iot_mqtt_telemetry_retention_hours = fields.Integer(
        string="MQTT Telemetry Retention (hours)",
        config_parameter="iot_control_center.mqtt_telemetry_retention_hours",
        default=24,
    )
    iot_mqtt_telemetry_sample_window_seconds = fields.Integer(
        string="MQTT Telemetry Sample Window (sec)",
        config_parameter="iot_control_center.mqtt_telemetry_sample_window_seconds",
        default=60,
    )
    iot_device_retention_days = fields.Integer(
        string="Unbound Device Retention (days)",
        config_parameter="iot_control_center.device_retention_days",
        default=30,
    )
    iot_online_timeout_sec = fields.Integer(
        string="Online Timeout (sec)", config_parameter="iot_control_center.online_timeout_sec", default=300
    )
    iot_firmware_base_url = fields.Char(
        string="Firmware Base URL",
        config_parameter="iot_control_center.firmware_base_url",
        default="iot.imytest.com",
    )
    iot_th_online_timeout_sec = fields.Integer(
        string="TH Online Timeout (sec)", config_parameter="iot_control_center.th_online_timeout_sec", default=300
    )
    iot_th_raw_retention_days = fields.Integer(
        string="TH Raw Retention (days)",
        related="company_id.iot_history_retention_days",
        readonly=False,
    )
    iot_middleware_base_url = fields.Char(
        string="Middleware Base URL",
        config_parameter="iot_control_center.middleware_base_url",
        default="http://127.0.0.1:8099",
    )
    iot_middleware_token = fields.Char(
        string="Middleware Token",
        config_parameter="iot_control_center.middleware_token",
        default=lambda self: secrets.token_urlsafe(24),
    )
    iot_openwrt_ssh_private_key_path = fields.Char(
        string="OpenWrt SSH Private Key Path",
        config_parameter="iot_control_center.openwrt_ssh_private_key_path",
        readonly=True,
    )
    iot_openwrt_ssh_public_key = fields.Char(
        string="OpenWrt SSH Public Key",
        config_parameter="iot_control_center.openwrt_ssh_public_key",
        readonly=True,
    )
    iot_openwrt_online_timeout_sec = fields.Integer(
        string="OpenWrt Online Timeout (sec)",
        config_parameter="iot_control_center.openwrt_online_timeout_sec",
        default=300,
    )
    iot_openwrt_heartbeat_interval_sec = fields.Integer(
        string="Heartbeat Interval (sec)",
        config_parameter="iot_control_center.openwrt_heartbeat_interval_sec",
        default=300,
    )
    iot_openwrt_full_probe_every = fields.Integer(
        string="Full Probe Every N Heartbeats",
        config_parameter="iot_control_center.openwrt_full_probe_every",
        default=6,
    )
    iot_openwrt_offline_failure_threshold = fields.Integer(
        string="Offline Failure Threshold",
        config_parameter="iot_control_center.openwrt_offline_failure_threshold",
        default=2,
    )
    iot_attendance_adms_port = fields.Integer(
        string="Attendance ADMS External Port",
        config_parameter="iot_control_center.attendance_adms_port",
        default=8069,
    )
    iot_attendance_allowed_ips = fields.Char(
        string="Attendance Source IP Allowlist",
        config_parameter="iot_control_center.attendance_allowed_ips",
        help="Comma-separated ADMS source IP allowlist. Leave blank to allow any source that matches a bound device.",
    )
    iot_attendance_max_open_hours = fields.Integer(
        string="Max Open Attendance Hours",
        config_parameter="iot_control_center.attendance_max_open_hours",
        default=16,
    )
    iot_attendance_request_retention_days = fields.Integer(
        string="Attendance Request Retention (days)",
        config_parameter="iot_control_center.attendance_request_retention_days",
        default=7,
    )
    iot_attendance_heartbeat_log_interval_seconds = fields.Integer(
        string="Attendance Heartbeat Log Interval (seconds)",
        config_parameter="iot_control_center.attendance_heartbeat_log_interval_seconds",
        default=600,
    )
    iot_attendance_punch_raw_retention_days = fields.Integer(
        string="Attendance Punch Raw Payload Retention (days)",
        config_parameter="iot_control_center.attendance_punch_raw_retention_days",
        default=7,
    )
    iot_firmware_log_payload_retention_days = fields.Integer(
        string="Firmware Log Payload Retention (days)",
        config_parameter="iot_control_center.firmware_log_payload_retention_days",
        default=7,
    )
    iot_firmware_log_retention_days = fields.Integer(
        string="Firmware Log Retention (days)",
        config_parameter="iot_control_center.firmware_log_retention_days",
        default=90,
    )
    iot_openwrt_job_payload_retention_days = fields.Integer(
        string="OpenWrt Job Payload Retention (days)",
        config_parameter="iot_control_center.openwrt_job_payload_retention_days",
        default=7,
    )
    iot_openwrt_job_retention_days = fields.Integer(
        string="OpenWrt Job Retention (days)",
        config_parameter="iot_control_center.openwrt_job_retention_days",
        default=30,
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

    def set_values(self):
        if not (self.iot_middleware_token or "").strip():
            self.iot_middleware_token = secrets.token_urlsafe(24)
        res = super().set_values()
        # V2 connections run only in the external bridge.
        return res
