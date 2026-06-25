"""Runtime switches for retaining uploaded clinical images.

Charge-capture images are always transient: they may be sent to OCR, but the
database stores reviewed billing data only. OP-note image retention remains an
explicit deployment switch because that workflow is managed separately.
"""
from __future__ import annotations

import os


def _env_flag(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in ("1", "true", "yes")


def charge_scan_images_enabled() -> bool:
    return False


def op_note_images_enabled() -> bool:
    return _env_flag("RVU_STORE_OP_NOTE_IMAGES")
