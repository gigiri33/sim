"""
Unit tests for bot/iran_panel/crypto_utils.py
"""
import sys
import os
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from bot.iran_panel.crypto_utils import (
    encrypt_secret,
    decrypt_secret,
    hash_with_salt,
    verify_hash,
    generate_reg_token,
    generate_agent_secret,
    generate_uuid,
    generate_salt,
)

_BOT_TOKEN = "test-bot-token-1234567890"


class TestEncryptDecrypt(unittest.TestCase):
    def test_roundtrip(self):
        plaintext = "supersecret_password"
        ciphertext = encrypt_secret(plaintext, _BOT_TOKEN)
        result = decrypt_secret(ciphertext, _BOT_TOKEN)
        self.assertEqual(result, plaintext)

    def test_ciphertext_differs_from_plaintext(self):
        plaintext = "supersecret_password"
        ciphertext = encrypt_secret(plaintext, _BOT_TOKEN)
        self.assertNotEqual(ciphertext, plaintext)

    def test_different_bot_token_fails(self):
        plaintext = "supersecret_password"
        ciphertext = encrypt_secret(plaintext, _BOT_TOKEN)
        # Different token should fail or return garbage
        result = decrypt_secret(ciphertext, "different-token")
        # Either raises or returns wrong value — it should NOT equal plaintext
        self.assertNotEqual(result, plaintext)

    def test_empty_string(self):
        ciphertext = encrypt_secret("", _BOT_TOKEN)
        result = decrypt_secret(ciphertext, _BOT_TOKEN)
        self.assertEqual(result, "")

    def test_unicode_password(self):
        plaintext = "رمز_عبور_فارسی_123"
        ciphertext = encrypt_secret(plaintext, _BOT_TOKEN)
        result = decrypt_secret(ciphertext, _BOT_TOKEN)
        self.assertEqual(result, plaintext)


class TestHashVerify(unittest.TestCase):
    def test_hash_verify_roundtrip(self):
        value = "my_agent_secret_here"
        salt = generate_salt()
        digest = hash_with_salt(value, salt)
        self.assertTrue(verify_hash(value, salt, digest))

    def test_wrong_value_fails(self):
        value = "correct_secret"
        salt = generate_salt()
        digest = hash_with_salt(value, salt)
        self.assertFalse(verify_hash("wrong_secret", salt, digest))

    def test_wrong_salt_fails(self):
        value = "my_secret"
        salt1 = generate_salt()
        salt2 = generate_salt()
        digest = hash_with_salt(value, salt1)
        self.assertFalse(verify_hash(value, salt2, digest))

    def test_hash_is_hex(self):
        digest = hash_with_salt("value", "salt")
        # Should be a 64-char hex string (SHA-256)
        self.assertEqual(len(digest), 64)
        int(digest, 16)  # should not raise


class TestGenerators(unittest.TestCase):
    def test_reg_token_length(self):
        token = generate_reg_token()
        self.assertEqual(len(token), 40)

    def test_reg_token_hex(self):
        token = generate_reg_token()
        int(token, 16)  # should not raise

    def test_reg_tokens_unique(self):
        tokens = {generate_reg_token() for _ in range(50)}
        self.assertEqual(len(tokens), 50)

    def test_agent_secret_length(self):
        secret = generate_agent_secret()
        self.assertEqual(len(secret), 64)

    def test_agent_secrets_unique(self):
        secrets = {generate_agent_secret() for _ in range(50)}
        self.assertEqual(len(secrets), 50)

    def test_uuid_format(self):
        import uuid
        uid = generate_uuid()
        parsed = uuid.UUID(uid)  # should not raise
        self.assertEqual(str(parsed), uid)

    def test_salt_is_hex(self):
        salt = generate_salt()
        int(salt, 16)  # should not raise


if __name__ == "__main__":
    unittest.main()
