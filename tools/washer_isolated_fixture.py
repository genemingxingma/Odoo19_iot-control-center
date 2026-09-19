"""Odoo shell fixture, restricted to the synthetic washer test database."""
import hashlib
import json
import os
from pathlib import Path

assert env.cr.dbname == 'iot_instruments_2031dd5c5ef9'
settings=json.loads(Path('/tmp/iot_instruments_2031dd5c5ef9/washer-fixture.json').read_text())
uid=settings['uid']
mode=os.environ.get('WASHER_FIXTURE_MODE','initial')
assert mode in ('initial','mutate','empty','check')
devices=env['iot.instrument'].sudo()
device=devices.search([('uid','=',uid)],limit=1)
if not device:
    assert mode=='initial'
    company=env['res.company'].sudo().create({'name':'Isolated USB Washer Test'})
    device=devices.create({'name':'USB washer output-locked test','uid':uid,'kind':'washer',
        'company_id':company.id,'token_hash':settings['token_hash']})
assert device.company_id.name=='Isolated USB Washer Test'
programs=env['iot.instrument.recipe'].sudo().with_context(active_test=False)
def create(index):
    identity=uid+'_p%02d'%index
    p=programs.search([('company_id','=',device.company_id.id),('uid','=',identity)],limit=1)
    if not p:
        p=programs.create({'name':'Synthetic USB test %02d'%index,'device_label':'USB TEST %02d - DO NOT RUN'%index,
            'uid':identity,'company_id':device.company_id.id,
            'step_ids':[(0,0,{'kind':'home','sequence':1,'duration_s':10}),
                        (0,0,{'kind':'home','sequence':2,'duration_s':10})]})
        p.action_release()
    return p
if mode=='initial':
    for index in range(1,9): create(index)
elif mode=='mutate':
    first=programs.search([('company_id','=',device.company_id.id),('uid','=',uid+'_p01'),('revision','=',1)])
    next_version=programs.browse(first.action_new_revision()['res_id'])
    next_version.write({'device_label':'USB TEST 01 UPDATED - DO NOT RUN'})
    next_version.action_release()
    programs.search([('company_id','=',device.company_id.id),('uid','=',uid+'_p02')]).write({'active':False})
    create(9)
elif mode=='empty':
    programs.search([('company_id','=',device.company_id.id)]).write({'active':False})
body,digest=device._program_catalog()
assert hashlib.sha256(body.encode()).hexdigest()==digest
env.cr.commit()
print('FIXTURE_RESULT '+json.dumps({'mode':mode,'count':json.loads(body)['count'],'sha256':digest}))
if mode=='check':
    pending=env['ir.module.module'].sudo().search([('state','in',['to install','to upgrade','to remove'])])
    print('PENDING_MODULES '+json.dumps([(m.name,m.state) for m in pending]))
