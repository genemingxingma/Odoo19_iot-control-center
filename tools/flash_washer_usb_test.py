"""First-install migration, deliberately leaving the ESP32 in download mode.

The matching screen must be installed before booting the new application.
Requires a verified full backup and an explicitly approved application hash.
"""
import argparse
import hashlib
import json
from pathlib import Path
import struct
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
BACKUP=Path('D:/Codex/device_backups/washer_20260919_171923/original-flash-4mb.bin')
BACKUP_SHA='8385a6cf347d9269adcce17bb6ca298e055b93f89f1a7b8798e38c77d01308ce'
EXPECTED_MAC='94e686bdfd34'

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--private-dir',type=Path,required=True)
    p.add_argument('--port',required=True)
    p.add_argument('--app-sha256',required=True)
    p.add_argument('--execute',action='store_true')
    p.add_argument('--confirm-actuator-power-off',action='store_true')
    a=p.parse_args()
    build=ROOT/'firmware/instruments/.pio/build/washer'
    backup=BACKUP.read_bytes()
    assert len(backup)==4194304 and hashlib.sha256(backup).hexdigest()==BACKUP_SHA
    app=(build/'firmware.bin').read_bytes()
    assert hashlib.sha256(app).hexdigest()==a.app_sha256.lower()
    assert b'IMYTESTFW1:washer:washer-esp32-4m-v1:30400:END' in app
    assert len(app)<=0x1b0000 and app[:4]==bytes.fromhex('e9050220')
    raw=(build/'partitions.bin').read_bytes(); partitions=[]
    for i in range(0,len(raw),32):
        if raw[i:i+2]!=b'\xaa\x50': break
        _,typ,sub,offset,size,name,flags=struct.unpack('<HBBII16sI',raw[i:i+32])
        partitions.append((name.rstrip(b'\0').decode(),typ,sub,offset,size,flags))
    assert partitions==[('nvs',1,2,0x9000,0x5000,0),('otadata',1,0,0xe000,0x2000,0),
        ('app0',0,16,0x10000,0x1b0000,0),('app1',0,17,0x1c0000,0x1b0000,0),
        ('littlefs',1,130,0x370000,0x90000,0)]
    hardware=json.loads((a.private_dir/'data/hardware.json').read_text())
    assert hardware['commissioned'] is False and hardware['open_rotor_commissioned'] is False
    framework=Path.home()/'.platformio/packages/framework-arduinoespressif32'
    pairs=[(0x1000,build/'bootloader.bin'),(0x8000,build/'partitions.bin'),
           (0xe000,framework/'tools/partitions/boot_app0.bin'),(0x10000,build/'firmware.bin'),
           (0x370000,a.private_dir/'littlefs-test.bin')]
    assert pairs[0][1].read_bytes()[:4]==bytes.fromhex('e9030220')
    assert len(pairs[0][1].read_bytes())<=0x7000 and len(pairs[2][1].read_bytes())==0x2000
    assert len(pairs[-1][1].read_bytes())==0x90000
    receipt=a.private_dir/'esp32-first-flash-receipt.json'
    result={'phase':'validated','application_sha256':a.app_sha256,'actuator_commissioning':False,
        'files':[{'offset':hex(offset),'bytes':path.stat().st_size,
                  'sha256':hashlib.sha256(path.read_bytes()).hexdigest()} for offset,path in pairs]}
    if not a.execute:
        print(json.dumps(result)); return
    if not a.confirm_actuator_power_off or receipt.exists(): raise RuntimeError('Missing isolation or existing receipt')
    esptool_dir=Path.home()/'.platformio/packages/tool-esptoolpy'
    sys.path.insert(0,str(esptool_dir))
    from esptool.targets.esp32 import ESP32ROM
    device=ESP32ROM(a.port,115200)
    try:
        device.connect(mode='default_reset',attempts=2)
        assert bytes(device.read_mac()).hex()==EXPECTED_MAC
        assert device.get_chip_description().startswith('ESP32-D0WD-V3')
    finally: device._port.close()
    def save(): receipt.write_text(json.dumps(result,indent=2),encoding='utf-8')
    save()
    command=[sys.executable,str(esptool_dir/'esptool.py'),'--chip','esp32','--port',a.port,
             '--baud','460800','--before','default_reset','--after','no_reset']
    arguments=[value for offset,path in pairs for value in (hex(offset),str(path))]
    try:
        result['phase']='writing'; save()
        subprocess.run(command+['write_flash','--flash_mode','keep','--flash_freq','keep','--flash_size','keep']+arguments,check=True)
        result['phase']='verifying'; save()
        subprocess.run(command+['verify_flash']+arguments,check=True)
        nvs=a.private_dir/'original-nvs.bin'; nvs.write_bytes(backup[0x9000:0xe000])
        subprocess.run(command+['verify_flash','0x9000',str(nvs)],check=True)
        result.update(phase='verified_held_in_rom',original_nvs_preserved=True)
    except Exception as exc:
        result['error_type']=type(exc).__name__
        raise
    finally: save()
    print('ESP32_FLASH_VERIFIED_HELD_IN_ROM')

if __name__=='__main__': main()
