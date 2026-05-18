#!/usr/bin/env python3
"""Seed a tiny local RVU dev dataset.

Run from repo root after the backend has initialized tables:
    python3 scripts/seed_local_dev.py
"""
from __future__ import annotations

from pathlib import Path
import os
import sys

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

load_dotenv(ROOT / ".env", override=False)

from app.auth import hash_password  # noqa: E402
from app.database import Base, SessionLocal, engine  # noqa: E402
from app.models_identity import RvuAdminUser, RvuStaff  # noqa: E402
from app.models_rvu import RvuScan, RvuUserSettings  # noqa: E402


def upsert_dev_data() -> None:
    Base.metadata.create_all(bind=engine, checkfirst=True)
    db = SessionLocal()
    try:
        admin = (
            db.query(RvuAdminUser)
            .filter(RvuAdminUser.username == "admin")
            .one_or_none()
        )
        if not admin:
            admin = RvuAdminUser(
                username="admin",
                email="admin@example.test",
                password_hash=hash_password("localdev123"),
                role="superadmin",
                is_active=True,
            )
            db.add(admin)

        staff = (
            db.query(RvuStaff)
            .filter(RvuStaff.email == "surgeon@midfloridasurgical.com")
            .one_or_none()
        )
        if not staff:
            staff = RvuStaff(
                first_name="Dev",
                last_name="Surgeon",
                suffix="MD",
                specialty="General Surgery",
                staff_type="physician",
                email="surgeon@midfloridasurgical.com",
                phone="",
                is_active=True,
            )
            db.add(staff)
            db.flush()

        settings = (
            db.query(RvuUserSettings)
            .filter(RvuUserSettings.surgeon_id == staff.id)
            .one_or_none()
        )
        if not settings:
            db.add(
                RvuUserSettings(
                    surgeon_id=staff.id,
                    default_facility=True,
                    cms_locality_num="99",
                    cf=float(os.environ.get("RVU_DEFAULT_CF", "41.0")),
                    show_estimated_dollars=True,
                    auto_suggest_from_scan=True,
                    cloud_sync_enabled=True,
                )
            )

        has_scan = db.query(RvuScan).filter(RvuScan.surgeon_id == staff.id).first()
        if not has_scan:
            db.add(
                RvuScan(
                    surgeon_id=staff.id,
                    cpts='["99213"]',
                    locality_num="99",
                    locality_name="National",
                    facility=True,
                    total_rvu=2.68,
                    total_payment=109.88,
                    cf=41.0,
                    ai_model="local-seed",
                    service_date=None,
                    patient_name="Test Patient",
                    mrn="TEST-001",
                    line_items='[{"cpt":"99213","description":"Office/outpatient visit","work_rvu":1.3}]',
                    scan_status="verified",
                    main_cpt="99213",
                    main_cpt_status="recognized",
                )
            )

        db.commit()
    finally:
        db.close()


if __name__ == "__main__":
    upsert_dev_data()
    print("Seeded local RVU dev data.")
    print("Portal login: admin / localdev123")
    print("Mobile test email: surgeon@midfloridasurgical.com")
