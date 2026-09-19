"""Start/modify/stop only the prevalidated synthetic washer USB-test fixture."""
import argparse
from pathlib import Path
import shlex
import sys
sys.path.insert(0,r'D:/Codex/laboratory_management/_deploy/native_pdf_fonts_310_20260901')
from run_release import connect, execute_sudo, read_config

STAGE='/tmp/iot_instruments_2031dd5c5ef9'
DB='iot_instruments_2031dd5c5ef9'
UNIT='iot-washer-usb-test-20260919'
ROOT=Path(__file__).resolve().parents[1]

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('mode',choices=('initial','start','mutate','empty','check','stop'))
    p.add_argument('--private-dir',type=Path,required=True)
    a=p.parse_args(); config=read_config(); client=connect('192.168.10.15',config)
    try:
        _,out,_=client.exec_command('hostname')
        if out.read().decode().strip()!='imytestth': raise RuntimeError('Wrong host')
        if a.mode=='stop':
            command=f'systemctl stop {UNIT}'
        else:
            with client.open_sftp() as sftp:
                sftp.put(str(a.private_dir/'fixture.json'),STAGE+'-washer-fixture.json')
                sftp.put(str(ROOT/'tools/washer_isolated_fixture.py'),STAGE+'-washer-fixture.py')
            common=f'-c {STAGE}/test.conf -d {DB} --addons-path={STAGE}/addons,/opt/odoo/odoo19/odoo/addons --data-dir={STAGE}/data --max-cron-threads=0'
            command=f'''set -e
test "$(hostname)" = imytestth
install -o odoo -g odoo -m 600 {STAGE}-washer-fixture.json {STAGE}/washer-fixture.json
install -o odoo -g odoo -m 644 {STAGE}-washer-fixture.py {STAGE}/washer-fixture.py
runuser -u odoo -- env WASHER_FIXTURE_MODE={a.mode} /opt/odoo/venv/bin/python3 /opt/odoo/odoo19/odoo-bin shell {common} --no-http --logfile={STAGE}/fixture.log < {STAGE}/washer-fixture.py
'''
            if a.mode=='start':
                command='set -e\ntest "$(hostname)" = imytestth\n'
            if a.mode in ('initial','start'):
                command+=f'''test -z "$(ss -H -ltn 'sport = :18769')"
systemd-run --quiet --collect --unit={UNIT} -p User=odoo -p IPAddressDeny=any -p IPAddressAllow=localhost -p IPAddressAllow=192.168.10.20 -p MemoryMax=3G -p NoNewPrivileges=yes -p RuntimeMaxSec=3600 /opt/odoo/venv/bin/python3 /opt/odoo/odoo19/odoo-bin {common} --db-filter=^{DB}$ --http-interface=127.0.0.1 --http-port=18769 --gevent-port=18772 --workers=0 --logfile={STAGE}/usb-http.log
'''
            command='bash -lc '+shlex.quote(command)
        rc,output=execute_sudo(client,command,config['REMOTE_PASSWORD'],120)
        print(output)
        if rc: raise RuntimeError('Isolated fixture operation failed')
    finally: client.close()

if __name__=='__main__': main()
