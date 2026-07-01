import os
import smtplib
from email.message import EmailMessage

import requests


def send_alert(subject: str, message: str) -> None:
    """Send best-effort operational alerts without blocking trading flow."""
    _send_webhook(os.getenv("ALERT_SLACK_WEBHOOK_URL"), subject, message)
    _send_webhook(os.getenv("ALERT_DISCORD_WEBHOOK_URL"), subject, message)
    _send_email(subject, message)


def _send_webhook(url: str | None, subject: str, message: str) -> None:
    if not url:
        return
    try:
        requests.post(url, json={"text": f"{subject}\n{message}"}, timeout=10)
    except requests.RequestException:
        return


def _send_email(subject: str, message: str) -> None:
    recipient = os.getenv("DAILY_REPORT_EMAIL_TO")
    sender = os.getenv("DAILY_REPORT_EMAIL_FROM")
    host = os.getenv("SMTP_HOST")
    username = os.getenv("SMTP_USERNAME")
    password = os.getenv("SMTP_PASSWORD")
    if not all([recipient, sender, host, username, password]):
        return

    email = EmailMessage()
    email["Subject"] = subject
    email["From"] = sender
    email["To"] = recipient
    email.set_content(message)

    port = int(os.getenv("SMTP_PORT", "587"))
    try:
        with smtplib.SMTP(host, port, timeout=20) as smtp:
            smtp.starttls()
            smtp.login(username, password)
            smtp.send_message(email)
    except OSError:
        return
