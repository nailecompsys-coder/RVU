"""Registration (magic link), staff OTP, and portal login — JSON + httpOnly cookies."""
from __future__ import annotations

import hashlib
import os
import secrets
from datetime import datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.auth import (
    create_admin_token,
    create_or_refresh_surgeon_device_session,
    create_surgeon_session_token,
    generate_magic_link_token,
    hash_password,
    redeem_magic_link,
    _parse_device_name,
    verify_password,
)
from app.models_identity import RvuAdminUser, RvuStaff, RvuStaffOtp
from app.database import get_db
from app.services import email_service
from app.services.email_service import send_magic_link_email, send_notification_email
from app.services.sms_service import send_sms

from .deps import get_current_staff

_email_executor = ThreadPoolExecutor(max_workers=2)
_OTP_EXPIRE_MINUTES = int(os.environ.get("RVU_OTP_EXPIRE_MINUTES", "10"))
_OTP_DEV_CODE = os.environ.get("RVU_OTP_DEV_CODE", "false").lower() in ("1", "true", "yes")

BASE_URL = os.environ.get("BASE_URL", "https://rvu.midfloridasurgical.com")

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])

# Local dev (http://localhost:5173): set RVU_COOKIE_SECURE=false
_COOKIE_SECURE = os.environ.get("RVU_COOKIE_SECURE", "false").lower() in ("1", "true", "yes")


def _format_us_phone(value: str | None) -> str | None:
    digits = "".join(ch for ch in str(value or "") if ch.isdigit())
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    if not digits:
        return None
    if len(digits) == 10:
        return f"({digits[:3]}) {digits[3:6]}-{digits[6:]}"
    return digits[:32]


def _normalize_staff_type(value: str | None) -> str:
    normalized = str(value or "physician").strip().lower()
    aliases = {
        "surgeon": "physician",
        "doctor": "physician",
        "pa-c": "pa",
        "pac": "pa",
        "physician_assistant": "pa",
        "physician assistant": "pa",
        "admin": "staff",
        "admin_staff": "staff",
        "admin staff": "staff",
    }
    normalized = aliases.get(normalized, normalized)
    return normalized if normalized in {"physician", "pa", "staff"} else "staff"


def _staff_type_for_response(staff: RvuStaff) -> str | None:
    staff_type = str(getattr(staff, "staff_type", "") or "").strip().lower()
    suffix = str(getattr(staff, "suffix", "") or "").strip().lower()
    if staff_type == "staff" and ("pa" in suffix or "physician assistant" in suffix):
        return "pa"
    return getattr(staff, "staff_type", None)


def _device_name_for_response(device_name: str | None, user_agent: str | None) -> str:
    existing = str(device_name or "").strip()
    if existing and existing.lower() not in {"unknown", "unknown device"}:
        return existing
    parsed = _parse_device_name(user_agent or "")
    return parsed if parsed != "Unknown Device" else "Registered device"


def _portal_user_for_staff(db: Session, staff: RvuStaff) -> RvuAdminUser | None:
    if not staff.email:
        return None
    email = staff.email.strip().lower()
    if not email:
        return None
    return db.query(RvuAdminUser).filter(func.lower(RvuAdminUser.email) == email).first()


def _staff_response(db: Session, staff: RvuStaff) -> dict[str, object]:
    portal_user = _portal_user_for_staff(db, staff)
    return {
        "id": staff.id,
        "first_name": staff.first_name,
        "last_name": staff.last_name,
        "full_name": staff.full_name,
        "staff_type": _staff_type_for_response(staff),
        "email": staff.email,
        "phone": staff.phone,
        "suffix": staff.suffix,
        "display_order": staff.display_order,
        "is_active": staff.is_active,
        "portal_user_id": portal_user.id if portal_user else None,
        "portal_username": portal_user.username if portal_user else None,
        "portal_role": portal_user.role if portal_user else None,
        "portal_access": bool(portal_user and portal_user.is_active),
    }


