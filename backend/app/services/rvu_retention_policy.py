"""Runtime switches for retaining uploaded clinical images.

Charge and op-note images are transient by default: they may be sent to OCR, but
the database stores extracted charge/text data only. Environment flags exist as
an explicit break-glass path for debugging.
"""
from __future__ import annotations

import os


def _env_flag(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in ("1", "true", "yes")


def charge_scan_images_enabled() -> bool:
    return _env_flag("RVU_STORE_CHARGE_IMAGES")


def op_note_images_enabled() -> bool:
    return _env_flag("RVU_STORE_OP_NOTE_IMAGES")
