import re
import resend
from app.config import settings


def send_email(
    to: list[str],
    subject: str,
    body: str,
    cc: list[str] | None = None,
    sender_name: str | None = None,
    reply_to: str | None = None,
) -> None:
    resend.api_key = settings.resend_api_key

    from_addr = settings.resend_from
    if sender_name:
        addr = re.search(r'<(.+?)>', from_addr)
        email_part = addr.group(1) if addr else from_addr
        from_addr = f"{sender_name} <{email_part}>"

    params: resend.Emails.SendParams = {
        "from": from_addr,
        "to": to,
        "subject": subject,
        "text": body,
    }
    if cc:
        params["cc"] = cc
    if reply_to:
        params["reply_to"] = reply_to

    resend.Emails.send(params)
