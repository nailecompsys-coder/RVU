"""RVU scan history and OP-note uploads (PostgreSQL).

Charge capture: `line_items` JSON is the canonical per-line billing snapshot after OCR
enrichment and surgeon edits (CPT, provider, per-line DOS, RVU/payment components).
`cpts` JSON is an ordered denormalized list of surgeon-line CPT codes — it must match
the surgeon rows in `line_items` (duplicates allowed for multi-day / same-code lines).
`scan_status` pending vs verified gates inclusion in compensation rollups.
"""
from datetime import datetime

from sqlalchemy import Boolean, Column, Date, DateTime, Float, ForeignKey, Index, Integer, LargeBinary, String, Text, func
from sqlalchemy.orm import relationship

from app.database import Base


class RvuScan(Base):
    __tablename__ = "rvu_scans"
    __table_args__ = (
        Index("ix_rvu_scans_surgeon_service_date", "surgeon_id", "service_date"),
        Index("ix_rvu_scans_surgeon_scan_status", "surgeon_id", "scan_status"),
        Index("ix_rvu_scans_surgeon_request_id", "surgeon_id", "client_request_id"),
    )

    id = Column(Integer, primary_key=True)
    surgeon_id = Column(Integer, ForeignKey("rvu_staff.id"), nullable=False)
    scanned_at = Column(DateTime, server_default=func.now())
    cpts = Column(Text)
    locality_num = Column(String(10))
    locality_name = Column(String(100))
    facility = Column(Boolean, default=False)
    total_rvu = Column(Float)
    total_payment = Column(Float)
    cf = Column(Float)
    ai_model = Column(String(64))
    image_kb = Column(Integer)
    elapsed_secs = Column(Float)
    service_date = Column(Date, nullable=True)
    patient_name = Column(String(255), nullable=True)
    mrn = Column(String(64), nullable=True)
    line_items = Column(Text, nullable=True)
    image_data = Column(LargeBinary, nullable=True)
    scan_status = Column(String(32), nullable=False, default="verified")
    main_cpt = Column(String(32), nullable=True)
    main_cpt_status = Column(String(16), nullable=True)
    review_reason = Column(String(255), nullable=True)
    client_request_id = Column(String(128), nullable=True)

    surgeon = relationship("RvuStaff")


class RvuUserSettings(Base):
    __tablename__ = "rvu_user_settings"

    id = Column(Integer, primary_key=True)
    surgeon_id = Column(Integer, ForeignKey("rvu_staff.id"), nullable=False, unique=True)
    default_facility = Column(Boolean, nullable=False, default=True)
    cms_locality_num = Column(String(10), nullable=False, default="99")
    cf = Column(Float, nullable=False, default=41.0)
    show_estimated_dollars = Column(Boolean, nullable=False, default=True)
    auto_suggest_from_scan = Column(Boolean, nullable=False, default=True)
    cloud_sync_enabled = Column(Boolean, nullable=False, default=True)

    surgeon = relationship("RvuStaff")


class RvuOpNote(Base):
    """Operative note / procedure photo captured by clinical staff; text via vision model."""

    __tablename__ = "rvu_op_notes"

    id = Column(Integer, primary_key=True)
    surgeon_id = Column(Integer, ForeignKey("rvu_staff.id"), nullable=False)
    scanned_at = Column(DateTime, server_default=func.now())
    image_data = Column(LargeBinary, nullable=True)
    image_kb = Column(Integer, default=0)
    extracted_text = Column(Text, nullable=True)
    ai_model = Column(String(64), nullable=True)
    elapsed_secs = Column(Float, nullable=True)

    surgeon = relationship("RvuStaff")
