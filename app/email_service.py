import resend
from flask import current_app


def send_email(to_emails, subject, html_content):
    resend.api_key = current_app.config["RESEND_API_KEY"]
    if isinstance(to_emails, str):
        to_emails = [to_emails]
    resend.Emails.send({
        "from": current_app.config["EMAIL_FROM"],
        "to": to_emails,
        "subject": subject,
        "html": html_content,
    })
