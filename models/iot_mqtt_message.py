import json
from datetime import datetime
from datetime import timedelta

from odoo import api, fields, models


class IoTMQTTMessage(models.Model):
    _name = "iot.mqtt.message"
    _description = "MQTT Message Queue"
    _order = "id desc"

    state = fields.Selection([("new", "New"), ("done", "Done"), ("error", "Error")], default="new", required=True)
    topic = fields.Char(required=True, index=True)
    payload = fields.Text(required=True)
    error = fields.Text()
    received_at = fields.Datetime(default=fields.Datetime.now, required=True)
    processed_at = fields.Datetime()

    device_serial = fields.Char(index=True)
    message_type = fields.Selection([("status", "Status"), ("telemetry", "Telemetry"), ("unknown", "Unknown")], default="unknown")
    device_id = fields.Many2one("iot.device")

    @api.model
    def _normalize_device_key(self, value):
        return (value or "").strip().lower()

    @api.model
    def _find_or_create_device_by_key(self, key):
        key = self._normalize_device_key(key)
        if not key:
            return self.env["iot.device"].browse()
        device_model = self.env["iot.device"].sudo()
        no_track_ctx = device_model._system_no_track_context()
        device_model = device_model.with_context(**no_track_ctx)

        # Prefer exact serial match over module_id match to avoid route ambiguity
        # when legacy rows still carry old serial values.
        device = device_model.search(
            [("serial", "=ilike", key)],
            order="company_id desc, last_seen desc, id desc",
            limit=1,
        )
        if not device:
            device = device_model.search(
                [("module_id", "=ilike", key)],
                order="company_id desc, last_seen desc, id desc",
                limit=1,
            )
        if device:
            return device

        # Serialize create-per-key to avoid duplicate rows under concurrent cron workers.
        self.env.cr.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", [f"iot.device:{key}"])
        device = device_model.search(
            [("serial", "=ilike", key)],
            order="company_id desc, last_seen desc, id desc",
            limit=1,
        )
        if not device:
            device = device_model.search(
                [("module_id", "=ilike", key)],
                order="company_id desc, last_seen desc, id desc",
                limit=1,
            )
        if device:
            return device
        return device_model.create({"name": key, "serial": key})

    @api.model
    def create_from_mqtt(self, topic, payload_text):
        serial = False
        msg_type = "unknown"
        parts = (topic or "").split("/")
        if len(parts) >= 3:
            serial = parts[-2]
            msg_type = parts[-1] if parts[-1] in ("status", "telemetry") else "unknown"
        vals = {
            "topic": topic,
            "payload": payload_text,
            "device_serial": serial,
            "message_type": msg_type,
        }
        return self.sudo().create(vals)

    def _parse_payload(self):
        self.ensure_one()
        try:
            return json.loads(self.payload)
        except Exception:
            v = (self.payload or "").strip().lower()
            if v in ("on", "off"):
                return {"state": v}
            return {}

    def _parse_reported_at(self, payload):
        value = payload.get("reported_at") if isinstance(payload, dict) else None
        if not value:
            return fields.Datetime.now()
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=None)
        except Exception:
            return fields.Datetime.now()

    def _process_one(self, preloaded_device=None):
        self.ensure_one()
        payload = self._parse_payload()
        device_model = self.env["iot.device"]
        no_track_ctx = device_model._system_no_track_context()
        device = preloaded_device or device_model.browse()
        if not device and self.device_serial:
            device = self._find_or_create_device_by_key(self.device_serial)
        done_vals = {
            "state": "done",
            "processed_at": fields.Datetime.now(),
        }
        if device:
            done_vals["device_id"] = device.id
            device = device.with_context(**no_track_ctx)
            state = payload.get("state") if isinstance(payload, dict) else None
            ota_state = payload.get("ota_state") if isinstance(payload, dict) else None
            ota_note = payload.get("ota_note") if isinstance(payload, dict) else None
            reported_at = self._parse_reported_at(payload)
            if state in ("on", "off", "unknown"):
                device.apply_state_report(state, reported_at=reported_at)
            else:
                device.last_seen = fields.Datetime.now()

            fw = payload.get("firmware_version") if isinstance(payload, dict) else None
            if fw:
                device.apply_firmware_report(fw, reported_at=reported_at, ota_state=ota_state)
            module_id = payload.get("module_id") if isinstance(payload, dict) else None
            if module_id:
                device.apply_identity_report(str(module_id), reported_at=reported_at)
            if isinstance(payload, dict) and "manual_override" in payload:
                device.apply_manual_override_report(payload, reported_at=reported_at)
            if isinstance(payload, dict) and "delay_active" in payload:
                device.apply_delay_report(payload, reported_at=reported_at)
            if ota_state:
                device.apply_firmware_upgrade_feedback(ota_state, note=ota_note, reported_at=reported_at)
            if isinstance(payload, dict) and "schedule_version" in payload:
                device.apply_schedule_report(payload, reported_at=reported_at)

        self.with_context(**no_track_ctx).write(done_vals)

    @api.model
    def _preload_devices(self, serials):
        key_list = [self._normalize_device_key(s) for s in serials if self._normalize_device_key(s)]
        if not key_list:
            return {}
        key_set = set(key_list)
        device_model = self.env["iot.device"].sudo()
        no_track_ctx = device_model._system_no_track_context()
        device_model = device_model.with_context(**no_track_ctx)

        devices = self.env["iot.device"].browse()
        try:
            self.env.cr.execute(
                """
                SELECT id
                FROM iot_device
                WHERE lower(serial) = ANY(%s)
                   OR lower(module_id) = ANY(%s)
                """,
                (list(key_set), list(key_set)),
            )
            devices = device_model.browse([row[0] for row in self.env.cr.fetchall()])
        except Exception:
            devices = self.env["iot.device"].browse()
            for key in key_set:
                dev = device_model.search(
                    ["|", ("serial", "=ilike", key), ("module_id", "=ilike", key)],
                    order="last_seen desc, id desc",
                    limit=1,
                )
                devices |= dev

        serial_map = {}
        module_map = {}
        for dev in devices:
            serial_key = self._normalize_device_key(dev.serial)
            module_key = self._normalize_device_key(dev.module_id)
            if serial_key and serial_key in key_set and serial_key not in serial_map:
                serial_map[serial_key] = dev
            if module_key and module_key in key_set and module_key not in module_map:
                module_map[module_key] = dev

        device_map = {}
        for key in key_set:
            # Always prefer serial-key match for topic key routing.
            device_map[key] = serial_map.get(key) or module_map.get(key)

        missing = [k for k in key_set if not device_map.get(k)]
        if missing:
            for key in missing:
                dev = self._find_or_create_device_by_key(key)
                device_map[key] = dev
        return device_map

    @api.model
    def _cron_process_new_messages(self, limit=500):
        no_track_ctx = self.env["iot.device"]._system_no_track_context()
        messages = self.with_context(**no_track_ctx).search(
            [("state", "=", "new")],
            limit=limit,
            order="id asc",
        )
        if not messages:
            return

        # Keep only the latest message per (device_serial, message_type) in this batch.
        # Older duplicates are marked as done directly to reduce write amplification.
        latest_by_key = {}
        for msg in messages:
            serial_key = (msg.device_serial or "").strip().lower()
            if serial_key:
                key = (serial_key, msg.message_type or "unknown")
            else:
                key = (f"__msg_{msg.id}", msg.message_type or "unknown")
            latest_by_key[key] = msg

        selected = self.browse([m.id for m in latest_by_key.values()])
        skipped = messages - selected
        if skipped:
            skipped.with_context(**no_track_ctx).write(
                {
                    "state": "done",
                    "processed_at": fields.Datetime.now(),
                }
            )
        serials = selected.mapped("device_serial")
        device_map = self._preload_devices(serials)
        for msg in selected:
            try:
                key = self._normalize_device_key(msg.device_serial)
                msg._process_one(preloaded_device=device_map.get(key))
            except Exception as exc:
                msg.with_context(**no_track_ctx).write(
                    {
                        "state": "error",
                        "error": str(exc),
                        "processed_at": fields.Datetime.now(),
                    }
                )

    @api.model
    def _cron_purge_old_messages(self):
        icp = self.env["ir.config_parameter"].sudo()
        retention_days_raw = icp.get_param("iot_control_center.mqtt_message_retention_days", "7")
        try:
            retention_days = max(int(retention_days_raw or 7), 1)
        except Exception:
            retention_days = 7
        cutoff = fields.Datetime.now() - timedelta(days=retention_days)
        self.env.cr.execute("DELETE FROM iot_mqtt_message WHERE received_at < %s", [cutoff])
