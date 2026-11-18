import unittest

from cryptography.fernet import Fernet

from app.security import SecretBox


class SecretBoxTests(unittest.TestCase):
    def test_encrypt_decrypt_round_trip(self):
        key = Fernet.generate_key().decode("ascii")
        box = SecretBox(key)
        secret = "example-heroku-api-token"
        encrypted = box.encrypt(secret)
        self.assertNotEqual(secret, encrypted)
        self.assertEqual(secret, box.decrypt(encrypted))

    def test_wrong_key_cannot_decrypt(self):
        first = SecretBox(Fernet.generate_key().decode("ascii"))
        second = SecretBox(Fernet.generate_key().decode("ascii"))
        encrypted = first.encrypt("sensitive-value")
        with self.assertRaises(RuntimeError):
            second.decrypt(encrypted)


if __name__ == "__main__":
    unittest.main()
