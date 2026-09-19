"""Generate private, output-locked washer test provisioning from Windows WLAN.

The destination must already be ACL-restricted by the operator. Never print
profile XML, device tokens, key contents or the generated filesystem contents.
"""
import argparse
import ctypes as C
from ctypes import wintypes as W
from datetime import datetime, timedelta, timezone
import hashlib
import ipaddress
import json
from pathlib import Path
import secrets
import uuid
import xml.etree.ElementTree as ET

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID


def wlan_profile(guid, profile):
    wlan = C.WinDLL('wlanapi')
    handle, negotiated = W.HANDLE(), W.DWORD()
    wlan.WlanOpenHandle.argtypes = [W.DWORD, C.c_void_p, C.POINTER(W.DWORD), C.POINTER(W.HANDLE)]
    wlan.WlanGetProfile.argtypes = [W.HANDLE, C.c_void_p, W.LPCWSTR, C.c_void_p,
                                   C.POINTER(C.c_void_p), C.POINTER(W.DWORD), C.POINTER(W.DWORD)]
    wlan.WlanFreeMemory.argtypes = [C.c_void_p]
    wlan.WlanCloseHandle.argtypes = [W.HANDLE, C.c_void_p]
    if wlan.WlanOpenHandle(2, None, C.byref(negotiated), C.byref(handle)):
        raise RuntimeError('Cannot open WLAN API')
    xml = C.c_void_p()
    try:
        interface = C.create_string_buffer(uuid.UUID(guid).bytes_le)
        flags, access = W.DWORD(4), W.DWORD()
        if wlan.WlanGetProfile(handle, interface, profile, None, C.byref(xml), C.byref(flags), C.byref(access)):
            raise RuntimeError('Cannot read the authorized WLAN profile')
        tree = ET.fromstring(C.wstring_at(xml))
        ns = {'w': 'http://www.microsoft.com/networking/WLAN/profile/v1'}
        ssid = tree.findtext('w:SSIDConfig/w:SSID/w:name', namespaces=ns)
        key = tree.find('w:MSM/w:security/w:sharedKey', ns)
        if key is None or key.findtext('w:protected', namespaces=ns) != 'false':
            raise RuntimeError('Plaintext WLAN key was not supplied by Windows')
        password = key.findtext('w:keyMaterial', namespaces=ns)
        if not ssid or not password:
            raise RuntimeError('WLAN profile is incomplete')
        return ssid, password
    finally:
        if xml.value: wlan.WlanFreeMemory(xml)
        wlan.WlanCloseHandle(handle, None)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--private-dir', type=Path, required=True)
    p.add_argument('--interface', required=True)
    p.add_argument('--profile', required=True)
    p.add_argument('--proxy-ip', required=True)
    a = p.parse_args()
    if not a.private_dir.is_dir() or list(a.private_dir.iterdir()):
        raise RuntimeError('Destination must be an existing empty restricted directory')
    ipaddress.ip_address(a.proxy_ip)
    ssid, password = wlan_profile(a.interface, a.profile)
    uid, token = uuid.uuid4().hex, secrets.token_hex(32)
    data = a.private_dir / 'data'; data.mkdir()
    def write(name, value):
        (data / name).write_text(json.dumps(value), encoding='utf-8')
    write('hardware.json', {'profile':'washer-esp32-4m-v1', 'commissioned':False,
        'rotor_mode':'open', 'open_rotor_commissioned':False, 'loading_calibrated':False})
    write('wifi.json', {'ssid':ssid, 'password':password})
    write('network.json', {'url':f'https://{a.proxy_ip}:18443', 'uid':uid, 'token':token})
    (a.private_dir / 'fixture.json').write_text(json.dumps({
        'uid':uid, 'token_hash':hashlib.sha256(token.encode()).hexdigest()}), encoding='utf-8')
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'Temporary isolated washer test')])
    now = datetime.now(timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
        .serial_number(x509.random_serial_number()).not_valid_before(now-timedelta(days=1))
        .not_valid_after(now+timedelta(days=2))
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .add_extension(x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address(a.proxy_ip)),
                                                  x509.DNSName(a.proxy_ip)]), critical=False)
        .sign(key, hashes.SHA256()))
    (data / 'server-ca.pem').write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    (a.private_dir / 'proxy-cert.pem').write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    (a.private_dir / 'proxy-key.pem').write_bytes(key.private_bytes(serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    signing = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    (a.private_dir / 'firmware-signing-private.pem').write_bytes(signing.private_bytes(serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    (data / 'ota-public.pem').write_bytes(signing.public_key().public_bytes(serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo))
    print('PRIVATE_TEST_PROVISIONING_READY; actuator commissioning disabled; credentials not displayed')


if __name__ == '__main__':
    main()
