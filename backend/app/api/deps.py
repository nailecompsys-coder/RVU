"""FastAPI dependencies — JSON 401 for SPA (no HTML redirects)."""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import Cookie, Depends, HTTPException, Request, status
from jose import JWTError, jwt
from sqlalchemy.orm import Session

from app.auth import ALGORITHM, SECRET_KEY
from app.cal_models import Surgeon, SurgeonDevice
from app.database import get_db


def get_current_staff(
    request: Request,
    surgeon_token: str | None = Cookie(default=None),
    db: Session = Depends(get_db),
) -> tuple[Surgeon, SurgeonDevice]:
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

    device = db.get(SurgeonDevice, device_id)
    if not device or not device.is_active:
        raise HTTPException(status_code=401, detail="Device session revoked")

    device.last_seen = datetime.now(timezone.utc)
    db.commit()

    surgeon = db.get(Surgeon, device.surgeon_id)
    if not surgeon or not surgeon.is_active:
        raise HTTPException(status_code=401, detail="Staff account inactive")

    return surgeon, device
