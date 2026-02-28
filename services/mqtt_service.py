import logging
import os
import threading
import time
import uuid
from pathlib import Path

import fcntl

import paho.mqtt.client as mqtt
import psycopg2
from odoo import SUPERUSER_ID, api
from odoo.modules.registry import Registry

_logger = logging.getLogger(__name__)

_instances = {}
_instances_lock = threading.Lock()


class MQTTService:
    def __init__(self, dbname, config):
        self.dbname = dbname
        self.config = config
        self._client = None
        self._started = False
        self._lock = threading.Lock()
        self._singleton_fd = None

    def _singleton_lock_path(self):
        safe_dbname = "".join(ch if ch.isalnum() or ch in ("_", "-") else "_" for ch in self.dbname)
        return Path("/tmp") / f"iot_mqtt_subscriber_{safe_dbname}.lock"

    def _acquire_singleton_lock(self):
        if self._singleton_fd:
            return True
        lock_path = self._singleton_lock_path()
        fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR, 0o644)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            os.close(fd)
            return False
        self._singleton_fd = fd
        return True

    def _release_singleton_lock(self):
        if not self._singleton_fd:
            return
        try:
            fcntl.flock(self._singleton_fd, fcntl.LOCK_UN)
        except OSError:
            pass
        try:
            os.close(self._singleton_fd)
        except OSError:
            pass
        self._singleton_fd = None

    def _make_client(self):
        # Use process-unique client_id to avoid cross-worker broker kick-out
        # loops when multiple Odoo workers ensure MQTT service concurrently.
        client_id = f"odoo-iot-{self.dbname}-{os.getpid()}"
        client = mqtt.Client(client_id=client_id, clean_session=True)
        # Backoff reconnect attempts to avoid hot reconnect loops under broker/network issues.
        client.reconnect_delay_set(min_delay=2, max_delay=30)
        username = self.config.get("username")
        password = self.config.get("password")
        if username:
            client.username_pw_set(username, password or None)

        def on_connect(c, userdata, flags, rc):
            if rc == 0:
                topic_root = self.config["topic_root"]
                c.subscribe(f"{topic_root}/+/status", qos=1)
                c.subscribe(f"{topic_root}/+/telemetry", qos=1)
                _logger.info("IoT MQTT connected and subscribed on %s", topic_root)
            else:
                _logger.error("IoT MQTT connect failed rc=%s", rc)

        def on_message(c, userdata, msg):
            payload_text = msg.payload.decode("utf-8", errors="ignore")
            self._enqueue_message(msg.topic, payload_text)

        def on_disconnect(c, userdata, rc):
            # Mark as disconnected so next publish will trigger reconnect.
            if rc != 0:
                _logger.warning("IoT MQTT disconnected rc=%s", rc)
            self._started = False

        client.on_connect = on_connect
        client.on_message = on_message
        client.on_disconnect = on_disconnect
        return client

    def _enqueue_message(self, topic, payload_text):
        registry = Registry(self.dbname)
        for attempt in range(3):
            try:
                with registry.cursor() as cr:
                    env = api.Environment(cr, SUPERUSER_ID, {})
                    msg = env["iot.mqtt.message"].create_from_mqtt(topic, payload_text)
                    try:
                        msg._process_one()
                    except Exception as exc:
                        _logger.exception("IoT MQTT message process failed topic=%s error=%s", topic, exc)
                    cr.commit()
                return
            except psycopg2.errors.SerializationFailure:
                if attempt >= 2:
                    _logger.exception("IoT MQTT enqueue failed after retries (serialization failure), topic=%s", topic)
                    return
                time.sleep(0.05 * (attempt + 1))

    def start(self):
        with self._lock:
            if self._started:
                return True
            if not self._acquire_singleton_lock():
                # Another worker/process owns MQTT subscription loop for this DB.
                return False
            host = self.config.get("host")
            port = self.config.get("port")
            keepalive = self.config.get("keepalive")
            if not host:
                self._release_singleton_lock()
                return False

            self._client = self._make_client()
            try:
                self._client.connect(host, port=port, keepalive=keepalive)
                self._client.loop_start()
                self._started = True
                return True
            except Exception as exc:
                _logger.error("IoT MQTT start failed for %s:%s (%s)", host, port, exc)
                self._client = None
                self._started = False
                self._release_singleton_lock()
                return False

    def publish(self, topic, payload):
        if not self.start():
            return False
        info = self._client.publish(topic, payload=payload, qos=1, retain=False)
        if info.rc == mqtt.MQTT_ERR_SUCCESS:
            return True

        # Retry once after reconnect to avoid transient disconnect causing UI errors.
        _logger.warning("IoT MQTT publish failed rc=%s topic=%s, retrying once", info.rc, topic)
        self.stop()
        if not self.start():
            return False
        info2 = self._client.publish(topic, payload=payload, qos=1, retain=False)
        return info2.rc == mqtt.MQTT_ERR_SUCCESS

    def stop(self):
        with self._lock:
            if self._client and self._started:
                self._client.loop_stop()
                self._client.disconnect()
            self._client = None
            self._started = False
            self._release_singleton_lock()



