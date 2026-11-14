"""Sends InternLink's emails through Gmail (or any SMTP server) or through Resend.

Gmail is used when SMTP_USER and SMTP_PASSWORD are set. It needs no domain:
turn on 2-Step Verification for the Gmail account, create an "app password",
and put that in SMTP_PASSWORD. Otherwise Resend is used when RESEND_API_KEY
and INTERNLINK_FROM_EMAIL are set.
"""

from __future__ import annotations

import json
import os
import re
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr, parseaddr
from html import unescape
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

DEFAULT_SMTP_HOST = "smtp.gmail.com"
DEFAULT_SMTP_PORT = 587
TIMEOUT_SECONDS = 10

NOT_CONFIGURED_MESSAGE = (
    "Sending email needs Gmail settings (SMTP_USER and SMTP_PASSWORD) "
    "or Resend settings (RESEND_API_KEY and INTERNLINK_FROM_EMAIL)."
)


class EmailNotConfigured(RuntimeError):
    """No email provider has been set up."""


class EmailFailed(RuntimeError):
    """The provider was reached but the email could not be sent."""


def provider() -> str | None:
    """Return "smtp", "resend", or None when nothing is set up."""
    if _env("SMTP_USER") and _env("SMTP_PASSWORD"):
        return "smtp"
    if _env("RESEND_API_KEY") and _env("INTERNLINK_FROM_EMAIL"):
        return "resend"
    return None


def is_configured() -> bool:
    return provider() is not None


def send(to: str, subject: str, html: str) -> None:
    """Send one HTML email. Raises EmailNotConfigured or EmailFailed."""
    chosen = provider()
    if chosen == "smtp":
        _send_smtp(to, subject, html)
    elif chosen == "resend":
        _send_resend(to, subject, html)
    else:
        raise EmailNotConfigured(NOT_CONFIGURED_MESSAGE)


def _env(name: str) -> str:
    return os.environ.get(name, "").strip()


def _sender(default_address: str) -> str:
    """The From header. INTERNLINK_FROM_EMAIL wins; a bare address gets the name InternLink."""
    configured = _env("INTERNLINK_FROM_EMAIL") or default_address
    name, address = parseaddr(configured)
    return formataddr((name or "InternLink", address or configured))


def plain_text(html: str) -> str:
    """A readable plain-text copy of the HTML, for mail apps that don't show HTML."""
    text = re.sub(r'<a\s[^>]*href="([^"]*)"[^>]*>(.*?)</a>', r"\2: \1", html, flags=re.I | re.S)
    text = re.sub(r"</p>|<br\s*/?>", "\n\n", text, flags=re.I)
    text = re.sub(r"<[^>]+>", "", text)
    text = unescape(text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def _send_smtp(to: str, subject: str, html: str) -> None:
    user = _env("SMTP_USER")
    # Google shows app passwords in groups of four ("abcd efgh ijkl mnop"); spaces aren't part of it.
    password = _env("SMTP_PASSWORD").replace(" ", "")
    host = _env("SMTP_HOST") or DEFAULT_SMTP_HOST
    try:
        port = int(_env("SMTP_PORT") or DEFAULT_SMTP_PORT)
    except ValueError as exc:
        raise EmailNotConfigured("SMTP_PORT must be a number, such as 587.") from exc

    message = EmailMessage()
    message["From"] = _sender(user)
    message["To"] = to
    message["Subject"] = subject
    message.set_content(plain_text(html))
    message.add_alternative(html, subtype="html")

    context = ssl.create_default_context()
    try:
        if port == 465:
            server = smtplib.SMTP_SSL(host, port, timeout=TIMEOUT_SECONDS, context=context)
        else:
            server = smtplib.SMTP(host, port, timeout=TIMEOUT_SECONDS)
        with server:
            if port != 465:
                server.starttls(context=context)
            server.login(user, password)
            server.send_message(message)
    except smtplib.SMTPAuthenticationError as exc:
        raise EmailFailed(
            "The email server rejected SMTP_USER/SMTP_PASSWORD. For Gmail, use an app password."
        ) from exc
    except (smtplib.SMTPException, OSError) as exc:
        raise EmailFailed(f"Could not send email through {host}:{port}: {exc}") from exc


def _send_resend(to: str, subject: str, html: str) -> None:
    data = json.dumps(
        {"from": _env("INTERNLINK_FROM_EMAIL"), "to": [to], "subject": subject, "html": html}
    ).encode("utf-8")
    request = Request(
        "https://api.resend.com/emails",
        data=data,
        headers={"Authorization": f"Bearer {_env('RESEND_API_KEY')}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            if response.status >= 300:
                raise EmailFailed(f"Resend returned HTTP {response.status}")
    except (HTTPError, URLError, TimeoutError, OSError) as exc:
        raise EmailFailed(f"Could not reach Resend: {exc}") from exc
