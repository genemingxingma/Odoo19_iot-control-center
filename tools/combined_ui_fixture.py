"""Synthetic fixture; ui_password is provided over SSH stdin, never persisted."""
import json
import time
from odoo import Command, fields
from odoo.tests.common import new_test_user

assert env.cr.dbname.startswith('iot_instruments_')
env['ir.cron'].search([]).write({'active': False})
env['ir.mail_server'].search([]).write({'active': False})
env['ir.config_parameter'].sudo().set_param('iot_control_center.middleware_base_url', '')
env.company.write({'name': 'Synthetic Instrument Lab', 'country_id': env.ref('base.th').id})
langs = env['res.lang'].with_context(active_test=False).search([('code','in',['en_US','zh_CN','th_TH'])])
if len(langs.filtered('active')) != 3:
    env['base.language.install'].create({'lang_ids':[Command.set(langs.ids)],'overwrite':True}).lang_install()
for lang in ('en_US','zh_CN','th_TH'):
    user = env['res.users'].search([('login','=','combined-ui-'+lang)])
    if user:
        user.write({'password': ui_password, 'lang': lang})
    else:
        new_test_user(env, login='combined-ui-'+lang, password=ui_password, lang=lang, tz='Asia/Bangkok',
                      groups='base.group_user,iot_control_center.group_iot_manager')
heater = env['iot.instrument'].sudo().search([('name','=','Synthetic Buffer Heater')],limit=1)
if not heater:
    heater = env['iot.instrument'].sudo().create({'name':'Synthetic Buffer Heater','kind':'heater','location_detail':'Bench A'})
stamp = int(time.time())
heater._exchange({'protocol':1,'event_id':'ui-heater-'+str(stamp),'boot_id':'ui-boot','seq':stamp,'uptime_ms':100,
    'sampled_at':int(time.time()),'observation':True,'status':{'state':'idle','firmware':'3.1.0-dev',
    'hardware':'heater-esp12s-ds18b20-v1','control_interface':'heater-control-v1',
    'local_enable':True,'remote_start':False,'chip_id':'ABCDEF','ip':'192.0.2.10','enabled':False,
    'settings_ready':True,'rise_window_s':600,'minimum_rise_c':1,
    'a':{'valid':True,'temperature':36.5,'target':37,'fault':'none','output':False}}})
if not env['iot.instrument'].sudo().search_count([('name','=','Synthetic Array Washer')]):
    env['iot.instrument'].sudo().create({'name':'Synthetic Array Washer','kind':'washer','location_detail':'Bench B'})
program = env['iot.instrument.recipe'].sudo().search([('name','=','Synthetic General Microarray V1.0')],limit=1)
if not program:
    kinds = ['fill_a','wait','wash','drain','fill_b','wash','drain','dry']
    program = env['iot.instrument.recipe'].sudo().create({'name':'Synthetic General Microarray V1.0',
        'device_label':'GENERAL MICROARRAY V1.0','step_ids':[Command.create({'kind':kind,'sequence':index*10,
        'duration_s':10,'rps':1 if kind=='wash' else 10 if kind=='dry' else 0,
        'cycles':3 if kind=='wash' else 0,'reverse_s':3}) for index,kind in enumerate(kinds,1)]})
if not env['iot.device'].sudo().search_count([('serial','=','UI-LOCKED')]):
    env['iot.device'].sudo().create({'name':'Synthetic Locked Relay','serial':'UI-LOCKED','location_detail':'Schedule test',
        'last_seen':fields.Datetime.now(),'runtime_reported_at':fields.Datetime.now(),'control_inhibited':True,
        'device_time_synced':True,'reported_schedule_count':14,'relay_state':'off'})
if program.state == 'draft':
    program.action_release()
washer = env['iot.instrument'].sudo().search([('name','=','Synthetic Array Washer')],limit=1)
washer.write({'program_scope':'all','assigned_program_ids':[Command.clear()]})
actions = {name:env.ref('iot_control_center.'+name).id for name in
           ('action_iot_operations_overview','action_buffer_heaters','action_array_washers','action_washer_programs','action_iot_device')}
env.cr.commit()
print('COMBINED_UI_FIXTURE',json.dumps({'actions':actions,'heater':heater.id,'washer':washer.id,'program':program.id}))
