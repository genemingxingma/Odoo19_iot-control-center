"""Create a device-verifiable OTA/SD package without embedding a private key.

Run with the instrument virtualenv (cryptography dependency). The signing key
must already exist outside the repository. A package is not field acceptance.
"""
import argparse
import base64
import getpass
import hashlib
import json
import re
from pathlib import Path

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

# Never accept the withdrawn dual-channel heater image for the single-output PCB.
TARGETS = {"heater": ("heater-esp12s-ds18b20-v1", 1000000), "washer": ("washer-esp32-4m-v1", 0x1B0000)}


def image_identity(raw):
    found = set(re.findall(rb"IMYTESTFW1:(heater|washer):([a-z0-9-]+):([0-9]+):END", raw))
    if len(found) != 1 or len(raw) < 32 or raw[0] != 0xE9:
        raise ValueError("Not a uniquely identified instrument application image")
    kind, hardware, version = next(iter(found))
    kind, hardware, version = kind.decode(), hardware.decode(), int(version)
    expected, limit = TARGETS[kind]
    if expected != hardware or len(raw) > limit or not 0 < version <= 2147483647:
        raise ValueError("Wrong hardware profile, version or image size")
    return kind, hardware, version


def signed_bytes(info):
    return ("IMYTEST-OTA-1\n{kind}\n{hardware}\n{version}\n{size}\n{sha256}\n".format(**info)).encode("ascii")


def manifest(raw, key):
    if not isinstance(key, rsa.RSAPrivateKey) or key.key_size != 2048:
        raise ValueError("RSA-2048 signing key required")
    kind, hardware, version = image_identity(raw)
    result = dict(schema=1, kind=kind, hardware=hardware, version=version, size=len(raw), sha256=hashlib.sha256(raw).hexdigest())
    result["signature"] = base64.b64encode(key.sign(signed_bytes(result), padding.PKCS1v15(), hashes.SHA256())).decode("ascii")
    return result


def verify(raw, info, public_key):
    kind, hardware, version = image_identity(raw)
    if (info.get("schema"), info.get("kind"), info.get("hardware"), info.get("version"), info.get("size"), info.get("sha256")) != (
            1, kind, hardware, version, len(raw), hashlib.sha256(raw).hexdigest()):
        raise ValueError("Package metadata does not match its image")
    public_key.verify(base64.b64decode(info["signature"], validate=True), signed_bytes(info), padding.PKCS1v15(), hashes.SHA256())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("binary", type=Path)
    parser.add_argument("--key", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    if args.key.resolve().is_relative_to(root):
        parser.error("Keep signing keys outside the repository")
    pem = args.key.read_bytes()
    try:
        key = serialization.load_pem_private_key(pem, password=None)
    except TypeError:
        key = serialization.load_pem_private_key(pem, password=getpass.getpass("Signing-key passphrase: ").encode())
    raw = args.binary.read_bytes()
    info = manifest(raw, key)
    verify(raw, info, key.public_key())
    args.out.mkdir(parents=True, exist_ok=False)
    (args.out / "firmware.bin").write_bytes(raw)
    (args.out / "manifest.json").write_text(json.dumps(info, indent=2) + "\n", encoding="ascii")
    print("SIGNED_PACKAGE_CREATED", args.out, "version", info["version"])


if __name__ == "__main__":
    main()
