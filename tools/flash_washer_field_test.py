"""Upgrade a backed-up washer without changing its partition table or NVS.

The field-test configuration requires local screen confirmation before motion.
This utility neither starts actuators nor claims that hardware is commissioned.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--private-dir', type=Path, required=True)
    parser.add_argument('--port', required=True)
    parser.add_argument('--expected-mac', required=True)
    parser.add_argument('--app-sha256', required=True)
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--confirm-actuator-power-off', action='store_true')
    args = parser.parse_args()
    private = args.private_dir.resolve()
    if not private.is_relative_to(Path('D:/Codex/device_backups').resolve()):
        raise RuntimeError('Use the protected device-backup directory')
    receipt = json.loads((private/'backup-receipt.json').read_text(encoding='utf-8-sig'))
    backup = Path(receipt['backup_file'])
    if not receipt['verify_flash_passed'] or digest(backup) != receipt['sha256']:
        raise RuntimeError('Backup is not verified')
    raw = backup.read_bytes()
    build = ROOT/'firmware/instruments/.pio/build/washer'
    app = build/'firmware.bin'
    partition = (build/'partitions.bin').read_bytes()
    boot_app = Path.home()/'.platformio/packages/framework-arduinoespressif32/tools/partitions/boot_app0.bin'
    if len(raw) != 0x400000 or raw[0x8000:0x8000+len(partition)] != partition:
        raise RuntimeError('Partition layout mismatch; no migration is authorized')
    if raw[0xe000:0x10000] != boot_app.read_bytes():
        raise RuntimeError('OTA state changed; determine the active slot before writing')
    if digest(app) != args.app_sha256.lower() or app.stat().st_size > 0x1b0000:
        raise RuntimeError('Wrong application hash or size')
    image = app.read_bytes()
    marker = re.search(rb'IMYTESTFW1:washer:washer-esp32-4m-v1:(\d+):END', image)
    previous = re.search(rb'IMYTESTFW1:washer:washer-esp32-4m-v1:(\d+):END', raw[0x10000:0x1c0000])
    if not marker or not previous or int(marker[1]) <= int(previous[1]):
        raise RuntimeError('Expected a forward update of the same hardware target')
    filesystem = private/'field-test-littlefs.bin'
    prepared = json.loads((private/'field-test-provisioning-receipt.json').read_text())
    if digest(filesystem) != prepared['filesystem_sha256'] or filesystem.stat().st_size != 0x90000:
        raise RuntimeError('Provisioning image mismatch')
    hardware = json.loads((private/'field-test-data/hardware.json').read_text())
    if hardware.get('commissioned') is not False or hardware.get('field_test') is not True:
        raise RuntimeError('Field test must not silently certify the hardware')
    result = dict(phase='validated', application_sha256=digest(app),
                  filesystem_sha256=digest(filesystem), backup_sha256=receipt['sha256'],
                  firmware_number=int(marker[1]), commissioned=False, automatic_startup=False)
    if not args.execute:
        print(json.dumps(result))
        return
    output = private/'field-test-flash-receipt.json'
    if not args.confirm_actuator_power_off or output.exists():
        raise RuntimeError('Actuator isolation or unused receipt path required')
    tool = Path.home()/'.platformio/packages/tool-esptoolpy'
    sys.path.insert(0, str(tool))
    from esptool.targets.esp32 import ESP32ROM
    chip = ESP32ROM(args.port, 115200)
    try:
        chip.connect(mode='no_reset', attempts=2)
        if bytes(chip.read_mac()).hex() != args.expected_mac.replace(':', '').lower():
            raise RuntimeError('Unexpected device identity')
        if not chip.get_chip_description().startswith('ESP32-D0WD-V3'):
            raise RuntimeError('Unexpected controller')
    finally:
        chip._port.close()
    command = [sys.executable, str(tool/'esptool.py'), '--chip', 'esp32', '--port', args.port,
               '--baud', '460800', '--before', 'no_reset', '--after', 'no_reset']
    def save():
        output.write_text(json.dumps(result, indent=2), encoding='ascii')
    save()
    try:
        # Verify that the device has not changed since backup, before any write.
        subprocess.run(command+['verify_flash', '0x0', str(backup)], check=True)
        result['phase'] = 'writing'
        save()
        pairs = ['0x10000', str(app), '0x370000', str(filesystem)]
        subprocess.run(command+['write_flash', '--flash_mode', 'keep', '--flash_freq', 'keep', '--flash_size', 'keep']+pairs, check=True)
        subprocess.run(command+['verify_flash']+pairs, check=True)
        preserved = private/'preserved-first-64k.bin'
        preserved.write_bytes(raw[:0x10000])
        subprocess.run(command+['verify_flash', '0x0', str(preserved)], check=True)
        result.update(phase='verified_held_in_rom', bootloader_partitions_nvs_preserved=True)
    except Exception as exc:
        result['error_type'] = type(exc).__name__
        raise
    finally:
        save()
    print('WASHER_FIELD_TEST_FLASH_VERIFIED ' + json.dumps(result))


if __name__ == '__main__':
    main()
