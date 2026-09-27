#!/usr/bin/env bash
set -euo pipefail
test "$(hostname)" = imytestth
test "$(id -u)" = 0
STAGE="$1"
DB="$2"
PROD=odoo-26-1-16
[[ "$STAGE" =~ ^/opt/odoo/module_backups/iot_instruments_test_[0-9]{8}_[0-9]{6}$ ]]
[[ "$DB" =~ ^iot_instruments_upgrade_[0-9]{8}_[0-9]{6}$ ]]
test ! -e "$STAGE"
test -f /tmp/iot-instrument-upgrade-candidate.tgz
mkdir -p "$STAGE/candidate" "$STAGE/old" "$STAGE/data" "$STAGE/evidence"
tar -xzf /tmp/iot-instrument-upgrade-candidate.tgz -C "$STAGE/candidate"
cp -a /opt/odoo/custom_addons/iot_control_center "$STAGE/old/"

umask 077
/opt/odoo/venv/bin/python3 - "$STAGE" <<'PY'
import configparser, pathlib, shlex, sys
root=pathlib.Path(sys.argv[1])
source=configparser.ConfigParser(interpolation=None); source.read('/opt/odoo/config/odoo.conf')
options=source['options']
safe=configparser.ConfigParser(interpolation=None)
safe['options']={k:v for k,v in options.items() if k in ('db_host','db_port','db_user','db_password','db_sslmode')}
safe['options'].update({'smtp_server':'127.0.0.1','smtp_port':'9'})
with (root/'test.conf').open('w') as handle: safe.write(handle)
host=options.get('db_host') or 'localhost'; port=options.get('db_port') or '5432'
user=options.get('db_user') or 'odoo'; password=options.get('db_password') or ''
(root/'pg.env').write_text('\n'.join([
    'export PGHOST='+shlex.quote(host), 'export PGPORT='+shlex.quote(port),
    'export PGUSER='+shlex.quote(user), 'export PGPASSWORD='+shlex.quote(password)])+'\n')
PY
source "$STAGE/pg.env"
pg_dump -Fc -f "$STAGE/production.dump" "$PROD"
pg_restore --list "$STAGE/production.dump" >/dev/null
createdb "$DB"
pg_restore --no-owner --no-acl -d "$DB" "$STAGE/production.dump"
# Keep attachment reads realistic without sharing writable inodes with production.
mkdir -p "$STAGE/data/filestore"
cp -a --reflink=auto "/opt/odoo/data/filestore/$PROD" "$STAGE/data/filestore/$DB"

fingerprint() {
    psql -X -v ON_ERROR_STOP=1 -At -d "$DB" <<'SQL'
SELECT 'res_company|'||count(*)||'|'||md5(coalesce(string_agg(md5(concat_ws('|',id,name,partner_id,currency_id)),'' ORDER BY id),'')) FROM res_company;
SELECT 'iot_device|'||count(*)||'|'||md5(coalesce(string_agg(md5(concat_ws('|',id,name,serial,module_id,company_id,active)),'' ORDER BY id),'')) FROM iot_device;
SELECT 'iot_instrument|'||count(*)||'|'||md5(coalesce(string_agg(md5(concat_ws('|',id,name,uid,kind,company_id,active,token_hash,last_seen,status_json::text)),'' ORDER BY id),'')) FROM iot_instrument;
SELECT 'iot_instrument_recipe|'||count(*)||'|'||md5(coalesce(string_agg(md5(concat_ws('|',id,name,uid,revision,state,company_id,active)),'' ORDER BY id),'')) FROM iot_instrument_recipe;
SELECT 'iot_instrument_recipe_step|'||count(*)||'|'||md5(coalesce(string_agg(md5(concat_ws('|',id,recipe_id,sequence,kind,duration_s,rps,reverse_s,cycles)),'' ORDER BY id),'')) FROM iot_instrument_recipe_step;
SELECT 'iot_instrument_command|'||count(*)||'|'||md5(coalesce(string_agg(md5(concat_ws('|',id,uid,instrument_id,name,state,payload::text)),'' ORDER BY id),'')) FROM iot_instrument_command;
SQL
}
fingerprint > "$STAGE/evidence/protected-before.txt"
psql -X -v ON_ERROR_STOP=1 -d "$DB" <<'SQL'
UPDATE ir_cron SET active=false;
UPDATE ir_mail_server SET active=false;
SQL
chown -R odoo:odoo "$STAGE"

ADDONS=$(/opt/odoo/venv/bin/python3 - <<'PY'
import configparser
c=configparser.ConfigParser(interpolation=None); c.read('/opt/odoo/config/odoo.conf')
print(c['options'].get('addons_path','/opt/odoo/odoo19/odoo/addons'))
PY
)
systemd-run --quiet --wait --pipe --collect --unit="$DB-tests" \
    -p User=odoo -p IPAddressDeny=any -p IPAddressAllow=localhost -p IPAddressAllow=192.168.10.20 \
    -p MemoryMax=3G -p NoNewPrivileges=yes \
    /opt/odoo/venv/bin/python3 /opt/odoo/odoo19/odoo-bin \
    -c "$STAGE/test.conf" -d "$DB" --db-filter="^$DB$" \
    --addons-path="$STAGE/candidate,$ADDONS" --data-dir="$STAGE/data" \
    -u iot_control_center --test-enable --test-tags=/iot_control_center \
    --stop-after-init --http-interface=127.0.0.1 --http-port=18869 --gevent-port=18872 \
    --workers=0 --max-cron-threads=0 --logfile="$STAGE/evidence/upgrade.log" || {
        tail -n 120 "$STAGE/evidence/upgrade.log"; exit 1; }
grep -E 'tests.stats|post-tests|failed|error\(s\)' "$STAGE/evidence/upgrade.log" | tail -n 30
! grep -Eq '[1-9][0-9]* failures|[1-9][0-9]* errors|At least one test failed' "$STAGE/evidence/upgrade.log"

fingerprint > "$STAGE/evidence/protected-after.txt"
diff -u "$STAGE/evidence/protected-before.txt" "$STAGE/evidence/protected-after.txt"
runuser -u odoo -- /opt/odoo/venv/bin/python3 /opt/odoo/odoo19/odoo-bin shell \
    -c "$STAGE/test.conf" -d "$DB" --no-http --max-cron-threads=0 \
    --addons-path="$STAGE/candidate,$ADDONS" --data-dir="$STAGE/data" <<'PY'
module=env['ir.module.module'].search([('name','=','iot_control_center')],limit=1)
assert module.latest_version == '19.0.2.6.0', module.latest_version
assert 'device_id' in env['iot.instrument']._fields
assert env.ref('iot_control_center.action_iot_instrument_bind').res_model == 'iot.instrument.bind.wizard'
print('UPGRADE_ORM_OK', module.latest_version)
PY
systemctl is-active --quiet odoo
echo "UPGRADE_REHEARSAL_OK database=$DB stage=$STAGE"
