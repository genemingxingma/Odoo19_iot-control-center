import copy
import unittest
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric import rsa
from tools.package_instrument_firmware import image_identity, manifest, verify


class InstrumentPackageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Ephemeral test-only key; no private material is persisted or printed.
        cls.key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        cls.raw = b'\xe9' + b'\0' * 64 + b'IMYTESTFW1:washer:washer-esp32-4m-v1:30001:END'

    def test_verified_package_matches_image(self):
        info = manifest(self.raw, self.key)
        verify(self.raw, info, self.key.public_key())
        self.assertEqual(info["version"], 30001)

    def test_withdrawn_heater_profiles_remain_blocked(self):
        for profile in ('heater-esp8266-v2', 'heater-esp8266-pcf8574-v1', 'heater-esp12s-ntc-v1'):
            raw = b'\xe9' + b'\0' * 64 + ('IMYTESTFW1:heater:' + profile + ':30003:END').encode('ascii')
            with self.subTest(profile=profile):
                with self.assertRaisesRegex(ValueError, 'Wrong hardware profile'):
                    image_identity(raw)
                with self.assertRaisesRegex(ValueError, 'Wrong hardware profile'):
                    manifest(raw, self.key)

    def test_previously_signed_heater_images_are_also_blocked(self):
        raw = b'\xe9' + b'\0' * 64 + b'IMYTESTFW1:heater:heater-esp8266-v2:30003:END'
        with self.assertRaisesRegex(ValueError, 'Wrong hardware profile'):
            verify(raw, {}, self.key.public_key())

    def test_source_verified_single_channel_profile_can_be_packaged(self):
        raw = b'\xe9' + b'\0' * 64 + b'IMYTESTFW1:heater:heater-esp12s-ds18b20-v1:31000:END'
        info = manifest(raw, self.key)
        verify(raw, info, self.key.public_key())
        self.assertEqual(info['hardware'], 'heater-esp12s-ds18b20-v1')

    def test_mutation_truncation_and_wrong_board_rejected(self):
        info = manifest(self.raw, self.key)
        for raw in (self.raw[:-1], self.raw+b'changed', self.raw.replace(b'washer-esp32', b'other-esp32')):
            with self.assertRaises(ValueError): verify(raw, info, self.key.public_key())

    def test_forged_signature_rejected(self):
        info = copy.deepcopy(manifest(self.raw, self.key))
        info["signature"] = "A" * 342 + "=="
        with self.assertRaises(InvalidSignature): verify(self.raw, info, self.key.public_key())

    def test_unsigned_legacy_images_and_multiple_identities_rejected(self):
        for raw in (b'\xe9' + b'\0' * 100, self.raw + b'IMYTESTFW1:heater:heater-esp8266-pcf8574-v1:30001:END'):
            with self.assertRaises(ValueError): image_identity(raw)
