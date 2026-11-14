"""Email sending through Gmail (SMTP) or Resend, with the network faked."""

import os
import smtplib
import unittest
from unittest.mock import patch

from student_module import mailer

GMAIL = {"SMTP_USER": "internlink.team@gmail.com", "SMTP_PASSWORD": "abcd efgh ijkl mnop"}
RESEND = {"RESEND_API_KEY": "re_test", "INTERNLINK_FROM_EMAIL": "noreply@internlink.test"}
EMPTY = {name: "" for name in ("SMTP_USER", "SMTP_PASSWORD", "SMTP_HOST", "SMTP_PORT", "RESEND_API_KEY", "INTERNLINK_FROM_EMAIL")}


class FakeSMTP:
    """Records what the mailer does instead of talking to a real server."""

    instances = []
    reject_login = False

    def __init__(self, host, port, timeout=None, context=None):
        self.host, self.port, self.timeout = host, port, timeout
        self.started_tls = False
        self.logged_in = None
        self.sent = []
        FakeSMTP.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def starttls(self, context=None):
        self.started_tls = True

    def login(self, user, password):
        if FakeSMTP.reject_login:
            raise smtplib.SMTPAuthenticationError(535, b"Username and Password not accepted")
        self.logged_in = (user, password)

    def send_message(self, message):
        self.sent.append(message)


class MailerTests(unittest.TestCase):
    def setUp(self):
        FakeSMTP.instances = []
        FakeSMTP.reject_login = False

    def env(self, **values):
        return patch.dict(os.environ, {**EMPTY, **values})

    def test_nothing_configured(self):
        with self.env():
            self.assertIsNone(mailer.provider())
            with self.assertRaises(mailer.EmailNotConfigured):
                mailer.send("a@b.com", "Hi", "<p>Hi</p>")

    def test_gmail_is_preferred_when_both_are_set(self):
        with self.env(**GMAIL, **RESEND):
            self.assertEqual(mailer.provider(), "smtp")
        with self.env(**RESEND):
            self.assertEqual(mailer.provider(), "resend")

    def test_sends_through_gmail(self):
        html = '<p>Hello Aisha,</p><p><a href="https://internlink.test/verify?token=x">Confirm email</a></p>'
        with self.env(**GMAIL), patch("smtplib.SMTP", FakeSMTP):
            mailer.send("aisha@std.must.ac.ug", "Confirm your InternLink email address", html)

        server = FakeSMTP.instances[0]
        self.assertEqual((server.host, server.port), ("smtp.gmail.com", 587))
        self.assertTrue(server.started_tls)
        # The spaces Google shows in app passwords are removed.
        self.assertEqual(server.logged_in, ("internlink.team@gmail.com", "abcdefghijklmnop"))
        message = server.sent[0]
        self.assertEqual(message["To"], "aisha@std.must.ac.ug")
        self.assertEqual(message["From"], "InternLink <internlink.team@gmail.com>")
        self.assertEqual(message["Subject"], "Confirm your InternLink email address")
        self.assertIn("https://internlink.test/verify?token=x", message.get_body(("plain",)).get_content())
        self.assertIn('<a href="https://internlink.test/verify?token=x">', message.get_body(("html",)).get_content())

    def test_from_address_can_be_set(self):
        with self.env(**GMAIL, INTERNLINK_FROM_EMAIL="InternLink Team <internlink.team@gmail.com>"), patch("smtplib.SMTP", FakeSMTP):
            mailer.send("a@b.com", "Hi", "<p>Hi</p>")
        self.assertEqual(FakeSMTP.instances[0].sent[0]["From"], "InternLink Team <internlink.team@gmail.com>")

    def test_port_465_uses_ssl(self):
        with self.env(**GMAIL, SMTP_PORT="465"), patch("smtplib.SMTP_SSL", FakeSMTP):
            mailer.send("a@b.com", "Hi", "<p>Hi</p>")
        server = FakeSMTP.instances[0]
        self.assertEqual(server.port, 465)
        self.assertFalse(server.started_tls)

    def test_wrong_password_is_explained(self):
        FakeSMTP.reject_login = True
        with self.env(**GMAIL), patch("smtplib.SMTP", FakeSMTP):
            with self.assertRaisesRegex(mailer.EmailFailed, "app password"):
                mailer.send("a@b.com", "Hi", "<p>Hi</p>")

    def test_unreachable_server(self):
        def refuse(*_args, **_kwargs):
            raise ConnectionRefusedError("no route")

        with self.env(**GMAIL), patch("smtplib.SMTP", refuse):
            with self.assertRaises(mailer.EmailFailed):
                mailer.send("a@b.com", "Hi", "<p>Hi</p>")

    def test_plain_text_copy(self):
        text = mailer.plain_text('<p>Hello &amp; welcome,</p><p><a href="https://x.test/v">Confirm</a></p>')
        self.assertEqual(text, "Hello & welcome,\n\nConfirm: https://x.test/v")


if __name__ == "__main__":
    unittest.main()
