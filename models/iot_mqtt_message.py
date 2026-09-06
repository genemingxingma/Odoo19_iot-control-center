import json
from datetime import datetime
from datetime import timedelta

from odoo import api, fields, models
from ..core.telemetry import timestamp


class IoTMQTTMessage(models.Model):
    _name = "iot.mqtt.message"
    _description = "MQTT Message Queue"
    _order = "id desc"

    state = fields.Selection([("new", "New"), ("done", "Done"), ("error", "Error")], default="new", required=True, index=True)
    topic = fields.Char(required=True, index=True)
    payload = fields.Text(required=True)
    retained = fields.Boolean(default=False, index=True)
    error = fields.Text()
    received_at = fields.Datetime(default=fields.Datetime.now, required=True)
    processed_at = fields.Datetime()

    device_serial = fields.Char(index=True)
    message_type = fields.Selection(
        [("status", "Status"), ("telemetry", "Telemetry"), ("unknown", "Unknown")],
        default="unknown",
        index=True,
    )
    device_id = fields.Many2one("iot.device")
    company_id = fields.Many2one(related="device_id.company_id", store=True, readonly=True, index=True)

    @api.model
    def init(self):
        self.env.cr.execute(
            """
            CREATE INDEX IF NOT EXISTS iot_mqtt_message_state_id_idx
            ON iot_mqtt_message (state, id)
            """
        )
        self.env.cr.execute(
            """
            CREATE INDEX IF NOT EXISTS iot_mqtt_message_serial_type_id_idx
            ON iot_mqtt_message (lower(device_serial), message_type, id DESC)
            """
        )
        self.env.cr.execute(
            """
            CREATE INDEX IF NOT EXISTS iot_mqtt_message_type_state_received_idx
            ON iot_mqtt_message (message_type, state, received_at DESC, id DESC)
            """
        )
        self.env.cr.execute(
            """
            CREATE INDEX IF NOT EXISTS iot_mqtt_message_serial_type_topic_received_idx
            ON iot_mqtt_message (lower(device_serial), message_type, topic, received_at DESC, id DESC)
            """
        )

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
            [("active", "=", True), ("serial", "=ilike", key)],
            order="company_id desc, last_seen desc, id desc",
            limit=1,
        )
        if not device:
            device = device_model.search(
                [("active", "=", True), ("module_id", "=ilike", key)],
                order="company_id desc, last_seen desc, id desc",
                limit=1,
            )
        if device:
            return device

        # Serialize create-per-key to avoid duplicate rows under concurrent cron workers.
        self.env.cr.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", [f"iot.device:{key}"])
        device = device_model.search(
            [("active", "=", True), ("serial", "=ilike", key)],
            order="company_id desc, last_seen desc, id desc",
            limit=1,
        )
        if not device:
            device = device_model.search(
                [("active", "=", True), ("module_id", "=ilike", key)],
                order="company_id desc, last_seen desc, id desc",
                limit=1,
            )
        if device:
            return device
        return device_model.with_context(iot_auto_discovery=True).create({"name": key, "serial": key, "company_id": False})

    @api.model
    def _create_from_mqtt(self, topic, payload_text, retained=False, received_at=None):
        parts = (topic or "").split("/")
        serial = parts[-2] if len(parts) >= 3 else False
        kind = parts[-1] if parts and parts[-1] in ("status", "telemetry") else "unknown"
        return self.sudo().create({"topic": topic, "payload": payload_text,
            "retained": bool(retained), "device_serial": serial, "message_type": kind,
            "received_at": received_at or fields.Datetime.now()})

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
            return self.received_at or fields.Datetime.now()
        try:
            return timestamp(value)
        except Exception:
            return self.received_at or fields.Datetime.now()

    @api.model
    def _find_device_by_reported_identity(self, module_id):
        key = self._normalize_device_key(module_id)
        if not key:
            return self.env["iot.device"].browse()
        return self.env["iot.device"].sudo().search(
            [
                ("active", "=", True),
                "|",
                ("module_id", "=ilike", key),
                ("serial", "=ilike", key),
            ],
            order="company_id desc, last_seen desc, id desc",
            limit=1,
        )

    def _process_one(self, preloaded_device=None):
        self.ensure_one()
        payload = self._parse_payload()
        device_model = self.env["iot.device"]
        no_track_ctx = device_model._system_no_track_context()
        module_id = payload.get("module_id") if isinstance(payload, dict) else None
        # The hardware module ID is authoritative. Legacy MQTT topics may still
        # contain an old alias, so resolve the reported identity before creating
        # an auto-discovered row for the topic key.
        device = self._find_device_by_reported_identity(module_id)
        if not device:
            device = preloaded_device or device_model.browse()
        if not device and self.device_serial:
            device = self._find_or_create_device_by_key(module_id or self.device_serial)
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
            if self.retained:
                vals = {}
                module_id = payload.get("module_id") if isinstance(payload, dict) else None
                if module_id and device.module_id != str(module_id):
                    vals["module_id"] = str(module_id)
                fw = payload.get("firmware_version") if isinstance(payload, dict) else None
                if fw and device.firmware_version != fw:
                    vals["firmware_version"] = fw
                if vals:
                    device.write(vals)
                self.with_context(**no_track_ctx).write(done_vals)
                return
            if state in ("on", "off", "unknown"):
                device._apply_state_report(state, reported_at=reported_at)
                device._apply_command_ack(payload, reported_at=reported_at)
            else:
                device.last_seen = reported_at

            fw = payload.get("firmware_version") if isinstance(payload, dict) else None
            if fw:
                device._apply_firmware_report(fw, reported_at=reported_at, ota_state=ota_state)
            if isinstance(payload, dict):
                device._apply_runtime_report(payload, reported_at=reported_at)
            if module_id:
                device._apply_identity_report(str(module_id), reported_at=reported_at)
            if isinstance(payload, dict) and "manual_override" in payload:
                device._apply_manual_override_report(payload, reported_at=reported_at)
            if isinstance(payload, dict) and "delay_active" in payload:
                device._apply_delay_report(payload, reported_at=reported_at)
            if ota_state:
                device._apply_firmware_upgrade_feedback(ota_state, note=ota_note, reported_at=reported_at)
            if isinstance(payload, dict) and "schedule_version" in payload:
                device._apply_schedule_report(payload, reported_at=reported_at)

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
                WHERE active IS TRUE
                  AND (
                    lower(serial) = ANY(%s)
                    OR lower(module_id) = ANY(%s)
                  )
                """,
                (list(key_set), list(key_set)),
            )
            devices = device_model.browse([row[0] for row in self.env.cr.fetchall()])
        except Exception:
            devices = self.env["iot.device"].browse()
            for key in key_set:
                dev = device_model.search(
                    [("active", "=", True), "|", ("serial", "=ilike", key), ("module_id", "=ilike", key)],
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

        # Do not create devices in bulk here. _process_one first resolves the
        # payload's module_id, preventing legacy topic aliases from creating a
        # second row that later collides with an existing hardware identity.
        return device_map

    @api.model
    def _cron_process_new_messages(self, limit=500):
        no_track_ctx = self.env["iot.device"]._system_no_track_context()
        # Multiple Odoo workers or an administrator-triggered run may overlap.
        # Lock only this worker's rows and let concurrent processors skip them.
        self.env.cr.execute(
            """
            SELECT id
              FROM iot_mqtt_message
             WHERE state = 'new'
             ORDER BY id ASC
             FOR UPDATE SKIP LOCKED
             LIMIT %s
            """,
            [int(limit)],
        )
        messages = self.with_context(**no_track_ctx).browse([row[0] for row in self.env.cr.fetchall()])
        if not messages:
            return

        # Every committed transition matters for uptime and command acknowledgement.
        selected = messages.sorted(key=lambda msg: (msg.received_at, msg.id))
        serials = selected.mapped("device_serial")
        device_map = self._preload_devices(serials)
        for msg in selected:
            try:
                # ORM writes are deferred until flush. Keep each message in its
                # own savepoint so a late constraint error cannot roll back the
                # entire MQTT batch, as happened with identity collisions.
                with self.env.cr.savepoint():
                    key = self._normalize_device_key(msg.device_serial)
                    msg._process_one(preloaded_device=device_map.get(key))
                    self.env.flush_all()
            except Exception as exc:
                msg.with_context(**no_track_ctx).write(
                    {
                        "state": "error",
                        "error": str(exc),
                        "processed_at": fields.Datetime.now(),
                    }
                )

    @api.model
    def _delete_in_batches(self, where_sql, params, batch_size):
        batch_size = max(int(batch_size or 5000), 100)
        total_deleted = 0
        while True:
            self.env.cr.execute(
                f"""
                WITH doomed AS (
                    SELECT id
                    FROM iot_mqtt_message
                    WHERE {where_sql}
                    ORDER BY id
                    LIMIT %s
                )
                DELETE FROM iot_mqtt_message msg
                USING doomed
                WHERE msg.id = doomed.id
                """,
                list(params) + [batch_size],
            )
            deleted = self.env.cr.rowcount
            total_deleted += max(deleted, 0)
            self.env.cr.commit()
            if deleted < batch_size:
                break
        return total_deleted

    @api.model
    def _cron_purge_old_messages(self, batch_size=5000):
        icp = self.env["ir.config_parameter"].sudo()
        retention_days_raw = icp.get_param("iot_control_center.mqtt_message_retention_days", "7")
        telemetry_hours_raw = icp.get_param("iot_control_center.mqtt_telemetry_retention_hours", "24")
        try:
            retention_days = max(int(retention_days_raw or 7), 1)
        except Exception:
            retention_days = 7
        try:
            telemetry_hours = max(int(telemetry_hours_raw or 24), 1)
        except Exception:
            telemetry_hours = 24
        cutoff = fields.Datetime.now() - timedelta(days=retention_days)
        telemetry_cutoff = fields.Datetime.now() - timedelta(hours=telemetry_hours)
        self._delete_in_batches(
            "message_type = 'telemetry' AND state = 'done' AND received_at < %s",
            [telemetry_cutoff],
            batch_size,
        )
        self._delete_in_batches(
            "received_at < %s",
            [cutoff],
            batch_size,
        )
