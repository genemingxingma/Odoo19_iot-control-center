#!/usr/bin/env bash
set -euo pipefail
test "$(hostname)" = imytestth
STAGE="$1"
DB="$2"
[[ "$STAGE" =~ ^/tmp/iot_reliability_[0-9a-f]{12}$ ]]
[[ "$DB" =~ ^iot_reliability_[0-9a-f]{12}$ ]]
test ! -e "$STAGE"
mkdir -p "$STAGE/addons" "$STAGE/data"
tar -xzf "$STAGE.tgz" -C "$STAGE/addons"
chown -R odoo:odoo "$STAGE"
cd "$STAGE"
DBHOST=$(/opt/odoo/venv/bin/python3 -c 'import configparser; c=configparser.ConfigParser(interpolation=None); c.read("/opt/odoo/config/odoo.conf"); print(c["options"].get("db_host","localhost"))')
[[ "$DBHOST" =~ ^[0-9.]+$|^localhost$|^False$ ]]
test "$DBHOST" != False || DBHOST=localhost
systemd-run --quiet --wait --pipe --collect --unit="$DB-tests" \
    -p User=odoo -p IPAddressDeny=any -p IPAddressAllow=localhost -p "IPAddressAllow=$DBHOST" \
    -p MemoryMax=3G -p NoNewPrivileges=yes \
    /opt/odoo/venv/bin/python3 /opt/odoo/odoo19/odoo-bin \
    -c /opt/odoo/config/odoo.conf -d "$DB" --db-filter="^$DB$" \
    --smtp-server=127.0.0.1 --smtp-port=9 \
    --addons-path="$STAGE/addons,/opt/odoo/odoo19/odoo/addons" \
    --data-dir="$STAGE/data" --without-demo=True \
    -i iot_control_center --test-enable --test-tags=/iot_control_center \
    --stop-after-init --http-interface=127.0.0.1 --http-port=18919 --gevent-port=18920 --workers=0 --max-cron-threads=0 \
    --logfile="$STAGE/test.log" || { tail -n 100 "$STAGE/test.log"; exit 1; }
grep -E 'Starting Test|tests.stats|post-tests|failed|error\(s\)' "$STAGE/test.log" | tail -n 65
! grep -Eq '[1-9][0-9]* failures|[1-9][0-9]* errors|At least one test failed' "$STAGE/test.log"
echo RELIABILITY_NATIVE_TESTS_OK
