"""Verify and apply the search-autofocus refinement to the accepted release."""
import base64
import hashlib
import json
from pathlib import Path
import re
import shlex
import sys

sys.path.insert(0, "D:/Codex/laboratory_management/_deploy/native_pdf_fonts_310_20260901")
from run_release import connect, execute_sudo, read_config

ROOT = Path(__file__).resolve().parents[1]
REMOTE = r'''
import base64, fcntl, hashlib, json, os, pwd, shlex, shutil, subprocess
from pathlib import Path
assert subprocess.check_output(['hostname'],text=True).strip()=='imytestth'
os.umask(0o077)
stage=Path(STAGE)
accepted=json.loads((stage/'test-receipt.json').read_text())
published=json.loads((stage/'production-receipt.json').read_text())
assert accepted['status']=='passed' and published['version']=='19.0.2.6.1'
locks=[]
for name in ('imytestth-laboratory-release','imytestth-iot-release'):
    lock=open('/run/lock/'+name+'.lock','w')
    fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB);locks.append(lock)
def inventory(folder):
    return {p.relative_to(folder).as_posix():hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(folder.rglob('*')) if p.is_file() and '__pycache__' not in p.parts and p.suffix!='.pyc'}
def run(args,label):
    with (stage/(label+'.log')).open('wb') as output:
        result=subprocess.run(args,stdout=output,stderr=output,timeout=180)
    assert result.returncode==0, label+' failed; inspect the protected log'
live=Path('/opt/odoo/custom_addons/iot_control_center')
candidate=Path(accepted['candidate'])
assert inventory(live)==accepted['candidate_inventory']
assert inventory(candidate)==accepted['candidate_inventory']
name='static/src/js/relay_live_refresh.js'
raw=(stage/'relay-search-focus.js').read_bytes()
assert hashlib.sha256(raw).hexdigest()==EXPECTED
(candidate/name).write_bytes(raw)
shutil.chown(candidate/name,user='odoo',group='odoo')
testroot=Path(accepted['root'])
db=accepted['database'];assert db!='odoo-26-1-16' and db.startswith('iot_relay_latency_')
source="""import json
assert env.cr.dbname == DATABASE
bundle=env['ir.qweb']._get_asset_bundle('web.assets_backend',css=False,js=True)
assets=[a for a in bundle.javascripts if 'relay_live_refresh.js' in getattr(a,'url','')]
assert len(assets)==1
code=assets[0].minify()
assert 'odoo.define' in code and '.o_searchview' in code and 'console.error' not in code
bundle.js()
print('RELAY_SEARCH_FOCUS_NATIVE_OK')
env.cr.rollback()
"""
source='DATABASE='+repr(db)+'\n'+source
encoded=base64.b64encode(source.encode()).decode()
command=shlex.join(['/opt/odoo/venv/bin/python3','/opt/odoo/odoo19/odoo-bin','shell','-c',str(testroot/'test.conf'),'-d',db,
    '--addons-path='+str(candidate.parent)+',/opt/odoo/odoo19/odoo/addons','--data-dir='+str(testroot/'data'),
    '--no-http','--max-cron-threads=0','--logfile=/dev/null'])
pipeline='printf %s '+shlex.quote(encoded)+' | base64 -d | '+command
run(['systemd-run','--quiet','--wait','--pipe','--collect','-p','User=odoo','-p','IPAddressDeny=any',
    '-p','IPAddressAllow=localhost','-p','IPAddressAllow=192.168.10.20','bash','-c',pipeline],'search-focus-native-assets')
assert 'RELAY_SEARCH_FOCUS_NATIVE_OK' in (stage/'search-focus-native-assets.log').read_text()
expected=dict(accepted['candidate_inventory']);expected[name]=EXPECTED
assert inventory(candidate)==expected
assert inventory(live)==accepted['candidate_inventory']
backup=Path(published['backup'])/'relay-live-refresh-before-search-fix.js'
assert not backup.exists()
shutil.copy2(live/name,backup);backup.chmod(0o600)
assert hashlib.sha256(backup.read_bytes()).hexdigest()==accepted['candidate_inventory'][name]
try:
    shutil.copy2(candidate/name,live/name)
    shutil.chown(live/name,user='root',group='odoo');(live/name).chmod(0o640)
    assert inventory(live)==expected
    run(['systemctl','restart','odoo'],'restart-after-search-focus')
    run(['curl','--retry','15','--retry-delay','2','--retry-connrefused','--max-time','5','-fsS','-o','/dev/null',
        'http://192.168.10.15:8069/web/login'],'search-focus-production-health')
except Exception:
    shutil.copy2(backup,live/name);shutil.chown(live/name,user='root',group='odoo');(live/name).chmod(0o640)
    subprocess.run(['systemctl','restart','odoo'])
    raise
receipt={'version':'19.0.2.6.1','status':'published','js_sha256':EXPECTED,'candidate_inventory':expected}
(stage/'frontend-receipt.json').write_text(json.dumps(receipt))
print('RELAY_SEARCH_FOCUS_PUBLISHED '+json.dumps({k:v for k,v in receipt.items() if k!='candidate_inventory'}))
'''


def main():
    stage = sys.argv[1]
    if not re.fullmatch(r"/home/mamingxing/iot-relay-latency-[0-9a-f]{12}", stage):
        raise ValueError("Use the accepted release stage")
    raw = (ROOT / "static/src/js/relay_live_refresh.js").read_bytes()
    source = "STAGE=" + repr(stage) + "\nEXPECTED=" + repr(hashlib.sha256(raw).hexdigest()) + "\n" + REMOTE
    cfg = read_config()
    client = connect("192.168.10.15", cfg)
    try:
        with client.open_sftp() as sftp:
            for name, content in (("relay-search-focus.js", raw), ("search-focus-server.py", source.encode())):
                with sftp.open(stage + "/" + name, "wb") as handle:
                    handle.write(content)
                sftp.chmod(stage + "/" + name, 0o600)
        code, output = execute_sudo(client, "python3 " + shlex.quote(stage + "/search-focus-server.py"), cfg["REMOTE_PASSWORD"], 240)
        print(output)
        raise SystemExit(code)
    finally:
        client.close()


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
