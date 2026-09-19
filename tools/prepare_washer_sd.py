"""Refresh the bounded washer handoff folder on an explicitly selected drive."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil


ROOT = Path(__file__).resolve().parents[1]
CARD_FOLDER = "WASHER_V3_PREP_20260919"
VERSION = "3.4.0-rc5"
NUMERIC_VERSION = 30403


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--drive", type=Path, required=True)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    drive = args.drive.resolve()
    target = drive / CARD_FOLDER
    if not drive.is_dir() or not target.is_dir() or not (drive / "WASHER_README.txt").is_file():
        parser.error("The selected drive is not the previously prepared washer handoff drive")

    build = ROOT / "firmware/instruments/.pio/build/washer"
    signed = ROOT / "firmware/instruments/out/packages/washer-30403"
    sources = {
        "SCREEN/washer-v3.tft": ROOT / "firmware/instruments/out/hmi/washer-v3.tft",
        "ESP32_USB_ONLY/firmware.bin": build / "firmware.bin",
        "ESP32_USB_ONLY/bootloader.bin": build / "bootloader.bin",
        "ESP32_USB_ONLY/partitions.bin": build / "partitions.bin",
        "ESP32_USB_ONLY/boot_app0.bin": Path.home() / ".platformio/packages/framework-arduinoespressif32/tools/partitions/boot_app0.bin",
        "ESP32_USB_ONLY/partitions_4mb.csv": ROOT / "firmware/instruments/partitions_4mb.csv",
        "ESP32_SD/imytest-update/firmware.bin": signed / "firmware.bin",
        "ESP32_SD/imytest-update/manifest.json": signed / "manifest.json",
        "COMMISSIONING.md": ROOT / "docs/INSTRUMENTS_V3_COMMISSIONING.md",
    }
    missing = [str(path) for path in sources.values() if not path.is_file()]
    if missing:
        raise RuntimeError("Missing release inputs: " + ", ".join(missing))
    package = json.loads((signed / "manifest.json").read_text(encoding="ascii"))
    if (package["kind"], package["hardware"], package["version"]) != (
            "washer", "washer-esp32-4m-v1", NUMERIC_VERSION):
        raise RuntimeError("Signed SD package identity does not match this release")
    if sha256(signed / "firmware.bin") != package["sha256"]:
        raise RuntimeError("Signed SD package hash mismatch")

    plan = {relative: {"bytes": path.stat().st_size, "sha256": sha256(path)} for relative, path in sources.items()}
    if not args.execute:
        print(json.dumps({"dry_run": True, "drive": str(drive), "files": plan}, indent=2))
        return

    for relative, source in sources.items():
        destination = target / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)

    readme = f"""洗脱仪 V3 更新与恢复文件 / 2026-09-19

当前版本：ESP32 {VERSION} / {NUMERIC_VERSION}；屏幕 TJC8048X550_011C。
本次屏幕和 ESP32 已通过 USB 完成更新；此卡保留最终交付文件。

目录 {CARD_FOLDER}：
- SCREEN/washer-v3.tft：屏幕固件。仅用于 TJC 屏幕的 SD 卡升级流程。
- ESP32_SD/imytest-update：新版 ESP32 可验证的签名 SD 更新包。
- ESP32_USB_ONLY：完整 USB 恢复文件，不是插卡自动升级文件。
- COMMISSIONING.md：现场接线、校准和安全验收清单。
- FILE_MANIFEST.json、SHA256SUMS.txt：版本、大小和 SHA-256 校验值。

ESP32 的 SD 更新：
1. 将 ESP32_SD/imytest-update 整个目录复制到连接 ESP32 的 SD 卡根目录。
2. 最终路径必须是 /imytest-update/manifest.json 和 /imytest-update/firmware.bin。
3. 设备必须空闲；从 DEVICE CARE > SD UPDATE 进入并在屏幕确认 INSTALL。
4. 更新不是插卡自动执行。验签、硬件型号或哈希不匹配时设备会拒绝安装。
5. 更新失败时不要删除包，保留现场状态和日志后检查原因。

屏幕 SD 更新与 ESP32 SD 更新使用不同的卡槽和文件格式。不要把 TFT 改名为
system_update.bin，也不要把 USB 恢复 BIN 放到屏幕卡根目录。USB 恢复文件的
偏移和分区必须由维护人员按 COMMISSIONING.md 执行，不能猜测。

当前设备仍未 commissioning、未绑定生产平台；软件更新不等于泵量、转向、
停止距离、平衡或负载安全验收。所有输出保持关闭，完成现场验收后方可启用。
"""
    (target / "README.txt").write_text(readme, encoding="utf-8")
    (drive / "WASHER_README.txt").write_text(readme, encoding="utf-8")

    listed = [*sources, "README.txt"]
    files = [{"path": relative, "bytes": (target / relative).stat().st_size,
              "sha256": sha256(target / relative)} for relative in listed]
    manifest = {
        "schema": 2,
        "prepared_at": datetime.now(timezone.utc).astimezone().isoformat(),
        "status": "USB_RECOVERY_AND_SIGNED_SD_UPDATE_READY",
        "sd_auto_update": False,
        "hardware_accepted": False,
        "secrets_included": False,
        "screen": "TJC8048X550_011C",
        "esp32": "washer-esp32-4m-v1",
        "version": VERSION,
        "numeric_version": NUMERIC_VERSION,
        "card_folder": CARD_FOLDER,
        "files": files,
    }
    (target / "FILE_MANIFEST.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (target / "SHA256SUMS.txt").write_text("".join(item["sha256"] + "  " + item["path"] + "\n" for item in files), encoding="ascii")
    for item in files:
        destination = target / item["path"]
        if destination.stat().st_size != item["bytes"] or sha256(destination) != item["sha256"]:
            raise RuntimeError("Post-copy verification failed: " + item["path"])
    print("WASHER_SD_READY", json.dumps({"drive": str(drive), "version": VERSION, "files": len(files)}))


if __name__ == "__main__":
    main()
