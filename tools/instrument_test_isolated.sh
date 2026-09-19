#!/usr/bin/env bash
set -euo pipefail
test "$(hostname)" = imytestth
STAGE="$1"
DB="$2"
[[ "$STAGE" =~ ^/tmp/iot_instruments_[0-9a-f]{12}$ ]]
[[ "$DB" =~ ^iot_instruments_[0-9a-f]{12}$ ]]
test ! -e "$STAGE"
mkdir -p "$STAGE/addons" "$STAGE/data"
tar -xzf "$STAGE.tgz" -C "$STAGE/addons"
umask 077
/opt/odoo/venv/bin/python3 - "$STAGE/test.conf" <<'PY'
import configparser
import sys
source = configparser.ConfigParser(interpolation=None)
source.read('/opt/odoo/config/odoo.conf')
config = configparser.ConfigParser(interpolation=None)
config['options'] = {key: value for key, value in source['options'].items()
                     if key in ('db_host', 'db_port', 'db_user', 'db_password', 'db_sslmode')}
config['options'].update({'smtp_server': '127.0.0.1', 'smtp_port': '9'})
with open(sys.argv[1], 'w') as destination:
    config.write(destination)
PY
chown -R odoo:odoo "$STAGE"
cd "$STAGE"
# A new database contains synthetic fixtures only. No clone, email, workers or cron.
systemd-run --quiet --wait --pipe --collect --unit="$DB-tests" \
    -p User=odoo -p IPAddressDeny=any -p IPAddressAllow=localhost -p IPAddressAllow=192.168.10.20 \
    -p MemoryMax=3G -p NoNewPrivileges=yes \
    /opt/odoo/venv/bin/python3 /opt/odoo/odoo19/odoo-bin \
    -c "$STAGE/test.conf" -d "$DB" --db-filter="^$DB$" \
    --addons-path="$STAGE/addons,/opt/odoo/odoo19/odoo/addons" \
    --data-dir="$STAGE/data" --without-demo=True \
    -i iot_control_center --test-enable --test-tags=/iot_control_center \
    --stop-after-init --http-interface=127.0.0.1 --http-port=18769 --gevent-port=18772 --workers=0 --max-cron-threads=0 \
    --logfile="$STAGE/test.log" || { tail -n 100 "$STAGE/test.log"; exit 1; }
grep -E 'Starting Test|tests.stats|post-tests|failed|error\(s\)' "$STAGE/test.log" | tail -n 60
! grep -Eq '[1-9][0-9]* failures|[1-9][0-9]* errors|At least one test failed' "$STAGE/test.log"
sudo -u odoo /opt/odoo/venv/bin/python3 /opt/odoo/odoo19/odoo-bin shell \
    -c "$STAGE/test.conf" -d "$DB" --no-http --max-cron-threads=0 \
    --addons-path="$STAGE/addons,/opt/odoo/odoo19/odoo/addons" --data-dir="$STAGE/data" \
    --logfile="$STAGE/export.log" < "$STAGE"_i18n.py