def _default_portal_username(db: Session, staff: RvuStaff, email: str) -> str:
    base = "".join(ch for ch in email.split("@", 1)[0].lower() if ch.isalnum() or ch in ("_", ".", "-")).strip(".-_")
    if not base:
        first = "".join(ch for ch in (staff.first_name or "").lower() if ch.isalnum())
        last = "".join(ch for ch in (staff.last_name or "").lower() if ch.isalnum())
        base = f"{first[:1]}{last}" or f"staff{staff.id}"
    candidate = base[:64]
    suffix = 2
    while db.query(RvuAdminUser).filter(RvuAdminUser.username == candidate).first():
        tail = f"{suffix}"
        candidate = f"{base[:64 - len(tail)]}{tail}"
        suffix += 1
    return candidate


def _apply_portal_access_for_staff(
    db: Session,
    staff: RvuStaff,
    *,
    portal_access: bool | None,
    portal_role: str | None,
    portal_password: str | None,
    current_admin: RvuAdminUser,
) -> None:
    portal_user = _portal_user_for_staff(db, staff)

    if portal_role is not None:
        portal_role = _normalize_role(portal_role)

    if portal_access is True:
        if not staff.email:
            raise HTTPException(status_code=400, detail="Email is required before enabling portal access.")
        email = staff.email.strip().lower()
        if portal_user is None:
            if not portal_password:
                raise HTTPException(status_code=400, detail="Password is required when enabling portal access.")
            portal_user = RvuAdminUser(
                username=_default_portal_username(db, staff, email),
                email=email,
                password_hash=hash_password(portal_password),
                role=portal_role or "admin",
                is_active=True,
            )
            db.add(portal_user)
        else:
            portal_user.is_active = True
            portal_user.email = email
            if portal_role is not None:
                portal_user.role = portal_role
            if portal_password:
                portal_user.password_hash = hash_password(portal_password)
    elif portal_access is False and portal_user is not None:
        if portal_user.id == current_admin.id:
            raise HTTPException(status_code=400, detail="You cannot deactivate your own portal access.")
        others = (
            db.query(RvuAdminUser)
            .filter(RvuAdminUser.is_active == True, RvuAdminUser.id != portal_user.id)  # noqa: E712
            .count()
        )
        if others == 0:
            raise HTTPException(status_code=400, detail="Cannot deactivate the last active portal user.")
        portal_user.is_active = False
    elif portal_user is not None:
        if portal_role is not None:
            portal_user.role = portal_role
        if portal_password:
            portal_user.password_hash = hash_password(portal_password)


class RegisterBody(BaseModel):
    token: str = Field(..., min_length=10)


class StaffOtpRequestBody(BaseModel):
    email: str = Field(..., min_length=3, max_length=255)


class StaffOtpVerifyBody(BaseModel):
    email: str = Field(..., min_length=3, max_length=255)
    code: str = Field(..., min_length=6, max_length=6)


def _normalize_email(email: str) -> str:
    return email.strip().lower()


def _hash_otp_code(code: str) -> str:
    return hashlib.sha256(code.encode()).hexdigest()


def _prune_expired_staff_otps(db: Session) -> None:
    now = datetime.now(timezone.utc)
    db.query(RvuStaffOtp).filter(RvuStaffOtp.expires_at <= now).delete(synchronize_session=False)


@router.post("/register")
def api_register(body: RegisterBody, request: Request, db: Session = Depends(get_db)):
    ua = request.headers.get("user-agent", "Unknown")
    device = redeem_magic_link(body.token.strip(), ua, db)

    session_token = create_surgeon_session_token(device.id)
    surgeon = db.get(RvuStaff, device.staff_id)
    resp = JSONResponse(
        {
            "ok": True,
            # Return the JWT in the response body so the frontend can store it in
            # localStorage as a fallback for iOS contexts where httponly cookies
            # are isolated (email in-app browser, standalone PWA, etc.).
            "token": session_token,
            "surgeon": {
                "id": surgeon.id,
                "full_name": surgeon.full_name,
                "staff_type": surgeon.staff_type,
                "email": surgeon.email,
            },
        }
    )
    resp.set_cookie(
        "surgeon_token",
        session_token,
        httponly=True,
        secure=_COOKIE_SECURE,
        samesite="lax",
        max_age=365 * 24 * 3600,
        path="/",
    )
    return resp


