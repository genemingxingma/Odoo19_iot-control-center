from importlib import import_module
import os
import socket


def pre_init_check(cr):
    missing = []
    required = {
        "paho.mqtt.client": "paho-mqtt",
        "pytz": "pytz",
    }
    for module_name, package_name in required.items():
        try:
            import_module(module_name)
        except Exception:
            missing.append(package_name)

    if missing:
        pkgs = " ".join(sorted(set(missing)))
        raise Exception(
            "IoT Control Center dependency check failed. Missing Python package(s): %s. "
            "Install in Odoo runtime environment, for example: "
            "'/opt/odoo/venv/bin/python3 -m pip install %s' then retry module install."
            % (pkgs, pkgs)
        )

    if os.getenv("IOT_SKIP_MQTT_BROKER_CHECK") == "1":
        return

    host = os.getenv("IOT_MQTT_CHECK_HOST", "iot.imytest.com")
    port = int(os.getenv("IOT_MQTT_CHECK_PORT", "1883"))
    try:
        with socket.create_connection((host, port), timeout=2.0):
            pass
    except OSError:
        raise Exception(
            "IoT Control Center requires an MQTT broker reachable at %s:%s. "
            "No service is reachable now. "
            "Install example (Ubuntu): "
            "'sudo apt update && sudo apt install -y mosquitto mosquitto-clients'; "
            "create user/password with "
            "'sudo mosquitto_passwd -c /etc/mosquitto/passwd imytest'; "
            "set listener/auth in /etc/mosquitto/conf.d/*.conf and run "
            "'sudo systemctl enable --now mosquitto'."
            % (host, port)
        )
