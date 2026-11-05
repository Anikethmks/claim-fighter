"""Outgoing email over SMTP. Without SMTP settings (dev), messages are written to the log."""

from __future__ import annotations

import logging
import smtplib
from email.message import EmailMessage

from .config import settings

log = logging.getLogger("claimfighter.mail")


class MailError(RuntimeError):
    pass


def send(to: str, subject: str, body: str) -> None:
    smtp = settings.smtp
    if not smtp["host"]:
        if settings.prod:
            raise MailError("Email isn't configured (CF_SMTP_HOST).")
        log.warning("DEV EMAIL to %s | %s\n%s", to, subject, body)
        return
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = smtp["sender"] or smtp["user"]
    msg["To"] = to
    msg.set_content(body)
    try:
        with smtplib.SMTP(smtp["host"], smtp["port"], timeout=15) as s:
            s.starttls()
            if smtp["user"]:
                s.login(smtp["user"], smtp["password"])
            s.send_message(msg)
    except (smtplib.SMTPException, OSError) as e:
        log.exception("Email to %s failed", to)
        raise MailError(str(e)) from e