@router.post("/otp/request")
def staff_request_otp(body: StaffOtpRequestBody, db: Session = Depends(get_db)):
    email = _normalize_email(body.email)
    surgeon = (
        db.query(RvuStaff)
        .filter(func.lower(RvuStaff.email) == email, RvuStaff.is_active == True)  # noqa: E712
        .first()
    )
    dev_code = None
    if surgeon and surgeon.email:
        code = f"{secrets.randbelow(1000000):06d}"
        if _OTP_DEV_CODE:
            code = "123456"
            dev_code = code
        expires_at = datetime.now(timezone.utc) + timedelta(minutes=_OTP_EXPIRE_MINUTES)
        _prune_expired_staff_otps(db)
        existing = db.query(RvuStaffOtp).filter(RvuStaffOtp.email == email).first()
        if existing:
            existing.staff_id = surgeon.id
            existing.code_hash = _hash_otp_code(code)
            existing.expires_at = expires_at
        else:
            db.add(
                RvuStaffOtp(
                    email=email,
                    staff_id=surgeon.id,
                    code_hash=_hash_otp_code(code),
                    expires_at=expires_at,
                )
            )
        db.commit()
        sms_sent = False
        if surgeon.phone:
            sms_sent = send_sms(
                surgeon.phone,
                (
                    f"RVU Insight code: {code}\n"
                    f"Expires in {_OTP_EXPIRE_MINUTES} min. Do not share."
                ),
            )
        if not sms_sent and email_service.SMTP_ENABLED and email_service.SMTP_USER and email_service.SMTP_PASS:
            _email_executor.submit(
                send_notification_email,
                to_email=surgeon.email,
                to_name=surgeon.full_name or surgeon.email,
                subject="Your RVU Insight login code",
                body_text=(
                    f"Your RVU Insight login code is {code}.\n\n"
                    f"It expires in {_OTP_EXPIRE_MINUTES} minutes.\n"
                    "If you did not request this code, you can ignore this email."
                ),
                body_html=(
                    f"<p>Your <strong>RVU Insight</strong> login code is:</p>"
                    f"<p style='font-size:28px;font-weight:700;letter-spacing:4px'>{code}</p>"
                    f"<p>This code expires in {_OTP_EXPIRE_MINUTES} minutes.</p>"
                    "<p>If you did not request this code, you can ignore this email.</p>"
                ),
            )
    response = {"ok": True, "message": "If that email is registered, a code was sent."}
    if dev_code:
        response["dev_code"] = dev_code
    return response


@router.post("/otp/verify")
def staff_verify_otp(body: StaffOtpVerifyBody, request: Request, db: Session = Depends(get_db)):
    email = _normalize_email(body.email)
    code = body.code.strip()
    now = datetime.now(timezone.utc)
    _prune_expired_staff_otps(db)
    payload = (
        db.query(RvuStaffOtp)
        .filter(
            RvuStaffOtp.email == email,
            RvuStaffOtp.code_hash == _hash_otp_code(code),
            RvuStaffOtp.expires_at > now,
        )
        .first()
    )
    if not payload:
        raise HTTPException(status_code=400, detail="Invalid or expired code.")
    surgeon_id = int(payload.staff_id)
    db.delete(payload)
    db.commit()

    surgeon = db.get(RvuStaff, surgeon_id)
    if not surgeon or not surgeon.is_active:
        raise HTTPException(status_code=400, detail="Staff account inactive.")

    ua = request.headers.get("user-agent", "Unknown")
    device = create_or_refresh_surgeon_device_session(surgeon.id, ua, db)
    session_token = create_surgeon_session_token(device.id)
    resp = JSONResponse(
        {
            "ok": True,
            "token": session_token,
            "surgeon": {
                "id": surgeon.id,
                "full_name": surgeon.full_name,
                "staff_type": surgeon.staff_type,
                "email": surgeon.email,
            },
        }
    )
    resp.set_cookie(
        "surgeon_token",
        session_token,
        httponly=True,
        secure=_COOKIE_SECURE,
        samesite="lax",
        max_age=365 * 24 * 3600,
        path="/",
    )
    return resp


