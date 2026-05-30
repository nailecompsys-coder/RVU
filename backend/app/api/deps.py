"""FastAPI dependencies — JSON 401 for SPA (no HTML redirects)."""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import Cookie, Depends, HTTPException, Request, status
from jose import JWTError
from sqlalchemy.orm import Session

from app.auth import decode_subject_token
from app.models_identity import RvuStaff, RvuStaffDevice
from app.database import get_db


def get_current_staff(
    request: Request,
    surgeon_token: str | None = Cookie(default=None),
    db: Session = Depends(get_db),
) -> tuple[RvuStaff, RvuStaffDevice]:
    # Native/mobile clients can carry an old httponly cookie from a prior account.
    # Prefer the explicit Bearer token when present; browser cookie remains the fallback.
    auth_header = request.headers.get("Authorization", "")
    token = auth_header[7:].strip() if auth_header.startswith("Bearer ") else None
    if not token:
        token = surgeon_token or request.cookies.get("surgeon_token")
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not signed in. Open your magic link to register this device.",
        )
    try:
        device_id = decode_subject_token(token, "surgeon")
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid session")

    device = db.get(RvuStaffDevice, device_id)
    if not device or not device.is_active:
        raise HTTPException(status_code=401, detail="Device session revoked")

    device.last_seen = datetime.now(timezone.utc)
    db.commit()

    staff = db.get(RvuStaff, device.staff_id)
    if not staff or not staff.is_active:
        raise HTTPException(status_code=401, detail="Staff account inactive")

    return staff, device
