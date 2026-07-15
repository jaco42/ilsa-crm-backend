import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.utils import formataddr
from app.config import settings


def send_email(
    to: str,
    subject: str,
    body: str,
    cc: list[str] | None = None,
    sender_name: str | None = None,
    reply_to: str | None = None,
) -> None:
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    smtp_addr = settings.smtp_from or settings.smtp_user
    msg["From"] = formataddr((sender_name, smtp_addr)) if sender_name else smtp_addr
    msg["To"] = to
    if cc:
        msg["Cc"] = ", ".join(cc)
    if reply_to:
        msg["Reply-To"] = reply_to

    msg.attach(MIMEText(body, "plain", "utf-8"))

    recipients = [to] + (cc or [])
    with smtplib.SMTP(settings.smtp_host, settings.smtp_port) as smtp:
        smtp.starttls()
        smtp.login(settings.smtp_user, settings.smtp_password)
        smtp.sendmail(smtp_addr, recipients, msg.as_string())