@router.get("/me")
def api_me(auth: tuple[RvuStaff, object] = Depends(get_current_staff)):
    surgeon, _device = auth
    return {
        "id": surgeon.id,
        "full_name": surgeon.full_name,
        "staff_type": surgeon.staff_type,
        "email": surgeon.email,
        "suffix": surgeon.suffix,
    }


@router.post("/logout")
def api_logout_staff():
    resp = JSONResponse({"ok": True})
    resp.delete_cookie("surgeon_token", path="/")
    return resp


class PortalLoginBody(BaseModel):
    username: str
    password: str


@router.post("/portal/login")
def portal_login(body: PortalLoginBody, db: Session = Depends(get_db)):
    admin = (
        db.query(RvuAdminUser)
        .filter(
            (RvuAdminUser.username == body.username.strip().lower())
            | (RvuAdminUser.email == body.username.strip().lower()),
            RvuAdminUser.is_active == True,  # noqa: E712
        )
        .first()
    )
    if not admin or not verify_password(body.password, admin.password_hash):
        raise HTTPException(status_code=401, detail="Invalid username or password.")

    token = create_admin_token(admin.id)
    resp = JSONResponse(
        {
            "ok": True,
            "token": token,
            "admin": {"id": admin.id, "username": admin.username, "email": admin.email, "role": admin.role},
        }
    )
    resp.set_cookie(
        "admin_token",
        token,
        httponly=True,
        secure=_COOKIE_SECURE,
        samesite="lax",
        max_age=12 * 3600,
        path="/",
    )
    return resp


def get_current_admin_api(
    request: Request,
    db: Session = Depends(get_db),
):
    from jose import JWTError

    from app.auth import decode_subject_token

    token = request.cookies.get("admin_token")
    if not token:
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header[7:].strip()
    if not token:
        raise HTTPException(status_code=401, detail="Portal login required")
    try:
        admin_id = decode_subject_token(token, "admin")
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid portal session")
    admin = db.get(RvuAdminUser, admin_id)
    if not admin or not admin.is_active:
        raise HTTPException(status_code=401, detail="Invalid portal session")
    return admin


@router.get("/portal/me")
def portal_me(admin: RvuAdminUser = Depends(get_current_admin_api)):
    return {"id": admin.id, "username": admin.username, "email": admin.email, "role": admin.role}


@router.post("/portal/logout")
def portal_logout():
    resp = JSONResponse({"ok": True})
    resp.delete_cookie("admin_token", path="/")
    return resp


# ── Portal user management (username / password office accounts) ───────────────

class PortalUserCreateBody(BaseModel):
    username: str = Field(..., min_length=2, max_length=64)
    email: str = Field(..., min_length=3, max_length=255)
    password: str = Field(..., min_length=8, max_length=128)
    role: str = Field(default="admin")


class PortalUserPatchBody(BaseModel):
    email: str | None = None
    password: str | None = Field(None, min_length=8, max_length=128)
    role: str | None = None
    is_active: bool | None = None


def _normalize_role(role: str) -> str:
    r = (role or "admin").strip().lower()
    if r not in ("admin", "superadmin"):
        raise HTTPException(status_code=400, detail="role must be admin or superadmin")
    return r


@router.get("/portal/users")
def portal_users_list(
    db: Session = Depends(get_db),
    _admin: RvuAdminUser = Depends(get_current_admin_api),
):
    users = db.query(RvuAdminUser).order_by(RvuAdminUser.username).all()
    return {
        "users": [
            {
                "id": u.id,
                "username": u.username,
                "email": u.email,
                "role": u.role,
                "is_active": u.is_active,
                "created_at": u.created_at.isoformat() if u.created_at else None,
            }
            for u in users
        ]
    }


