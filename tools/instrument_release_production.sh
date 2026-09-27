#!/usr/bin/env bash
set -Eeuo pipefail

REHEARSAL=${1:?rehearsal path required}
RELEASE=${2:?release path required}
PROD=odoo-26-1-16
TARGET=/opt/odoo/custom_addons/iot_control_center
CANDIDATE="$REHEARSAL/candidate/iot_control_center"
FILESTORE=/opt/odoo/data/filestore/$PROD

[[ "$REHEARSAL" =~ ^/opt/odoo/module_backups/iot_instruments_test_[0-9]{8}_[0-9]{6}$ ]]
[[ "$RELEASE" =~ ^/opt/odoo/module_backups/iot_instruments_production_[0-9]{8}_[0-9]{6}$ ]]
test -d "$CANDIDATE"
test -f "$CANDIDATE/deploy/lan_ota_proxy.py"
test -f "$CANDIDATE/__manifest__.py"
test ! -e "$RELEASE"
test -d "$TARGET"
test -d "$FILESTORE"

mkdir -p "$RELEASE/backup" "$RELEASE/evidence"
cp -a "$TARGET" "$RELEASE/backup/iot_control_center"
cp -a /usr/local/bin/iot_bridge "$RELEASE/backup/iot_bridge"
for item in /etc/systemd/system/iot-bridge.service /etc/systemd/system/iot-ota-proxy.service; do
    test ! -e "$item" || cp -a "$item" "$RELEASE/backup/"
done

/opt/odoo/venv/bin/python3 - "$RELEASE" <<'PY'
import configparser, pathlib, shlex, sys
root = pathlib.Path(sys.argv[1])
source = configparser.ConfigParser(interpolation=None)
source.read('/opt/odoo/config/odoo.conf')
options = source['options']
host = options.get('db_host') or 'localhost'
port = options.get('db_port') or '5432'
user = options.get('db_user') or 'odoo'
password = options.get('db_password') or ''
(root / 'pg.env').write_text('\n'.join([
    'export PGHOST=' + shlex.quote(host),
    'export PGPORT=' + shlex.quote(port),
    'export PGUSER=' + shlex.quote(user),
    'export PGPASSWORD=' + shlex.quote(password),
]) + '\n')
PY
chmod 600 "$RELEASE/pg.env"
source "$RELEASE/pg.env"

fingerprint() {
    psql -X -v ON_ERROR_STOP=1 -At -d "$PROD" <<'SQL'
SELECT 'res_company|'||count(*)||'|'||md5(coalesce(string_agg(md5(concat_ws('|',id,name,partner_id,currency_id)),'' ORDER BY id),'')) FROM res_company;
SELECT 'iot_device|'||count(*)||'|'||md5(coalesce(string_agg(md5(concat_ws('|',id,name,serial,module_id,company_id,active)),'' ORDER BY id),'')) FROM iot_device;
SELECT 'iot_instrument|'||count(*)||'|'||md5(coalesce(string_agg(md5(concat_ws('|',id,name,uid,kind,company_id,active,token_hash)),'' ORDER BY id),'')) FROM iot_instrument;
SELECT 'iot_instrument_recipe|'||count(*)||'|'||md5(coalesce(string_agg(md5(concat_ws('|',id,name,uid,revision,state,company_id,active)),'' ORDER BY id),'')) FROM iot_instrument_recipe;
SELECT 'iot_instrument_recipe_step|'||count(*)||'|'||md5(coalesce(string_agg(md5(concat_ws('|',id,recipe_id,sequence,kind,duration_s,rps,reverse_s,cycles)),'' ORDER BY id),'')) FROM iot_instrument_recipe_step;
SELECT 'iot_instrument_command|'||count(*)||'|'||md5(coalesce(string_agg(md5(concat_ws('|',id,uid,instrument_id,name,payload::text)),'' ORDER BY id),'')) FROM iot_instrument_command;
SQL
}

manifest() {
    local root=$1
    (cd "$root" && find . -type f ! -path '*/__pycache__/*' ! -name '*.pyc' -print0 | sort -z | xargs -0 sha256sum)
}

filestore_manifest() {
    local root=$1
    (cd "$root" && find . -type f -print0 | sort -z | xargs -0 sha256sum)
}

backup_failure() {
    local rc=$?
    trap - ERR
    systemctl start odoo || true
    systemctl start iot-ota-proxy || true
    echo "RELEASE_ABORTED backup_or_preflight_failed rc=$rc"
    exit "$rc"
}

