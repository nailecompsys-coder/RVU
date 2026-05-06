"""
Shared transactional email service — Gmail SMTP (Google Workspace).

Config via environment variables (add to .env):
    SMTP_HOST=smtp.gmail.com
    SMTP_PORT=587
    SMTP_USER=noreply@midfloridasurgical.com
    SMTP_PASS=xxxx xxxx xxxx xxxx   ← 16-char Google App Password
    SMTP_FROM_NAME=Mid Florida Surgical
    SMTP_ENABLED=true                ← set false to log-only in dev

Usage:
    from app.services.email_service import send_magic_link_email
    send_magic_link_email(
        to_email="surgeon@example.com",
        to_name="Dr. Smith",
        magic_url="https://rvu.midfloridasurgical.com/register?token=...",
        app_name="RVU Estimator",
    )
"""
from __future__ import annotations

import base64
import io
import logging
import os
import smtplib
import textwrap
from email.mime.image import MIMEImage
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import qrcode
from qrcode.image.pil import PilImage

log = logging.getLogger(__name__)

# ── Config ────────────────────────────────────────────────────────────────────
SMTP_HOST      = os.environ.get("SMTP_HOST",      "smtp.gmail.com")
SMTP_PORT      = int(os.environ.get("SMTP_PORT",  "587"))
SMTP_USER      = os.environ.get("SMTP_USER",      "")
SMTP_PASS      = os.environ.get("SMTP_PASS",      "")
SMTP_FROM_NAME = os.environ.get("SMTP_FROM_NAME", "Mid Florida Surgical")
SMTP_ENABLED   = os.environ.get("SMTP_ENABLED",   "true").lower() == "true"


# ── QR code builder ───────────────────────────────────────────────────────────
def _make_qr_png(url: str) -> bytes:
    qr = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=8,
        border=3,
    )
    qr.add_data(url)
    qr.make(fit=True)
    img: PilImage = qr.make_image(fill_color="black", back_color="white")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _qr_data_uri(url: str) -> str:
    return "data:image/png;base64," + base64.b64encode(_make_qr_png(url)).decode()


# ── Core send ────────────────────────────────────────────────────────────────
def _send(msg: MIMEMultipart) -> None:
    if not SMTP_ENABLED:
        log.info("[email_service] SMTP_ENABLED=false — would send to %s", msg["To"])
        return
    if not SMTP_USER or not SMTP_PASS:
        log.error("[email_service] SMTP_USER/SMTP_PASS not set — cannot send email")
        return
    with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as s:
        s.ehlo()
        s.starttls()
        s.ehlo()
        s.login(SMTP_USER, SMTP_PASS)
        s.send_message(msg)
    log.info("[email_service] sent → %s subject=%r", msg["To"], msg["Subject"])


