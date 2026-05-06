"""
Models for the RVU app.
Surgeon / MagicLink / SurgeonDevice are read from cal's existing tables.
RvuScan is the only new table — added to cal's DB on startup.
"""
from datetime import datetime
from sqlalchemy import (
    Boolean, Column, DateTime, Float, ForeignKey,
    Integer, String, Text, func,
)
from sqlalchemy.orm import relationship
from .database import Base


# ── Read-only mirrors of cal tables (no create_all for these) ────────────────

class Surgeon(Base):
    __tablename__ = "surgeons"
    __table_args__ = {"extend_existing": True}
    id = Column(Integer, primary_key=True)
    first_name = Column(String(64))
    last_name = Column(String(64))
    email = Column(String(255))
    specialty = Column(String(128))
    suffix = Column(String(32))
    is_active = Column(Boolean, default=True)

    @property
    def full_name(self):
        return f"{self.first_name or ''} {self.last_name or ''}".strip()


class MagicLink(Base):
    __tablename__ = "magic_links"
    __table_args__ = {"extend_existing": True}
    id = Column(Integer, primary_key=True)
    surgeon_id = Column(Integer, ForeignKey("surgeons.id"))
    token_hash = Column(String(255), unique=True)
    expires_at = Column(DateTime)
    used_at = Column(DateTime)
    created_at = Column(DateTime, server_default=func.now())
    surgeon = relationship("Surgeon")


class SurgeonDevice(Base):
    __tablename__ = "surgeon_devices"
    __table_args__ = {"extend_existing": True}
    id = Column(Integer, primary_key=True)
    surgeon_id = Column(Integer, ForeignKey("surgeons.id"))
    device_name = Column(String(128))
    user_agent = Column(Text)
    token_hash = Column(String(255), unique=True)
    registered_at = Column(DateTime, server_default=func.now())
    last_seen = Column(DateTime)
    is_active = Column(Boolean, default=True)
    surgeon = relationship("Surgeon")


# ── New table owned by RVU app ───────────────────────────────────────────────

class RvuScan(Base):
    __tablename__ = "rvu_scans"
    id = Column(Integer, primary_key=True)
    surgeon_id = Column(Integer, ForeignKey("surgeons.id"), nullable=False)
    scanned_at = Column(DateTime, server_default=func.now())
    cpts = Column(Text)           # JSON array e.g. '["99223","27447"]'
    locality_num = Column(String(10))
    locality_name = Column(String(100))
    facility = Column(Boolean, default=False)
    total_rvu = Column(Float)
    total_payment = Column(Float)
    cf = Column(Float)
    ai_model = Column(String(64))
    image_kb = Column(Integer)
    elapsed_secs = Column(Float)

    surgeon = relationship("Surgeon")
