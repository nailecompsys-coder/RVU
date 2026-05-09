"""RVU-owned identity/config ORM models for shadow and post-split runtime.

These models are intentionally inert until the RVU runtime is switched away from
`app.cal_models`. Adding them does not change current production behavior.
"""

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import relationship

from app.database import Base


class RvuAdminUser(Base):
    __tablename__ = "rvu_admin_users"

    id = Column(Integer, primary_key=True)
    username = Column(String(64), unique=True, nullable=False)
    email = Column(String(255), unique=True, nullable=False)
    password_hash = Column(String(255), nullable=False)
    role = Column(String(32), nullable=False, default="admin")
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, server_default=func.now())
    legacy_cal_admin_user_id = Column(Integer, unique=True)


class RvuStaff(Base):
    __tablename__ = "rvu_staff"

    id = Column(Integer, primary_key=True)
    first_name = Column(String(64), nullable=False)
    last_name = Column(String(64), nullable=False)
    specialty = Column(String(128))
    suffix = Column(String(32))
    staff_type = Column(String(16), nullable=False, default="physician")
    email = Column(String(255), unique=True)
    phone = Column(String(32))
    color = Column(String(16), default="#3b82f6")
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, server_default=func.now())
    legacy_cal_surgeon_id = Column(Integer, unique=True)

    devices = relationship("RvuStaffDevice", back_populates="staff", cascade="all, delete-orphan")
    magic_links = relationship("RvuMagicLink", back_populates="staff", cascade="all, delete-orphan")
    scans = relationship("RvuScan", back_populates="surgeon")
    user_settings = relationship("RvuUserSettings", back_populates="surgeon", uselist=False)
    op_notes = relationship("RvuOpNote", back_populates="surgeon")

    def _strip_dr(self, name: str) -> str:
        if not name:
            return name
        stripped = name.strip()
        if stripped.upper().startswith("DR."):
            return stripped[3:].strip()
        if stripped.upper().startswith("DR "):
            return stripped[2:].strip()
        return stripped

    @property
    def full_name(self) -> str:
        first = self._strip_dr(self.first_name or "")
        last = self._strip_dr(self.last_name or "")
        return f"{first} {last}".strip() or f"{self.first_name or ''} {self.last_name or ''}".strip()


class RvuStaffDevice(Base):
    __tablename__ = "rvu_staff_devices"

    id = Column(Integer, primary_key=True)
    staff_id = Column(Integer, ForeignKey("rvu_staff.id"), nullable=False)
    device_name = Column(String(128))
    user_agent = Column(Text)
    token_hash = Column(String(255), unique=True, nullable=False)
    registered_at = Column(DateTime, server_default=func.now())
    last_seen = Column(DateTime)
    is_active = Column(Boolean, nullable=False, default=True)
    legacy_cal_device_id = Column(Integer, unique=True)

    staff = relationship("RvuStaff", back_populates="devices")


class RvuMagicLink(Base):
    __tablename__ = "rvu_magic_links"

    id = Column(Integer, primary_key=True)
    staff_id = Column(Integer, ForeignKey("rvu_staff.id"), nullable=False)
    token_hash = Column(String(255), unique=True, nullable=False)
    expires_at = Column(DateTime, nullable=False)
    used_at = Column(DateTime)
    created_at = Column(DateTime, server_default=func.now())
    legacy_cal_magic_link_id = Column(Integer, unique=True)

    staff = relationship("RvuStaff", back_populates="magic_links")


class RvuRuleConfig(Base):
    __tablename__ = "rvu_rule_configs"

    id = Column(Integer, primary_key=True)
    rule_id = Column(String(64), unique=True, nullable=False)
    enabled = Column(Boolean, nullable=False, default=True)
    config = Column(Text)