@router.post("/portal/users")
def portal_users_create(
    body: PortalUserCreateBody,
    db: Session = Depends(get_db),
    _admin: RvuAdminUser = Depends(get_current_admin_api),
):
    un = body.username.strip().lower()
    em = body.email.strip().lower()
    if db.query(RvuAdminUser).filter(RvuAdminUser.username == un).first():
        raise HTTPException(status_code=409, detail="Username already taken")
    if db.query(RvuAdminUser).filter(RvuAdminUser.email == em).first():
        raise HTTPException(status_code=409, detail="Email already in use")
    role = _normalize_role(body.role)
    u = RvuAdminUser(
        username=un,
        email=em,
        password_hash=hash_password(body.password),
        role=role,
        is_active=True,
    )
    db.add(u)
    db.commit()
    db.refresh(u)
    return {
        "id": u.id,
        "username": u.username,
        "email": u.email,
        "role": u.role,
        "is_active": u.is_active,
        "created_at": u.created_at.isoformat() if u.created_at else None,
    }


@router.patch("/portal/users/{user_id}")
def portal_users_patch(
    user_id: int,
    body: PortalUserPatchBody,
    db: Session = Depends(get_db),
    admin: RvuAdminUser = Depends(get_current_admin_api),
):
    u = db.get(RvuAdminUser, user_id)
    if not u:
        raise HTTPException(status_code=404, detail="User not found")

    if body.email is not None:
        em = body.email.strip().lower()
        dup = db.query(RvuAdminUser).filter(RvuAdminUser.email == em, RvuAdminUser.id != user_id).first()
        if dup:
            raise HTTPException(status_code=409, detail="Email already in use")
        u.email = em

    if body.password is not None:
        u.password_hash = hash_password(body.password)

    if body.role is not None:
        u.role = _normalize_role(body.role)

    if body.is_active is not None:
        if body.is_active is False and u.id == admin.id:
            raise HTTPException(status_code=400, detail="You cannot deactivate your own account")
        if body.is_active is False:
            others = (
                db.query(RvuAdminUser)
                .filter(RvuAdminUser.is_active == True, RvuAdminUser.id != u.id)  # noqa: E712
                .count()
            )
            if others == 0:
                raise HTTPException(status_code=400, detail="Cannot deactivate the last active portal user")
        u.is_active = body.is_active

    db.commit()
    db.refresh(u)
    return {
        "id": u.id,
        "username": u.username,
        "email": u.email,
        "role": u.role,
        "is_active": u.is_active,
        "created_at": u.created_at.isoformat() if u.created_at else None,
    }


@router.delete("/portal/users/{user_id}")
def portal_users_delete(
    user_id: int,
    db: Session = Depends(get_db),
    admin: RvuAdminUser = Depends(get_current_admin_api),
):
    """Soft-delete (deactivate) a portal user."""
    u = db.get(RvuAdminUser, user_id)
    if not u:
        raise HTTPException(status_code=404, detail="User not found")
    if u.id == admin.id:
        raise HTTPException(status_code=400, detail="You cannot delete your own account")
    others = (
        db.query(RvuAdminUser)
        .filter(RvuAdminUser.is_active == True, RvuAdminUser.id != u.id)  # noqa: E712
        .count()
    )
    if others == 0:
        raise HTTPException(status_code=400, detail="Cannot remove the last active portal user")
    u.is_active = False
    db.commit()
    return {"ok": True}


# ── Admin: generate + email a magic link ────────────────────────────────────

def _make_qr_b64(url: str) -> str:
    """Return a base64-encoded PNG of a QR code for *url*."""
    import base64
    import io
    import qrcode  # type: ignore

    qr = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=8,
        border=3,
    )
    qr.add_data(url)
    qr.make(fit=True)
    img = qr.make_image(fill_color="#14305A", back_color="white")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode()


class SendMagicLinkBody(BaseModel):
    surgeon_id: int


@router.post("/admin/send-magic-link")
def send_magic_link(
    body: SendMagicLinkBody,
    db: Session = Depends(get_db),
    admin: RvuAdminUser = Depends(get_current_admin_api),
):
    """Generate a fresh magic link + QR code. Emails it if the surgeon has an address."""
    surgeon = db.get(RvuStaff, body.surgeon_id)
    if not surgeon or not surgeon.is_active:
        raise HTTPException(status_code=404, detail="RvuStaff not found or inactive")

    magic_url = generate_magic_link_token(surgeon.id, db, BASE_URL)
    qr_b64 = _make_qr_b64(magic_url)

    emailed = False
    if surgeon.email:
        _email_executor.submit(
            send_magic_link_email,
            to_email=surgeon.email,
            to_name=surgeon.full_name or surgeon.email,
            magic_url=magic_url,
            app_name="RVU Estimator",
            expiry_hours=int(os.environ.get("MAGIC_LINK_EXPIRE_HOURS", "168")),
        )
        emailed = True

    return {
        "ok": True,
        "surgeon": surgeon.full_name,
        "email": surgeon.email,
        "magic_url": magic_url,
        "qr_b64": qr_b64,
        "emailed": emailed,
    }