def _load_config(env):
    icp = env["ir.config_parameter"].sudo()
    host = icp.get_param("iot_control_center.mqtt_host")
    if host in (False, None, "", "False", "false"):
        host = ""

    port_raw = icp.get_param("iot_control_center.mqtt_port", 1883)
    keepalive_raw = icp.get_param("iot_control_center.mqtt_keepalive", 60)
    try:
        port = int(port_raw)
    except (TypeError, ValueError):
        port = 1883
    try:
        keepalive = int(keepalive_raw)
    except (TypeError, ValueError):
        keepalive = 60

    topic_root = icp.get_param("iot_control_center.mqtt_topic_root")
    if topic_root in (False, None, "", "False", "false"):
        topic_root = "iot/relay"
    username = icp.get_param("iot_control_center.mqtt_username")
    if username in (False, None, "False", "false"):
        username = ""
    password = icp.get_param("iot_control_center.mqtt_password")
    if password in (False, None, "False", "false"):
        password = ""

    return {
        "host": host,
        "port": port,
        "username": username,
        "password": password,
        "topic_root": topic_root,
        "keepalive": keepalive,
    }


def ensure_running(env):
    dbname = env.cr.dbname
    config = _load_config(env)
    if not config.get("host"):
        return None

    key = (dbname, config["host"], config["port"], config["username"], config["password"], config["topic_root"])
    with _instances_lock:
        current = _instances.get(dbname)
        if current and getattr(current, "config", {}) != config:
            current.stop()
            _instances.pop(dbname, None)
            current = None

        if not current:
            current = MQTTService(dbname, config)
            _instances[dbname] = current

    current.start()
    return current


def publish_once(env, topic, payload, retain=False):
    config = _load_config(env)
    host = config.get("host")
    if not host:
        return False
    port = config.get("port") or 1883
    keepalive = config.get("keepalive") or 60
    client_id = f"odoo-iot-pub-{env.cr.dbname}-{os.getpid()}-{uuid.uuid4().hex[:8]}"
    client = mqtt.Client(client_id=client_id, clean_session=True)
    if config.get("username"):
        client.username_pw_set(config.get("username"), config.get("password") or None)
    try:
        client.connect(host, port=port, keepalive=keepalive)
        client.loop_start()
        info = client.publish(topic, payload=payload, qos=1, retain=retain)
        info.wait_for_publish(timeout=2.0)
        return info.rc == mqtt.MQTT_ERR_SUCCESS
    except Exception as exc:
        _logger.error("IoT MQTT publish_once failed topic=%s error=%s", topic, exc)
        return False
    finally:
        try:
            client.loop_stop()
            client.disconnect()
        except Exception:
            pass
