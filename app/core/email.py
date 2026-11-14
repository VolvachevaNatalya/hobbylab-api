"""
Email delivery module.

Production: set all four SMTP_* env vars and SMTP_FROM; emails are sent via
SMTP with STARTTLS.

When SMTP is not configured the function returns silently without delivering
anything. The OTP is never written to any log at any level — not even DEBUG.
Operations must configure SMTP before the password-reset flow is usable.

Required env vars for production:
  SMTP_HOST      — e.g. smtp.sendgrid.net
  SMTP_PORT      — e.g. 587
  SMTP_USER      — SMTP username
  SMTP_PASSWORD  — SMTP password
  SMTP_FROM      — sender address, e.g. noreply@hobbylab.co.il
"""
import logging
import os
import smtplib
import ssl
from email.mime.text import MIMEText

logger = logging.getLogger(__name__)

_SMTP_HOST = os.getenv("SMTP_HOST", "")
_SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
_SMTP_USER = os.getenv("SMTP_USER", "")
_SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
_SMTP_FROM = os.getenv("SMTP_FROM", "noreply@hobbylab.co.il")

_EMAIL_CONFIGURED = bool(_SMTP_HOST and _SMTP_USER and _SMTP_PASSWORD)


def send_password_reset_otp(to_email: str, otp: str) -> None:
    """Send a password-reset OTP to *to_email*.

    The raw OTP is never written to any log under any circumstance.  When SMTP
    is not configured the function returns silently; the caller still commits
    the token to the database so the flow can complete once SMTP is live.
    """
    if not _EMAIL_CONFIGURED:
        logger.warning(
            "password_reset_otp_not_sent | SMTP not configured — set SMTP_HOST, "
            "SMTP_USER, SMTP_PASSWORD env vars to enable email delivery | to=%s",
            to_email,
        )
        return

    subject = "Your HobbyLab password reset code"
    body = (
        f"Your HobbyLab password reset code is: {otp}\n\n"
        f"This code expires in 15 minutes and can only be used once.\n\n"
        f"If you did not request a password reset, you can safely ignore this email."
    )

    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"] = _SMTP_FROM
    msg["To"] = to_email

    try:
        context = ssl.create_default_context()
        with smtplib.SMTP(_SMTP_HOST, _SMTP_PORT, timeout=15) as server:
            server.ehlo()
            server.starttls(context=context)
            server.login(_SMTP_USER, _SMTP_PASSWORD)
            server.sendmail(_SMTP_FROM, [to_email], msg.as_string())
        logger.info("password_reset_otp_sent | to=%s", to_email)
    except Exception as exc:
        # Suppress so the caller returns its enumeration-safe 200 response.
        # Alert on this log entry in production monitoring.
        logger.error("password_reset_otp_send_failed | to=%s | error=%s", to_email, exc)
