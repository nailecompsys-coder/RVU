"""RVU / Medicare payment calculations — wraps fee-schedule lookup."""
from __future__ import annotations

import json
import os
import re
import uuid
from dataclasses import asdict, is_dataclass
from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.models_rvu import RvuScan
from app.rvu.lookup import CF_2026, RvuRow, calc_payment, get_localities

APP_CF_DEFAULT = float(os.environ.get("RVU_DEFAULT_CF", "41.0"))


def _normalize_modifier_text(value: str) -> str:
    parts = [
        re.sub(r"[^A-Z0-9]", "", p.strip().upper())
        for p in str(value or "").replace("/", ",").split(",")
        if p.strip()
    ]
    return ",".join(dict.fromkeys(p for p in parts if p))


def _normalize_units(value: Any) -> int:
    try:
        units = int(str(value).strip())
    except (TypeError, ValueError, AttributeError):
        return 1
    return units if units > 0 else 1


def _apply_units_multiplier(row: dict[str, Any], units: int) -> dict[str, Any]:
    if units <= 1:
        return row
    scaled = dict(row)
    scaled["units"] = units
    scaled["quantity"] = units
    for key in (
        "work_rvu",
        "pe_rvu",
        "mp_rvu",
        "total_rvu",
        "work_payment",
        "pe_payment",
        "mp_payment",
        "payment",
    ):
        scaled[key] = round(float(scaled.get(key) or 0) * units, 2)
    return scaled