@router.get("/admin/staff")
def list_staff(
    db: Session = Depends(get_db),
    admin: RvuAdminUser = Depends(get_current_admin_api),
    include_inactive: bool = False,
):
    """Return surgeons/staff."""
    q = db.query(RvuStaff)
    if not include_inactive:
        q = q.filter(RvuStaff.is_active == True)  # noqa: E712
    from sqlalchemy import case

    physician_first = case(
        (RvuStaff.staff_type.is_(None), 2),
        (RvuStaff.staff_type.ilike("physician"), 0),
        (RvuStaff.staff_type.ilike("pa"), 1),
        else_=2,
    )
    surgeons = (
        q.order_by(RvuStaff.display_order.is_(None), RvuStaff.display_order, physician_first, RvuStaff.last_name, RvuStaff.first_name).all()
    )
    return {
        "staff": [_staff_response(db, s) for s in surgeons]
    }


# ── Staff: create ────────────────────────────────────────────────────────────

class StaffCreateBody(BaseModel):
    first_name: str
    last_name: str
    suffix: str | None = None
    staff_type: str = "physician"
    email: str | None = None
    phone: str | None = Field(None, max_length=32)
    display_order: int | None = None
    portal_access: bool | None = None
    portal_role: str | None = None
    portal_password: str | None = Field(None, min_length=8, max_length=128)


@router.post("/admin/staff")
def create_staff(
    body: StaffCreateBody,
    db: Session = Depends(get_db),
    admin: RvuAdminUser = Depends(get_current_admin_api),
):
    """Add a new surgeon/staff member."""
    clean_email = body.email.strip().lower() if body.email else None
    if clean_email:
        existing = db.query(RvuStaff).filter(func.lower(RvuStaff.email) == clean_email).first()
        if existing:
            raise HTTPException(status_code=409, detail="A staff member with that email already exists.")
    s = RvuStaff(
        first_name=body.first_name.strip(),
        last_name=body.last_name.strip(),
        suffix=body.suffix.strip() if body.suffix else None,
        staff_type=_normalize_staff_type(body.staff_type),
        email=clean_email,
        phone=_format_us_phone(body.phone),
        display_order=body.display_order,
        is_active=True,
    )
    db.add(s)
    db.flush()
    _apply_portal_access_for_staff(
        db,
        s,
        portal_access=body.portal_access,
        portal_role=body.portal_role,
        portal_password=body.portal_password,
        current_admin=admin,
    )
    db.commit()
    db.refresh(s)
    return _staff_response(db, s)


# ── Staff: edit ──────────────────────────────────────────────────────────────

class StaffPatchBody(BaseModel):
    first_name: str | None = None
    last_name: str | None = None
    suffix: str | None = None
    staff_type: str | None = None
    email: str | None = None
    phone: str | None = Field(None, max_length=32)
    display_order: int | None = None
    is_active: bool | None = None
    portal_access: bool | None = None
    portal_role: str | None = None
    portal_password: str | None = Field(None, min_length=8, max_length=128)


