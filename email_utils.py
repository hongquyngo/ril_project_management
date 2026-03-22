"""
Email Utility Module
====================
Reusable email sender using Gmail SMTP.

Setup:
    pip install python-dotenv

.env file:
    EMAIL_SENDER=erp@rozitek.com
    EMAIL_PASSWORD=jzswlqttcysjzpcb
    SMTP_HOST=smtp.gmail.com
    SMTP_PORT=587
"""

import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# ── Config ──────────────────────────────────────────────
SMTP_HOST = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", 587))
EMAIL_SENDER = os.getenv("EMAIL_SENDER")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD")


def send_email(
    to: str | list[str],
    subject: str,
    body: str,
    html: str | None = None,
    cc: str | list[str] | None = None,
    bcc: str | list[str] | None = None,
    attachments: list[str] | None = None,
    reply_to: str | None = None,
) -> dict:
    """
    Send an email via SMTP.

    Args:
        to:          Recipient(s) - single email or list
        subject:     Email subject
        body:        Plain text body
        html:        Optional HTML body (sends as multipart/alternative)
        cc:          CC recipient(s)
        bcc:         BCC recipient(s)
        attachments: List of file paths to attach
        reply_to:    Reply-To address

    Returns:
        dict with 'success' (bool) and 'message' (str)
    """
    if not EMAIL_SENDER or not EMAIL_PASSWORD:
        return {"success": False, "message": "Missing EMAIL_SENDER or EMAIL_PASSWORD in .env"}

    # Normalize recipients
    to_list = [to] if isinstance(to, str) else to
    cc_list = [cc] if isinstance(cc, str) else (cc or [])
    bcc_list = [bcc] if isinstance(bcc, str) else (bcc or [])
    all_recipients = to_list + cc_list + bcc_list

    # Build message
    msg = MIMEMultipart("mixed")
    msg["From"] = EMAIL_SENDER
    msg["To"] = ", ".join(to_list)
    msg["Subject"] = subject

    if cc_list:
        msg["Cc"] = ", ".join(cc_list)
    if reply_to:
        msg["Reply-To"] = reply_to

    # Body: plain text + optional HTML
    if html:
        alt = MIMEMultipart("alternative")
        alt.attach(MIMEText(body, "plain", "utf-8"))
        alt.attach(MIMEText(html, "html", "utf-8"))
        msg.attach(alt)
    else:
        msg.attach(MIMEText(body, "plain", "utf-8"))

    # Attachments
    for filepath in (attachments or []):
        path = Path(filepath)
        if not path.exists():
            return {"success": False, "message": f"Attachment not found: {filepath}"}
        part = MIMEBase("application", "octet-stream")
        part.set_payload(path.read_bytes())
        encoders.encode_base64(part)
        part.add_header("Content-Disposition", f'attachment; filename="{path.name}"')
        msg.attach(part)

    # Send
    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.starttls()
            server.login(EMAIL_SENDER, EMAIL_PASSWORD)
            server.sendmail(EMAIL_SENDER, all_recipients, msg.as_string())
        return {"success": True, "message": f"Email sent to {', '.join(to_list)}"}
    except smtplib.SMTPAuthenticationError:
        return {"success": False, "message": "SMTP authentication failed. Check EMAIL_PASSWORD (use App Password for Gmail)."}
    except Exception as e:
        return {"success": False, "message": f"Send failed: {e}"}


# ── Quick test ──────────────────────────────────────────
if __name__ == "__main__":

    # 1) Simple text email
    result = send_email(
        to="recipient@example.com",
        subject="Test từ ERP Rozitek",
        body="Xin chào, đây là email test từ hệ thống ERP.",
    )
    print(result)

    # 2) HTML email with CC and attachment
    # result = send_email(
    #     to=["user1@example.com", "user2@example.com"],
    #     subject="Báo cáo tháng 3/2026",
    #     body="Vui lòng xem báo cáo đính kèm.",
    #     html="""
    #         <h2>Báo cáo tháng 3/2026</h2>
    #         <p>Kính gửi Anh/Chị,</p>
    #         <p>Đính kèm là báo cáo tổng hợp tháng 3.</p>
    #         <p style="color: #666;">— ERP System, Rozitek</p>
    #     """,
    #     cc="manager@rozitek.com",
    #     attachments=["./reports/report_2026_03.pdf"],
    # )
    # print(result)
