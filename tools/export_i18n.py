"""Run through Odoo shell in an isolated database after upgrading this addon.

Then run check_i18n.py --write locally to merge reviewed translations.
Native extraction supplies model/view references and Odoo 19 runtime markers.
"""
from pathlib import Path

from odoo.modules.module import get_module_path
from odoo.tools.translate import trans_export

assert env.cr.dbname in {"iot_ui_test_20260906", "iot_v2_isolated_20260906"}
destination = Path(get_module_path("iot_control_center")) / "i18n" / "iot_control_center.pot"
with destination.open("wb") as output:
    trans_export(None, ["iot_control_center"], output, "po", env)
print("NATIVE_TRANSLATION_EXPORT_OK")
