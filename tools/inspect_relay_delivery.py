"""Read-only, redacted production relay delivery inspection; never sends commands."""
import base64
import json
from pathlib import Path
import re
import shlex
import sys

sys.path.insert(0, "D:/Codex/laboratory_management/_deploy/native_pdf_fonts_310_20260901")
from run_release import connect, execute_sudo, read_config

REMOTE = r'''
import json
from datetime import datetime
from urllib.parse import urlsplit
assert env.cr.dbname == 'odoo-26-1-16'
env.cr.rollback()
env.cr.execute('SET TRANSACTION READ ONLY')
env.cr.execute("SET LOCAL statement_timeout = '12s'")
env.cr.execute("SELECT now() AT TIME ZONE 'UTC'")
result={'server_utc':str(env.cr.fetchone()[0])}
fields=['id','name','serial','module_id','active','company_id','location_detail',
 'relay_state','desired_relay_state','relay_command_state','last_command_at',
 'last_command_confirmed_at','last_seen','control_inhibited','safety_tripped',
 'device_time_synced','runtime_reported_at','firmware_version','mqtt_route',
 'mqtt_active_host','delay_active','max_continuous_on_minutes','safety_critical']
env.cr.execute("SELECT column_name FROM information_schema.columns WHERE table_name='iot_device'")
columns={r[0] for r in env.cr.fetchall()}
fields=[f for f in fields if f in columns]
env.cr.execute('SELECT '+','.join(fields)+" FROM iot_device WHERE lower(serial)=%s OR lower(module_id)=%s",[SERIAL,SERIAL])
devices=[dict(zip(fields,row)) for row in env.cr.fetchall()]
result['devices']=devices
ids=[d['id'] for d in devices]
if ids:
 env.cr.execute("SELECT id,command,state,attempts,create_date,sent_at,expires_at,payload FROM iot_command WHERE device_id=ANY(%s) ORDER BY id DESC LIMIT 30",[ids])
 commands=[]
 for row in env.cr.fetchall():
  item=dict(zip(['id','command','state','attempts','created_at','sent_at','expires_at'],row[:7]))
  payload=row[7] or {}
  item['intent']={k:payload[k] for k in ('state','max_on_sec','duration_sec','command_seq') if k in payload}
  if row[4] and row[5]: item['send_delay_s']=(row[5]-row[4]).total_seconds()
  commands.append(item)
 result['commands']=commands
 env.cr.execute("SELECT state,received_at,processed_at,retained,payload,create_date FROM iot_mqtt_message WHERE device_id=ANY(%s) ORDER BY id DESC LIMIT 60",[ids])
 messages=[]
 for state,received,processed,retained,payload,created in env.cr.fetchall():
  item={'state':state,'received_at':received,'enqueued_at':created,'processed_at':processed,'retained':retained}
  item['ingress_delay_s']=(created-received).total_seconds()
  if processed: item['queue_delay_s']=(processed-created).total_seconds()
  if processed: item['processing_delay_s']=(processed-received).total_seconds()
  try:
   raw=json.loads(payload)
   item['report']={k:raw[k] for k in ('state','command_seq','control_inhibit','safety_trip','uptime_sec','mqtt_route','time_synced','firmware_version','max_on_sec','delay_active') if k in raw}
  except (ValueError,TypeError): item['invalid_json']=True
  messages.append(item)
 result['reports']=messages[:6]
 if commands:
  latest=commands[0]
  acks=[m for m in messages if not m['retained'] and m.get('report',{}).get('command_seq')==latest['id'] and m.get('report',{}).get('state')==latest['intent'].get('state')]
  if acks: result['first_latest_command_report']=min(acks,key=lambda m:m['received_at'])
env.cr.execute("SELECT state,count(*) FROM iot_command WHERE create_date>now()-interval '15 minutes' GROUP BY state")
result['recent_fleet_command_counts']=dict(env.cr.fetchall())
env.cr.execute("SELECT state,count(*),min(received_at) FROM iot_mqtt_message WHERE state IN ('new','error') GROUP BY state")
result['inbound_queue']=[{'state':r[0],'count':r[1],'oldest':r[2]} for r in env.cr.fetchall()]
cron=env['ir.cron'].sudo().search([('code','=','model._cron_dispatch()')])
cron_fields=[f for f in ('active','interval_number','interval_type','nextcall','lastcall') if f in cron._fields]
result['dispatch_cron']=cron.read(cron_fields)
process_cron=env['ir.cron'].sudo().search([('code','=','model._cron_process_new_messages()')])
result['receipt_processing_cron']=process_cron.read(cron_fields)
import hashlib
from pathlib import Path
from odoo.addons.iot_control_center.controllers import internal_ingest
addon=Path(internal_ingest.__file__).resolve().parent.parent
result['runtime_source_hashes']={name:hashlib.sha256((addon/name).read_bytes()).hexdigest() for name in ('controllers/internal_ingest.py','models/iot_mqtt_message.py','models/iot_device.py')}
env.cr.execute("SELECT value FROM ir_config_parameter WHERE key='iot_control_center.middleware_base_url'")
row=env.cr.fetchone()
if row:
 u=urlsplit(row[0]); result['middleware_origin']={'scheme':u.scheme,'host':u.hostname,'port':u.port}
env.cr.rollback()
print('RELAY_DELIVERY_INSPECT '+json.dumps(result,default=str,ensure_ascii=False))
'''