# ── Magic-link email ──────────────────────────────────────────────────────────
_MAGIC_HTML = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
  *{{box-sizing:border-box;margin:0;padding:0}}
  body{{background:#f5f5f7;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;
        color:#1c1c1e;padding:32px 16px}}
  .wrap{{max-width:520px;margin:0 auto;background:#fff;border-radius:16px;
         overflow:hidden;box-shadow:0 4px 24px rgba(0,0,0,.08)}}
  .header{{background:#1a2540;padding:28px 32px;text-align:center}}
  .header h1{{color:#fff;font-size:20px;font-weight:700;margin-bottom:4px}}
  .header p{{color:#94a3b8;font-size:13px}}
  .body{{padding:32px}}
  .greeting{{font-size:17px;font-weight:600;margin-bottom:12px}}
  .copy{{font-size:14px;color:#475569;line-height:1.6;margin-bottom:24px}}
  .btn{{display:block;background:#007aff;color:#fff;text-decoration:none;
        font-size:16px;font-weight:700;text-align:center;padding:15px 24px;
        border-radius:12px;margin-bottom:28px}}
  .divider{{display:flex;align-items:center;gap:12px;color:#94a3b8;
            font-size:12px;margin-bottom:24px}}
  .divider::before,.divider::after{{content:'';flex:1;height:1px;background:#e2e8f0}}
  .qr-wrap{{text-align:center;margin-bottom:24px}}
  .qr-wrap img{{width:180px;height:180px;border:1px solid #e2e8f0;border-radius:12px;padding:8px}}
  .qr-label{{font-size:12px;color:#94a3b8;margin-top:8px}}
  .link-box{{background:#f8fafc;border:1px solid #e2e8f0;border-radius:8px;
             padding:10px 14px;font-size:11px;color:#64748b;word-break:break-all;
             margin-bottom:24px}}
  .expiry{{font-size:12px;color:#94a3b8;margin-bottom:20px}}
  .footer{{background:#f8fafc;border-top:1px solid #e2e8f0;padding:18px 32px;
           font-size:11px;color:#94a3b8;text-align:center;line-height:1.6}}
</style>
</head>
<body>
<div class="wrap">
  <div class="header">
    <h1>{app_name}</h1>
    <p>Mid Florida Surgical</p>
  </div>
  <div class="body">
    <div class="greeting">Hi {to_name} 👋</div>
    <p class="copy">
      Your access link is ready. Tap the button below on your phone to register
      this device — or scan the QR code if you're reading this on a desktop.
    </p>

    <!-- Big tap button -->
    <a href="{magic_url}" class="btn">Open {app_name} →</a>

    <!-- QR code for desktop readers -->
    <div class="divider">or scan with your phone camera</div>
    <div class="qr-wrap">
      <img src="cid:qrcode" alt="QR code">
      <div class="qr-label">Point your phone camera here</div>
    </div>

    <!-- Raw link fallback -->
    <p class="copy" style="font-size:12px;margin-bottom:8px">
      Can't tap or scan? Copy this link into your phone's browser:
    </p>
    <div class="link-box">{magic_url}</div>

    <p class="expiry">⏱ This link expires in {expiry_hours} hours and can only be used once.</p>
  </div>
  <div class="footer">
    Mid Florida Surgical · This email was sent by {app_name}<br>
    If you didn't expect this, you can safely ignore it.
  </div>
</div>
</body>
</html>
"""

_MAGIC_TEXT = """\
Hi {to_name},

Your {app_name} access link:

  {magic_url}

Open this link on your phone to register your device.
It expires in {expiry_hours} hours and can only be used once.

If you didn't expect this, you can safely ignore it.
— Mid Florida Surgical
"""


def send_magic_link_email(
    *,
    to_email: str,
    to_name: str,
    magic_url: str,
    app_name: str = "RVU Estimator",
    expiry_hours: int = 72,
) -> None:
    """Send a magic-link email with an embedded QR code.

    Raises nothing — logs errors so the API caller isn't blocked by email failures.
    """
    try:
        qr_png = _make_qr_png(magic_url)

        msg = MIMEMultipart("related")
        msg["Subject"] = f"Your {app_name} access link"
        msg["From"]    = f"{SMTP_FROM_NAME} <{SMTP_USER}>"
        msg["To"]      = f"{to_name} <{to_email}>"
        msg["Reply-To"] = SMTP_USER

        alt = MIMEMultipart("alternative")
        msg.attach(alt)

        plain = _MAGIC_TEXT.format(
            to_name=to_name, app_name=app_name,
            magic_url=magic_url, expiry_hours=expiry_hours,
        )
        html = _MAGIC_HTML.format(
            to_name=to_name, app_name=app_name,
            magic_url=magic_url, expiry_hours=expiry_hours,
        )
        alt.attach(MIMEText(plain, "plain"))
        alt.attach(MIMEText(html,  "html"))

        # Embed QR as inline image (Content-ID: qrcode)
        qr_img = MIMEImage(qr_png, _subtype="png")
        qr_img.add_header("Content-ID",          "<qrcode>")
        qr_img.add_header("Content-Disposition", "inline", filename="qrcode.png")
        msg.attach(qr_img)

        _send(msg)
    except Exception:
        log.exception("[email_service] failed to send magic link to %s", to_email)


# ── Generic notification email ────────────────────────────────────────────────
def send_notification_email(
    *,
    to_email: str,
    to_name: str,
    subject: str,
    body_html: str,
    body_text: str,
) -> None:
    """Send a plain notification (no QR). body_html/body_text are the full content."""
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"]    = f"{SMTP_FROM_NAME} <{SMTP_USER}>"
        msg["To"]      = f"{to_name} <{to_email}>"
        msg.attach(MIMEText(body_text, "plain"))
        msg.attach(MIMEText(body_html,  "html"))
        _send(msg)
    except Exception:
        log.exception("[email_service] failed to send notification to %s", to_email)
