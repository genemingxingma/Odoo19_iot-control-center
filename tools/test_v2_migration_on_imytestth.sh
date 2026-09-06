#!/usr/bin/env bash
set -euo pipefail
test "$(hostname)" = "imytestth"
test "$(id -u)" = 0
BASE=/opt/odoo/iot-v2-isolated-20260906
DB=iot_v2_migration_20260906
PY=/opt/odoo/venv/bin/python3
ODOO=/opt/odoo/odoo19/odoo-bin
CONF=/opt/odoo/config/odoo.conf
mkdir -p "$BASE/v1-addons/iot_control_center" "$BASE/migration-data"
tar -xzf /home/mamingxing/iot-v1-fixture.tar.gz -C "$BASE/v1-addons/iot_control_center"
chown -R odoo:odoo "$BASE/v1-addons" "$BASE/migration-data"
cd "$BASE"
CORE=/opt/odoo/odoo19/odoo/addons
COMMON=(-c "$CONF" -d "$DB" --db-filter="^${DB}$" --data-dir="$BASE/migration-data"
  --workers=0 --max-cron-threads=0 --no-http --http-interface=127.0.0.1 --http-port=18079 --gevent-port=18082)
run_version() {
  local version=$1
  shift
  runuser -u odoo -- timeout 1800 nice -n 10 "$PY" "$ODOO" "${COMMON[@]}" \
    --addons-path="$BASE/$version,$CORE" --without-demo=True --stop-after-init "$@"
}
fixture() {
  local version=$1 phase=$2
  runuser -u odoo -- env IOT_FIXTURE_PHASE="$phase" "$PY" "$ODOO" shell "${COMMON[@]}" \
    --addons-path="$BASE/$version,$CORE" --logfile="$BASE/migration-fixture.log" \
    < "$BASE/addons/iot_control_center/tools/v2_migration_fixture.py"
}
# Do not reuse this name after a completed migration; create a new named fixture.
run_version v1-addons -i iot_control_center --logfile="$BASE/migration-v1.log"
fixture v1-addons seed
set +e
run_version addons -u iot_control_center --logfile="$BASE/migration-gate.log"
gate_result=$?
set -e
test "$gate_result" != 0
grep -q 'V2 cutover requires a verified backup' "$BASE/migration-gate.log"
fixture v1-addons authorize
run_version addons -u iot_control_center --logfile="$BASE/migration-v2.log"
fixture addons verify
systemctl is-active odoo iot-bridge iot-ota-proxy
printf 'IOT_V2_ISOLATED_MIGRATION_OK\n'
