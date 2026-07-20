"""Runtime switches for retaining uploaded clinical images.

Charge-capture images are intentionally never retained in the database.
They may be sent to OCR at capture time, but only reviewed billing data is
stored afterward. This avoids large BYTEA payloads that previously made
history and portal scan lists slow on mobile and admin.

Do NOT re-enable charge-scan image storage without a separate thumbnail
pipeline, lazy image endpoints, and size caps. OP-note image retention
remains an explicit deployment switch because that workflow is managed
separately.
"""
from __future__ import annotations

import os


def _env_flag(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in ("1", "true", "yes")


def charge_scan_images_enabled() -> bool:
    """Always off — charge images are OCR-transient only (performance)."""
    return False


def op_note_images_enabled() -> bool:
    return _env_flag("RVU_STORE_OP_NOTE_IMAGES")
