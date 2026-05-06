import hashlib
import os
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import Cookie, Depends, HTTPException, Request, status
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy import desc
from sqlalchemy.orm import Session

from app.database import get_db
from app.cal_models import AdminUser, MagicLink, Surgeon, SurgeonDevice

SECRET_KEY = os.environ["SECRET_KEY"]
ALGORITHM = "HS256"
ADMIN_TOKEN_EXPIRE_HOURS = 12
SURGEON_TOKEN_EXPIRE_DAYS = 365  # device tokens are long-lived
MAGIC_LINK_EXPIRE_HOURS = int(os.environ.get("MAGIC_LINK_EXPIRE_HOURS", "168"))  # default 7 days

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


# ── Password helpers ─────────────────────────────────────────────────────────

def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


# ── Admin JWT ────────────────────────────────────────────────────────────────

def create_admin_token(admin_id: int) -> str:
    expire = datetime.now(timezone.utc) + timedelta(hours=ADMIN_TOKEN_EXPIRE_HOURS)
    return jwt.encode({"sub": str(admin_id), "exp": expire, "type": "admin"}, SECRET_KEY, algorithm=ALGORITHM)


def get_current_admin(
    request: Request,
    admin_token: str | None = Cookie(default=None),
    db: Session = Depends(get_db),
) -> AdminUser:
    token = admin_token or request.cookies.get("admin_token")
    if not token:
        raise HTTPException(status_code=302, headers={"Location": "/admin/login"})
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        if payload.get("type") != "admin":
            raise HTTPException(status_code=302, headers={"Location": "/admin/login"})
        admin_id = int(payload["sub"])
    except (JWTError, ValueError):
        raise HTTPException(status_code=302, headers={"Location": "/admin/login"})
    admin = db.get(AdminUser, admin_id)
    if not admin or not admin.is_active:
        raise HTTPException(status_code=302, headers={"Location": "/admin/login"})
    return admin


# ── Magic Link ───────────────────────────────────────────────────────────────

def generate_magic_link_token(surgeon_id: int, db: Session, base_url: str) -> str:
    """Creates a magic link record and returns the full URL."""
    raw_token = secrets.token_urlsafe(48)
    token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
    expires_at = datetime.now(timezone.utc) + timedelta(hours=MAGIC_LINK_EXPIRE_HOURS)

    link = MagicLink(surgeon_id=surgeon_id, token_hash=token_hash, expires_at=expires_at)
    db.add(link)
    db.commit()
    return f"{base_url}/register?token={raw_token}"


def redeem_magic_link(raw_token: str, user_agent: str, db: Session) -> SurgeonDevice:
    """Validate magic link and return the staff device session.

    One active registration per surgeon: refresh the most recently seen device row
    (new token, UA, friendly name) and deactivate older rows so the portal does
    not list multiple devices per person after re-registering.
    """
    token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
    now = datetime.now(timezone.utc)

    link = db.query(MagicLink).filter(
        MagicLink.token_hash == token_hash,
        MagicLink.used_at.is_(None),
        MagicLink.expires_at > now,
    ).first()

    if not link:
        raise HTTPException(status_code=400, detail="Invalid or expired registration link.")

    # Mark link as used (still single-use — prevents replay)
    link.used_at = now

    device = create_or_refresh_surgeon_device_session(link.surgeon_id, user_agent, db)

    # Attach raw token so the caller can return it in the response body
    return device


def create_or_refresh_surgeon_device_session(
    surgeon_id: int,
    user_agent: str,
    db: Session,
) -> SurgeonDevice:
    """Create or refresh the current device session for a surgeon."""
    raw_device_token = secrets.token_urlsafe(64)
    device_token_hash = hashlib.sha256(raw_device_token.encode()).hexdigest()
    device_name = _parse_device_name(user_agent)
    devices = (
        db.query(SurgeonDevice)
        .filter(SurgeonDevice.surgeon_id == surgeon_id)
        .order_by(desc(SurgeonDevice.last_seen), desc(SurgeonDevice.id))
        .all()
    )
    now = datetime.now(timezone.utc)

    if devices:
        device = devices[0]
        device.token_hash = device_token_hash
        device.last_seen = now
        device.is_active = True
        device.user_agent = user_agent
        device.device_name = device_name
        for other in devices[1:]:
            other.is_active = False
    else:
        device = SurgeonDevice(
            surgeon_id=surgeon_id,
            device_name=device_name,
            user_agent=user_agent,
            token_hash=device_token_hash,
            last_seen=now,
        )
        db.add(device)

    db.commit()
    db.refresh(device)

    # Attach raw token so the caller can return it in the response body
    device._raw_token = raw_device_token  # type: ignore[attr-defined]
    return device


def _parse_device_name(ua: str) -> str:
    ua_lower = ua.lower()
    if "iphone" in ua_lower:
        return "iPhone"
    if "ipad" in ua_lower:
        return "iPad"
    if "android" in ua_lower:
        return "Android"
    if "macintosh" in ua_lower or "mac os" in ua_lower:
        return "Mac"
    if "windows" in ua_lower:
        return "Windows PC"
    return "Unknown Device"


# ── Surgeon Device Auth ──────────────────────────────────────────────────────

def create_surgeon_session_token(device_id: int) -> str:
    expire = datetime.now(timezone.utc) + timedelta(days=SURGEON_TOKEN_EXPIRE_DAYS)
    return jwt.encode({"sub": str(device_id), "exp": expire, "type": "surgeon"}, SECRET_KEY, algorithm=ALGORITHM)


def get_current_surgeon(
    request: Request,
    surgeon_token: str | None = Cookie(default=None),
    db: Session = Depends(get_db),
) -> tuple[Surgeon, SurgeonDevice]:
    token = surgeon_token or request.cookies.get("surgeon_token")
    if not token:
        raise HTTPException(status_code=302, headers={"Location": "/surgeon/register"})
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        if payload.get("type") != "surgeon":
            raise HTTPException(status_code=302, headers={"Location": "/surgeon/register"})
        device_id = int(payload["sub"])
    except (JWTError, ValueError):
        raise HTTPException(status_code=302, headers={"Location": "/surgeon/register"})

    device = db.get(SurgeonDevice, device_id)
    if not device or not device.is_active:
        raise HTTPException(status_code=302, headers={"Location": "/surgeon/register"})

    # Update last seen
    device.last_seen = datetime.now(timezone.utc)
    db.commit()

    surgeon = db.get(Surgeon, device.surgeon_id)
    if not surgeon or not surgeon.is_active:
        raise HTTPException(status_code=302, headers={"Location": "/surgeon/register"})

    return surgeon, device