@router.patch("/admin/staff/{surgeon_id}")
def patch_staff(
    surgeon_id: int,
    body: StaffPatchBody,
    db: Session = Depends(get_db),
    admin: RvuAdminUser = Depends(get_current_admin_api),
):
    """Update a surgeon/staff record."""
    s = db.get(RvuStaff, surgeon_id)
    if not s:
        raise HTTPException(status_code=404, detail="Staff member not found")
    portal_user = _portal_user_for_staff(db, s)

    if body.first_name is not None:
        s.first_name = body.first_name.strip()
    if body.last_name is not None:
        s.last_name = body.last_name.strip()
    if body.suffix is not None:
        s.suffix = body.suffix.strip() or None
    if body.staff_type is not None:
        s.staff_type = _normalize_staff_type(body.staff_type)
    if body.email is not None:
        clean_email = body.email.strip().lower() or None
        if clean_email:
            dup = db.query(RvuStaff).filter(func.lower(RvuStaff.email) == clean_email, RvuStaff.id != surgeon_id).first()
            if dup:
                raise HTTPException(status_code=409, detail="That email is already used by another staff member.")
        s.email = clean_email
        if portal_user is not None:
            if clean_email:
                dup = db.query(RvuAdminUser).filter(RvuAdminUser.email == clean_email, RvuAdminUser.id != portal_user.id).first()
                if dup:
                    raise HTTPException(status_code=409, detail="That email is already used by another portal user.")
                portal_user.email = clean_email
            else:
                portal_user.is_active = False
    if body.phone is not None:
        s.phone = _format_us_phone(body.phone)
    if "display_order" in body.model_fields_set:
        s.display_order = body.display_order
    if body.is_active is not None:
        s.is_active = body.is_active
    if (
        "portal_access" in body.model_fields_set
        or body.portal_role is not None
        or body.portal_password is not None
    ):
        _apply_portal_access_for_staff(
            db,
            s,
            portal_access=body.portal_access if "portal_access" in body.model_fields_set else None,
            portal_role=body.portal_role,
            portal_password=body.portal_password,
            current_admin=admin,
        )

    db.commit()
    db.refresh(s)
    return _staff_response(db, s)


# ── Portal: device registry ──────────────────────────────────────────────────

@router.get("/admin/devices")
def list_devices(
    db: Session = Depends(get_db),
    admin: RvuAdminUser = Depends(get_current_admin_api),
):
    """Return one device row per staff member (most recently seen)."""
    from app.models_identity import RvuStaffDevice

    devices = (
        db.query(RvuStaffDevice)
        .order_by(RvuStaffDevice.last_seen.desc().nulls_last(), RvuStaffDevice.id.desc())
        .all()
    )
    seen_staff: set[int] = set()
    out = []
    for d in devices:
        if d.staff_id in seen_staff:
            continue
        seen_staff.add(d.staff_id)
        surgeon = db.get(RvuStaff, d.staff_id)
        out.append({
            "id": d.id,
            "surgeon_id": d.staff_id,
            "surgeon_name": surgeon.full_name if surgeon else "Unknown",
            "display_order": surgeon.display_order if surgeon else None,
            "device_name": _device_name_for_response(d.device_name, d.user_agent),
            "user_agent": d.user_agent,
            "registered_at": d.registered_at.isoformat() if d.registered_at else None,
            "last_seen": d.last_seen.isoformat() if d.last_seen else None,
            "is_active": d.is_active,
        })
    out.sort(
        key=lambda row: (
            row["display_order"] if isinstance(row.get("display_order"), int) else 9999,
            str(row.get("surgeon_name") or "").lower(),
        )
    )
    return {"devices": out}


@router.patch("/admin/devices/{device_id}")
def patch_device(
    device_id: int,
    body: dict,
    db: Session = Depends(get_db),
    admin: RvuAdminUser = Depends(get_current_admin_api),
):
    from app.models_identity import RvuStaffDevice
    device = db.get(RvuStaffDevice, device_id)
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")
    if "is_active" in body:
        device.is_active = bool(body["is_active"])
    db.commit()
    surgeon = db.get(RvuStaff, device.staff_id)
    return {
        "id": device.id,
        "surgeon_id": device.staff_id,
        "surgeon_name": surgeon.full_name if surgeon else "Unknown",
        "display_order": surgeon.display_order if surgeon else None,
        "device_name": _device_name_for_response(device.device_name, device.user_agent),
        "user_agent": device.user_agent,
        "registered_at": device.registered_at.isoformat() if device.registered_at else None,
        "last_seen": device.last_seen.isoformat() if device.last_seen else None,
        "is_active": device.is_active,
    }
