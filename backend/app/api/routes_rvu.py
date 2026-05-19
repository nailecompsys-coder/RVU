"""RVU capture API — JSON + SSE for staff mobile and portal."""
from __future__ import annotations

import json
import os
import re
import time
from collections import Counter
from datetime import date, datetime, timedelta, timezone
import logging
from collections.abc import Callable
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, UploadFile
from typing import Optional
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import case, desc, func, or_
from sqlalchemy.orm import Session

from app.models_identity import RvuStaff
from app.database import get_db
from app.models_rvu import RvuOpNote, RvuScan, RvuScanAiRun, RvuUserSettings
from app.rvu.lookup import CF_2026
from app.services.rvu_cpt_service import (
    RvuCptExtractionService,
    _cpts_for_surgeon_lines,
    _normalize_mrn_digits,
)
from app.services.rvu_payment_service import RvuPaymentService
from app.services.rvu_rules_service import (
    get_effective_modifier_rules,
    get_effective_rvu_overrides,
    get_recognized_cpts,
    list_cpt_catalog,
    list_modifier_rules,
    patch_cpt_rule,
    patch_modifier_rule,
)

from .deps import get_current_staff
from .routes_auth import get_current_admin_api

router = APIRouter(prefix="/api/v1/rvu", tags=["rvu"])
payment_svc = RvuPaymentService()
cpt_svc = RvuCptExtractionService()
APP_CF_DEFAULT = float(os.environ.get("RVU_DEFAULT_CF", "41.0"))
logging.basicConfig(level=logging.INFO)
log = logging.getLogger("rvu.scan")
SUPPORT_EMAIL = os.environ.get("RVU_SUPPORT_EMAIL", "support@midfloridasurgical.com")
APP_TIME_ZONE = ZoneInfo("America/New_York")


def _normalized_mrn_or_none(value: str | None) -> str | None:
    return _normalize_mrn_digits(value)


def _normalize_capture_dates(
    cap: dict,
    *,
    fallback_service_date: date | None = None,
) -> dict:
    out = {**cap}

    def _fix_one(value: object) -> str | None:
        parsed = payment_svc.parse_service_date(value)
        if not parsed:
            return None
        if (
            fallback_service_date is not None
            and parsed.year != fallback_service_date.year
            and parsed.month == fallback_service_date.month
            and parsed.day == fallback_service_date.day
        ):
            return fallback_service_date.isoformat()
        return parsed.isoformat()

    fixed_top = _fix_one(out.get("service_date"))
    if fixed_top:
        out["service_date"] = fixed_top

    lines_out: list[dict] = []
    for line in out.get("lines") or []:
        if not isinstance(line, dict):
            continue
        line_copy = dict(line)
        fixed_line = _fix_one(line_copy.get("line_service_date"))
        if fixed_line:
            line_copy["line_service_date"] = fixed_line
        lines_out.append(line_copy)
    if lines_out:
        out["lines"] = lines_out

    return out


def _exception_client_message(exc: BaseException, *, max_len: int = 500) -> str:
    """Short, JSON-safe-ish message for clients when vision/OCR aborts."""
    if isinstance(exc, HTTPException):
        d = exc.detail
        msg = d if isinstance(d, str) else json.dumps(d, default=str)
    else:
        msg = str(exc) or exc.__class__.__name__
    msg = msg.strip()
    if len(msg) > max_len:
        return msg[: max_len - 1] + "…"
    return msg


def _format_mm_dd_yy(value: date | datetime | str | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, date):
        dt = datetime.combine(value, datetime.min.time())
    else:
        parsed = payment_svc.parse_service_date(value)
        if not parsed:
            return None
        dt = datetime.combine(parsed, datetime.min.time())
    return dt.strftime("%m-%d-%y")


def _format_hh_mm(value: datetime | str | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return dt.strftime("%H:%M")


def _coerce_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _iso_utc(value: datetime | None) -> str | None:
    dt = _coerce_utc(value)
    return dt.isoformat() if dt else None


def _iso_et(value: datetime | None) -> str | None:
    dt = _coerce_utc(value)
    return dt.astimezone(APP_TIME_ZONE).isoformat() if dt else None


def _label_et(value: datetime | None) -> str | None:
    dt = _coerce_utc(value)
    if not dt:
        return None
    return dt.astimezone(APP_TIME_ZONE).strftime("%m/%d/%Y %I:%M %p %Z")


def _elapsed_label(elapsed_secs: float | None) -> str | None:
    if elapsed_secs is None:
        return None
    return f"{float(elapsed_secs):.1f}s OCR"


def _effective_scan_date(scan: RvuScan) -> date | None:
    if scan.service_date:
        return scan.service_date
    if scan.scanned_at:
        return scan.scanned_at.date()
    return None


def _parse_line_items(raw: str | None) -> list[dict]:
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return []
    return [item for item in parsed if isinstance(item, dict)] if isinstance(parsed, list) else []


def _parse_saved_json_object(raw: str | None) -> dict | list | None:
    if not raw:
        return None
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, (dict, list)) else None


def _primary_line_items(line_items: list[dict]) -> list[dict]:
    return [
        item
        for item in line_items
        if not bool(item.get("is_assist"))
    ]


def _is_assist_line_item(item: dict) -> bool:
    return bool(item.get("is_assist")) or bool(re.search(r"\bAS\b", str(item.get("modifier") or ""), re.I))


def _scan_financial_summary(scan: RvuScan, line_items: list[dict] | None = None) -> dict[str, float | int]:
    items = line_items if line_items is not None else _parse_line_items(scan.line_items)
    cpt_count = len(items)
    assist_count = sum(1 for item in items if _is_assist_line_item(item))
    surgeon_items = [item for item in items if not _is_assist_line_item(item)]
    work_rvu = round(
        sum(float(item.get("work_rvu") or 0.0) for item in surgeon_items),
        2,
    )
    cf = float(scan.cf or 32.3465)
    has_work_payment = any(item.get("work_payment") is not None for item in surgeon_items)
    surgeon_value = round(
        sum(float(item.get("work_payment") or 0.0) for item in surgeon_items) if has_work_payment else work_rvu * cf,
        2,
    )
    total_payment = round(float(scan.total_payment or 0.0), 2)
    facility_share = round(total_payment - surgeon_value, 2)
    return {
        "cpt_count": cpt_count,
        "work_rvu": work_rvu,
        "surgeon_value": surgeon_value,
        "facility_share": facility_share,
        "assist_count": assist_count,
    }


def _persist_ai_runs(db: Session, scan: RvuScan, cap: dict | None) -> None:
    if not isinstance(cap, dict):
        return
    raw_runs = cap.get("_ai_runs")
    if not isinstance(raw_runs, list) or not raw_runs:
        return
    db.query(RvuScanAiRun).filter(RvuScanAiRun.scan_id == scan.id).delete()
    for idx, item in enumerate(raw_runs):
        if not isinstance(item, dict):
            continue
        parsed_json = item.get("parsed_json")
        db.add(
            RvuScanAiRun(
                scan_id=scan.id,
                sequence_num=idx,
                stage=str(item.get("stage") or "")[:64] or "unknown",
                provider=(str(item.get("provider") or "").strip()[:32] or None),
                model=(str(item.get("model") or "").strip()[:120] or None),
                raw_response=str(item.get("raw_response") or "") or None,
                parsed_json=(json.dumps(parsed_json, default=str) if parsed_json is not None else None),
                error_text=(str(item.get("error_text") or "") or None),
            )
        )
    db.commit()


def _scan_ai_run_dict(run: RvuScanAiRun) -> dict:
    return {
        "id": run.id,
        "scan_id": run.scan_id,
        "sequence_num": run.sequence_num,
        "stage": run.stage,
        "provider": run.provider,
        "model": run.model,
        "raw_response": run.raw_response,
        "parsed_json": _parse_saved_json_object(run.parsed_json),
        "error_text": run.error_text,
        "created_at": _iso_utc(run.created_at),
        "created_at_et": _iso_et(run.created_at),
    }


def _is_verified_scan(scan: RvuScan) -> bool:
    return (scan.scan_status or "verified") == "verified"


def _scan_wrvu(scan: RvuScan) -> float:
    line_items = _primary_line_items(_parse_line_items(scan.line_items))
    if line_items:
        return round(sum(float(item.get("work_rvu") or item.get("total_rvu") or 0.0) for item in line_items), 2)
    return round(float(scan.total_rvu or 0.0), 2)


def _review_reason_from_scan_fields(
    *,
    main_cpt: str | None,
    main_cpt_status: str | None,
    patient_name: str | None,
    mrn: str | None,
    service_date: date | None,
) -> str | None:
    if main_cpt_status == "na" and main_cpt:
        return f"CPT {main_cpt} not in library"
    if main_cpt_status == "none":
        return "No CPT recognized from scan"
    if not str(patient_name or "").strip():
        return "Confirm patient name"
    if not str(mrn or "").strip():
        return "Confirm MRN"
    return None


def _get_scan_review_reason(scan: RvuScan) -> str | None:
    return scan.review_reason or _review_reason_from_scan_fields(
        main_cpt=scan.main_cpt,
        main_cpt_status=scan.main_cpt_status,
        patient_name=scan.patient_name,
        mrn=scan.mrn,
        service_date=scan.service_date,
    )


def _touch_review_reason(scan: RvuScan) -> None:
    scan.review_reason = _get_scan_review_reason(scan)


def _scan_status_label(scan: RvuScan) -> str:
    status = (scan.scan_status or "verified").strip().lower()
    if status == "verified":
        return "Saved"
    if status == "pending_review":
        return "Saved, needs review"
    if status == "pending_processing":
        return "Processing"
    return status.replace("_", " ").title()


def _parse_cpts_json(raw: str | None) -> list[str]:
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, list):
        return []
    return [str(item).strip() for item in parsed if str(item).strip()]


def _saved_scan_payload(scan: RvuScan) -> dict[str, object]:
    lines = _parse_line_items(scan.line_items)
    primary_lines = _primary_line_items(lines)
    return {
        "cpts": _parse_cpts_json(scan.cpts),
        "service_date": scan.service_date.isoformat() if scan.service_date else None,
        "patient_name": scan.patient_name,
        "mrn": scan.mrn,
        "lines": lines,
        "rows": primary_lines if primary_lines else lines,
        "total_payment": round(float(scan.total_payment or 0.0), 2),
        "ai_model": scan.ai_model,
        "doc_type_guess": "charge_sheet",
    }


def _sanitize_client_request_id(value: str | None) -> str | None:
    raw = str(value or "").strip()
    if not raw or raw == "-":
        return None
    return raw[:128]


def _find_existing_request_scan(db: Session, surgeon_id: int, request_id: str | None) -> RvuScan | None:
    if not request_id:
        return None
    return (
        db.query(RvuScan)
        .filter(RvuScan.surgeon_id == surgeon_id, RvuScan.client_request_id == request_id)
        .order_by(desc(RvuScan.scanned_at))
        .first()
    )


