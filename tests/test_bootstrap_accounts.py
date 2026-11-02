import unittest

import bcrypt

from scripts.seed_initial_accounts import ACCOUNTS, generate_passwords, password_hash


class BootstrapAccountTests(unittest.TestCase):
    def test_passwords_are_unique_and_cryptographically_generated(self):
        passwords = generate_passwords()
        self.assertEqual(set(passwords), {email for email, _, _ in ACCOUNTS})
        self.assertEqual(len(set(passwords.values())), len(ACCOUNTS))
        self.assertTrue(all(len(password) >= 24 for password in passwords.values()))
        self.assertTrue(set(passwords.values()).isdisjoint(generate_passwords().values()))

    def test_password_hash_is_bcrypt_and_verifiable(self):
        password = "single-use-test-password"
        encoded = password_hash(password)
        self.assertTrue(encoded.startswith("$2"))
        self.assertTrue(bcrypt.checkpw(password.encode(), encoded.encode()))
        self.assertFalse(bcrypt.checkpw(b"incorrect-password", encoded.encode()))


if __name__ == "__main__":
    unittest.main()
