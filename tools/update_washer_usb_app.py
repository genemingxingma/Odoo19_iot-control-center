"""Application-only USB update with a verified, current 4 MB backup.

The controller remains in its bootloader after verification. Network credentials,
programs, journals, NVS, partition metadata and the screen are never overwritten.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]


def sha(value):
    return hashlib.sha256(value).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--backup-dir', type=Path, required=True)
    parser.add_argument('--port', required=True)
    parser.add_argument('--expected-mac', required=True)
    parser.add_argument('--app-sha256', required=True)
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--confirm-actuator-power-off', action='store_true')
    args = parser.parse_args()
    root = args.backup_dir.resolve()
    if not root.is_relative_to(Path('D:/Codex/device_backups').resolve()):
        raise RuntimeError('A protected backup directory is required')
    receipt = json.loads((root/'backup-receipt.json').read_text(encoding='utf-8-sig'))
    backup = Path(receipt['backup_file']).resolve()
    raw = backup.read_bytes()
    if backup.parent != root or not receipt['verify_flash_passed'] or len(raw) != 0x400000 or sha(raw) != receipt['sha256']:
        raise RuntimeError('Invalid backup')
    build = ROOT/'firmware/instruments/.pio/build/washer'
    app = build/'firmware.bin'
    image = app.read_bytes()
    marker = re.search(rb'IMYTESTFW1:washer:washer-esp32-4m-v1:(\d+):END', image)
    previous = re.search(rb'IMYTESTFW1:washer:washer-esp32-4m-v1:(\d+):END', raw[0x10000:0x1c0000])
    if not marker or not previous or int(marker[1]) <= int(previous[1]):
        raise RuntimeError('Expected a forward update of the same hardware target')
    if sha(image) != args.app_sha256.lower() or len(image) > 0x1b0000:
        raise RuntimeError('Application hash or size mismatch')
    partition = (build/'partitions.bin').read_bytes()
    boot_app = Path.home()/'.platformio/packages/framework-arduinoespressif32/tools/partitions/boot_app0.bin'
    if raw[0x8000:0x8000+len(partition)] != partition or raw[0xe000:0x10000] != boot_app.read_bytes():
        raise RuntimeError('Partition or OTA state changed; refusing to guess the active slot')
    result = dict(phase='validated', firmware_number=int(marker[1]), application_sha256=sha(image),
                  backup_sha256=sha(raw), filesystem_unchanged=True, physical_acceptance=False)
    if not args.execute:
        print(json.dumps(result))
        return
    output = root/'application-update-receipt.json'
    if not args.confirm_actuator_power_off or output.exists():
        raise RuntimeError('Actuator isolation and a new receipt are required')
    tool = Path.home()/'.platformio/packages/tool-esptoolpy'
    sys.path.insert(0, str(tool))
    from esptool.loader import ESPLoader
    from esptool.reset import ClassicReset
    from esptool.targets.esp32 import ESP32ROM
    chip = ESP32ROM(args.port, 115200)

    def save():
        output.write_text(json.dumps(result, indent=2), encoding='ascii')

    try:
        # Keep reset, verification and writing in one session. Reopening a CH340
        # port can toggle its control lines and silently leave download mode.
        ClassicReset(chip._port, reset_delay=0.2)()
        chip.connect(mode='no_reset', attempts=2)
        if bytes(chip.read_mac()).hex() != args.expected_mac.replace(':', '').lower():
            raise RuntimeError('Unexpected controller identity')
        if not chip.get_chip_description().startswith('ESP32-D0WD-V3'):
            raise RuntimeError('Unexpected controller model')
        chip = chip.run_stub()
        chip.change_baud(460800)
        if chip.flash_md5sum(0, len(raw)).lower() != hashlib.md5(raw).hexdigest():
            raise RuntimeError('Device changed after the verified backup')

        (root/'application.bin').write_bytes(image)
        result['phase'] = 'writing'
        save()

        blocks = chip.flash_begin(len(image), 0x10000)
        for sequence in range(blocks):
            start = sequence * chip.FLASH_WRITE_SIZE
            block = image[start:start + chip.FLASH_WRITE_SIZE]
            block += b'\xff' * (chip.FLASH_WRITE_SIZE - len(block))
            chip.flash_block(block, sequence)
            if (sequence + 1) % 16 == 0 or sequence + 1 == blocks:
                done = min(len(image), (sequence + 1) * chip.FLASH_WRITE_SIZE)
                print(f'APPLICATION_WRITE_BYTES {done}/{len(image)}', flush=True)
        chip.read_reg(ESPLoader.CHIP_DETECT_MAGIC_REG_ADDR)
        chip.flash_begin(0, 0)
        chip.flash_finish(False)

        if chip.flash_md5sum(0x10000, len(image)).lower() != hashlib.md5(image).hexdigest():
            raise RuntimeError('Application verification failed')
        for name, start, end in (('preserved-prefix.bin', 0, 0x10000),
                                 ('preserved-data.bin', 0x1c0000, 0x400000)):
            path = root/name
            preserved = raw[start:end]
            path.write_bytes(preserved)
            if chip.flash_md5sum(start, len(preserved)).lower() != hashlib.md5(preserved).hexdigest():
                raise RuntimeError(f'{name} verification failed')
        result['phase'] = 'verified_held_in_rom'
    except Exception as exc:
        result['error_type'] = type(exc).__name__
        raise
    finally:
        chip._port.close()
        save()
    print('WASHER_APPLICATION_VERIFIED ' + json.dumps(result))


if __name__ == '__main__':
    main()
