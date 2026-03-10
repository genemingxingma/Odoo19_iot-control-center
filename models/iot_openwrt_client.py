from odoo import fields, models


class IoTOpenwrtClient(models.Model):
    _name = "iot.openwrt.client"
    _description = "OpenWrt AP Client"
    _order = "band asc, ip_address asc, mac_address asc, id asc"

    ap_id = fields.Many2one("iot.openwrt.ap", required=True, ondelete="cascade", index=True)
    company_id = fields.Many2one(related="ap_id.company_id", store=True, index=True)
    hostname = fields.Char(readonly=True)
    ip_address = fields.Char(readonly=True, index=True)
    mac_address = fields.Char(required=True, readonly=True, index=True)
    band = fields.Selection(
        [
            ("2.4g", "2.4G"),
            ("5g", "5G"),
            ("other", "Other"),
        ],
        default="other",
        required=True,
        readonly=True,
        index=True,
    )
    signal_dbm = fields.Integer(readonly=True)
    upload_rate_mbps = fields.Float(readonly=True, digits=(16, 2))
    download_rate_mbps = fields.Float(readonly=True, digits=(16, 2))
    upload_bytes_total = fields.Float(readonly=True, digits=(16, 0))
    download_bytes_total = fields.Float(readonly=True, digits=(16, 0))
    connected_seconds = fields.Integer(readonly=True)
    last_seen = fields.Datetime(readonly=True, default=fields.Datetime.now)

    _sql_constraints = [
        ("iot_openwrt_client_ap_mac_uniq", "unique(ap_id, mac_address)", "AP client MAC must be unique per AP."),
    ]
