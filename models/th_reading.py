from odoo import api, fields, models


class IoTTHReading(models.Model):
    _name = "iot.th.reading"
    _description = "Temperature/Humidity Reading"
    _order = "reported_at desc, id desc"

    sensor_id = fields.Many2one("iot.th.sensor", required=True, index=True, ondelete="cascade")
    sensor_code = fields.Char(related="sensor_id.probe_code", string="Sensor Channel", store=True, index=True)
    gateway_id = fields.Many2one("iot.th.gateway", required=True, index=True, ondelete="cascade")
    node_id = fields.Char(related="sensor_id.node_id", string="Node ID", store=True, index=True)
    company_id = fields.Many2one(related="sensor_id.company_id", store=True, index=True)

    reported_at = fields.Datetime(required=True, index=True)
    temperature = fields.Float(required=True)
    humidity = fields.Float(required=True)

    @api.model
    def fields_get(self, allfields=None, attributes=None):
        result = super().fields_get(allfields=allfields, attributes=attributes)
        for fname in ("temperature", "humidity"):
            if fname in result:
                result[fname]["aggregator"] = "avg"
        return result

    def _force_avg_measures(self, field_specs):
        normalized = []
        for spec in field_specs or []:
            if spec == "temperature":
                normalized.append("temperature:avg")
            elif spec == "humidity":
                normalized.append("humidity:avg")
            elif isinstance(spec, str) and spec.startswith("temperature:"):
                normalized.append("temperature:avg")
            elif isinstance(spec, str) and spec.startswith("humidity:"):
                normalized.append("humidity:avg")
            else:
                normalized.append(spec)
        return normalized

    def read_group(self, domain, fields, groupby, offset=0, limit=None, orderby=False, lazy=True):
        return super().read_group(
            domain,
            self._force_avg_measures(fields),
            groupby,
            offset=offset,
            limit=limit,
            orderby=orderby,
            lazy=lazy,
        )