class RvuPaymentService:
    """Build CPT payment rows and persist scan history."""

    @staticmethod
    def clean_cpt_codes(codes: list[str]) -> list[str]:
        return [c.strip() for c in codes if re.fullmatch(r"\d{5}", (c or "").strip())]

    def build_rows(
        self,
        cpts: list[str],
        locality: str,
        facility: bool,
        cf: float,
        modifiers: dict[str, str] | None = None,
        quantities: dict[str, int] | None = None,
        cpt_overrides: dict[str, RvuRow] | None = None,
        modifier_rules: dict[str, dict[str, object]] | None = None,
        cpt_catalog: dict[str, dict[str, Any]] | None = None,
    ) -> tuple[list[dict[str, Any]], float]:
        rows: list[dict[str, Any]] = []
        for cpt in cpts:
            mod = _normalize_modifier_text((modifiers or {}).get(cpt, ""))
            r = calc_payment(
                cpt,
                locality,
                facility,
                cf,
                modifier=mod,
                rvu_override=(cpt_overrides or {}).get(cpt),
                modifier_rules=modifier_rules,
            )
            row = r.to_dict()
            rule_entry = (cpt_catalog or {}).get(cpt, {})
            row["has_override"] = bool(rule_entry.get("has_override"))
            row["override_source"] = rule_entry.get("override_source")
            row["cpt_status"] = rule_entry.get("status")
            row["multiple_procedure_factor"] = 1.0
            rows.append(row)
        ranked_indexes = [
            idx for idx, row in enumerate(rows)
            if "AS" not in str(row.get("modifier") or "").upper()
        ]
        ranked_indexes.sort(key=lambda idx: float(rows[idx].get("work_rvu") or 0), reverse=True)
        if len(ranked_indexes) > 1:
            for idx in ranked_indexes[1:]:
                row = rows[idx]
                factor = 0.5
                row["multiple_procedure_factor"] = factor
                row["work_rvu"] = round(float(row.get("work_rvu") or 0) * factor, 2)
                row["pe_rvu"] = round(float(row.get("pe_rvu") or 0) * factor, 2)
                row["mp_rvu"] = round(float(row.get("mp_rvu") or 0) * factor, 2)
                row["total_rvu"] = round(float(row.get("total_rvu") or 0) * factor, 2)
                row["work_payment"] = round(float(row.get("work_payment") or 0) * factor, 2)
                row["pe_payment"] = round(float(row.get("pe_payment") or 0) * factor, 2)
                row["mp_payment"] = round(float(row.get("mp_payment") or 0) * factor, 2)
                row["payment"] = round(float(row.get("payment") or 0) * factor, 2)
        if quantities:
            for idx, cpt in enumerate(cpts):
                rows[idx] = _apply_units_multiplier(rows[idx], _normalize_units(quantities.get(cpt)))
        total = round(sum(float(row.get("payment") or 0) for row in rows), 2)
        return rows, total

    def build_rows_from_lines(
        self,
        lines: list[dict[str, Any]],
        locality: str,
        facility: bool,
        cf: float,
        *,
        cpt_overrides: dict[str, RvuRow] | None = None,
        modifier_rules: dict[str, dict[str, object]] | None = None,
        cpt_catalog: dict[str, dict[str, Any]] | None = None,
    ) -> tuple[list[dict[str, Any]], float]:
        rows: list[dict[str, Any]] = []
        row_units: list[int] = []
        for line in lines:
            if not isinstance(line, dict):
                continue
            cpt = str(line.get("cpt") or "").strip()
            if not re.fullmatch(r"\d{5}", cpt):
                continue
            units = _normalize_units(line.get("units", line.get("quantity")))
            modifier = _normalize_modifier_text(str(line.get("modifier") or ""))
            role = str(line.get("provider_role") or "").strip().lower()
            is_assist = bool(line.get("is_assist")) or role in ("pa", "assistant") or "AS" in modifier
            if is_assist and "AS" not in modifier:
                continue
            r = calc_payment(
                cpt,
                locality,
                facility,
                cf,
                modifier=modifier,
                rvu_override=(cpt_overrides or {}).get(cpt),
                modifier_rules=modifier_rules,
            )
            row = r.to_dict()
            rule_entry = (cpt_catalog or {}).get(cpt, {})
            row["has_override"] = bool(rule_entry.get("has_override"))
            row["override_source"] = rule_entry.get("override_source")
            row["cpt_status"] = rule_entry.get("status")
            row["multiple_procedure_factor"] = 1.0
            rows.append(row)
            row_units.append(units)
        ranked_indexes = [
            idx for idx, row in enumerate(rows)
            if "AS" not in str(row.get("modifier") or "").upper()
        ]
        ranked_indexes.sort(key=lambda idx: float(rows[idx].get("work_rvu") or 0), reverse=True)
        if len(ranked_indexes) > 1:
            for idx in ranked_indexes[1:]:
                row = rows[idx]
                factor = 0.5
                row["multiple_procedure_factor"] = factor
                row["work_rvu"] = round(float(row.get("work_rvu") or 0) * factor, 2)
                row["pe_rvu"] = round(float(row.get("pe_rvu") or 0) * factor, 2)
                row["mp_rvu"] = round(float(row.get("mp_rvu") or 0) * factor, 2)
                row["total_rvu"] = round(float(row.get("total_rvu") or 0) * factor, 2)
                row["work_payment"] = round(float(row.get("work_payment") or 0) * factor, 2)
                row["pe_payment"] = round(float(row.get("pe_payment") or 0) * factor, 2)
                row["mp_payment"] = round(float(row.get("mp_payment") or 0) * factor, 2)
                row["payment"] = round(float(row.get("payment") or 0) * factor, 2)
        for idx, units in enumerate(row_units):
            rows[idx] = _apply_units_multiplier(rows[idx], units)
        total = round(sum(float(row.get("payment") or 0) for row in rows), 2)
        return rows, total

    def locality_name(self, locality: str) -> str:
        locs = get_localities()
        return next((l.locality_name for l in locs if l.locality_num == locality), locality)

    @staticmethod
    def enrich_line_items(
        rows: list[dict[str, Any]],
        lines: list[dict[str, Any]] | None,
    ) -> list[dict[str, Any]]:
        """Attach procedure_name from client lines (by CPT); fee-schedule desc as fallback."""
        def _clean_provider_name(name: str) -> str:
            n = str(name or "").strip()
            if not n:
                return ""
            # If OCR prepends procedure words, keep trailing person-like name.
            m = re.search(r"([A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,3})$", n)
            return m.group(1) if m else n

        def _pa_name_from_text(text: str) -> str:
            t = str(text or "")
            m = re.search(r"([A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,3})\s*,?\s*PA(?:-C)?\b", t)
            return m.group(1).strip() if m else ""

        name_by_cpt: dict[str, str] = {}
        primary_meta_by_cpt: dict[str, dict[str, str]] = {}
        fallback_surgeon_name = ""
        explicit_assist_cpts: set[str] = set()
        ocr_primary_queue: list[dict[str, Any]] = []
        line_meta_queue: list[dict[str, Any]] = []
        if lines:
            for L in lines:
                if not isinstance(L, dict):
                    continue
                cpt = str(L.get("cpt") or "").strip()
                if re.fullmatch(r"\d{5}", cpt):
                    proc = str(L.get("procedure_name") or "").strip()
                    if proc:
                        name_by_cpt[cpt] = proc
                    role = str(L.get("provider_role") or "").strip().lower()
                    modifier = _normalize_modifier_text(str(L.get("modifier") or ""))
                    is_assist = bool(L.get("is_assist")) or role in ("pa", "assistant") or "AS" in modifier
                    pname = _clean_provider_name(str(L.get("provider_name") or "").strip())
                    if is_assist:
                        explicit_assist_cpts.add(cpt)
                    line_sd = None
                    for key in ("line_service_date", "service_date", "dos", "date_of_service", "charge_date"):
                        v = L.get(key)
                        if v:
                            line_sd = RvuPaymentService.coerce_service_date_iso(str(v))
                            if line_sd:
                                break
                    line_meta_queue.append(
                        {
                            "cpt": cpt,
                            "provider_name": pname,
                            "provider_role": role if role in ("pa", "assistant", "surgeon") else "unknown",
                            "modifier": modifier,
                            "is_assist": is_assist,
                            "line_service_date": line_sd,
                            "line_service_datetime_raw": str(L.get("line_service_datetime_raw") or "").strip(),
                            "line_service_time_raw": str(L.get("line_service_time_raw") or "").strip(),
                            "quantity": L.get("units", L.get("quantity")),
                            "raw_row_text": str(L.get("raw_row_text") or "").strip(),
                        }
                    )
                    if not is_assist:
                        # Keep surgeon modifiers but strip AS token if OCR noise includes it.
                        mod_parts = [p.strip() for p in modifier.split(",") if p.strip()]
                        mod_parts = [p for p in mod_parts if p != "AS"]
                        clean_modifier = ",".join(mod_parts)
                        primary_meta_by_cpt[cpt] = {
                            "provider_name": pname,
                            "provider_role": "surgeon",
                            "modifier": clean_modifier,
                        }
                        if pname and not fallback_surgeon_name:
                            fallback_surgeon_name = pname
                        ocr_primary_queue.append(
                            {
                                "cpt": cpt,
                                "provider_name": pname,
                                "provider_role": "surgeon",
                                "modifier": clean_modifier,
                                "line_service_date": line_sd,
                                "line_service_datetime_raw": str(L.get("line_service_datetime_raw") or "").strip(),
                                "line_service_time_raw": str(L.get("line_service_time_raw") or "").strip(),
                                "quantity": L.get("units", L.get("quantity")),
                                "raw_row_text": str(L.get("raw_row_text") or "").strip(),
                            }
                        )
        out: list[dict[str, Any]] = []
        row_lookup = {
            str(row.get("cpt") or "").strip(): row
            for row in rows
            if str(row.get("cpt") or "").strip()
        }
        paid_assist_mod_keys: set[tuple[str, str]] = set()
        for row in rows:
            cpt = row.get("cpt", "")
            row_modifier = _normalize_modifier_text(str(row.get("modifier") or ""))
            proc = name_by_cpt.get(cpt, "") or str(row.get("desc") or "")
            meta = primary_meta_by_cpt.get(cpt, {})
            picked: dict[str, Any] | None = None
            for i, item in enumerate(ocr_primary_queue):
                if item.get("cpt") == cpt:
                    picked = ocr_primary_queue.pop(i)
                    break
            if picked is None:
                fallback_index: int | None = None
                for i, item in enumerate(line_meta_queue):
                    if item.get("cpt") != cpt:
                        continue
                    if str(item.get("modifier") or "") == row_modifier:
                        fallback_index = i
                        break
                    if fallback_index is None:
                        fallback_index = i
                if fallback_index is not None:
                    picked = line_meta_queue.pop(fallback_index)
            if picked is not None:
                pname = str(picked.get("provider_name") or "") or fallback_surgeon_name
                prole = str(picked.get("provider_role") or "surgeon") or "surgeon"
                pmod = str(picked.get("modifier") or "")
                line_sd = picked.get("line_service_date")
                line_dt_raw = str(picked.get("line_service_datetime_raw") or "").strip()
                line_time_raw = str(picked.get("line_service_time_raw") or "").strip()
                quantity = picked.get("quantity")
                raw_row_text = str(picked.get("raw_row_text") or "").strip()
            else:
                pname = meta.get("provider_name", "") or fallback_surgeon_name
                prole = meta.get("provider_role", "surgeon") or "surgeon"
                pmod = meta.get("modifier", "")
                line_sd = None
                line_dt_raw = ""
                line_time_raw = ""
                quantity = None
                raw_row_text = ""
            is_assist_row = bool(picked and picked.get("is_assist")) or "AS" in (pmod or row_modifier).split(",")
            out_line: dict[str, Any] = {
                "cpt": cpt,
                "procedure_name": proc,
                "provider_name": pname,
                "provider_role": prole,
                "modifier": pmod or row.get("modifier", ""),
                "modifier_code": row.get("modifier_code", ""),
                "modifier_factor": row.get("modifier_factor", 1.0),
                "modifier_desc": row.get("modifier_desc", ""),
                "multiple_procedure_factor": row.get("multiple_procedure_factor", 1.0),
                "is_assist": is_assist_row,
                "work_rvu": row.get("work_rvu"),
                "pe_rvu": row.get("pe_rvu"),
                "pe_nonfac_rvu": row.get("pe_nonfac_rvu"),
                "pe_fac_rvu": row.get("pe_fac_rvu"),
                "mp_rvu": row.get("mp_rvu"),
                "pw_gpci": row.get("pw_gpci"),
                "pe_gpci": row.get("pe_gpci"),
                "mp_gpci": row.get("mp_gpci"),
                "total_rvu": row.get("total_rvu"),
                "work_payment": row.get("work_payment"),
                "pe_payment": row.get("pe_payment"),
                "mp_payment": row.get("mp_payment"),
                "payment": round(float(row.get("payment") or 0), 2),
            }
            if line_sd:
                out_line["line_service_date"] = line_sd
            if line_dt_raw:
                out_line["line_service_datetime_raw"] = line_dt_raw
            if line_time_raw:
                out_line["line_service_time_raw"] = line_time_raw
            if quantity not in (None, ""):
                out_line["quantity"] = quantity
                out_line["units"] = _normalize_units(quantity)
            if raw_row_text:
                out_line["raw_row_text"] = raw_row_text
            out.append(out_line)
            if is_assist_row:
                paid_assist_mod_keys.add((str(cpt), _normalize_modifier_text(str(out_line.get("modifier") or ""))))
        # Keep assistant/PA lines from OCR/text for auditing, but do not add to surgeon payment totals.
        if lines:
            for L in lines:
                if not isinstance(L, dict):
                    continue
                cpt = str(L.get("cpt") or "").strip()
                if not re.fullmatch(r"\d{5}", cpt):
                    continue
                role = str(L.get("provider_role") or "unknown").strip().lower()
                line_modifier = _normalize_modifier_text(str(L.get("modifier") or ""))
                is_assist = bool(L.get("is_assist")) or role in ("pa", "assistant") or "AS" in line_modifier
                if not is_assist:
                    continue
                if (cpt, line_modifier) in paid_assist_mod_keys:
                    continue
                assist_sd = None
                for key in ("line_service_date", "service_date", "dos", "date_of_service", "charge_date"):
                    v = L.get(key)
                    if v:
                        assist_sd = RvuPaymentService.coerce_service_date_iso(str(v))
                        if assist_sd:
                            break
                assist_row: dict[str, Any] = {
                    "cpt": cpt,
                    "procedure_name": str(L.get("procedure_name") or "").strip(),
                    "provider_name": _clean_provider_name(str(L.get("provider_name") or "").strip()),
                    "provider_role": role if role in ("pa", "assistant", "surgeon") else "unknown",
                    "modifier": line_modifier,
                    "is_assist": True,
                    "work_rvu": round(float((row_lookup.get(cpt) or {}).get("work_rvu") or 0) * 0.2, 2),
                    "total_rvu": round(float((row_lookup.get(cpt) or {}).get("work_rvu") or 0) * 0.2, 2),
                    "payment": round(float((row_lookup.get(cpt) or {}).get("work_payment") or 0) * 0.2, 2),
                }
                if assist_sd:
                    assist_row["line_service_date"] = assist_sd
                if str(L.get("line_service_datetime_raw") or "").strip():
                    assist_row["line_service_datetime_raw"] = str(L.get("line_service_datetime_raw") or "").strip()
                if str(L.get("line_service_time_raw") or "").strip():
                    assist_row["line_service_time_raw"] = str(L.get("line_service_time_raw") or "").strip()
                if str(L.get("raw_row_text") or "").strip():
                    assist_row["raw_row_text"] = str(L.get("raw_row_text") or "").strip()
                if L.get("quantity") not in (None, ""):
                    assist_row["quantity"] = L.get("quantity")
                    assist_row["units"] = _normalize_units(L.get("quantity"))
                out.append(assist_row)
        # If OCR missed explicit AS but PA is present in row text, synthesize an audit assist row.
        if lines:
            existing_assist_keys = {
                f"{str(x.get('cpt') or '').strip()}::{str(x.get('provider_name') or '').strip().lower()}"
                for x in out
                if bool(x.get("is_assist"))
            }
            for L in lines:
                if not isinstance(L, dict):
                    continue
                cpt = str(L.get("cpt") or "").strip()
                if not re.fullmatch(r"\d{5}", cpt):
                    continue
                if cpt in explicit_assist_cpts:
                    continue
                proc = str(L.get("procedure_name") or "")
                if not re.search(r"\bPA(?:-C)?\b", proc, re.I):
                    continue
                pa_name = _pa_name_from_text(proc) or _clean_provider_name(str(L.get("provider_name") or "").strip())
                key = f"{cpt}::{pa_name.strip().lower()}"
                if not pa_name or key in existing_assist_keys:
                    continue
                out.append(
                    {
                        "cpt": cpt,
                        "procedure_name": proc.strip(),
                        "provider_name": pa_name,
                        "provider_role": "pa",
                        "modifier": "AS",
                        "is_assist": True,
                        "work_rvu": round(float((row_lookup.get(cpt) or {}).get("work_rvu") or 0) * 0.2, 2),
                        "total_rvu": round(float((row_lookup.get(cpt) or {}).get("work_rvu") or 0) * 0.2, 2),
                        "payment": round(float((row_lookup.get(cpt) or {}).get("work_payment") or 0) * 0.2, 2),
                    }
                )
                existing_assist_keys.add(key)
        for item in out:
            if isinstance(item, dict) and not str(item.get("line_id") or "").strip():
                item["line_id"] = str(uuid.uuid4())
        return out

    @staticmethod
    def coerce_service_date_iso(s: str | None) -> str | None:
        """Normalize common US / ISO date strings to YYYY-MM-DD, or None."""
        if not s:
            return None
        t = str(s).strip().strip('"').strip("'")
        if not t:
            return None
        # YYYY-MM-DD (allow single-digit month/day)
        m = re.fullmatch(r"(\d{4})-(\d{1,2})-(\d{1,2})", t)
        if m:
            y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
            try:
                datetime(y, mo, d)
                return f"{y:04d}-{mo:02d}-{d:02d}"
            except ValueError:
                return None
        # M/D/YYYY or MM/DD/YYYY (charge screens)
        m = re.fullmatch(r"(\d{1,2})/(\d{1,2})/(\d{4})", t)
        if m:
            mo, d, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
            try:
                datetime(y, mo, d)
                return f"{y:04d}-{mo:02d}-{d:02d}"
            except ValueError:
                return None
        # M-D-YYYY
        m = re.fullmatch(r"(\d{1,2})-(\d{1,2})-(\d{4})", t)
        if m:
            mo, d, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
            try:
                datetime(y, mo, d)
                return f"{y:04d}-{mo:02d}-{d:02d}"
            except ValueError:
                return None
        # Embedded date inside a larger timestamp/text value like "5/11/2026 10:43 AM"
        m = re.search(r"(\d{1,2}[/-]\d{1,2}[/-]\d{4})", t)
        if m and m.group(1) != t:
            return RvuPaymentService.coerce_service_date_iso(m.group(1))
        return None

    @staticmethod
    def parse_service_date(s: str | None) -> date | None:
        iso = RvuPaymentService.coerce_service_date_iso(s)
        if not iso:
            return None
        try:
            y, mth, d = iso.split("-")
            return date(int(y), int(mth), int(d))
        except (ValueError, TypeError):
            return None

    def save_scan(
        self,
        db: Session,
        surgeon_id: int,
        cpts: list[str],
        locality: str,
        locality_name: str,
        facility: bool,
        total_rvu: float,
        total_payment: float,
        cf: float,
        model: str,
        image_kb: int,
        elapsed: float,
        service_date: date | None = None,
        patient_name: str | None = None,
        mrn: str | None = None,
        line_items_json: str | None = None,
        image_bytes: bytes | None = None,
        scan_status: str = "verified",
        main_cpt: str | None = None,
        main_cpt_status: str | None = None,
        review_reason: str | None = None,
        client_request_id: str | None = None,
    ) -> RvuScan:
        scan = RvuScan(
            surgeon_id=surgeon_id,
            scanned_at=datetime.now(timezone.utc),
            cpts=json.dumps(cpts),
            locality_num=locality,
            locality_name=locality_name,
            facility=facility,
            total_rvu=round(total_rvu, 2),
            total_payment=round(total_payment, 2),
            cf=cf,
            ai_model=model,
            image_kb=image_kb,
            elapsed_secs=round(elapsed, 1),
            service_date=service_date,
            patient_name=(patient_name[:255] if patient_name else None),
            mrn=(mrn[:64] if mrn else None),
            line_items=line_items_json,
            image_data=image_bytes,
            scan_status=scan_status,
            main_cpt=(main_cpt[:32] if main_cpt else None),
            main_cpt_status=(main_cpt_status[:16] if main_cpt_status else None),
            review_reason=(review_reason[:255] if review_reason else None),
            client_request_id=(client_request_id[:128] if client_request_id else None),
        )
        db.add(scan)
        db.commit()
        db.refresh(scan)
        return scan

    def localities_payload(self) -> dict[str, Any]:
        locs = get_localities()
        return {
            "localities": [asdict(loc) if is_dataclass(loc) else vars(loc) for loc in locs],
            "cf": APP_CF_DEFAULT,
        }