def main():
    serial = sys.argv[1] if len(sys.argv) > 1 else "06458F"
    if not re.fullmatch(r"[0-9a-fA-F]{6}", serial):
        raise ValueError("Use a six-character relay identifier")
    config = read_config()
    client = connect("192.168.10.15", config)
    try:
        _, out, _ = client.exec_command("hostname")
        if out.read().decode().strip() != "imytestth":
            raise RuntimeError("Unexpected production host")
        source = "SERIAL=" + repr(serial.lower()) + "\n" + REMOTE
        encoded = base64.b64encode(source.encode()).decode()
        command = shlex.join([
            "/opt/odoo/venv/bin/python3", "/opt/odoo/odoo19/odoo-bin", "shell",
            "-c", "/opt/odoo/config/odoo.conf", "-d", "odoo-26-1-16", "--no-http",
            "--max-cron-threads=0", "--logfile=/dev/null",
        ])
        pipeline = "printf %s " + shlex.quote(encoded) + " | base64 -d | " + command
        code, output = execute_sudo(client, shlex.join([
            "systemd-run", "--quiet", "--wait", "--pipe", "--collect", "-p", "User=odoo",
            "-p", "IPAddressDeny=any", "-p", "IPAddressAllow=192.168.10.20",
            "-p", "MemoryMax=512M", "-p", "NoNewPrivileges=yes", "bash", "-c", pipeline,
        ]), config["REMOTE_PASSWORD"], 90)
        line = next((s for s in output.splitlines() if s.startswith("RELAY_DELIVERY_INSPECT ")), None)
        if code or not line:
            # Do not echo arbitrary startup logs or configuration errors.
            safe_errors=re.findall(r'^(?:psycopg2\.errors\.\w+|\w*Error): (?:column|relation) [^\n]+',output,re.M)
            if safe_errors:
                print('READ_ONLY_QUERY_ERROR '+safe_errors[-1][:250])
            raise RuntimeError("Read-only production inspection failed; no commands were sent")
        result=json.loads(line.split(" ", 1)[1])
        import hashlib
        root=Path(__file__).resolve().parents[1]
        result['runtime_files_match_local']={name:hashlib.sha256((root/name).read_bytes()).hexdigest()==value for name,value in result.pop('runtime_source_hashes',{}).items()}
        print(json.dumps(result, ensure_ascii=False, indent=2))
    finally:
        client.close()


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
