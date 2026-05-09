"""FastAPI dependencies — JSON 401 for SPA (no HTML redirects)."""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import Cookie, Depends, HTTPException, Request, status
from jose import JWTError, jwt
from sqlalchemy.orm import Session

from app.auth import ALGORITHM, SECRET_KEY
from app.models_identity import RvuStaff, RvuStaffDevice
from app.database import get_db


def get_current_staff(
    request: Request,
    surgeon_token: str | None = Cookie(default=None),
    db: Session = Depends(get_db),
) -> tuple[RvuStaff, RvuStaffDevice]:
    # Cookie first; fall back to Authorization: Bearer header (needed for iOS
    # standalone / in-app-browser contexts where httponly cookies are isolated).
    token = surgeon_token or request.cookies.get("surgeon_token")
    if not token:
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header[7:].strip()
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not signed in. Open your magic link to register this device.",
        )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        if payload.get("type") != "surgeon":
            raise HTTPException(status_code=401, detail="Invalid session")
        device_id = int(payload["sub"])
    except (JWTError, ValueError, KeyError):
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
