from importlib import import_module


def pre_init_check(cr):
    missing = []
    required = {
        "pytz": "pytz",
        "paho.mqtt.client": "paho-mqtt",
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
