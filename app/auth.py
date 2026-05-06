"""
RVU app auth — accepts cal's surgeon_token cookie directly.
Both apps share SECRET_KEY and the surgical_cal database.
No separate registration or magic link flow needed.
"""
import os
from datetime import datetime, timezone

from fastapi import Cookie, Depends, HTTPException, Request
from jose import JWTError, jwt
from sqlalchemy.orm import Session

from .database import get_db
from .models import Surgeon, SurgeonDevice

SECRET_KEY = os.environ["SECRET_KEY"]
ALGORITHM  = "HS256"
CAL_URL    = os.environ.get("CAL_URL", "https://cal.midfloridasurgical.com")


def get_current_surgeon(
    request: Request,
    surgeon_token: str | None = Cookie(default=None),
    db: Session = Depends(get_db),
) -> tuple[Surgeon, SurgeonDevice]:
    """Accept the same surgeon_token cookie that cal issues (shared parent-domain cookie)."""
    token = surgeon_token or request.cookies.get("surgeon_token")
    if not token:
        raise HTTPException(
            status_code=302,
            headers={"Location": f"{CAL_URL}/surgeon/register"},
        )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        if payload.get("type") != "surgeon":
            raise ValueError("wrong token type")
        device_id = int(payload["sub"])
    except (JWTError, ValueError):
        raise HTTPException(
            status_code=302,
            headers={"Location": f"{CAL_URL}/surgeon/register"},
        )

    device = db.get(SurgeonDevice, device_id)
    if not device or not device.is_active:
        raise HTTPException(
            status_code=302,
            headers={"Location": f"{CAL_URL}/surgeon/register"},
        )

    device.last_seen = datetime.now(timezone.utc)
    db.commit()

    surgeon = db.get(Surgeon, device.surgeon_id)
    if not surgeon or not surgeon.is_active:
        raise HTTPException(
            status_code=302,
            headers={"Location": f"{CAL_URL}/surgeon/register"},
        )

    return surgeon, device
