"""Native Odoo extraction, only in the synthetic instrument test database."""
from pathlib import Path
from odoo.modules.module import get_module_path
from odoo.tools.translate import trans_export

assert env.cr.dbname.startswith("iot_instruments_")
path = Path(get_module_path("iot_control_center")) / "i18n/iot_control_center.pot"
with path.open("wb") as output:
    trans_export(None, ["iot_control_center"], output, "po", env)
print("INSTRUMENT_NATIVE_TRANSLATION_EXPORT_OK")
