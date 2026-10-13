"""Known synthetic ciphertext generated with cryptography 46.0.7 before upgrade.

The test key is intentionally public. No production material belongs here.
"""
import base64
import unittest

from cryptography.exceptions import InvalidTag
from backend.service import RecordCodec


KEY = bytes(range(32))
IDENTITY = 'legacy-compatibility'
PAYLOAD = {'message': 'Synthetic only', 'version': 1}
CIPHERTEXT = base64.b64decode('jMbcUQMeuKTeo4mTl/QRE38+RSjzwpq+6xYPOG8qfYqNxAel4KWg9TIC4QijI5PvX71j1ELZrpJwT6JyVX0sEV4vO40=')
DIGEST_KEY = '9ba9b39027c493b68bbd31c1f48bd3fb0774705f58d47cd9ace49200a393aed7'


class CryptoCompatibilityTests(unittest.TestCase):
    def test_legacy_record_and_hkdf_key_remain_compatible(self):
        codec = RecordCodec(KEY)
        self.assertEqual(codec.open(IDENTITY, CIPHERTEXT), PAYLOAD)
        self.assertEqual(codec.key.hex(), DIGEST_KEY)

    def test_legacy_record_still_authenticates_key_identity_and_ciphertext(self):
        for key, identity, blob in ((b'x' * 32, IDENTITY, CIPHERTEXT),
                                    (KEY, 'different-identity', CIPHERTEXT),
                                    (KEY, IDENTITY, CIPHERTEXT[:-1] + bytes([CIPHERTEXT[-1] ^ 1])),
                                    (KEY, IDENTITY, CIPHERTEXT[:-1])):
            with self.subTest(identity=identity, size=len(blob)), self.assertRaises(InvalidTag):
                RecordCodec(key).open(identity, blob)

    def test_new_record_roundtrip_and_unique_nonce(self):
        codec = RecordCodec(KEY)
        left, right = codec.seal(IDENTITY, PAYLOAD), codec.seal(IDENTITY, PAYLOAD)
        self.assertNotEqual(left[:12], right[:12])
        self.assertEqual(codec.open(IDENTITY, left), PAYLOAD)
        self.assertEqual(codec.open(IDENTITY, right), PAYLOAD)


if __name__ == '__main__':
    unittest.main()
