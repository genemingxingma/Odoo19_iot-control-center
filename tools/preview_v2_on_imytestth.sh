#!/usr/bin/env bash
set -euo pipefail
test "$(hostname)" = "imytestth"
test "$(id -u)" = 0
BASE=/opt/odoo/iot-v2-isolated-20260906
DB=iot_v2_isolated_20260906
PY=/opt/odoo/venv/bin/python3
ODOO=/opt/odoo/odoo19/odoo-bin
cd "$BASE"
COMMON=(-c /opt/odoo/config/odoo.conf -d "$DB" --db-filter="^${DB}$"
  --data-dir="$BASE/data" --addons-path="$BASE/addons,/opt/odoo/odoo19/odoo/addons"
  --workers=0 --max-cron-threads=0 --http-interface=127.0.0.1 --http-port=18069 --gevent-port=18072)
runuser -u odoo -- "$PY" "$ODOO" shell "${COMMON[@]}" --no-http --logfile="$BASE/ui-fixture.log" \
  < "$BASE/addons/iot_control_center/tools/v2_ui_fixture.py"
printf 'UI_PREVIEW_LOOPBACK_ONLY_18069\n'
runuser -u odoo -- timeout 900 "$PY" "$ODOO" "${COMMON[@]}" --logfile="$BASE/ui-preview.log"
