#!/usr/bin/env bash
set -euo pipefail

# Fresh, named test database only. Never stop the production service or upgrade
# its database. Reuse the protected runtime configuration without copying secrets.
test "$(hostname)" = "imytestth"
test "$(id -u)" = 0
ARCHIVE=/home/mamingxing/iot-v2-candidate.tar.gz
BASE=/opt/odoo/iot-v2-isolated-20260906
DB=iot_v2_isolated_20260906
PY=/opt/odoo/venv/bin/python3
ODOO=/opt/odoo/odoo19/odoo-bin
CONF=/opt/odoo/config/odoo.conf
test -f "$ARCHIVE"
test -f "$CONF"
mkdir -p "$BASE/addons/iot_control_center" "$BASE/data"
tar -xzf "$ARCHIVE" -C "$BASE/addons/iot_control_center"
chown -R odoo:odoo "$BASE"
cd "$BASE"
ADDONS=$("$PY" - "$CONF" <<'PY'
import configparser,sys
c=configparser.ConfigParser(interpolation=None)
c.read(sys.argv[1])
print(c['options'].get('addons_path','/opt/odoo/odoo19/addons'))
PY
)
sha256sum "$ARCHIVE"
set +e
runuser -u odoo -- timeout 1800 nice -n 10 "$PY" "$ODOO" -c "$CONF" \
  --addons-path="$BASE/addons,$ADDONS" --data-dir="$BASE/data" \
  -d "$DB" --db-filter="^${DB}$" -i iot_control_center -u iot_control_center \
  --test-enable --test-tags=/iot_control_center --without-demo=all \
  --workers=0 --max-cron-threads=0 --no-http --stop-after-init \
  --http-interface=127.0.0.1 --http-port=18089 --gevent-port=18092 \
  --logfile="$BASE/test.log" >"$BASE/console.log" 2>&1
RESULT=$?
set -e
chmod 644 "$BASE/test.log" "$BASE/console.log"
tail -n 25 "$BASE/test.log"
if test "$RESULT" != 0; then tail -n 35 "$BASE/console.log"; fi
systemctl is-active odoo iot-bridge
printf 'IOT_V2_ISOLATED_TEST_EXIT=%s\n' "$RESULT"
exit "$RESULT"