def _get_or_create_user_settings(db: Session, surgeon_id: int) -> RvuUserSettings:
    row = db.query(RvuUserSettings).filter(RvuUserSettings.surgeon_id == surgeon_id).first()
    if row:
        return row
    row = RvuUserSettings(
        surgeon_id=surgeon_id,
        default_facility=True,
        cms_locality_num="99",
        cf=APP_CF_DEFAULT,
        show_estimated_dollars=True,
        auto_suggest_from_scan=True,
        cloud_sync_enabled=True,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _settings_dict(row: RvuUserSettings) -> dict[str, object]:
    return {
        "default_facility": bool(row.default_facility),
        "cms_locality_num": row.cms_locality_num or "99",
        "cf": float(row.cf or APP_CF_DEFAULT),
        "show_estimated_dollars": bool(row.show_estimated_dollars),
        "auto_suggest_from_scan": bool(row.auto_suggest_from_scan),
        "cloud_sync_enabled": bool(row.cloud_sync_enabled),
        "support_email": SUPPORT_EMAIL,
    }


def _entry_row_dict(scan: RvuScan, surgeon: RvuStaff | None = None) -> dict[str, object]:
    line_items = _parse_line_items(scan.line_items)
    primary_lines = _primary_line_items(line_items)
    primary = primary_lines[0] if primary_lines else {}
    modifier = str(primary.get("modifier") or "").strip()
    description = str(primary.get("procedure_name") or "").strip()
    display_date = _effective_scan_date(scan)
    return {
        **_scan_history_dict(scan, surgeon),
        "display_date": _format_mm_dd_yy(display_date),
        "display_time": _format_hh_mm(scan.scanned_at),
        "entry_count": 1,
        "modifier_summary": modifier or None,
        "description_summary": description or None,
        "wrvu": _scan_wrvu(scan),
        "review_reason": _get_scan_review_reason(scan),
        "setting_label": "Facility" if bool(scan.facility) else "Non-Facility",
        "status_label": _scan_status_label(scan),
        "scanned_at_et": _iso_et(scan.scanned_at),
        "scanned_at_label": _label_et(scan.scanned_at),
        "ocr_elapsed_label": _elapsed_label(scan.elapsed_secs),
    }


def _ai_second_pass_enabled() -> bool:
    """Extra refine pass via the same cloud pipeline (Anthropic/OpenAI). Off by default."""
    return os.environ.get("RVU_AI_SECOND_PASS", "false").lower() in ("1", "true", "yes")


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


def _is_dev_staff(surgeon: RvuStaff) -> bool:
    allowed_emails = {
        e.strip().lower()
        for e in os.environ.get("RVU_DEV_STAFF_EMAILS", "").split(",")
        if e.strip()
    }
    allowed_ids = {
        int(x.strip())
        for x in os.environ.get("RVU_DEV_STAFF_IDS", "").split(",")
        if x.strip().isdigit()
    }
    email = (surgeon.email or "").strip().lower()
    return (email and email in allowed_emails) or (surgeon.id in allowed_ids)


def _extract_modifiers(lines: list[dict] | None) -> dict[str, str]:
    """Build a CPT→modifier map from OCR lines (surgeon lines only, no -AS assist lines)."""
    mods: dict[str, str] = {}
    if not lines:
        return mods
    import re as _re
    for L in lines:
        if not isinstance(L, dict):
            continue
        cpt = str(L.get("cpt") or "").strip()
        if not _re.fullmatch(r"\d{5}", cpt):
            continue
        modifier = str(L.get("modifier") or "").strip().upper()
        if not modifier:
            continue
        role = str(L.get("provider_role") or "").strip().lower()
        is_assist = bool(L.get("is_assist")) or role in ("pa", "assistant") or "AS" in modifier
        if is_assist:
            continue
        # Strip AS token if OCR noise added it to a surgeon line
        parts = [p.strip() for p in modifier.split(",") if p.strip() and p.strip() != "AS"]
        clean = ",".join(parts)
        if clean and cpt not in mods:
            mods[cpt] = clean
    return mods


def _preview_from_capture(
    cap: dict,
    locality: str,
    facility: bool,
    cf: float,
    model: str,
    *,
    cpt_overrides=None,
    modifier_rules=None,
) -> dict:
    cpts = cap.get("cpts") or []
    base = {
        "cpts": cpts,
        "service_date": cap.get("service_date"),
        "patient_name": cap.get("patient_name"),
        "mrn": cap.get("mrn"),
        "lines": cap.get("lines") or [],
        "doc_type_guess": cap.get("doc_type_guess") or "unknown",
        "ai_model": model,
    }
    if not cpts:
        return {**base, "rows": [], "total_payment": 0.0}
    lines = [line for line in (cap.get("lines") or []) if isinstance(line, dict)]
    if lines:
        rows, total = payment_svc.build_rows_from_lines(
            lines,
            locality,
            facility,
            cf,
            cpt_overrides=cpt_overrides,
            modifier_rules=modifier_rules,
        )
    else:
        modifiers = _extract_modifiers(lines)
        rows, total = payment_svc.build_rows(
            cpts,
            locality,
            facility,
            cf,
            modifiers=modifiers,
            cpt_overrides=cpt_overrides,
            modifier_rules=modifier_rules,
        )
    return {**base, "rows": rows, "total_payment": round(total, 2)}


def _filter_capture_to_recognized(cap: dict, recognized_cpts: set[str]) -> dict:
    if not recognized_cpts:
        return cap
    filtered_lines = [
        line for line in (cap.get("lines") or [])
        if str(line.get("cpt") or "").strip() in recognized_cpts
    ]
    filtered_cpts = _cpts_for_surgeon_lines(filtered_lines)
    return {
        **cap,
        "lines": filtered_lines,
        "cpts": filtered_cpts,
        "raw_detected_cpts": cap.get("raw_detected_cpts") or [],
    }


def _apply_clinician_capture_fields(
    cap: dict,
    *,
    mrn: str | None = None,
    patient_name: str | None = None,
    service_date: str | None = None,
) -> dict:
    """When staff typed chart identifiers, prefer them over vision OCR."""
    out = {**cap}
    m = str(mrn or "").strip()
    if m:
        out["mrn"] = _normalized_mrn_or_none(m)
    p = str(patient_name or "").strip()
    if p:
        out["patient_name"] = p[:255]
    sd_raw = str(service_date or "").strip()
    if sd_raw:
        iso = payment_svc.coerce_service_date_iso(sd_raw)
        if iso:
            out["service_date"] = iso
    return out


def _effective_rule_inputs(db: Session) -> tuple[set[str], dict[str, object], dict[str, dict[str, object]]]:
    return (
        get_recognized_cpts(db),
        get_effective_rvu_overrides(db),
        get_effective_modifier_rules(db),
    )


def _stored_binary_usable(blob: bytes | None, *, min_len: int = 64) -> bool:
    """Avoid treating NULL or empty BYTEA as a real thumbnail."""
    return bool(blob) and len(blob) >= min_len


def _guess_image_media_type(data: bytes) -> str:
    """Set Content-Type from magic bytes — stored blobs may be PNG/WebP/GIF, not only JPEG."""
    if len(data) >= 3 and data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if len(data) >= 8 and data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    if len(data) >= 6 and data[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    if len(data) >= 12 and data[4:8] == b"ftyp":
        brand = data[8:12].lower()
        if brand in (b"heic", b"heix", b"hevc", b"heim", b"heis", b"mif1", b"msf1"):
            return "image/heic"
    return "application/octet-stream"


def _binary_image_response(data: bytes) -> Response:
    return Response(
        content=data,
        media_type=_guess_image_media_type(data),
        headers={"Cache-Control": "private, max-age=3600"},
    )


def _prepare_uploaded_image(raw: bytes) -> tuple[bytes, int, int]:
    if len(raw) > 30 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Image too large (max 30 MB)")
    if len(raw) < 64:
        raise HTTPException(status_code=400, detail="Image upload empty or too small.")
    orig_kb = len(raw) // 1024
    shrunk = cpt_svc.shrink_image(raw)
    if len(shrunk) < 64:
        raise HTTPException(status_code=400, detail="Processed image is unusably small.")
    return shrunk, orig_kb, len(shrunk) // 1024


def _provider_mentions_other_physician(provider: str, other: RvuStaff, anchor: RvuStaff) -> bool:
    """Conservative name match for fan-out (requires last name + first name or full-name overlap)."""
    p = re.sub(r"\s+", " ", str(provider or "").strip())
    if len(p) < 4 or other.id == anchor.id:
        return False
    pl = p.lower()
    a_full = re.sub(r"\s+", " ", (anchor.full_name or "").strip()).lower()
    if len(a_full) > 3 and pl == a_full:
        return False
    o_full = re.sub(r"\s+", " ", (other.full_name or "").strip()).lower()
    if len(o_full) > 3 and (o_full in pl or pl in o_full):
        return True
    last = (other.last_name or "").strip().lower()
    first = (other.first_name or "").strip().lower()
    if len(last) < 2 or last not in pl:
        return False
    if first and len(first) > 1 and first in pl:
        return True
    if "," in p and last in pl:
        return True
    return False


def _maybe_fanout_charge_capture_for_other_surgeons(
    db: Session,
    *,
    scan: RvuScan,
    cap_lines: list | None,
) -> None:
    """
    Optional: duplicate the stored charge image into additional RvuScan rows for other physicians
    when OCR provider_name clearly matches another active surgeon (same practice DB).

    Enable with RVU_OCR_FANOUT_SCANS=1 — off by default to avoid false-positive duplicates.
    """
    if os.environ.get("RVU_OCR_FANOUT_SCANS", "").strip().lower() not in ("1", "true", "yes"):
        return
    if not scan.image_data or not _stored_binary_usable(scan.image_data):
        return
    anchor = db.get(RvuStaff, scan.surgeon_id)
    if not anchor or not anchor.is_active:
        return
    raw_lines = cap_lines if isinstance(cap_lines, list) else []
    candidates = (
        db.query(RvuStaff)
        .filter(
            RvuStaff.is_active == True,  # noqa: E712
            RvuStaff.id != anchor.id,
            or_(RvuStaff.staff_type.is_(None), RvuStaff.staff_type.ilike("%physician%")),
        )
        .all()
    )
    by_other: dict[int, list[dict]] = {}
    for L in raw_lines:
        if not isinstance(L, dict):
            continue
        role = str(L.get("provider_role") or "").strip().lower()
        is_assist = bool(L.get("is_assist")) or role in ("pa", "assistant") or "AS" in str(L.get("modifier") or "").upper()
        if is_assist:
            continue
        pname = str(L.get("provider_name") or "").strip()
        if not pname:
            continue
        matched: RvuStaff | None = None
        for s in candidates:
            if _provider_mentions_other_physician(pname, s, anchor):
                matched = s
                break
        if matched is None:
            continue
        by_other.setdefault(matched.id, []).append(dict(L))
    if not by_other:
        return
    img_copy = bytes(scan.image_data)
    fanout_kb = max(1, len(img_copy) // 1024)
    for other_id, subset in by_other.items():
        if not subset:
            continue
        cpt_list: list[str] = []
        for row in subset:
            c = str(row.get("cpt") or "").strip()
            if re.fullmatch(r"\d{5}", c):
                cpt_list.append(c)
        clean = payment_svc.clean_cpt_codes(cpt_list)
        if not clean:
            continue
        mods = _extract_modifiers(subset)
        try:
            _, cpt_overrides, modifier_rules = _effective_rule_inputs(db)
            rows, total = payment_svc.build_rows(
                clean,
                scan.locality_num or "00",
                bool(scan.facility),
                float(scan.cf or APP_CF_DEFAULT),
                modifiers=mods,
                cpt_overrides=cpt_overrides,
                modifier_rules=modifier_rules,
            )
        except Exception as exc:
            log.warning("fanout build_rows failed scan_id=%s other_id=%s err=%s", scan.id, other_id, str(exc)[:200])
            continue
        enriched_sub = payment_svc.enrich_line_items(rows, subset)
        scan_date = scan.service_date
        if scan_date is None:
            for r in enriched_sub:
                if not isinstance(r, dict):
                    continue
                ld = r.get("line_service_date")
                if ld:
                    scan_date = payment_svc.parse_service_date(str(ld))
                    if scan_date:
                        break
        main_cpt, main_cpt_status = _main_cpt_summary(
            {"cpts": clean, "lines": subset, "raw_detected_cpts": []},
            {"cpts": clean, "rows": rows, "total_payment": total},
        )
        rr = (
            None
            if (scan.scan_status or "") == "verified"
            else _review_reason_from_scan_fields(
                main_cpt=main_cpt,
                main_cpt_status=main_cpt_status,
                patient_name=scan.patient_name,
                mrn=scan.mrn,
                service_date=scan_date,
            )
        )
        payment_svc.save_scan(
            db,
            other_id,
            clean,
            scan.locality_num or "00",
            scan.locality_name or payment_svc.locality_name(scan.locality_num or "00"),
            bool(scan.facility),
            round(sum(float(r.get("total_rvu") or 0) for r in rows), 2),
            round(total, 2),
            float(scan.cf or APP_CF_DEFAULT),
            (scan.ai_model or "vision")[:64],
            fanout_kb,
            float(scan.elapsed_secs or 0),
            service_date=scan_date,
            patient_name=scan.patient_name,
            mrn=scan.mrn,
            line_items_json=json.dumps(enriched_sub),
            image_bytes=img_copy,
            scan_status=scan.scan_status or "pending_review",
            main_cpt=main_cpt,
            main_cpt_status=main_cpt_status,
            review_reason=rr,
        )


def _main_cpt_summary(cap: dict, payload: dict) -> tuple[str | None, str | None]:
    recognized = [str(cpt or "").strip() for cpt in (payload.get("cpts") or []) if str(cpt or "").strip()]
    if recognized:
        return recognized[0], "recognized"
    raw_detected = [str(cpt or "").strip() for cpt in (cap.get("raw_detected_cpts") or []) if str(cpt or "").strip()]
    if raw_detected:
        return raw_detected[0], "na"
    return "No CPT", "none"


def _create_pending_scan_stub(
    *,
    db: Session,
    surgeon: RvuStaff,
    locality: str,
    facility: bool,
    cf: float,
    image_kb: int,
    image_bytes: bytes | None = None,
    client_request_id: str | None = None,
) -> RvuScan:
    return payment_svc.save_scan(
        db,
        surgeon.id,
        [],
        locality,
        payment_svc.locality_name(locality),
        facility,
        0.0,
        0.0,
        cf,
        "processing",
        image_kb,
        0.0,
        line_items_json=json.dumps([]),
        image_bytes=image_bytes,
        scan_status="pending_processing",
        main_cpt=None,
        main_cpt_status=None,
        review_reason="Processing charge capture",
        client_request_id=client_request_id,
    )


def _apply_pending_scan_result(
    *,
    db: Session,
    scan: RvuScan,
    payload: dict,
    cap: dict,
    locality: str,
    facility: bool,
    cf: float,
    ai_model: str,
    image_kb: int,
    elapsed: float,
    verified: bool = False,
    review_reason_override: str | None = None,
) -> RvuScan:
    rows = payload["rows"]
    total = payload["total_payment"]
    loc_name = payment_svc.locality_name(locality)
    enriched = payment_svc.enrich_line_items(rows, cap.get("lines"))
    main_cpt, main_cpt_status = _main_cpt_summary(cap, payload)
    synced = _cpts_for_surgeon_lines(enriched)
    scan.cpts = json.dumps(synced if synced else (payload.get("cpts") or []))
    scan.locality_num = locality
    scan.locality_name = loc_name
    scan.facility = facility
    scan.total_rvu = round(sum(r["total_rvu"] for r in rows), 2)
    scan.total_payment = round(total, 2)
    scan.cf = cf
    scan.ai_model = ai_model
    scan.image_kb = image_kb
    scan.elapsed_secs = round(elapsed, 1)
    scan.service_date = payment_svc.parse_service_date(cap.get("service_date"))
    scan.patient_name = (str(cap.get("patient_name") or "").strip() or None)
    scan.mrn = _normalized_mrn_or_none(cap.get("mrn"))
    scan.line_items = json.dumps(enriched)
    scan.scan_status = "verified" if verified else "pending_review"
    scan.main_cpt = main_cpt
    scan.main_cpt_status = main_cpt_status
    if verified:
        scan.review_reason = None
    elif review_reason_override is not None:
        scan.review_reason = review_reason_override[:255]
    else:
        scan.review_reason = _review_reason_from_scan_fields(
            main_cpt=main_cpt,
            main_cpt_status=main_cpt_status,
            patient_name=scan.patient_name,
            mrn=scan.mrn,
            service_date=scan.service_date,
        )
    db.commit()
    db.refresh(scan)
    _persist_ai_runs(db, scan, cap)
    _maybe_fanout_charge_capture_for_other_surgeons(db, scan=scan, cap_lines=cap.get("lines") if isinstance(cap.get("lines"), list) else None)
    return scan


def _persist_capture_result(
    *,
    db: Session,
    surgeon: RvuStaff,
    payload: dict,
    cap: dict,
    locality: str,
    facility: bool,
    cf: float,
    ai_model: str,
    image_kb: int,
    elapsed: float,
    image_bytes: bytes | None = None,
    client_request_id: str | None = None,
) -> RvuScan:
    rows = payload["rows"]
    total = payload["total_payment"]
    loc_name = payment_svc.locality_name(locality)
    enriched = payment_svc.enrich_line_items(rows, cap.get("lines"))
    main_cpt, main_cpt_status = _main_cpt_summary(cap, payload)
    synced_cpts = _cpts_for_surgeon_lines(enriched)
    if not synced_cpts:
        synced_cpts = list(payload.get("cpts") or [])
    scan = payment_svc.save_scan(
        db,
        surgeon.id,
        synced_cpts,
        locality,
        loc_name,
        facility,
        sum(r["total_rvu"] for r in rows),
        total,
        cf,
        ai_model,
        image_kb,
        elapsed,
        service_date=payment_svc.parse_service_date(cap.get("service_date")),
        patient_name=cap.get("patient_name"),
        mrn=_normalized_mrn_or_none(cap.get("mrn")),
        line_items_json=json.dumps(enriched),
        image_bytes=image_bytes,
        scan_status="pending_review",
        main_cpt=main_cpt,
        main_cpt_status=main_cpt_status,
        review_reason=_review_reason_from_scan_fields(
            main_cpt=main_cpt,
            main_cpt_status=main_cpt_status,
            patient_name=cap.get("patient_name"),
            mrn=_normalized_mrn_or_none(cap.get("mrn")),
            service_date=payment_svc.parse_service_date(cap.get("service_date")),
        ),
        client_request_id=client_request_id,
    )
    _persist_ai_runs(db, scan, cap)
    _maybe_fanout_charge_capture_for_other_surgeons(db, scan=scan, cap_lines=cap.get("lines") if isinstance(cap.get("lines"), list) else None)
    return scan


def _finalize_capture_response(
    *,
    payload: dict,
    locality: str,
    elapsed: float,
    persisted: bool,
    scan: RvuScan | None = None,
    surgeon: RvuStaff | None = None,
    include_staff: bool = False,
) -> dict:
    response = {
        **payload,
        "locality_name": payment_svc.locality_name(locality),
        "elapsed_secs": round(elapsed, 1),
        "persisted": persisted,
    }
    if scan is not None:
        response["id"] = scan.id
        response["patient_name"] = scan.patient_name
        response["scan_status"] = scan.scan_status
        response["status_label"] = _scan_status_label(scan)
        response["main_cpt"] = scan.main_cpt
        response["main_cpt_status"] = scan.main_cpt_status
        response["has_image"] = _stored_binary_usable(scan.image_data)
        response["scanned_at"] = _iso_utc(scan.scanned_at)
        response["scanned_at_et"] = _iso_et(scan.scanned_at)
        response["scanned_at_label"] = _label_et(scan.scanned_at)
        response["review_reason"] = _get_scan_review_reason(scan)
    response["ocr_elapsed_label"] = _elapsed_label(response.get("elapsed_secs"))
    if include_staff and surgeon is not None:
        response["surgeon_name"] = getattr(surgeon, "full_name", None)
        response["staff_type"] = getattr(surgeon, "staff_type", None)
    return response


def _field_confidence(value: str | None, present: float = 0.96, missing: float = 0.0) -> float:
    return present if str(value or "").strip() else missing


def _line_confidence(line: dict) -> float:
    cpt = str(line.get("cpt") or "").strip()
    modifier = str(line.get("modifier") or "").strip()
    provider_name = str(line.get("provider_name") or "").strip()
    score = 0.55
    if re.fullmatch(r"\d{5}", cpt):
        score += 0.25
    if provider_name:
        score += 0.1
    if modifier:
        score += 0.05
    if line.get("provider_role") in ("surgeon", "pa", "assistant"):
        score += 0.05
    return round(min(score, 0.99), 2)


def _reconciliation_line_items(lines: list[dict] | None) -> list[dict]:
    out: list[dict] = []
    for idx, line in enumerate(lines or [], start=1):
        if not isinstance(line, dict):
            continue
        cpt = str(line.get("cpt") or "").strip()
        if not re.fullmatch(r"\d{5}", cpt):
            continue
        modifier = str(line.get("modifier") or "").strip().upper()
        provider_name = str(line.get("provider_name") or "").strip()
        provider_role = str(line.get("provider_role") or "unknown").strip().lower()
        if provider_role not in ("surgeon", "pa", "assistant", "unknown"):
            provider_role = "unknown"
        out.append(
            {
                "line_id": f"line-{idx}",
                "cpt": cpt,
                "modifier": modifier,
                "procedure_name": str(line.get("procedure_name") or "").strip(),
                "provider_name": provider_name,
                "provider_role": provider_role,
                "is_assist": bool(line.get("is_assist")) or "AS" in modifier or provider_role in ("pa", "assistant"),
                "line_service_date": str(line.get("line_service_date") or "").strip(),
                "line_service_datetime_raw": str(line.get("line_service_datetime_raw") or "").strip(),
                "line_service_time_raw": str(line.get("line_service_time_raw") or "").strip(),
                "quantity": line.get("quantity"),
                "raw_row_text": str(line.get("raw_row_text") or "").strip(),
                "confidence": _line_confidence(line),
                "source": "ocr_parser",
                "bbox": None,
            }
        )
    return out


def _select_line_items_for_cpts(
    existing_lines: list[dict] | None,
    cpts: list[str],
    modifiers: dict[str, str] | None = None,
) -> list[dict]:
    """Preserve one record per visible line item instead of collapsing duplicates by CPT."""
    if not existing_lines or not cpts:
        return []
    requested = [c for c in cpts if re.fullmatch(r"\d{5}", str(c or "").strip())]
    if not requested:
        return []

    source_lines = [row for row in existing_lines if isinstance(row, dict)]
    primary_pool: dict[str, list[dict]] = {}
    assist_pool: dict[str, list[dict]] = {}
    for item in source_lines:
        cpt = str(item.get("cpt") or "").strip()
        if not re.fullmatch(r"\d{5}", cpt):
            continue
        modifier = str(item.get("modifier") or "").strip().upper()
        is_assist = bool(item.get("is_assist")) or "AS" in modifier or str(item.get("provider_role") or "").strip().lower() in ("pa", "assistant")
        target = assist_pool if is_assist else primary_pool
        target.setdefault(cpt, []).append(dict(item))

    merged: list[dict] = []
    requested_counts = Counter(requested)
    for cpt in requested:
        pool = primary_pool.get(cpt) or []
        existing = pool.pop(0) if pool else {"cpt": cpt, "procedure_name": ""}
        if modifiers is not None:
            existing["modifier"] = modifiers.get(cpt, str(existing.get("modifier") or ""))
            existing["is_assist"] = bool(existing.get("is_assist"))
        merged.append(existing)

    for cpt, needed in requested_counts.items():
        extras = assist_pool.get(cpt) or []
        for extra in extras[:needed]:
            merged.append(extra)

    return merged


def _build_reconciliation_draft(
    *,
    cap: dict,
    surgeon: RvuStaff,
    provider: str,
    elapsed: float,
    locality: str,
    facility: bool,
    cf: float,
) -> dict:
    surgeon_name = str(cap.get("surgeon_name") or "").strip() or getattr(surgeon, "full_name", None) or ""
    service_date = cap.get("service_date")
    mrn = cap.get("mrn")
    line_items = _reconciliation_line_items(cap.get("lines") or [])
    return {
        "status": "draft",
        "doc_type": cap.get("doc_type_guess") or "unknown",
        "timing": {
            "elapsed_secs": round(elapsed, 1),
            "provider": provider,
        },
        "context": {
            "locality": locality,
            "locality_name": payment_svc.locality_name(locality),
            "facility": facility,
            "cf": cf,
        },
        "patient": {
            "name": cap.get("patient_name") or "",
            "name_confidence": _field_confidence(cap.get("patient_name")),
            "mrn": mrn or "",
            "mrn_confidence": _field_confidence(mrn),
        },
        "encounter": {
            "service_date": service_date or "",
            "service_date_confidence": _field_confidence(service_date),
        },
        "providers": {
            "surgeon_name": surgeon_name,
            "surgeon_confidence": _field_confidence(surgeon_name, present=0.9),
            "staff_name": getattr(surgeon, "full_name", None),
            "staff_type": getattr(surgeon, "staff_type", None),
        },
        "line_items": line_items,
        "ocr_artifacts": {
            "tokens": [],
            "image_variant": "normalized",
            "engine": provider,
            "engine_version": "",
        },
        "needs_attention": not bool(line_items),
    }


def _run_text_capture(
    raw_text: str,
    *,
    db: Session,
    locality: str,
    facility: bool,
    cf: float,
    event_cb: Callable[[str, str], None] | None = None,
) -> tuple[dict, dict, float, str]:
    t_start = datetime.now(timezone.utc)
    print(f"[text_capture] raw_text ({len(raw_text)} chars):\n{raw_text[:2000]}", flush=True)
    cap: dict = {"cpts": [], "service_date": None, "patient_name": None, "mrn": None, "lines": []}
    if event_cb:
        event_cb("status", "Sending text to AI…")
    for item in cpt_svc.stream_text(raw_text):
        if item[0] == "error":
            raise HTTPException(status_code=500, detail=item[1])
        if item[0] == "token" and event_cb:
            event_cb("token", item[1])
        if item[0] == "done":
            cap = item[1] if isinstance(item[1], dict) else {"cpts": item[1], "lines": [], "service_date": None, "patient_name": None, "mrn": None}
    if _ai_second_pass_enabled():
        if event_cb:
            event_cb("status", "Second pass: checking for more CPT codes…")
        try:
            extra = cpt_svc.refine_text_additional(raw_text, cap, artifact_sink=cap.setdefault("_ai_runs", []))
            cap = RvuCptExtractionService.merge_captures(cap, extra)
        except Exception:
            pass
    elapsed = (datetime.now(timezone.utc) - t_start).total_seconds()
    recognized_cpts, cpt_overrides, modifier_rules = _effective_rule_inputs(db)
    cap = _filter_capture_to_recognized(cap, recognized_cpts)
    payload = _preview_from_capture(
        cap,
        locality,
        facility,
        cf,
        cpt_svc.text_model,
        cpt_overrides=cpt_overrides,
        modifier_rules=modifier_rules,
    )
    return cap, payload, elapsed, cpt_svc.text_model


def _run_vision_capture(
    image_bytes: bytes,
    *,
    db: Session,
    locality: str,
    facility: bool,
    cf: float,
    scan_mode: str,
    event_cb: Callable[[str, str], None] | None = None,
    clinician_mrn: str | None = None,
    clinician_patient_name: str | None = None,
    clinician_service_date: str | None = None,
) -> tuple[dict, dict, float, str, str]:
    t_start = datetime.now(timezone.utc)
    mode = (scan_mode or "balanced").strip().lower()
    cap: dict = {"cpts": [], "service_date": None, "patient_name": None, "mrn": None, "lines": []}
    if event_cb:
        event_cb("status", "vision: stream start")
    first_token_at: datetime | None = None
    for item in cpt_svc.stream_vision(image_bytes, scan_mode=scan_mode):
        if item[0] == "error":
            raise HTTPException(status_code=500, detail=item[1])
        if item[0] == "status":
            if event_cb:
                event_cb("status", str(item[1]))
            continue
        if item[0] == "token":
            if first_token_at is None and event_cb:
                first_token_at = datetime.now(timezone.utc)
                dt = (first_token_at - t_start).total_seconds()
                event_cb("status", f"vision: first token at {dt:.1f}s")
            if event_cb:
                event_cb("token", item[1])
        if item[0] == "done":
            cap = item[1] if isinstance(item[1], dict) else {"cpts": item[1], "lines": [], "service_date": None, "patient_name": None, "mrn": None}
    if event_cb:
        event_cb("status", "vision: stream done")
    cap["raw_detected_cpts"] = [
        str(cpt or "").strip()
        for cpt in (cap.get("cpts") or [])
        if str(cpt or "").strip()
    ]
    recognized_cpts, cpt_overrides, modifier_rules = _effective_rule_inputs(db)
    cap = _filter_capture_to_recognized(cap, recognized_cpts)
    if _ai_second_pass_enabled():
        if event_cb:
            event_cb("status", "Second pass: checking for more CPT codes…")
        try:
            extra = cpt_svc.refine_vision_additional(image_bytes, cap, artifact_sink=cap.setdefault("_ai_runs", []))
            cap = RvuCptExtractionService.merge_captures(cap, extra)
        except Exception:
            pass
    cap = _apply_clinician_capture_fields(
        cap,
        mrn=clinician_mrn,
        patient_name=clinician_patient_name,
        service_date=clinician_service_date,
    )
    elapsed = (datetime.now(timezone.utc) - t_start).total_seconds()
    vision_backend = getattr(cpt_svc, "last_charge_capture_backend", None) or "unknown"
    payload = _preview_from_capture(
        cap,
        locality,
        facility,
        cf,
        cpt_svc.vision_model,
        cpt_overrides=cpt_overrides,
        modifier_rules=modifier_rules,
    )
    payload["vision_backend"] = vision_backend
    log.info(
        "vision_capture_done backend=%s mode=%s elapsed=%.2fs cpts=%s",
        vision_backend,
        mode,
        elapsed,
        len(payload.get("cpts") or []),
    )
    return cap, payload, elapsed, vision_backend, mode


@router.get("/localities")
def localities():
    """Public — static CMS GPCI/fee-schedule data, no PII."""
    return payment_svc.localities_payload()


@router.get("/providers")
def list_providers(
    db: Session = Depends(get_db),
    _auth: tuple[RvuStaff, object] = Depends(get_current_staff),
):
    """Return active providers for fast native charge assignment."""

    def _role_for_staff(staff_type: str | None) -> str:
        value = str(staff_type or "").strip().lower()
        if value in {"pa", "physician_assistant", "assistant", "staff"}:
            return "pa"
        return "surgeon"

    role_order = case(
        (RvuStaff.staff_type.ilike("physician"), 0),
        (RvuStaff.staff_type.ilike("pa"), 1),
        (RvuStaff.staff_type.ilike("staff"), 1),
        else_=2,
    )
    providers = (
        db.query(RvuStaff)
        .filter(RvuStaff.is_active == True)  # noqa: E712
        .order_by(role_order, RvuStaff.last_name, RvuStaff.first_name)
        .all()
    )
    return {
        "providers": [
            {
                "id": s.id,
                "full_name": s.full_name,
                "staff_type": s.staff_type,
                "provider_role": _role_for_staff(s.staff_type),
            }
            for s in providers
        ]
    }


class LookupBody(BaseModel):
    cpts: list[str] = Field(default_factory=list)
    locality: str = "00"
    facility: bool = False
    cf: float = APP_CF_DEFAULT
    modifiers: dict[str, str] = Field(default_factory=dict)


class VisionConfigPatch(BaseModel):
    provider: str | None = None
    vision_model: str | None = None
    openai_api_key: str | None = None
    anthropic_api_key: str | None = None


@router.get("/dev/vision-config")
def staff_dev_get_vision_config(
    auth: tuple[RvuStaff, object] = Depends(get_current_staff),
):
    surgeon, _ = auth
    if not _is_dev_staff(surgeon):
        raise HTTPException(status_code=403, detail="Developer staff access required")
    return cpt_svc.get_vision_config()


@router.get("/vision-config")
def staff_get_vision_config(
    auth: tuple[RvuStaff, object] = Depends(get_current_staff),
):
    _surgeon, _ = auth
    return cpt_svc.get_vision_config()


@router.patch("/dev/vision-config")
def staff_dev_set_vision_config(
    body: VisionConfigPatch,
    auth: tuple[RvuStaff, object] = Depends(get_current_staff),
):
    surgeon, _ = auth
    if not _is_dev_staff(surgeon):
        raise HTTPException(status_code=403, detail="Developer staff access required")
    try:
        return cpt_svc.set_vision_config(
            provider=body.provider,
            model=body.vision_model,
            openai_api_key=body.openai_api_key,
            anthropic_api_key=body.anthropic_api_key,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/preview")
def preview_lookup(
    body: LookupBody,
    db: Session = Depends(get_db),
    _auth: tuple[RvuStaff, object] = Depends(get_current_staff),
):
    """Recalculate wRVU / payment from CPT list without persisting."""
    clean = payment_svc.clean_cpt_codes(body.cpts)
    if not clean:
        return {"cpts": [], "rows": [], "total_payment": 0.0}
    _, cpt_overrides, modifier_rules = _effective_rule_inputs(db)
    rows, total = payment_svc.build_rows(
        clean,
        body.locality,
        body.facility,
        body.cf,
        modifiers=body.modifiers or None,
        cpt_overrides=cpt_overrides,
        modifier_rules=modifier_rules,
    )
    return {"cpts": clean, "rows": rows, "total_payment": round(total, 2)}


@router.post("/lookup")
def direct_lookup(
    body: LookupBody,
    db: Session = Depends(get_db),
    auth: tuple[RvuStaff, object] = Depends(get_current_staff),
):
    surgeon, _ = auth
    clean = payment_svc.clean_cpt_codes(body.cpts)
    if not clean:
        return {"cpts": [], "rows": [], "total_payment": 0.0}
    _, cpt_overrides, modifier_rules = _effective_rule_inputs(db)
    rows, total = payment_svc.build_rows(
        clean,
        body.locality,
        body.facility,
        body.cf,
        cpt_overrides=cpt_overrides,
        modifier_rules=modifier_rules,
    )
    loc_name = payment_svc.locality_name(body.locality)
    enriched = payment_svc.enrich_line_items(rows, None)
    synced_direct = _cpts_for_surgeon_lines(enriched) or clean
    payment_svc.save_scan(
        db,
        surgeon.id,
        synced_direct,
        body.locality,
        loc_name,
        body.facility,
        sum(r["total_rvu"] for r in rows),
        total,
        body.cf,
        "direct",
        0,
        0.0,
        line_items_json=json.dumps(enriched),
    )
    return {"cpts": synced_direct, "rows": rows, "total_payment": round(total, 2)}


class LineItemIn(BaseModel):
    cpt: str
    procedure_name: str = ""
    provider_name: str = ""
    provider_role: str = "unknown"
    modifier: str = ""
    is_assist: bool = False
    line_service_date: str = ""


class CommitBody(BaseModel):
    cpts: list[str] = Field(default_factory=list)
    locality: str = "00"
    facility: bool = False
    cf: float = APP_CF_DEFAULT
    service_date: str | None = None
    patient_name: str | None = None
    mrn: str | None = None
    lines: list[LineItemIn] = Field(default_factory=list)
    ai_model: str = "staff"
    image_kb: int = 0
    elapsed_secs: float = 0.0


@router.post("/commit")
async def commit_scan(
    # multipart fields — all come from FormData when image is attached
    cpts: str = Form(...),                        # JSON array string
    locality: str = Form("00"),
    facility: str = Form("false"),
    cf: float = Form(APP_CF_DEFAULT),
    service_date: Optional[str] = Form(None),
    patient_name: Optional[str] = Form(None),
    mrn: Optional[str] = Form(None),
    lines: str = Form("[]"),                      # JSON array string
    ai_model: str = Form("vision"),
    image_kb: int = Form(0),
    elapsed_secs: float = Form(0.0),
    image: Optional[UploadFile] = File(None),
    db: Session = Depends(get_db),
    auth: tuple[RvuStaff, object] = Depends(get_current_staff),
):
    """Persist a reviewed capture. Accepts optional image upload."""
    surgeon, _ = auth
    clean = payment_svc.clean_cpt_codes(json.loads(cpts))
    if not clean:
        raise HTTPException(status_code=400, detail="No valid CPT codes")

    fac = facility.lower() == "true"
    line_dicts = json.loads(lines)
    _, cpt_overrides, modifier_rules = _effective_rule_inputs(db)
    rows, total = (
        payment_svc.build_rows_from_lines(
            line_dicts,
            locality,
            fac,
            cf,
            cpt_overrides=cpt_overrides,
            modifier_rules=modifier_rules,
        )
        if line_dicts
        else payment_svc.build_rows(
            clean,
            locality,
            fac,
            cf,
            modifiers=None,
            cpt_overrides=cpt_overrides,
            modifier_rules=modifier_rules,
        )
    )
    loc_name = payment_svc.locality_name(locality)
    enriched = payment_svc.enrich_line_items(rows, line_dicts)
    synced_commit = _cpts_for_surgeon_lines(enriched) or clean
    sd = payment_svc.parse_service_date(service_date)

    img_bytes: bytes | None = None
    actual_kb = image_kb
    if image and image.filename:
        raw = await image.read()
        if len(raw) > 10 * 1024 * 1024:
            raise HTTPException(status_code=413, detail="Image too large (max 10 MB)")
        if len(raw) >= 64:
            try:
                shrunk, _orig_kb, small_kb = _prepare_uploaded_image(raw)
                img_bytes = shrunk
                actual_kb = small_kb
            except HTTPException:
                raise
            except Exception:
                img_bytes = raw
                actual_kb = len(raw) // 1024

    scan = payment_svc.save_scan(
        db,
        surgeon.id,
        synced_commit,
        locality,
        loc_name,
        fac,
        sum(r["total_rvu"] for r in rows),
        total,
        cf,
        ai_model,
        actual_kb,
        elapsed_secs,
        service_date=sd,
        patient_name=patient_name,
        mrn=_normalized_mrn_or_none(mrn),
        line_items_json=json.dumps(enriched),
        image_bytes=img_bytes,
    )
    return {
        "id": scan.id,
        "cpts": synced_commit,
        "rows": rows,
        "total_payment": round(total, 2),
        "line_items": enriched,
        "has_image": img_bytes is not None,
    }


class TextScanBody(BaseModel):
    raw_text: str
    locality: str = "00"
    facility: bool = False
    cf: float = APP_CF_DEFAULT
    persist: bool = False


@router.post("/text-stream")
def text_stream(
    body: TextScanBody,
    db: Session = Depends(get_db),
    auth: tuple[RvuStaff, object] = Depends(get_current_staff),
    rvu_request_id: str | None = Header(None, alias="X-RVU-Request-Id"),
):
    surgeon, _ = auth
    do_persist = body.persist
    client_request_id = _sanitize_client_request_id(rvu_request_id)

    def generate():
        if do_persist and client_request_id:
            existing_scan = _find_existing_request_scan(db, surgeon.id, client_request_id)
            if existing_scan is not None:
                log.info(
                    "[b09ef5] text_stream_reused req_id=%s surgeon_id=%s scan_id=%s status=%s",
                    client_request_id[:64],
                    surgeon.id,
                    existing_scan.id,
                    existing_scan.scan_status,
                )
                response = _finalize_capture_response(
                    payload=_saved_scan_payload(existing_scan),
                    locality=existing_scan.locality_num or body.locality,
                    elapsed=float(existing_scan.elapsed_secs or 0.0),
                    persisted=True,
                    scan=existing_scan,
                )
                response["idempotency_reused"] = True
                yield _sse("done", response)
                return
        events: list[tuple[str, str]] = []
        try:
            cap, payload, elapsed, ai_model = _run_text_capture(
                body.raw_text,
                db=db,
                locality=body.locality,
                facility=body.facility,
                cf=body.cf,
                event_cb=lambda kind, msg: events.append((kind, msg)),
            )
        except HTTPException as exc:
            yield _sse("error", {"msg": str(exc.detail)})
            return
        except Exception as exc:
            yield _sse("error", {"msg": str(exc)})
            return
        for kind, msg in events:
            key = "t" if kind == "token" else "msg"
            yield _sse(kind, {key: msg})
        if body.persist and payload["cpts"]:
            saved = _persist_capture_result(
                db=db,
                surgeon=surgeon,
                payload=payload,
                cap=cap,
                locality=body.locality,
                facility=body.facility,
                cf=body.cf,
                ai_model=ai_model,
                image_kb=0,
                elapsed=elapsed,
                client_request_id=client_request_id,
            )
        else:
            saved = None
        yield _sse(
            "done",
            _finalize_capture_response(
                payload=payload,
                locality=body.locality,
                elapsed=elapsed,
                persisted=bool(body.persist and payload["cpts"]),
                scan=saved,
            ),
        )

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )

@router.post("/text-scan")
def text_scan(
    body: TextScanBody,
    db: Session = Depends(get_db),
    auth: tuple[RvuStaff, object] = Depends(get_current_staff),
    rvu_request_id: str | None = Header(None, alias="X-RVU-Request-Id"),
):
    """Non-streaming JSON endpoint for native app; same logic as text-stream."""
    surgeon, _ = auth
    do_persist = body.persist
    client_request_id = _sanitize_client_request_id(rvu_request_id)
    if do_persist and client_request_id:
        existing_scan = _find_existing_request_scan(db, surgeon.id, client_request_id)
        if existing_scan is not None:
            log.info(
                "[b09ef5] text_scan_reused req_id=%s surgeon_id=%s scan_id=%s status=%s",
                client_request_id[:64],
                surgeon.id,
                existing_scan.id,
                existing_scan.scan_status,
            )
            response = _finalize_capture_response(
                payload=_saved_scan_payload(existing_scan),
                locality=existing_scan.locality_num or body.locality,
                elapsed=float(existing_scan.elapsed_secs or 0.0),
                persisted=True,
                scan=existing_scan,
            )
            response["idempotency_reused"] = True
            return response
    cap, payload, elapsed, ai_model = _run_text_capture(
        body.raw_text,
        db=db,
        locality=body.locality,
        facility=body.facility,
        cf=body.cf,
    )
    saved_scan = None
    if body.persist and payload["cpts"]:
        saved_scan = _persist_capture_result(
            db=db,
            surgeon=surgeon,
            payload=payload,
            cap=cap,
            locality=body.locality,
            facility=body.facility,
            cf=body.cf,
            ai_model=ai_model,
            image_kb=0,
            elapsed=elapsed,
            client_request_id=client_request_id,
        )
    return _finalize_capture_response(
        payload=payload,
        locality=body.locality,
        elapsed=elapsed,
        persisted=bool(body.persist and payload["cpts"]),
        scan=saved_scan,
    )

@router.post("/vision-scan")
async def vision_scan(
    image: UploadFile = File(...),
    locality: str = Form("00"),
    facility: str = Form("false"),
    cf: float = Form(APP_CF_DEFAULT),
    scan_mode: str = Form("balanced"),
    persist: str = Form("false"),
    mrn: Optional[str] = Form(None),
    patient_name: Optional[str] = Form(None),
    service_date: Optional[str] = Form(None),
    db: Session = Depends(get_db),
    auth: tuple[RvuStaff, object] = Depends(get_current_staff),
    rvu_request_id: str | None = Header(None, alias="X-RVU-Request-Id"),
):
    """Non-streaming JSON endpoint for native app; same logic as vision-stream."""
    surgeon, _ = auth
    fac = facility.lower() == "true"
    do_persist = persist.lower() == "true"
    client_request_id = _sanitize_client_request_id(rvu_request_id)
    if do_persist and client_request_id:
        existing_scan = _find_existing_request_scan(db, surgeon.id, client_request_id)
        if existing_scan is not None:
            log.info(
                "[b09ef5] vision_scan_reused req_id=%s surgeon_id=%s scan_id=%s status=%s",
                client_request_id[:64],
                surgeon.id,
                existing_scan.id,
                existing_scan.scan_status,
            )
            response = _finalize_capture_response(
                payload=_saved_scan_payload(existing_scan),
                locality=existing_scan.locality_num or locality,
                elapsed=float(existing_scan.elapsed_secs or 0.0),
                persisted=True,
                scan=existing_scan,
                surgeon=surgeon,
                include_staff=True,
            )
            response["idempotency_reused"] = True
            return response
    image_bytes, orig_kb, small_kb = _prepare_uploaded_image(await image.read())
    wall_start_s = time.monotonic()
    _rid = (client_request_id or "-")[:64]
    log.info(
        "[b09ef5] vision_scan_begin req_id=%s surgeon_id=%s orig_kb=%s small_kb=%s mode=%s persist=%s",
        _rid,
        surgeon.id,
        orig_kb,
        small_kb,
        scan_mode,
        do_persist,
    )
    pending_scan = None
    if do_persist:
        pending_scan = _create_pending_scan_stub(
            db=db,
            surgeon=surgeon,
            locality=locality,
            facility=fac,
            cf=cf,
            image_kb=small_kb,
            image_bytes=image_bytes,
            client_request_id=client_request_id,
        )
    t_started = datetime.now(timezone.utc)
    try:
        cap, payload, elapsed, vision_backend, _mode = _run_vision_capture(
            image_bytes,
            db=db,
            locality=locality,
            facility=fac,
            cf=cf,
            scan_mode=scan_mode,
            clinician_mrn=mrn,
            clinician_patient_name=patient_name,
            clinician_service_date=service_date,
        )
    except Exception as exc:
        if pending_scan is None:
            raise
        elapsed_fb = (datetime.now(timezone.utc) - t_started).total_seconds()
        err_txt = _exception_client_message(exc)
        log.warning(
            "[b09ef5] vision_scan_soft_fail req_id=%s surgeon_id=%s wall_s=%.2f err=%s",
            _rid,
            surgeon.id,
            time.monotonic() - wall_start_s,
            err_txt[:200],
        )
        log.warning("vision_scan vision failed persisted_stub surgeon=%s err=%s", surgeon.id, err_txt[:200])
        recognized_cpts, cpt_overrides, modifier_rules = _effective_rule_inputs(db)
        empty_cap: dict = _apply_clinician_capture_fields(
            {
                "cpts": [],
                "lines": [],
                "service_date": None,
                "patient_name": None,
                "mrn": None,
                "raw_detected_cpts": [],
            },
            mrn=mrn,
            patient_name=patient_name,
            service_date=service_date,
        )
        fb_payload = _preview_from_capture(
            empty_cap,
            locality,
            fac,
            cf,
            cpt_svc.vision_model,
            cpt_overrides=cpt_overrides,
            modifier_rules=modifier_rules,
        )
        fb_payload["vision_error"] = err_txt
        rr = f"Vision failed — photo saved; enter CPTs manually. ({err_txt[:140]})"
        saved_scan = _apply_pending_scan_result(
            db=db,
            scan=pending_scan,
            payload=fb_payload,
            cap=empty_cap,
            locality=locality,
            facility=fac,
            cf=cf,
            ai_model=cpt_svc.vision_model,
            image_kb=small_kb,
            elapsed=elapsed_fb,
            verified=False,
            review_reason_override=rr[:255],
        )
        return _finalize_capture_response(
            payload=fb_payload,
            locality=locality,
            elapsed=elapsed_fb,
            persisted=True,
            scan=saved_scan,
            surgeon=surgeon,
            include_staff=True,
        )
    log.info(
        "[b09ef5] vision_scan_ok req_id=%s wall_s=%.2f surgeon_id=%s vision_backend=%s cpts=%s",
        _rid,
        time.monotonic() - wall_start_s,
        surgeon.id,
        vision_backend,
        len(payload.get("cpts") or []),
    )
    log.info(
        "vision_scan ok vision_backend=%s mode=%s orig_kb=%s small_kb=%s cpts=%s",
        vision_backend,
        scan_mode,
        orig_kb,
        small_kb,
        len(payload.get("cpts") or []),
    )
    saved_scan = None
    if do_persist:
        saved_scan = _apply_pending_scan_result(
            db=db,
            scan=pending_scan,
            payload=payload,
            cap=cap,
            locality=locality,
            facility=fac,
            cf=cf,
            ai_model=cpt_svc.vision_model,
            image_kb=small_kb,
            elapsed=elapsed,
            verified=False,
        )
    return _finalize_capture_response(
        payload=payload,
        locality=locality,
        elapsed=elapsed,
        persisted=bool(do_persist),
        scan=saved_scan,
        surgeon=surgeon,
        include_staff=True,
    )


@router.post("/reconciliation/draft")
async def reconciliation_draft(
    image: UploadFile = File(...),
    locality: str = Form("00"),
    facility: str = Form("false"),
    cf: float = Form(APP_CF_DEFAULT),
    scan_mode: str = Form("balanced"),
    mrn: Optional[str] = Form(None),
    patient_name: Optional[str] = Form(None),
    service_date: Optional[str] = Form(None),
    db: Session = Depends(get_db),
    auth: tuple[RvuStaff, object] = Depends(get_current_staff),
):
    """Return a fast, reviewable reconciliation draft without persisting."""
    surgeon, _ = auth
    image_bytes, _orig_kb, _small_kb = _prepare_uploaded_image(await image.read())
    fac = facility.lower() == "true"
    cap, _payload, elapsed, vision_backend, _mode = _run_vision_capture(
        image_bytes,
        db=db,
        locality=locality,
        facility=fac,
        cf=cf,
        scan_mode=scan_mode,
        clinician_mrn=mrn,
        clinician_patient_name=patient_name,
        clinician_service_date=service_date,
    )
    return _build_reconciliation_draft(
        cap=cap,
        surgeon=surgeon,
        provider=str(vision_backend or "unknown"),
        elapsed=elapsed,
        locality=locality,
        facility=fac,
        cf=cf,
    )

@router.post("/vision-stream")
async def vision_stream(
    image: UploadFile = File(...),
    locality: str = Form("00"),
    facility: str = Form("false"),
    cf: float = Form(APP_CF_DEFAULT),
    scan_mode: str = Form("balanced"),
    persist: str = Form("false"),
    mrn: Optional[str] = Form(None),
    patient_name: Optional[str] = Form(None),
    service_date: Optional[str] = Form(None),
    db: Session = Depends(get_db),
    auth: tuple[RvuStaff, object] = Depends(get_current_staff),
    rvu_request_id: str | None = Header(None, alias="X-RVU-Request-Id"),
):
    surgeon, _ = auth
    fac = facility.lower() == "true"
    do_persist = persist.lower() == "true"
    client_request_id = _sanitize_client_request_id(rvu_request_id)
    mode = (scan_mode or "balanced").strip().lower()

    if do_persist and client_request_id:
        existing_scan = _find_existing_request_scan(db, surgeon.id, client_request_id)
        if existing_scan is not None:
            log.info(
                "[b09ef5] vision_stream_reused req_id=%s surgeon_id=%s scan_id=%s status=%s",
                client_request_id[:64],
                surgeon.id,
                existing_scan.id,
                existing_scan.scan_status,
            )

            def generate_reuse():
                response = _finalize_capture_response(
                    payload=_saved_scan_payload(existing_scan),
                    locality=existing_scan.locality_num or locality,
                    elapsed=float(existing_scan.elapsed_secs or 0.0),
                    persisted=True,
                    scan=existing_scan,
                    surgeon=surgeon,
                    include_staff=True,
                )
                response["idempotency_reused"] = True
                yield _sse("done", response)

            return StreamingResponse(
                generate_reuse(),
                media_type="text/event-stream",
                headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
            )

    image_bytes, orig_kb, small_kb = _prepare_uploaded_image(await image.read())
    log.info("vision_stream start mode=%s image_kb=%s", mode, small_kb)

    def generate():
        yield _sse("status", {"msg": f"Resized {orig_kb} KB to {small_kb} KB; mode={mode}"})
        events: list[tuple[str, str]] = []
        vision_backend = "unknown"
        try:
            cap, payload, elapsed, vision_backend, _mode = _run_vision_capture(
                image_bytes,
                db=db,
                locality=locality,
                facility=fac,
                cf=cf,
                scan_mode=scan_mode,
                event_cb=lambda kind, msg: events.append((kind, msg)),
                clinician_mrn=mrn,
                clinician_patient_name=patient_name,
                clinician_service_date=service_date,
            )
        except HTTPException as exc:
            yield _sse("error", {"msg": str(exc.detail)})
            return
        except Exception as exc:
            yield _sse("error", {"msg": str(exc)})
            return
        for kind, msg in events:
            key = "t" if kind == "token" else "msg"
            yield _sse(kind, {key: msg})
        log.info(
            "vision_stream done vision_backend=%s mode=%s elapsed=%.2fs cpts=%s lines=%s",
            vision_backend,
            mode,
            elapsed,
            len(payload.get("cpts") or []),
            len((cap.get("lines") or [])),
        )
        saved_scan = None
        if do_persist:
            saved_scan = _persist_capture_result(
                db=db,
                surgeon=surgeon,
                payload=payload,
                cap=cap,
                locality=locality,
                facility=fac,
                cf=cf,
                ai_model=cpt_svc.vision_model,
                image_kb=small_kb,
                elapsed=elapsed,
                image_bytes=image_bytes,
                client_request_id=client_request_id,
            )
        yield _sse(
            "done",
            _finalize_capture_response(
                payload=payload,
                locality=locality,
                elapsed=elapsed,
                persisted=bool(do_persist),
                scan=saved_scan,
                surgeon=surgeon,
                include_staff=True,
            ),
        )

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )

def _scan_history_dict(s: RvuScan, surgeon: "RvuStaff | None" = None) -> dict:
    line_parsed = _parse_line_items(s.line_items)
    return {
        "id": s.id,
        "scanned_at": _iso_utc(s.scanned_at),
        "scanned_at_et": _iso_et(s.scanned_at),
        "scanned_at_label": _label_et(s.scanned_at),
        "service_date": s.service_date.isoformat() if s.service_date else None,
        "patient_name": s.patient_name,
        "mrn": s.mrn,
        "line_items": line_parsed,
        "cpts": s.cpts,
        "total_rvu": s.total_rvu,
        "total_payment": s.total_payment,
        "cf": s.cf,
        "locality_num": s.locality_num,
        "locality_name": s.locality_name,
        "facility": s.facility,
        "ai_model": s.ai_model,
        "has_image": _stored_binary_usable(s.image_data),
        "scan_status": s.scan_status or "verified",
        "status_label": _scan_status_label(s),
        "main_cpt": s.main_cpt,
        "main_cpt_status": s.main_cpt_status,
        "surgeon_name": getattr(surgeon, "full_name", None) if surgeon else None,
        "staff_type": getattr(surgeon, "staff_type", None) if surgeon else None,
        "elapsed_secs": s.elapsed_secs,
        "ocr_elapsed_label": _elapsed_label(s.elapsed_secs),
        "review_reason": _get_scan_review_reason(s),
        **_scan_financial_summary(s, line_parsed),
    }


def _scan_list_dict(s: RvuScan, surgeon: "RvuStaff | None" = None) -> dict:
    return {
        "id": s.id,
        "scanned_at": _iso_utc(s.scanned_at),
        "scanned_at_et": _iso_et(s.scanned_at),
        "scanned_at_label": _label_et(s.scanned_at),
        "service_date": s.service_date.isoformat() if s.service_date else None,
        "patient_name": s.patient_name,
        "mrn": s.mrn,
        "cpts": s.cpts,
        "total_rvu": s.total_rvu,
        "total_payment": s.total_payment,
        "cf": s.cf,
        "locality_num": s.locality_num,
        "locality_name": s.locality_name,
        "facility": s.facility,
        "ai_model": s.ai_model,
        "has_image": _stored_binary_usable(s.image_data),
        "scan_status": s.scan_status or "verified",
        "status_label": _scan_status_label(s),
        "main_cpt": s.main_cpt,
        "main_cpt_status": s.main_cpt_status,
        "surgeon_id": s.surgeon_id,
        "surgeon_name": getattr(surgeon, "full_name", None) if surgeon else None,
        "staff_type": getattr(surgeon, "staff_type", None) if surgeon else None,
        "elapsed_secs": s.elapsed_secs,
        "ocr_elapsed_label": _elapsed_label(s.elapsed_secs),
        "review_reason": _get_scan_review_reason(s),
        **_scan_financial_summary(s),
    }


@router.get("/history")
def staff_history(
    db: Session = Depends(get_db),
    auth: tuple[RvuStaff, object] = Depends(get_current_staff),
):
    surgeon, _ = auth
    scans = (
        db.query(RvuScan)
        .filter(RvuScan.surgeon_id == surgeon.id, RvuScan.scan_status == "verified")
        .order_by(desc(RvuScan.scanned_at))
        .limit(100)
        .all()
    )
    return {"scans": [_scan_history_dict(s, surgeon) for s in scans]}


@router.get("/pending")
def staff_pending_scans(
    db: Session = Depends(get_db),
    auth: tuple[RvuStaff, object] = Depends(get_current_staff),
):
    surgeon, _ = auth
    scans = (
        db.query(RvuScan)
        .filter(RvuScan.surgeon_id == surgeon.id, RvuScan.scan_status == "pending_review")
        .order_by(desc(RvuScan.scanned_at))
        .limit(100)
        .all()
    )
    return {"scans": [_entry_row_dict(s, surgeon) for s in scans]}


class ScanPatchBody(BaseModel):
    cpts: Optional[list[str]] = None
    modifiers: dict[str, str] = Field(default_factory=dict)
    lines: Optional[list[LineItemIn]] = None
    service_date: Optional[str] = None
    patient_name: Optional[str] = None
    mrn: Optional[str] = None
    locality: Optional[str] = None
    facility: Optional[bool] = None
    cf: Optional[float] = None


class ManualDraftBody(BaseModel):
    locality: Optional[str] = None
    facility: Optional[bool] = None
    cf: Optional[float] = None
    patient_name: Optional[str] = None
    mrn: Optional[str] = None
    service_date: Optional[str] = None


class SettingsBody(BaseModel):
    default_facility: bool | None = None
    cms_locality_num: str | None = None
    cf: float | None = None
    show_estimated_dollars: bool | None = None
    auto_suggest_from_scan: bool | None = None
    cloud_sync_enabled: bool | None = None


def _load_staff_scans(db: Session, surgeon_id: int) -> list[RvuScan]:
    return (
        db.query(RvuScan)
        .filter(RvuScan.surgeon_id == surgeon_id)
        .order_by(desc(RvuScan.scanned_at))
        .all()
    )


def _load_staff_op_notes(db: Session, surgeon_id: int) -> list[RvuOpNote]:
    return (
        db.query(RvuOpNote)
        .filter(RvuOpNote.surgeon_id == surgeon_id)
        .order_by(desc(RvuOpNote.scanned_at))
        .all()
    )


def _filter_notes_by_day(notes: list[RvuOpNote], target: date) -> list[RvuOpNote]:
    return [n for n in notes if n.scanned_at is not None and n.scanned_at.date() == target]


def _effective_note_day(note: RvuOpNote) -> date | None:
    if note.scanned_at is None:
        return None
    return note.scanned_at.date()


def _op_note_mobile_row(n: RvuOpNote) -> dict[str, object]:
    scanned = n.scanned_at
    disp_date = _format_mm_dd_yy(scanned.date()) if scanned else ""
    disp_time = scanned.strftime("%H:%M") if scanned else ""
    excerpt = (n.extracted_text or "").strip().replace("\n", " ")[:140]
    return {
        "id": n.id,
        "scanned_at": scanned.isoformat() if scanned else None,
        "display_date": disp_date or None,
        "display_time": disp_time or None,
        "title": "Operative note",
        "preview": excerpt,
        "image_kb": n.image_kb,
        "ai_model": n.ai_model or "",
        "elapsed_secs": n.elapsed_secs,
        "has_image": _stored_binary_usable(n.image_data),
    }


def _filter_scans_by_day(scans: list[RvuScan], target: date) -> list[RvuScan]:
    return [scan for scan in scans if _effective_scan_date(scan) == target]


def _month_label(key: str) -> str:
    return datetime.strptime(key, "%Y-%m").strftime("%B %Y")


def _build_month_summaries(scans: list[RvuScan]) -> list[dict[str, object]]:
    grouped: dict[str, dict[str, object]] = {}
    for scan in scans:
        effective = _effective_scan_date(scan)
        if effective is None:
            continue
        key = effective.strftime("%Y-%m")
        bucket = grouped.setdefault(
            key,
            {"month": key, "label": _month_label(key), "entry_count": 0, "total_wrvu": 0.0, "pending_count": 0},
        )
        if _is_verified_scan(scan):
            bucket["entry_count"] = int(bucket["entry_count"]) + 1
            bucket["total_wrvu"] = round(float(bucket["total_wrvu"]) + _scan_wrvu(scan), 2)
        elif scan.scan_status == "pending_review":
            bucket["pending_count"] = int(bucket["pending_count"]) + 1
    return sorted(grouped.values(), key=lambda item: str(item["month"]), reverse=True)


def _build_day_summaries(
    scans: list[RvuScan],
    month: str | None = None,
    notes: list[RvuOpNote] | None = None,
) -> list[dict[str, object]]:
    grouped: dict[str, dict[str, object]] = {}
    for scan in scans:
        effective = _effective_scan_date(scan)
        if effective is None:
            continue
        if month is not None and effective.strftime("%Y-%m") != month:
            continue
        key = effective.isoformat()
        bucket = grouped.setdefault(
            key,
            {
                "date": key,
                "label": _format_mm_dd_yy(effective),
                "entry_count": 0,
                "total_wrvu": 0.0,
                "pending_count": 0,
                "document_scan_count": 0,
            },
        )
        if _is_verified_scan(scan):
            bucket["entry_count"] = int(bucket["entry_count"]) + 1
            bucket["total_wrvu"] = round(float(bucket["total_wrvu"]) + _scan_wrvu(scan), 2)
        elif scan.scan_status == "pending_review":
            bucket["pending_count"] = int(bucket["pending_count"]) + 1

    for note in notes or []:
        effective = _effective_note_day(note)
        if effective is None:
            continue
        if month is not None and effective.strftime("%Y-%m") != month:
            continue
        key = effective.isoformat()
        bucket = grouped.setdefault(
            key,
            {
                "date": key,
                "label": _format_mm_dd_yy(effective),
                "entry_count": 0,
                "total_wrvu": 0.0,
                "pending_count": 0,
                "document_scan_count": 0,
            },
        )
        bucket["document_scan_count"] = int(bucket.get("document_scan_count", 0)) + 1

    return sorted(grouped.values(), key=lambda item: str(item["date"]), reverse=True)


def _period_bounds(range_key: str, today: date) -> tuple[date, date, date, date]:
    if range_key == "week":
        start = today - timedelta(days=6)
        end = today
        prev_end = start - timedelta(days=1)
        prev_start = prev_end - timedelta(days=6)
        return start, end, prev_start, prev_end
    if range_key == "ytd":
        start = date(today.year, 1, 1)
        end = today
        prev_start = date(today.year - 1, 1, 1)
        try:
            prev_end = date(today.year - 1, today.month, today.day)
        except ValueError:
            prev_end = date(today.year - 1, today.month + 1, 1) - timedelta(days=1)
        return start, end, prev_start, prev_end
    # "month" = rolling 30 calendar days (inclusive), same idea as "week"'s rolling 7d.
    # Calendar month-to-date left early-month stats empty while Week still showed recent cases.
    if range_key == "month":
        end = today
        start = today - timedelta(days=29)
        prev_end = start - timedelta(days=1)
        prev_start = prev_end - timedelta(days=29)
        return start, end, prev_start, prev_end
    raise ValueError(f"unsupported stats range: {range_key!r}")


def _sum_wrvu(scans: list[RvuScan]) -> float:
    return round(sum(_scan_wrvu(scan) for scan in scans if _is_verified_scan(scan)), 2)


def _sum_estimated_comp(scans: list[RvuScan]) -> float:
    return round(sum(_scan_wrvu(scan) * float(scan.cf or APP_CF_DEFAULT) for scan in scans if _is_verified_scan(scan)), 2)


def _trend_delta(current: float, previous: float) -> float:
    return round(current - previous, 2)


def _build_monthly_trend(scans: list[RvuScan], today: date) -> list[dict[str, object]]:
    months: list[tuple[int, int]] = []
    year = today.year
    month = today.month
    for _ in range(6):
        months.append((year, month))
        month -= 1
        if month == 0:
            month = 12
            year -= 1
    months.reverse()
    trend: list[dict[str, object]] = []
    for year, month in months:
        key = f"{year:04d}-{month:02d}"
        month_scans = [
            scan
            for scan in scans
            if _is_verified_scan(scan) and (_effective_scan_date(scan) or today).strftime("%Y-%m") == key
        ]
        trend.append(
            {
                "month": key,
                "label": datetime(year, month, 1).strftime("%b"),
                "cases": len(month_scans),
                "wrvu": _sum_wrvu(month_scans),
            }
        )
    return trend


def _build_procedure_breakdown(scans: list[RvuScan]) -> list[dict[str, object]]:
    grouped: dict[str, dict[str, object]] = {}
    for scan in scans:
        if not _is_verified_scan(scan):
            continue
        for item in _primary_line_items(_parse_line_items(scan.line_items)):
            code = str(item.get("cpt") or "").strip()
            if not code:
                continue
            bucket = grouped.setdefault(
                code,
                {
                    "cpt": code,
                    "description": str(item.get("procedure_name") or "").strip(),
                    "count": 0,
                    "wrvu": 0.0,
                },
            )
            if not bucket["description"]:
                bucket["description"] = str(item.get("procedure_name") or "").strip()
            bucket["count"] = int(bucket["count"]) + 1
            bucket["wrvu"] = round(float(bucket["wrvu"]) + float(item.get("work_rvu") or item.get("total_rvu") or 0.0), 2)
    rows = list(grouped.values())
    rows.sort(key=lambda item: (-float(item["wrvu"]), -int(item["count"]), str(item["cpt"])))
    return rows[:10]


def _build_setting_breakdown(scans: list[RvuScan]) -> list[dict[str, object]]:
    grouped = {
        "Facility": {"label": "Facility", "count": 0, "wrvu": 0.0},
        "Non-Facility": {"label": "Non-Facility", "count": 0, "wrvu": 0.0},
    }
    for scan in scans:
        if not _is_verified_scan(scan):
            continue
        key = "Facility" if bool(scan.facility) else "Non-Facility"
        grouped[key]["count"] += 1
        grouped[key]["wrvu"] = round(float(grouped[key]["wrvu"]) + _scan_wrvu(scan), 2)
    return [grouped["Facility"], grouped["Non-Facility"]]


@router.get("/settings")
def staff_get_settings(
    db: Session = Depends(get_db),
    auth: tuple[RvuStaff, object] = Depends(get_current_staff),
):
    surgeon, _ = auth
    return _settings_dict(_get_or_create_user_settings(db, surgeon.id))


@router.patch("/settings")
def staff_patch_settings(
    body: SettingsBody,
    db: Session = Depends(get_db),
    auth: tuple[RvuStaff, object] = Depends(get_current_staff),
):
    surgeon, _ = auth
    row = _get_or_create_user_settings(db, surgeon.id)
    if body.default_facility is not None:
        row.default_facility = body.default_facility
    if body.cms_locality_num is not None:
        row.cms_locality_num = body.cms_locality_num.zfill(2)
    if body.cf is not None:
        row.cf = round(float(body.cf), 2)
    if body.show_estimated_dollars is not None:
        row.show_estimated_dollars = body.show_estimated_dollars
    if body.auto_suggest_from_scan is not None:
        row.auto_suggest_from_scan = body.auto_suggest_from_scan
    if body.cloud_sync_enabled is not None:
        row.cloud_sync_enabled = body.cloud_sync_enabled
    db.commit()
    db.refresh(row)
    return _settings_dict(row)


@router.get("/today")
def staff_today_scans(
    date_value: str | None = None,
    db: Session = Depends(get_db),
    auth: tuple[RvuStaff, object] = Depends(get_current_staff),
):
    surgeon, _ = auth
    target = payment_svc.parse_service_date(date_value) if date_value else datetime.now().date()
    scans = _filter_scans_by_day(_load_staff_scans(db, surgeon.id), target)
    scans.sort(key=lambda scan: scan.scanned_at or datetime.min)
    verified_scans = [scan for scan in scans if _is_verified_scan(scan)]
    return {
        "date": target.isoformat(),
        "display_date": _format_mm_dd_yy(target),
        "entry_count": len(verified_scans),
        "total_wrvu": _sum_wrvu(verified_scans),
        "entries": [_entry_row_dict(scan, surgeon) for scan in scans],
    }


@router.get("/history/months")
def staff_history_months(
    db: Session = Depends(get_db),
    auth: tuple[RvuStaff, object] = Depends(get_current_staff),
):
    surgeon, _ = auth
    scans = _load_staff_scans(db, surgeon.id)
    return {"months": _build_month_summaries(scans)}


@router.get("/history/months/{month}/days")
def staff_history_days(
    month: str,
    db: Session = Depends(get_db),
    auth: tuple[RvuStaff, object] = Depends(get_current_staff),
):
    if not re.fullmatch(r"\d{4}-\d{2}", month):
        raise HTTPException(status_code=400, detail="Month must be YYYY-MM")
    surgeon, _ = auth
    scans = _load_staff_scans(db, surgeon.id)
    notes = _load_staff_op_notes(db, surgeon.id)
    return {
        "month": month,
        "label": _month_label(month),
        "days": _build_day_summaries(scans, month, notes),
    }


@router.get("/history/days")
def staff_history_days_index(
    db: Session = Depends(get_db),
    auth: tuple[RvuStaff, object] = Depends(get_current_staff),
):
    surgeon, _ = auth
    scans = _load_staff_scans(db, surgeon.id)
    notes = _load_staff_op_notes(db, surgeon.id)
    return {"days": _build_day_summaries(scans, None, notes)}


@router.get("/history/days/{day_value}")
def staff_history_day_detail(
    day_value: str,
    db: Session = Depends(get_db),
    auth: tuple[RvuStaff, object] = Depends(get_current_staff),
):
    target = payment_svc.parse_service_date(day_value)
    if target is None:
        raise HTTPException(status_code=400, detail="Date must be YYYY-MM-DD")
    surgeon, _ = auth
    scans = _filter_scans_by_day(_load_staff_scans(db, surgeon.id), target)
    scans.sort(key=lambda scan: scan.scanned_at or datetime.min)
    verified_scans = [scan for scan in scans if _is_verified_scan(scan)]
    notes_day = _filter_notes_by_day(_load_staff_op_notes(db, surgeon.id), target)
    notes_day.sort(key=lambda n: n.scanned_at or datetime.min)
    return {
        "date": target.isoformat(),
        "display_date": _format_mm_dd_yy(target),
        "entry_count": len(verified_scans),
        "total_wrvu": _sum_wrvu(verified_scans),
        "entries": [_entry_row_dict(scan, surgeon) for scan in scans],
        "document_scans": [_op_note_mobile_row(n) for n in notes_day],
    }


@router.get("/stats")
def staff_stats(
    range: str = "month",
    db: Session = Depends(get_db),
    auth: tuple[RvuStaff, object] = Depends(get_current_staff),
):
    surgeon, _ = auth
    settings = _get_or_create_user_settings(db, surgeon.id)
    range_key = (range or "month").strip().lower()
    if range_key not in {"week", "month", "ytd"}:
        raise HTTPException(status_code=400, detail="Range must be week, month, or ytd")
    all_scans = _load_staff_scans(db, surgeon.id)
    today = datetime.now().date()
    start, end, prev_start, prev_end = _period_bounds(range_key, today)
    period_scans = [
        scan
        for scan in all_scans
        if _is_verified_scan(scan) and (effective := _effective_scan_date(scan)) and start <= effective <= end
    ]
    previous_scans = [
        scan
        for scan in all_scans
        if _is_verified_scan(scan) and (effective := _effective_scan_date(scan)) and prev_start <= effective <= prev_end
    ]
    cases = len(period_scans)
    wrvu_total = _sum_wrvu(period_scans)
    previous_cases = len(previous_scans)
    previous_wrvu = _sum_wrvu(previous_scans)
    return {
        "range": range_key,
        "cases": cases,
        "wrvu_total": wrvu_total,
        "estimated_compensation": round(wrvu_total * float(settings.cf or APP_CF_DEFAULT), 2),
        "case_delta": _trend_delta(float(cases), float(previous_cases)),
        "wrvu_delta": _trend_delta(wrvu_total, previous_wrvu),
        "monthly_trend": _build_monthly_trend(all_scans, today),
        "procedure_breakdown": _build_procedure_breakdown(period_scans),
        "setting_breakdown": _build_setting_breakdown(period_scans),
    }


@router.get("/scans/{scan_id}")
def staff_get_scan(
    scan_id: int,
    db: Session = Depends(get_db),
    auth: tuple[RvuStaff, object] = Depends(get_current_staff),
):
    surgeon, _ = auth
    scan = db.query(RvuScan).filter(
        RvuScan.id == scan_id,
        RvuScan.surgeon_id == surgeon.id,
    ).first()
    if not scan:
        raise HTTPException(status_code=404, detail="Scan not found")
    return _entry_row_dict(scan, surgeon)

@router.post("/manual-draft")
def create_manual_draft(
    body: ManualDraftBody,
    db: Session = Depends(get_db),
    auth: tuple[RvuStaff, object] = Depends(get_current_staff),
):
    surgeon, _ = auth
    locality = (body.locality or "99").zfill(2)
    facility = bool(body.facility) if body.facility is not None else True
    cf = body.cf if body.cf is not None else APP_CF_DEFAULT
    scan = payment_svc.save_scan(
        db,
        surgeon.id,
        [],
        locality,
        payment_svc.locality_name(locality),
        facility,
        0.0,
        0.0,
        cf,
        "manual-draft",
        0,
        0.0,
        service_date=payment_svc.parse_service_date(body.service_date),
        patient_name=body.patient_name,
        mrn=body.mrn,
        line_items_json=json.dumps([]),
        scan_status="pending_review",
        main_cpt="No CPT",
        main_cpt_status="none",
        review_reason=_review_reason_from_scan_fields(
            main_cpt=None,
            main_cpt_status=None,
            patient_name=body.patient_name,
            mrn=body.mrn,
            service_date=payment_svc.parse_service_date(body.service_date),
        ),
    )
    return _scan_history_dict(scan, surgeon)


@router.patch("/scans/{scan_id}")
def patch_scan(
    scan_id: int,
    body: ScanPatchBody,
    db: Session = Depends(get_db),
    auth: tuple[RvuStaff, object] = Depends(get_current_staff),
):
    """RvuStaff edits their own scan — recalculates RVU/payment and persists."""
    surgeon, _ = auth
    scan = db.query(RvuScan).filter(
        RvuScan.id == scan_id, RvuScan.surgeon_id == surgeon.id,
    ).first()
    if not scan:
        raise HTTPException(status_code=404, detail="Scan not found")
    clean = payment_svc.clean_cpt_codes(body.cpts or [])
    locality = body.locality if body.locality is not None else (scan.locality_num or "00")
    fac = body.facility if body.facility is not None else bool(scan.facility)
    cf_val = body.cf if body.cf is not None else (scan.cf or APP_CF_DEFAULT)
    _, cpt_overrides, modifier_rules = _effective_rule_inputs(db)
    existing_lines = _parse_line_items(scan.line_items)
    request_lines = [line.model_dump() for line in body.lines] if body.lines is not None else None
    if clean:
        line_source = request_lines if request_lines is not None else _select_line_items_for_cpts(existing_lines, clean, body.modifiers)
        rows, total = (
            payment_svc.build_rows_from_lines(
                line_source,
                locality,
                fac,
                cf_val,
                cpt_overrides=cpt_overrides,
                modifier_rules=modifier_rules,
            )
            if line_source
            else payment_svc.build_rows(
                clean,
                locality,
                fac,
                cf_val,
                modifiers=body.modifiers,
                cpt_overrides=cpt_overrides,
                modifier_rules=modifier_rules,
            )
        )
        enriched = payment_svc.enrich_line_items(rows, line_source)
        total_rvu = round(sum(r["total_rvu"] for r in rows), 4)
        total_payment = round(total, 2)
        main_cpt = clean[0]
        main_cpt_status = "recognized"
    else:
        rows = []
        enriched = []
        total_rvu = 0.0
        total_payment = 0.0
        main_cpt = "No CPT"
        main_cpt_status = "none"
    if enriched:
        clean = _cpts_for_surgeon_lines(enriched) or clean
    scan.cpts = json.dumps(clean)
    if body.service_date is not None:
        scan.service_date = payment_svc.parse_service_date(body.service_date)
    if body.patient_name is not None:
        scan.patient_name = body.patient_name[:255] if body.patient_name else None
    if body.mrn is not None:
        scan.mrn = _normalized_mrn_or_none(body.mrn)
    scan.locality_num = locality
    scan.locality_name = payment_svc.locality_name(locality)
    scan.facility = fac
    scan.cf = cf_val
    scan.total_rvu = total_rvu
    scan.total_payment = total_payment
    scan.line_items = json.dumps(enriched)
    scan.main_cpt = main_cpt
    scan.main_cpt_status = main_cpt_status
    scan.review_reason = _review_reason_from_scan_fields(
        main_cpt=main_cpt,
        main_cpt_status=main_cpt_status,
        patient_name=scan.patient_name,
        mrn=scan.mrn,
        service_date=scan.service_date,
    ) if scan.scan_status == "pending_review" else None
    db.commit()
    db.refresh(scan)
    return _scan_history_dict(scan, surgeon)


@router.post("/scans/{scan_id}/verify")
def verify_scan(
    scan_id: int,
    db: Session = Depends(get_db),
    auth: tuple[RvuStaff, object] = Depends(get_current_staff),
):
    surgeon, _ = auth
    scan = db.query(RvuScan).filter(
        RvuScan.id == scan_id, RvuScan.surgeon_id == surgeon.id,
    ).first()
    if not scan:
        raise HTTPException(status_code=404, detail="Scan not found")
    missing_fields: list[str] = []
    if not str(scan.patient_name or "").strip():
        missing_fields.append("Patient Name")
    if not str(scan.mrn or "").strip():
        missing_fields.append("MRN")
    if missing_fields:
        _touch_review_reason(scan)
        db.commit()
        raise HTTPException(
            status_code=400,
            detail=f"Please enter {' and '.join(missing_fields)} before saving this entry.",
        )
    primary_lines = _primary_line_items(_parse_line_items(scan.line_items))
    if primary_lines:
        scan.total_rvu = round(sum(float(x.get("total_rvu") or 0.0) for x in primary_lines), 2)
        scan.total_payment = round(sum(float(x.get("payment") or 0.0) for x in primary_lines), 2)
    scan.scan_status = "verified"
    scan.review_reason = None
    db.commit()
    db.refresh(scan)
    return _scan_history_dict(scan, surgeon)


@router.delete("/scans/{scan_id}", status_code=204)
def delete_scan(
    scan_id: int,
    db: Session = Depends(get_db),
    auth: tuple[RvuStaff, object] = Depends(get_current_staff),
):
    """RvuStaff deletes their own scan record."""
    surgeon, _ = auth
    scan = db.query(RvuScan).filter(
        RvuScan.id == scan_id, RvuScan.surgeon_id == surgeon.id,
    ).first()
    if not scan:
        raise HTTPException(status_code=404, detail="Scan not found")
    db.query(RvuScanAiRun).filter(RvuScanAiRun.scan_id == scan_id).delete(synchronize_session=False)
    db.delete(scan)
    db.commit()
    return Response(status_code=204)


@router.get("/scans/{scan_id}/image")
def get_scan_image(
    scan_id: int,
    db: Session = Depends(get_db),
    auth: tuple[RvuStaff, object] = Depends(get_current_staff),
):
    """Return the original scan image for a surgeon's own scan."""
    surgeon, _ = auth
    scan = db.query(RvuScan).filter(
        RvuScan.id == scan_id, RvuScan.surgeon_id == surgeon.id,
    ).first()
    if not scan:
        raise HTTPException(status_code=404, detail="Scan not found")
    if not _stored_binary_usable(scan.image_data):
        raise HTTPException(status_code=404, detail="No image stored for this scan")
    return _binary_image_response(scan.image_data)


class StaffCptRulePatch(BaseModel):
    recognized: bool | None = None
    desc: str | None = None
    work_rvu: float | None = None


class StaffModifierRulePatch(BaseModel):
    factor: float | None = None
    desc: str | None = None


@router.get("/cpt-library")
def staff_list_cpt_library(
    search: str = "",
    db: Session = Depends(get_db),
    _auth: tuple[RvuStaff, object] = Depends(get_current_staff),
):
    return {"cpts": list_cpt_catalog(db, search)}


@router.patch("/cpt-library/{cpt}")
def staff_patch_cpt_library(
    cpt: str,
    body: StaffCptRulePatch,
    db: Session = Depends(get_db),
    _auth: tuple[RvuStaff, object] = Depends(get_current_staff),
):
    try:
        return patch_cpt_rule(
            db,
            cpt,
            recognized=body.recognized,
            desc=body.desc,
            work_rvu=body.work_rvu,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/modifier-library")
def staff_list_modifier_library(
    db: Session = Depends(get_db),
    _auth: tuple[RvuStaff, object] = Depends(get_current_staff),
):
    return {"modifiers": list_modifier_rules(db)}


@router.patch("/modifier-library/{code}")
def staff_patch_modifier_library(
    code: str,
    body: StaffModifierRulePatch,
    db: Session = Depends(get_db),
    _auth: tuple[RvuStaff, object] = Depends(get_current_staff),
):
    try:
        return patch_modifier_rule(db, code, factor=body.factor, desc=body.desc)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


def _op_note_dict(n: RvuOpNote, surgeon_name: str | None) -> dict:
    return {
        "id": n.id,
        "surgeon_id": n.surgeon_id,
        "surgeon_name": surgeon_name,
        "scanned_at": n.scanned_at.isoformat() if n.scanned_at else None,
        "image_kb": n.image_kb,
        "extracted_text": (n.extracted_text or "")[:20000],
        "ai_model": n.ai_model,
        "elapsed_secs": n.elapsed_secs,
        "has_image": _stored_binary_usable(n.image_data),
    }


@router.post("/op-note")
async def staff_upload_op_note(
    image: UploadFile = File(...),
    db: Session = Depends(get_db),
    auth: tuple[RvuStaff, object] = Depends(get_current_staff),
    rvu_request_id: str | None = Header(None, alias="X-RVU-Request-Id"),
):
    """Snap an operative note; vision model transcribes text and stores image + text for the portal."""
    surgeon, _ = auth
    wall_start_s = time.monotonic()
    _rid = (rvu_request_id or "-")[:64]
    raw = await image.read()
    log.info(
        "[b09ef5] op_note_begin req_id=%s surgeon_id=%s raw_kb=%s",
        _rid,
        surgeon.id,
        len(raw) // 1024,
    )
    if len(raw) > 24 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Image too large (max 24 MB)")
    text, elapsed, model, small = cpt_svc.extract_op_note_best(raw)
    kb = max(1, len(small) // 1024)
    note = RvuOpNote(
        surgeon_id=surgeon.id,
        image_data=small,
        image_kb=kb,
        extracted_text=text or None,
        ai_model=model,
        elapsed_secs=elapsed,
    )
    db.add(note)
    db.commit()
    db.refresh(note)
    log.info(
        "[b09ef5] op_note_ok req_id=%s id=%s surgeon_id=%s wall_s=%.2f ocr_s=%s model=%s text_len=%s",
        _rid,
        note.id,
        surgeon.id,
        time.monotonic() - wall_start_s,
        elapsed,
        model,
        len(text or ""),
    )
    return {
        "ok": True,
        "id": note.id,
        "extracted_text": text,
        "image_kb": kb,
        "elapsed_secs": elapsed,
        "ai_model": model,
    }


@router.get("/op-note/history")
def staff_op_note_history(
    db: Session = Depends(get_db),
    auth: tuple[RvuStaff, object] = Depends(get_current_staff),
    limit: int = 50,
):
    surgeon, _ = auth
    limit = min(max(limit, 1), 100)
    notes = (
        db.query(RvuOpNote)
        .filter(RvuOpNote.surgeon_id == surgeon.id)
        .order_by(desc(RvuOpNote.scanned_at))
        .limit(limit)
        .all()
    )
    return {"notes": [_op_note_dict(n, None) for n in notes]}


@router.get("/op-notes/{note_id}")
def staff_get_op_note_detail(
    note_id: int,
    db: Session = Depends(get_db),
    auth: tuple[RvuStaff, object] = Depends(get_current_staff),
):
    surgeon, _ = auth
    note = db.get(RvuOpNote, note_id)
    if not note or note.surgeon_id != surgeon.id:
        raise HTTPException(status_code=404, detail="Note not found")
    row = dict(_op_note_mobile_row(note))
    row["extracted_text"] = (note.extracted_text or "")[:80000]
    return row


@router.get("/op-notes/{note_id}/image")
def staff_get_op_note_image(
    note_id: int,
    db: Session = Depends(get_db),
    auth: tuple[RvuStaff, object] = Depends(get_current_staff),
):
    surgeon, _ = auth
    note = db.get(RvuOpNote, note_id)
    if not note or note.surgeon_id != surgeon.id:
        raise HTTPException(status_code=404, detail="Note not found")
    if not _stored_binary_usable(note.image_data):
        raise HTTPException(status_code=404, detail="No image for this note")
    return _binary_image_response(note.image_data)


# ── Portal (admin): aggregate scans across all staff ─────────────────────────

portal_router = APIRouter(prefix="/api/v1/portal/rvu", tags=["portal-rvu"])


def _is_dev_admin(admin) -> bool:
    allowed_users = {
        u.strip().lower()
        for u in os.environ.get("RVU_DEV_ADMIN_USERS", "").split(",")
        if u.strip()
    }
    return bool(
        (getattr(admin, "role", "") or "").lower() == "superadmin"
        or ((getattr(admin, "username", "") or "").lower() in allowed_users)
    )


class PortalCptRulePatch(BaseModel):
    recognized: bool | None = None
    desc: str | None = None
    work_rvu: float | None = None
    pe_nonfac_rvu: float | None = None
    pe_fac_rvu: float | None = None
    mp_rvu: float | None = None


class PortalModifierRulePatch(BaseModel):
    factor: float | None = None
    desc: str | None = None


@portal_router.get("/cpt-rules")
def portal_list_cpt_rules(
    db: Session = Depends(get_db),
    _admin=Depends(get_current_admin_api),
    search: str = "",
):
    return {"cpts": list_cpt_catalog(db, search)}


@portal_router.patch("/cpt-rules/{cpt}")
def portal_patch_cpt_rule(
    cpt: str,
    body: PortalCptRulePatch,
    db: Session = Depends(get_db),
    _admin=Depends(get_current_admin_api),
):
    try:
        return patch_cpt_rule(
            db,
            cpt,
            recognized=body.recognized,
            desc=body.desc,
            work_rvu=body.work_rvu,
            pe_nonfac_rvu=body.pe_nonfac_rvu,
            pe_fac_rvu=body.pe_fac_rvu,
            mp_rvu=body.mp_rvu,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@portal_router.get("/modifier-rules")
def portal_list_modifier_rules(
    db: Session = Depends(get_db),
    _admin=Depends(get_current_admin_api),
):
    return {"modifiers": list_modifier_rules(db)}


@portal_router.patch("/modifier-rules/{code}")
def portal_patch_modifier_rule_endpoint(
    code: str,
    body: PortalModifierRulePatch,
    db: Session = Depends(get_db),
    _admin=Depends(get_current_admin_api),
):
    try:
        return patch_modifier_rule(db, code, factor=body.factor, desc=body.desc)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@portal_router.get("/scans")
def portal_all_scans(
    db: Session = Depends(get_db),
    _admin=Depends(get_current_admin_api),
    limit: int = 100,
    offset: int = 0,
):
    limit = min(max(limit, 1), 250)
    offset = max(offset, 0)
    total_count = db.query(func.count(RvuScan.id)).scalar() or 0
    rows = (
        db.query(RvuScan, RvuStaff)
        .outerjoin(RvuStaff, RvuStaff.id == RvuScan.surgeon_id)
        .order_by(desc(RvuScan.scanned_at))
        .offset(offset)
        .limit(limit)
        .all()
    )
    scans = [_scan_list_dict(scan, surgeon) for scan, surgeon in rows]
    return {
        "scans": scans,
        "limit": limit,
        "offset": offset,
        "total_count": total_count,
        "has_more": (offset + len(scans)) < total_count,
    }


@portal_router.get("/scans/{scan_id}")
def portal_scan_detail(
    scan_id: int,
    db: Session = Depends(get_db),
    _admin=Depends(get_current_admin_api),
):
    row = (
        db.query(RvuScan, RvuStaff)
        .outerjoin(RvuStaff, RvuStaff.id == RvuScan.surgeon_id)
        .filter(RvuScan.id == scan_id)
        .first()
    )
    if not row:
        raise HTTPException(status_code=404, detail="Scan not found")
    scan, surgeon = row
    detail = _scan_history_dict(scan, surgeon)
    detail["surgeon_id"] = scan.surgeon_id
    return detail


@portal_router.get("/scans/{scan_id}/ai-runs")
def portal_scan_ai_runs(
    scan_id: int,
    db: Session = Depends(get_db),
    _admin=Depends(get_current_admin_api),
):
    scan = db.get(RvuScan, scan_id)
    if not scan:
        raise HTTPException(status_code=404, detail="Scan not found")
    runs = (
        db.query(RvuScanAiRun)
        .filter(RvuScanAiRun.scan_id == scan_id)
        .order_by(RvuScanAiRun.sequence_num.asc(), RvuScanAiRun.id.asc())
        .all()
    )
    return {"scan_id": scan_id, "ai_runs": [_scan_ai_run_dict(run) for run in runs]}


@portal_router.get("/scans/{scan_id}/image")
def portal_scan_image(
    scan_id: int,
    thumb: bool = False,
    db: Session = Depends(get_db),
    _admin=Depends(get_current_admin_api),
):
    scan = db.get(RvuScan, scan_id)
    if not scan or not _stored_binary_usable(scan.image_data):
        raise HTTPException(status_code=404, detail="No image for this scan")
    data = scan.image_data
    if thumb:
        try:
            data = cpt_svc.shrink_image(scan.image_data, max_dim=160)
        except Exception:
            data = scan.image_data
    return _binary_image_response(data)


class ScanPatch(BaseModel):
    service_date: str | None = None   # "YYYY-MM-DD" or null
    patient_name: str | None = None
    mrn: str | None = None
    locality_num: str | None = None
    locality_name: str | None = None
    facility: bool | None = None
    cpts: list[str] | None = None     # replaces stored cpts JSON
    modifiers: dict[str, str] | None = None
    line_items: list[dict] | None = None


@portal_router.patch("/scans/{scan_id}")
def portal_patch_scan(
    scan_id: int,
    body: ScanPatch,
    db: Session = Depends(get_db),
    _admin=Depends(get_current_admin_api),
):
    scan = db.get(RvuScan, scan_id)
    if not scan:
        raise HTTPException(status_code=404, detail="Scan not found")

    if body.service_date is not None:
        scan.service_date = payment_svc.parse_service_date(body.service_date)
    if body.patient_name is not None:
        scan.patient_name = body.patient_name[:255] if body.patient_name else None
    if body.mrn is not None:
        scan.mrn = _normalized_mrn_or_none(body.mrn)
    if body.locality_num is not None:
        scan.locality_num = body.locality_num
    if body.locality_name is not None:
        scan.locality_name = body.locality_name
    if body.facility is not None:
        scan.facility = body.facility
    current_cpts: list[str] | None = None
    should_recalc = any(
        value is not None
        for value in (body.cpts, body.modifiers, body.line_items, body.locality_num, body.locality_name, body.facility)
    )
    if body.cpts is not None:
        current_cpts = payment_svc.clean_cpt_codes(body.cpts)
        scan.cpts = json.dumps(current_cpts)
    elif body.line_items is not None:
        current_cpts = payment_svc.clean_cpt_codes(
            [
                str(item.get("cpt") or "").strip()
                for item in body.line_items
                if isinstance(item, dict)
                and not bool(item.get("is_assist"))
                and "AS" not in str(item.get("modifier") or "").upper()
            ]
        )
        scan.cpts = json.dumps(current_cpts)
    elif should_recalc:
        try:
            current_cpts = payment_svc.clean_cpt_codes(json.loads(scan.cpts or "[]"))
        except json.JSONDecodeError:
            current_cpts = []

    if should_recalc:
        existing_lines: list[dict] = []
        if body.line_items is not None:
            existing_lines = [row for row in body.line_items if isinstance(row, dict)]
        elif scan.line_items:
            try:
                parsed = json.loads(scan.line_items)
                if isinstance(parsed, list):
                    existing_lines = [row for row in parsed if isinstance(row, dict)]
            except json.JSONDecodeError:
                existing_lines = []

        clean = current_cpts or []
        if clean:
            _, cpt_overrides, modifier_rules = _effective_rule_inputs(db)
            modifiers = (
                body.modifiers
                if body.modifiers is not None
                else _extract_modifiers(existing_lines)
            )
            merged_lines = _select_line_items_for_cpts(existing_lines, clean, modifiers if body.modifiers is not None else None)
            rows, total = (
                payment_svc.build_rows_from_lines(
                    merged_lines,
                    scan.locality_num or "00",
                    scan.facility or False,
                    scan.cf or APP_CF_DEFAULT,
                    cpt_overrides=cpt_overrides,
                    modifier_rules=modifier_rules,
                )
                if merged_lines
                else payment_svc.build_rows(
                    clean,
                    scan.locality_num or "00",
                    scan.facility or False,
                    scan.cf or APP_CF_DEFAULT,
                    modifiers=modifiers,
                    cpt_overrides=cpt_overrides,
                    modifier_rules=modifier_rules,
                )
            )
            scan.total_rvu = round(sum(r.get("total_rvu", 0) for r in rows), 2)
            scan.total_payment = round(total, 2)
            if body.locality_num is not None and body.locality_name is None:
                scan.locality_name = payment_svc.locality_name(scan.locality_num or "00")
            merged_enriched = payment_svc.enrich_line_items(rows, merged_lines)
            scan.line_items = json.dumps(merged_enriched)
            synced_portal = _cpts_for_surgeon_lines(merged_enriched)
            if synced_portal:
                scan.cpts = json.dumps(synced_portal)
        else:
            scan.total_rvu = 0.0
            scan.total_payment = 0.0
            scan.line_items = json.dumps([])

    db.commit()
    db.refresh(scan)
    sur = db.get(RvuStaff, scan.surgeon_id)
    row = _scan_history_dict(scan)
    row["surgeon_id"] = scan.surgeon_id
    row["surgeon_name"] = sur.full_name if sur else None
    row["staff_type"] = sur.staff_type if sur else None
    return row


@portal_router.delete("/scans/{scan_id}", status_code=204)
def portal_delete_scan(
    scan_id: int,
    db: Session = Depends(get_db),
    _admin=Depends(get_current_admin_api),
):
    scan = db.get(RvuScan, scan_id)
    if not scan:
        raise HTTPException(status_code=404, detail="Scan not found")
    db.query(RvuScanAiRun).filter(RvuScanAiRun.scan_id == scan_id).delete(synchronize_session=False)
    db.delete(scan)
    db.commit()


@portal_router.get("/op-notes")
def portal_list_op_notes(
    db: Session = Depends(get_db),
    _admin=Depends(get_current_admin_api),
    limit: int = 200,
):
    limit = min(max(limit, 1), 500)
    notes = db.query(RvuOpNote).order_by(desc(RvuOpNote.scanned_at)).limit(limit).all()
    out = []
    for n in notes:
        sur = db.get(RvuStaff, n.surgeon_id)
        out.append(_op_note_dict(n, sur.full_name if sur else None))
    return {"notes": out}


@portal_router.get("/op-notes/{note_id}/image")
def portal_op_note_image(
    note_id: int,
    db: Session = Depends(get_db),
    _admin=Depends(get_current_admin_api),
):
    note = db.get(RvuOpNote, note_id)
    if not note or not _stored_binary_usable(note.image_data):
        raise HTTPException(status_code=404, detail="No image for this note")
    return _binary_image_response(note.image_data)


@portal_router.delete("/op-notes/{note_id}", status_code=204)
def portal_delete_op_note(
    note_id: int,
    db: Session = Depends(get_db),
    _admin=Depends(get_current_admin_api),
):
    note = db.get(RvuOpNote, note_id)
    if not note:
        raise HTTPException(status_code=404, detail="Not found")
    db.delete(note)
    db.commit()


@portal_router.get("/dev/vision-config")
def dev_get_vision_config(
    admin=Depends(get_current_admin_api),
):
    if not _is_dev_admin(admin):
        raise HTTPException(status_code=403, detail="Developer admin access required")
    return cpt_svc.get_vision_config()


@portal_router.patch("/dev/vision-config")
def dev_set_vision_config(
    body: VisionConfigPatch,
    admin=Depends(get_current_admin_api),
):
    if not _is_dev_admin(admin):
        raise HTTPException(status_code=403, detail="Developer admin access required")
    try:
        return cpt_svc.set_vision_config(
            provider=body.provider,
            model=body.vision_model,
            openai_api_key=body.openai_api_key,
            anthropic_api_key=body.anthropic_api_key,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
