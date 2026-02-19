from odoo import fields, models


class IoTTHRawPacket(models.Model):
    _name = "iot.th.raw.packet"
    _description = "Temperature/Humidity Raw Packet"
    _order = "received_at desc, id desc"

    gateway_id = fields.Many2one("iot.th.gateway", index=True, ondelete="set null")
    company_id = fields.Many2one(related="gateway_id.company_id", store=True, index=True)

    received_at = fields.Datetime(required=True, default=fields.Datetime.now, index=True)
    source_ip = fields.Char(index=True)
    source_port = fields.Integer()
    protocol = fields.Selection(
        [("tcp_chunk", "TCP Chunk"), ("tcp_json", "TCP JSON"), ("tcp_binary", "TCP Binary"), ("tcp_unknown", "TCP Unknown")],
        required=True,
        default="tcp_unknown",
        index=True,
    )
    node_id = fields.Char(string="Node ID", index=True)
    serial_hint = fields.Char(index=True)
    raw_payload = fields.Text(required=True)
    parse_ok = fields.Boolean(default=False, index=True)
    parse_error = fields.Char()
