"""Real UI test on imytestth's isolated upgrade DB; never use the live database."""
import argparse
import json
from pathlib import Path
import re
import secrets
import select
import shlex
import socketserver
import sys
import threading
import time
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, r'D:/Codex/laboratory_management/_deploy/native_pdf_fonts_310_20260901')
from run_release import connect, execute_sudo, read_config


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('receipt', type=Path)
    args = parser.parse_args()
    receipt = json.loads(args.receipt.read_text())
    assert receipt['status'] in ('native_passed', 'passed') and receipt['host'] == 'imytestth'
    args.database = receipt['database']
    assert re.fullmatch(r'iot_instruments_upgrade_[0-9]{14}', args.database)
    stage = receipt['root']
    assert re.fullmatch(r'/opt/odoo/module_backups/iot_instruments_test_[0-9]{8}_[0-9]{6}', stage)
    config = read_config()
    client = connect('192.168.10.15',config)
    password = secrets.token_hex(32)
    unit = args.database+'-ui'
    output_dir = ROOT/'deploy/artifacts/combined-ui-imytestth-20260920-r250'
    output_dir.mkdir(parents=True,exist_ok=True)
    try:
        _,out,_ = client.exec_command('hostname')
        assert out.read().decode().strip() == 'imytestth'
        common = ['/opt/odoo/venv/bin/python3','/opt/odoo/odoo19/odoo-bin',
                  '-c',stage+'/test.conf','-d',args.database,
                  '--addons-path='+stage+'/candidate,/opt/odoo/odoo19/odoo/addons',
                  '--data-dir='+stage+'/data','--max-cron-threads=0','--workers=0']
        # Native shell creates only synthetic users/data in this disposable DB.
        command = shlex.join(['sudo','-S','-p','','-u','odoo',common[0],common[1],'shell',*common[2:],
                             '--no-http','--logfile='+stage+'/evidence/ui-fixture.log'])
        inp,out,err = client.exec_command(command,timeout=240)
        inp.write(config['REMOTE_PASSWORD']+'\n'); inp.flush()
        inp.write('ui_password='+repr(password)+'\n'+(ROOT/'tools/combined_ui_fixture.py').read_text(encoding='utf-8'))
        inp.flush(); inp.channel.shutdown_write()
        result = out.read().decode(); errors = err.read().decode()
        assert out.channel.recv_exit_status()==0, 'Synthetic fixture failed: '+errors.replace(password,'[redacted]').replace(config['REMOTE_PASSWORD'],'[redacted]')[-500:]
        fixture = json.loads(next(line.split(' ',1)[1] for line in result.splitlines() if line.startswith('COMBINED_UI_FIXTURE ')))
        host = '192.168.10.20'
        start = shlex.join(['systemd-run','--quiet','--collect','--unit='+unit,'-p','User=odoo',
                           '-p','IPAddressDeny=any','-p','IPAddressAllow=localhost','-p','IPAddressAllow='+host,
                           '-p','MemoryMax=3G','-p','NoNewPrivileges=yes',*common,
                           '--http-interface=127.0.0.1','--http-port=18929','--gevent-port=18930',
                           '--logfile='+stage+'/evidence/ui.log'])
        rc,_ = execute_sudo(client,start,config['REMOTE_PASSWORD'],30)
        assert rc==0
        transport=client.get_transport()
        class Handler(socketserver.BaseRequestHandler):
            def handle(self):
                channel=transport.open_channel('direct-tcpip',('127.0.0.1',18929),self.request.getpeername())
                try:
                    while True:
                        readable,_,_=select.select([self.request,channel],[],[],30)
                        for origin in readable:
                            data=origin.recv(65536)
                            if not data: return
                            (channel if origin is self.request else self.request).sendall(data)
                finally: channel.close()
        class Server(socketserver.ThreadingTCPServer):
            daemon_threads=True
            allow_reuse_address=True
            def __exit__(self, *args):
                self.shutdown()
                return super().__exit__(*args)
        with Server(('127.0.0.1',0),Handler) as server:
            threading.Thread(target=server.serve_forever,daemon=True).start()
            base='http://127.0.0.1:'+str(server.server_address[1])
            with sync_playwright() as p:
                browser=p.chromium.launch(channel='msedge',headless=True)
                results=[]
                for lang in ('en_US','zh_CN','th_TH'):
                    context=browser.new_context(viewport={'width':1440,'height':900})
                    for attempt in range(30):
                        try:
                            response=context.request.post(base+'/web/session/authenticate',data={'jsonrpc':'2.0','method':'call','id':1,
                                'params':{'db':args.database,'login':'combined-ui-'+lang,'password':password}},timeout=10000)
                            session = response.json().get('result', {})
                            assert session.get('uid')
                            print('UI_SESSION_LANGUAGE',lang,session.get('user_context',{}).get('lang'),flush=True)
                            assert session.get('user_context',{}).get('lang') == lang
                            break
                        except Exception:
                            if attempt==29: raise RuntimeError('Preview login unavailable') from None
                            time.sleep(1)
                    reset=context.request.post(base+'/web/dataset/call_kw/iot.instrument/write',data={
                        'jsonrpc':'2.0','method':'call','id':2,'params':{'model':'iot.instrument','method':'write',
                        'args':[[fixture['washer']],{'program_scope':'all','assigned_program_ids':[[5,0,0]]}], 'kwargs':{}}})
                    assert reset.json().get('result') is True, 'Synthetic selection reset failed'
                    page=context.new_page(); errors=[]
                    page.on('pageerror',lambda error:errors.append(str(error)))
                    page.goto(base+'/odoo/action-'+str(fixture['actions']['action_iot_operations_overview']),wait_until='domcontentloaded')
                    page.locator('.iot_module_card').first.wait_for(timeout=90000)
                    assert page.locator('.iot_module_card').count()==6
                    descriptions = {'en_US':'Temperature settings and hourly history',
                                    'zh_CN':'目标温度设置与每小时温度趋势',
                                    'th_TH':'การตั้งค่าอุณหภูมิและประวัติรายชั่วโมง'}
                    page.get_by_text(descriptions[lang],exact=True).wait_for()
                    for width,height in ((1920,1080),(1440,900),(1366,768),(390,844)):
                        page.set_viewport_size({'width':width,'height':height})
                        page.reload(wait_until='domcontentloaded')
                        page.locator('.iot_module_card').first.wait_for(timeout=60000)
                        page.locator('.iot_module_card').evaluate_all('nodes => Promise.all(nodes.flatMap(node => node.getAnimations()).map(animation => animation.finished.catch(() => {})))')
                        scroll=page.locator('.iot_workspace_inner')
                        scroll.evaluate('e=>e.scrollTop=0')
                        if width < 1200:
                            scroll.hover(); page.mouse.wheel(0,10000)
                            page.wait_for_function('document.querySelector(".iot_workspace_inner").scrollTop>0')
                        metrics=scroll.evaluate('e=>({client:e.clientHeight,total:e.scrollHeight,scroll:e.scrollTop})')
                        page.screenshot(path=str(output_dir/(lang+'-'+str(width)+'-overview.png')))
                        if width >= 1200:
                            assert metrics['total'] <= metrics['client'] + 1, (lang,width,metrics)
                        else:
                            assert metrics['total']>metrics['client'] and metrics['scroll']>0
                        overflowing=page.evaluate('''()=>Array.from(document.querySelectorAll('body *')).filter(e=>e.getBoundingClientRect().right>innerWidth+1 && e.getBoundingClientRect().width>0).slice(0,15).map(e=>({cls:e.className,w:e.getBoundingClientRect().width,right:e.getBoundingClientRect().right}))''')
                        print('UI_METRICS',lang,width,json.dumps(metrics),json.dumps(overflowing),flush=True)
                        assert page.evaluate('document.documentElement.scrollWidth<=window.innerWidth'), (lang,width,overflowing)
                        results.append({'lang':lang,'width':width,'scroll':metrics})
                    page.set_viewport_size({'width':1440,'height':900})
                    page.goto(base+'/odoo/action-'+str(fixture['actions']['action_iot_operations_overview']))
                    page.locator('.iot_quick_actions button').nth(1).click()
                    page.get_by_text('Synthetic Array Washer',exact=True).wait_for()
                    page.locator('.o_kanban_record').filter(has_text='Synthetic Array Washer').locator('[name="action_open_program_selection"]').click()
                    page.locator('[name="program_scope"]').wait_for()
                    assert page.locator('[name="program_sync_state"]').count()>0
                    pump_labels={'en_US':'Device Fill A (s)','zh_CN':'设备 A 泵注液时间（秒）','th_TH':'เวลาเติม A ของเครื่อง (วินาที)'}
                    page.get_by_text(pump_labels[lang],exact=True).wait_for()
                    assert page.locator('[name="pump_settings_revision"]').count()>0
                    assert page.locator('[name="action_apply_programs"]').is_visible()
                    page.locator('[name="program_scope"] input').nth(1).check()
                    selector=page.locator('[name="assigned_program_ids"] input')
                    selector.fill('Synthetic General')
                    page.get_by_role('option').filter(has_text='Synthetic General Microarray').first.click()
                    page.locator('[name="action_apply_programs"]').click()
                    page.locator('.o_notification').first.wait_for()
                    page.reload(wait_until='domcontentloaded')
                    page.locator('[name="program_scope"]').wait_for()
                    assert page.locator('[name="program_scope"] input').nth(1).is_checked()
                    assert page.locator('[name="effective_program_ids"] .o_data_row').count()==1
                    page.set_viewport_size({'width':1440,'height':1100})
                    page.screenshot(path=str(output_dir/(lang+'-washer-selection.png')),full_page=True)
                    page.locator('[name="pump_settings_revision"]').scroll_into_view_if_needed()
                    page.screenshot(path=str(output_dir/(lang+'-washer-pumps.png')),full_page=True)
                    page.set_viewport_size({'width':1440,'height':900})
                    page.goto(base+'/odoo/action-'+str(fixture['actions']['action_buffer_heaters']))
                    page.get_by_text('Synthetic Buffer Heater',exact=True).wait_for()
                    page.get_by_text('Synthetic Buffer Heater',exact=True).click()
                    page.locator('.o_form_view').wait_for()
                    assert page.locator('[name="target_a"]').count()>0
                    assert page.locator('[name="target_b"]').count()==0
                    labels={'en_US':'Requested Temperature','zh_CN':'待下发目标温度','th_TH':'อุณหภูมิเป้าหมายที่ต้องการส่ง'}
                    page.screenshot(path=str(output_dir/(lang+'-heater.png')))
                    print('HEATER_FORM_LABELS',lang,page.locator('.o_form_label').all_text_contents(),flush=True)
                    page.get_by_text(labels[lang],exact=True).first.wait_for()
                    page.screenshot(path=str(output_dir/(lang+'-heater.png')))
                    page.goto(base+'/odoo/action-'+str(fixture['actions']['action_washer_programs']))
                    page.get_by_text('Synthetic General Microarray V1.0',exact=True).wait_for()
                    page.get_by_text('Synthetic General Microarray V1.0',exact=True).click()
                    page.locator('.o_form_view').wait_for()
                    guidance={
                        'en_US':'Publishing automatically adds a homing step at the beginning. Drain before changing buffer or spin drying. Operator waits require local Continue. One wash cycle is forward plus reverse; cycle count times twice the reverse interval determines wash duration.',
                        'zh_CN':'发布程序时会自动在开头加入转子归零。更换洗液或甩干前必须排液；人工等待须在设备上按“继续”。正转、反转各一次为一个洗脱循环，洗脱时长为循环次数乘以两倍换向间隔。',
                        'th_TH':'เมื่อเผยแพร่ ระบบจะเพิ่มขั้นตอนกลับตำแหน่งโรเตอร์ที่ต้นโปรแกรมโดยอัตโนมัติ ต้องระบายน้ำยาก่อนเปลี่ยนน้ำยาหรือปั่นแห้ง และการรอผู้ปฏิบัติงานต้องกดดำเนินการต่อที่เครื่อง หนึ่งรอบล้างคือหมุนไปข้างหน้าและย้อนกลับอย่างละหนึ่งครั้ง ระยะเวลาล้างเท่ากับจำนวนรอบคูณสองเท่าของช่วงเวลาสลับทิศทาง'}
                    motor_guidance={
                        'en_US':'Original motor baseline: inlet and filling overflow at full output; both pumps during drainage 150/255, during spin drying 50/255. New wash steps default to 1 rev/s and spin-dry steps to 10 rev/s. Spindle speed is pulse controlled, not a voltage percentage.',
                        'zh_CN':'沿用原程序电机参数：注液时进液泵和溢水泵全输出；两泵排液时均为 150/255，甩干时均为 50/255。新增洗脱、甩干步骤默认分别为 1、10 转/秒。主轴通过脉冲调速，不按电压百分比控制。',
                        'th_TH':'ใช้ค่ามอเตอร์ตามโปรแกรมเดิม: ระหว่างเติมน้ำยา ปั๊มเติมและปั๊มน้ำล้นทำงานเต็มกำลัง ระหว่างระบายทั้งสองปั๊มใช้ 150/255 และขณะปั่นแห้งใช้ 50/255 ขั้นตอนล้างและปั่นแห้งที่สร้างใหม่ใช้ค่าเริ่มต้น 1 และ 10 รอบ/วินาทีตามลำดับ แกนหมุนควบคุมความเร็วด้วยพัลส์ ไม่ใช่เปอร์เซ็นต์แรงดันไฟฟ้า'}
                    paragraphs = page.locator('.o_form_view p').all_text_contents()
                    print('PROGRAM_GUIDANCE', lang, json.dumps(paragraphs, ensure_ascii=True), flush=True)
                    normalize = lambda value: re.sub(r'[\s\"“”‘’]+', '', value)
                    assert normalize(guidance[lang]) in {normalize(value) for value in paragraphs}, (lang, paragraphs)
                    assert normalize(motor_guidance[lang]) in {normalize(value) for value in paragraphs}, (lang, paragraphs)
                    rows=page.locator('[name="step_ids"] .o_data_row')
                    rows.first.wait_for(); assert rows.count()==8
                    for index in (0,4):
                        cell = rows.nth(index).locator('[name="duration_s"]')
                        print('FILL_TIME_CELL',lang,index,cell.inner_html(),flush=True)
                        # Odoo keeps the table cell to align columns; its editor/value must be absent.
                        assert not cell.inner_text().strip() and cell.locator('input').count()==0
                    assert rows.nth(3).locator('[name="duration_s"]').inner_text().strip()
                    page.screenshot(path=str(output_dir/(lang+'-washer-program.png')),full_page=True)
                    assert not errors,errors
                    context.close()
                browser.close()
                ui_receipt = {'status':'passed','host':'imytestth','database':args.database,
                              'sha256':receipt['sha256'],'scenarios':results,'heater_forms':3,'program_forms':3,'washer_selection_forms':3}
                (output_dir/'results.json').write_text(json.dumps(ui_receipt,indent=2),encoding='utf-8')
                (ROOT/'deploy/artifacts/pump250-ui-receipt.json').write_text(json.dumps(ui_receipt),encoding='utf-8')
            server.shutdown()
        print('COMBINED_UI_OK',len(results),'responsive scenarios; 3 heater, 3 program and 3 program-selection forms',flush=True)
    finally:
        execute_sudo(client,'systemctl stop '+shlex.quote(unit),config['REMOTE_PASSWORD'],30)
        client.close()


if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    main()
