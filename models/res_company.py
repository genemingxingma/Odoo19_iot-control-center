import ipaddress
import re

import pytz

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class ResCompany(models.Model):
    _inherit = "res.company"

    iot_history_retention_days = fields.Integer(string="IoT Raw History Retention (Days)", default=0,
        help="Zero keeps raw observations indefinitely. A positive value explicitly authorizes expiry deletion.")

    iot_prefer_internal_network = fields.Boolean(string="Prefer IoT Internal Network", default=True)
    iot_internal_host = fields.Char(string="IoT Internal Server Host")
    iot_internal_odoo_port = fields.Integer(string="IoT Internal Odoo Port", default=8069)
    iot_internal_mqtt_port = fields.Integer(string="IoT Internal MQTT Port", default=1883)
    iot_internal_ota_port = fields.Integer(string="IoT Internal OTA HTTPS Port", default=8443)
    iot_ota_tls_fingerprint = fields.Char(string="OTA TLS Certificate Fingerprint", copy=False,
        help="Trusted SHA-1 certificate fingerprint provisioned by an administrator. OTA fails closed when absent.")

    @api.constrains("iot_history_retention_days")
    def _check_history_retention(self):
        if any(company.iot_history_retention_days < 0 for company in self):
            raise ValidationError(_("History retention must be zero or a positive number of days."))

    @api.constrains("iot_ota_tls_fingerprint")
    def _check_ota_tls_fingerprint(self):
        for company in self:
            fingerprint = (company.iot_ota_tls_fingerprint or "").strip()
            if fingerprint and not re.fullmatch(r"(?:[0-9A-Fa-f]{2}[ :]){19}[0-9A-Fa-f]{2}|[0-9A-Fa-f]{40}", fingerprint):
                raise ValidationError(_("Enter a valid 20-byte SHA-1 certificate fingerprint."))

    def write(self, vals):
        network_fields = {
            "iot_prefer_internal_network",
            "iot_internal_host",
            "iot_internal_odoo_port",
            "iot_internal_mqtt_port",
            "iot_internal_ota_port",
            "iot_ota_tls_fingerprint",
        }
        changed = bool(network_fields & set(vals))
        result = super().write(vals)
        if changed:
            devices = self.env["iot.device"].sudo().search(
                [("active", "=", True), ("company_id", "in", self.ids)]
            )
            devices.with_context(**self.env["iot.device"]._system_no_track_context()).write(
                {"network_config_dirty": True}
            )
        return result

    @api.constrains("iot_internal_host")
    def _check_iot_internal_host(self):
        hostname_pattern = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9.-]{0,251}[A-Za-z0-9])?$")
        for company in self:
            host = (company.iot_internal_host or "").strip()
            if not host:
                continue
            candidate = host[1:-1] if host.startswith("[") and host.endswith("]") else host
            try:
                ipaddress.ip_address(candidate)
                continue
            except ValueError:
                pass
            if not hostname_pattern.fullmatch(candidate) or ".." in candidate:
                raise ValidationError(_("Enter an internal IP address or hostname without a scheme, port, or path."))

    @api.constrains("iot_internal_odoo_port", "iot_internal_mqtt_port", "iot_internal_ota_port")
    def _check_iot_internal_ports(self):
        for company in self:
            for value in (
                company.iot_internal_odoo_port,
                company.iot_internal_mqtt_port,
                company.iot_internal_ota_port,
            ):
                if value < 1 or value > 65535:
                    raise ValidationError(_("IoT internal ports must be between 1 and 65535."))

    def _iot_internal_host_for_url(self):
        self.ensure_one()
        host = (self.iot_internal_host or "").strip()
        if ":" in host and not host.startswith("["):
            return f"[{host}]"
        return host

    def get_iot_internal_odoo_base_url(self):
        self.ensure_one()
        if not self.iot_prefer_internal_network or not (self.iot_internal_host or "").strip():
            return False
        return f"http://{self._iot_internal_host_for_url()}:{self.iot_internal_odoo_port}"

    def get_iot_internal_ota_base_url(self):
        self.ensure_one()
        if not self.iot_prefer_internal_network or not (self.iot_internal_host or "").strip():
            return False
        return f"https://{self._iot_internal_host_for_url()}:{self.iot_internal_ota_port}"

    def get_iot_internal_mqtt_endpoint(self):
        self.ensure_one()
        if not self.iot_prefer_internal_network or not (self.iot_internal_host or "").strip():
            return False
        return ((self.iot_internal_host or "").strip().strip("[]"), self.iot_internal_mqtt_port)

    def get_iot_country_code(self):
        self.ensure_one()
        country = self.country_id or self.partner_id.country_id
        code = (country.code or "").strip().upper() if country else ""
        if not code:
            raise ValidationError(
                _("Configure the country on company %(company)s before using IoT devices.", company=self.display_name)
            )
        return code

    def get_iot_timezone(self):
        """Resolve device time exclusively from the owning company configuration."""
        self.ensure_one()
        country_code = self.get_iot_country_code()
        country_timezones = list(pytz.country_timezones.get(country_code, ()))
        partner_timezone = (self.partner_id.tz or "").strip()

        if len(country_timezones) == 1:
            return country_timezones[0]
        if partner_timezone in country_timezones:
            return partner_timezone
        if not country_timezones and partner_timezone in pytz.all_timezones_set:
            return partner_timezone

        if country_timezones:
            raise ValidationError(
                _(
                    "Company %(company)s is in a country with multiple timezones. "
                    "Set the timezone on the company contact before using IoT schedules.",
                    company=self.display_name,
                )
            )
        raise ValidationError(
            _(
                "No timezone mapping is available for company %(company)s. "
                "Set the timezone on the company contact.",
                company=self.display_name,
            )
        )