rollback() {
    local rc=$?
    trap - ERR
    echo "RELEASE_FAILED rollback_start rc=$rc"
    systemctl stop odoo iot-ota-proxy || true
    rm -rf "$TARGET"
    cp -a "$RELEASE/backup/iot_control_center" "$TARGET"
    dropdb --if-exists "$PROD"
    createdb "$PROD"
    pg_restore --no-owner --no-acl -d "$PROD" "$RELEASE/backup/production.dump"
    rm -rf "$FILESTORE"
    cp -a --reflink=auto "$RELEASE/backup/filestore/$PROD" "$FILESTORE"
    systemctl start odoo
    systemctl start iot-ota-proxy || true
    echo "RELEASE_FAILED rollback_complete rc=$rc"
    exit "$rc"
}
manifest "$CANDIDATE" > "$RELEASE/evidence/candidate.sha256"

systemctl stop odoo iot-ota-proxy
trap backup_failure ERR
! systemctl is-active --quiet odoo
fingerprint > "$RELEASE/evidence/protected-before.txt"

umask 077
pg_dump -Fc -f "$RELEASE/backup/production.dump" "$PROD"
pg_restore --list "$RELEASE/backup/production.dump" > "$RELEASE/evidence/production-dump.list"
sha256sum "$RELEASE/backup/production.dump" > "$RELEASE/evidence/production-dump.sha256"
mkdir -p "$RELEASE/backup/filestore"
cp -a --reflink=auto "$FILESTORE" "$RELEASE/backup/filestore/$PROD"
test "$(find "$FILESTORE" -type f | wc -l)" = "$(find "$RELEASE/backup/filestore/$PROD" -type f | wc -l)"
filestore_manifest "$FILESTORE" > "$RELEASE/evidence/filestore-before.sha256"
filestore_manifest "$RELEASE/backup/filestore/$PROD" > "$RELEASE/evidence/filestore-backup.sha256"
diff -u "$RELEASE/evidence/filestore-before.sha256" "$RELEASE/evidence/filestore-backup.sha256"

trap rollback ERR

rm -rf "$TARGET"
cp -a "$CANDIDATE" "$TARGET"
chown -R root:odoo "$TARGET"
manifest "$TARGET" > "$RELEASE/evidence/installed.sha256"
diff -u "$RELEASE/evidence/candidate.sha256" "$RELEASE/evidence/installed.sha256"
python3 -m py_compile "$TARGET/deploy/lan_ota_proxy.py"

ADDONS=$(/opt/odoo/venv/bin/python3 - <<'PY'
import configparser
c = configparser.ConfigParser(interpolation=None)
c.read('/opt/odoo/config/odoo.conf')
print(c['options'].get('addons_path', '/opt/odoo/odoo19/odoo/addons'))
PY
)
touch "$RELEASE/evidence/upgrade.log"
chown odoo:odoo "$RELEASE/evidence/upgrade.log"
runuser -u odoo -- /opt/odoo/venv/bin/python3 /opt/odoo/odoo19/odoo-bin \
    -c /opt/odoo/config/odoo.conf -d "$PROD" --db-filter="^$PROD$" \
    --addons-path="$ADDONS" -u iot_control_center --stop-after-init --no-http \
    --workers=0 --max-cron-threads=0 --logfile="$RELEASE/evidence/upgrade.log"

systemctl start odoo
systemctl start iot-ota-proxy
for _ in $(seq 1 30); do
    if systemctl is-active --quiet odoo && curl -fsS -o /dev/null http://192.168.10.15:8069/web/login; then
        break
    fi
    sleep 2
done
systemctl is-active --quiet odoo iot-bridge iot-ota-proxy mosquitto
curl -fsS -o /dev/null http://192.168.10.15:8069/web/login
systemctl restart iot-ota-proxy
systemctl is-active --quiet iot-ota-proxy
test -f "$TARGET/deploy/lan_ota_proxy.py"

fingerprint > "$RELEASE/evidence/protected-after.txt"
diff -u "$RELEASE/evidence/protected-before.txt" "$RELEASE/evidence/protected-after.txt"

runuser -u odoo -- /opt/odoo/venv/bin/python3 /opt/odoo/odoo19/odoo-bin shell \
    -c /opt/odoo/config/odoo.conf -d "$PROD" --no-http --max-cron-threads=0 \
    --addons-path="$ADDONS" <<'PY'
module = env['ir.module.module'].search([('name', '=', 'iot_control_center')], limit=1)
assert module.latest_version == '19.0.2.6.0', module.latest_version
assert 'device_id' in env['iot.instrument']._fields
assert env.ref('iot_control_center.action_iot_instrument_bind').res_model == 'iot.instrument.bind.wizard'
print('PRODUCTION_ORM_OK', module.latest_version)
PY

sha256sum /usr/local/bin/iot_bridge "$RELEASE/backup/iot_bridge" > "$RELEASE/evidence/bridge.sha256"
rm -f "$RELEASE/pg.env"
trap - ERR
echo "PRODUCTION_RELEASE_OK database=$PROD release=$RELEASE"
