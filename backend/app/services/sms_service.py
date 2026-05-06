"""
SMS service via TextBelt.
https://textbelt.com - buy credits, no carrier registration required.

Config (.env):
    TEXTBELT_KEY=your_key_here
"""

from __future__ import annotations

import logging
import os

import requests

log = logging.getLogger(__name__)

TEXTBELT_KEY = os.environ.get("TEXTBELT_KEY", "").strip()
TEXTBELT_URL = "https://textbelt.com/text"


def send_sms(phone: str, message: str) -> bool:
    """Send an SMS via TextBelt. Returns True on success, False on failure."""
    digits = "".join(c for c in (phone or "") if c.isdigit())
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    if len(digits) != 10:
        log.error("[sms_service] invalid phone number: %r", phone)
        return False
    if not TEXTBELT_KEY:
        log.error("[sms_service] TEXTBELT_KEY not set")
        return False

    try:
        resp = requests.post(
            TEXTBELT_URL,
            data={"phone": digits, "message": message, "key": TEXTBELT_KEY},
            timeout=10,
        )
        result = resp.json()
        if result.get("success"):
            log.info(
                "[sms_service] sent to %s (quota remaining: %s)",
                digits,
                result.get("quotaRemaining"),
            )
            return True
        log.error("[sms_service] failed to send to %s: %s", digits, result.get("error"))
        return False
    except Exception:
        log.exception("[sms_service] exception sending to %s", phone)
        return False
