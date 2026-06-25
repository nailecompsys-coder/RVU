"""Portal-managed CPT recognition and modifier rule overrides."""
from __future__ import annotations

import json
import re
from dataclasses import asdict
from functools import lru_cache
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.models_identity import RvuRuleConfig
from app.models_rvu import RvuScan
from app.rvu.lookup import (
    COMMERCIAL_CONSULT_OVERRIDES,
    DEFAULT_MODIFIER_DESC,
    DEFAULT_MODIFIER_FACTORS,
    PRACTICE_RVU_OVERRIDES,
    RvuRow,
    get_base_rvu_catalog,
    get_rvu_catalog,
)

CPT_RULE_CONFIG_ID = "rvu_cpt_rules"
MODIFIER_RULE_CONFIG_ID = "rvu_modifier_rules"


@lru_cache(maxsize=1)
def _general_surgery_focus_cpts() -> set[str]:
    path = Path(__file__).resolve().parents[1] / "rvu" / "data" / "general_surgery_cpts.json"
    try:
        raw = json.loads(path.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return set()
    if not isinstance(raw, list):
        return set()
    return {
        code
        for code in (_clean_cpt(item) for item in raw)
        if len(code) == 5
    }


def _load_rule_config(db: Session, rule_id: str) -> dict[str, Any]:
    row = db.query(RvuRuleConfig).filter(RvuRuleConfig.rule_id == rule_id).first()
    if not row or not row.config:
        return {}
    try:
        parsed = json.loads(row.config)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _save_rule_config(db: Session, rule_id: str, payload: dict[str, Any]) -> None:
    row = db.query(RvuRuleConfig).filter(RvuRuleConfig.rule_id == rule_id).first()
    if not row:
        row = RvuRuleConfig(rule_id=rule_id, enabled=True, config="{}")
        db.add(row)
    row.enabled = True
    row.config = json.dumps(payload, sort_keys=True)
    db.commit()


def _clean_cpt(code: str) -> str:
    return re.sub(r"[^\d]", "", str(code or "").strip())[:5]


def _clean_modifier_code(code: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", str(code or "").strip().upper())


def _coerce_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return round(float(value), 2)
    except (TypeError, ValueError):
        return None


def _catalog_status(entry: dict[str, Any]) -> str:
    if bool(entry.get("is_custom")):
        return "custom"
    if not bool(entry.get("recognized")):
        return "disabled"
    if bool(entry.get("has_override")):
        return "override"
    return "catalog"


def _built_in_override_source(cpt: str) -> str | None:
    if cpt in PRACTICE_RVU_OVERRIDES:
        return "practice"
    if cpt in COMMERCIAL_CONSULT_OVERRIDES:
        return "commercial"
    return None


def _built_in_override_row(cpt: str) -> RvuRow | None:
    if cpt in PRACTICE_RVU_OVERRIDES:
        return PRACTICE_RVU_OVERRIDES[cpt]
    if cpt in COMMERCIAL_CONSULT_OVERRIDES:
        return COMMERCIAL_CONSULT_OVERRIDES[cpt]
    return None


def _practice_used_cpts(db: Session) -> dict[str, int]:
    counts: dict[str, int] = {}
    rows = db.query(RvuScan.cpts, RvuScan.main_cpt).all()
    for cpts_raw, main_cpt in rows:
        seen_for_scan: set[str] = set()
        if isinstance(cpts_raw, str) and cpts_raw.strip():
            try:
                parsed = json.loads(cpts_raw)
            except json.JSONDecodeError:
                parsed = []
            if isinstance(parsed, list):
                for item in parsed:
                    clean = _clean_cpt(str(item or ""))
                    if len(clean) == 5:
                        seen_for_scan.add(clean)
        clean_main = _clean_cpt(str(main_cpt or ""))
        if len(clean_main) == 5:
            seen_for_scan.add(clean_main)
        for cpt in seen_for_scan:
            counts[cpt] = counts.get(cpt, 0) + 1
    return counts


def get_effective_modifier_rules(db: Session) -> dict[str, dict[str, object]]:
    overrides = _load_rule_config(db, MODIFIER_RULE_CONFIG_ID)
    rules: dict[str, dict[str, object]] = {
        code: {
            "code": code,
            "factor": factor,
            "desc": DEFAULT_MODIFIER_DESC.get(code, code),
            "source": "default",
            "needs_review": False,
        }
        for code, factor in DEFAULT_MODIFIER_FACTORS.items()
    }
    for code, raw in overrides.items():
        if not isinstance(raw, dict):
            continue
        key = _clean_modifier_code(str(code or ""))
        if not key:
            continue
        rule = rules.get(key, {"code": key, "factor": 1.0, "desc": key})
        factor = _coerce_float(raw.get("factor"))
        desc = str(raw.get("desc") or "").strip()
        if factor is not None:
            rule["factor"] = factor
        if desc:
            rule["desc"] = desc
        for field in ("source", "added_by_staff_id", "added_by_staff_name", "added_at"):
            if raw.get(field) not in (None, ""):
                rule[field] = raw.get(field)
        if raw.get("needs_review") is not None:
            rule["needs_review"] = bool(raw.get("needs_review"))
        elif key not in DEFAULT_MODIFIER_FACTORS:
            rule["needs_review"] = True
        rules[key] = rule
    return rules


def list_modifier_rules(db: Session) -> list[dict[str, object]]:
    rules = get_effective_modifier_rules(db)
    return [rules[code] for code in sorted(rules)]


def patch_modifier_rule(
    db: Session,
    code: str,
    *,
    factor: float | None = None,
    desc: str | None = None,
    source: str | None = None,
    needs_review: bool | None = None,
    added_by_staff_id: int | None = None,
    added_by_staff_name: str | None = None,
    added_at: str | None = None,
) -> dict[str, object]:
    key = _clean_modifier_code(code)
    if not key:
        raise ValueError("Modifier code is required")
    overrides = _load_rule_config(db, MODIFIER_RULE_CONFIG_ID)
    current = overrides.get(key, {})
    if not isinstance(current, dict):
        current = {}
    if factor is not None:
        current["factor"] = round(float(factor), 4)
    if desc is not None:
        current["desc"] = desc.strip()
    if source is not None:
        current["source"] = source.strip() or "portal"
    if needs_review is not None:
        current["needs_review"] = bool(needs_review)
    if added_by_staff_id is not None and current.get("added_by_staff_id") is None:
        current["added_by_staff_id"] = int(added_by_staff_id)
    if added_by_staff_name and not current.get("added_by_staff_name"):
        current["added_by_staff_name"] = added_by_staff_name.strip()
    if added_at and not current.get("added_at"):
        current["added_at"] = added_at
    overrides[key] = current
    _save_rule_config(db, MODIFIER_RULE_CONFIG_ID, overrides)
    return get_effective_modifier_rules(db)[key]


def get_effective_cpt_catalog(db: Session) -> dict[str, dict[str, Any]]:
    cms_catalog = get_base_rvu_catalog()
    full_catalog = get_rvu_catalog()
    overrides = _load_rule_config(db, CPT_RULE_CONFIG_ID)
    catalog: dict[str, dict[str, Any]] = {}

    for cpt, cms_row in cms_catalog.items():
        built_in_row = _built_in_override_row(cpt) or cms_row
        built_in_source = _built_in_override_source(cpt)
        catalog[cpt] = {
            "cpt": cpt,
            "recognized": True,
            "desc": built_in_row.desc,
            "work_rvu": built_in_row.work_rvu,
            "pe_nonfac_rvu": built_in_row.pe_nonfac_rvu,
            "pe_fac_rvu": built_in_row.pe_fac_rvu,
            "mp_rvu": built_in_row.mp_rvu,
            "cms_desc": cms_row.desc,
            "cms_work_rvu": cms_row.work_rvu,
            "cms_pe_nonfac_rvu": cms_row.pe_nonfac_rvu,
            "cms_pe_fac_rvu": cms_row.pe_fac_rvu,
            "cms_mp_rvu": cms_row.mp_rvu,
            "cms_present": True,
            "is_custom": False,
            "has_override": built_in_source is not None,
            "override_source": built_in_source,
            "status": "override" if built_in_source is not None else "catalog",
            "clear_builtin_override": False,
            "added_by_admin_id": None,
            "added_by_admin_name": None,
            "updated_at": None,
        }

    for cpt, row in full_catalog.items():
        if cpt in catalog:
            continue
        built_in_source = _built_in_override_source(cpt)
        catalog[cpt] = {
            "cpt": cpt,
            "recognized": True,
            "desc": row.desc,
            "work_rvu": row.work_rvu,
            "pe_nonfac_rvu": row.pe_nonfac_rvu,
            "pe_fac_rvu": row.pe_fac_rvu,
            "mp_rvu": row.mp_rvu,
            "cms_desc": None,
            "cms_work_rvu": None,
            "cms_pe_nonfac_rvu": None,
            "cms_pe_fac_rvu": None,
            "cms_mp_rvu": None,
            "cms_present": False,
            "is_custom": False,
            "has_override": built_in_source is not None,
            "override_source": built_in_source,
            "status": "override" if built_in_source is not None else "catalog",
            "clear_builtin_override": False,
            "added_by_admin_id": None,
            "added_by_admin_name": None,
            "updated_at": None,
        }

    for raw_code, raw in overrides.items():
        if not isinstance(raw, dict):
            continue
        cpt = _clean_cpt(raw_code)
        if len(cpt) != 5:
            continue
        clear_builtin_override = bool(raw.get("clear_builtin_override"))
        entry = catalog.get(
            cpt,
            {
                "cpt": cpt,
                "recognized": False,
                "desc": "",
                "work_rvu": 0.0,
                "pe_nonfac_rvu": 0.0,
                "pe_fac_rvu": 0.0,
                "mp_rvu": 0.0,
                "cms_desc": None,
                "cms_work_rvu": None,
                "cms_pe_nonfac_rvu": None,
                "cms_pe_fac_rvu": None,
                "cms_mp_rvu": None,
                "cms_present": False,
                "is_custom": True,
                "has_override": True,
                "override_source": "portal",
                "clear_builtin_override": False,
                "added_by_admin_id": None,
                "added_by_admin_name": None,
                "updated_at": None,
            },
        )
        if clear_builtin_override and entry.get("cms_present"):
            cms_desc = entry.get("cms_desc")
            if cms_desc:
                entry["desc"] = cms_desc
            for key, cms_key in (
                ("work_rvu", "cms_work_rvu"),
                ("pe_nonfac_rvu", "cms_pe_nonfac_rvu"),
                ("pe_fac_rvu", "cms_pe_fac_rvu"),
                ("mp_rvu", "cms_mp_rvu"),
            ):
                cms_value = entry.get(cms_key)
                if cms_value is not None:
                    entry[key] = cms_value
            entry["has_override"] = False
            entry["override_source"] = None
        if "recognized" in raw:
            entry["recognized"] = bool(raw.get("recognized"))
        if raw.get("desc") not in (None, ""):
            entry["desc"] = str(raw.get("desc")).strip()
            entry["has_override"] = True
            entry["override_source"] = "portal"
        for key in ("work_rvu", "pe_nonfac_rvu", "pe_fac_rvu", "mp_rvu"):
            coerced = _coerce_float(raw.get(key))
            if coerced is not None:
                entry[key] = coerced
                entry["has_override"] = True
                entry["override_source"] = "portal"
        for field in ("added_by_admin_id", "added_by_admin_name", "updated_at"):
            if raw.get(field) not in (None, ""):
                entry[field] = raw.get(field)
        entry["clear_builtin_override"] = clear_builtin_override
        if entry["is_custom"] and raw.get("recognized") is None:
            entry["recognized"] = True
        entry["status"] = _catalog_status(entry)
        catalog[cpt] = entry

    return catalog


def list_cpt_catalog(
    db: Session,
    search: str = "",
    *,
    overrides_only: bool = False,
    used_only: bool = False,
) -> list[dict[str, Any]]:
    term = str(search or "").strip().lower()
    used_counts = _practice_used_cpts(db)
    if term:
        base_catalog = get_rvu_catalog()
        effective_catalog = get_effective_cpt_catalog(db)
        rows: list[dict[str, Any]] = []
        seen: set[str] = set()

        for cpt, row in effective_catalog.items():
            desc = str(row.get("desc") or "")
            if term not in cpt.lower() and term not in desc.lower():
                continue
            if overrides_only and not bool(row.get("has_override")):
                continue
            if used_only and used_counts.get(cpt, 0) <= 0:
                continue
            row = {**row, "used_by_practice": used_counts.get(cpt, 0) > 0, "practice_use_count": used_counts.get(cpt, 0)}
            rows.append(row)
            seen.add(cpt)

        for cpt, row in base_catalog.items():
            if cpt in seen:
                continue
            if term not in cpt.lower() and term not in row.desc.lower():
                continue
            rows.append(
                {
                    "cpt": cpt,
                    "recognized": False,
                    "desc": row.desc,
                    "work_rvu": row.work_rvu,
                    "pe_nonfac_rvu": row.pe_nonfac_rvu,
                    "pe_fac_rvu": row.pe_fac_rvu,
                    "mp_rvu": row.mp_rvu,
                    "is_custom": False,
                    "has_override": _built_in_override_source(cpt) is not None,
                    "override_source": _built_in_override_source(cpt),
                    "status": "override" if _built_in_override_source(cpt) is not None else "catalog",
                    "used_by_practice": used_counts.get(cpt, 0) > 0,
                    "practice_use_count": used_counts.get(cpt, 0),
                }
            )
        rows.sort(key=lambda row: str(row.get("cpt") or ""))
        return rows

    catalog = get_effective_cpt_catalog(db)
    rows = []
    for row in catalog.values():
        cpt = str(row.get("cpt") or "")
        if overrides_only and not bool(row.get("has_override")):
            continue
        if used_only and used_counts.get(cpt, 0) <= 0:
            continue
        rows.append({**row, "used_by_practice": used_counts.get(cpt, 0) > 0, "practice_use_count": used_counts.get(cpt, 0)})
    rows.sort(key=lambda row: str(row.get("cpt") or ""))
    return rows


def get_recognized_cpts(db: Session) -> set[str]:
    catalog = get_effective_cpt_catalog(db)
    return {
        cpt
        for cpt, row in catalog.items()
        if bool(row.get("recognized"))
    }


def get_effective_rvu_overrides(db: Session) -> dict[str, RvuRow]:
    catalog = get_effective_cpt_catalog(db)
    return {
        cpt: RvuRow(
            desc=str(row.get("desc") or ""),
            work_rvu=float(row.get("work_rvu") or 0.0),
            pe_nonfac_rvu=float(row.get("pe_nonfac_rvu") or 0.0),
            pe_fac_rvu=float(row.get("pe_fac_rvu") or 0.0),
            mp_rvu=float(row.get("mp_rvu") or 0.0),
        )
        for cpt, row in catalog.items()
        if bool(row.get("recognized"))
    }


def patch_cpt_rule(
    db: Session,
    cpt: str,
    *,
    recognized: bool | None = None,
    desc: str | None = None,
    work_rvu: float | None = None,
    pe_nonfac_rvu: float | None = None,
    pe_fac_rvu: float | None = None,
    mp_rvu: float | None = None,
) -> dict[str, Any]:
    clean = _clean_cpt(cpt)
    if len(clean) != 5:
        raise ValueError("CPT must be a 5-digit code")
    overrides = _load_rule_config(db, CPT_RULE_CONFIG_ID)
    current = overrides.get(clean, {})
    if not isinstance(current, dict):
        current = {}
    if recognized is not None:
        current["recognized"] = bool(recognized)
    if desc is not None:
        current["desc"] = desc.strip()
    if work_rvu is not None:
        current["work_rvu"] = round(float(work_rvu), 2)
    if pe_nonfac_rvu is not None:
        current["pe_nonfac_rvu"] = round(float(pe_nonfac_rvu), 2)
    if pe_fac_rvu is not None:
        current["pe_fac_rvu"] = round(float(pe_fac_rvu), 2)
    if mp_rvu is not None:
        current["mp_rvu"] = round(float(mp_rvu), 2)
    overrides[clean] = current
    _save_rule_config(db, CPT_RULE_CONFIG_ID, overrides)
    return get_effective_cpt_catalog(db)[clean]


def save_cpt_rule(
    db: Session,
    cpt: str,
    *,
    recognized: bool | None = None,
    desc: str | None = None,
    work_rvu: float | None = None,
    pe_nonfac_rvu: float | None = None,
    pe_fac_rvu: float | None = None,
    mp_rvu: float | None = None,
    clear_builtin_override: bool | None = None,
    added_by_admin_id: int | None = None,
    added_by_admin_name: str | None = None,
    updated_at: str | None = None,
) -> dict[str, Any]:
    clean = _clean_cpt(cpt)
    if len(clean) != 5:
        raise ValueError("CPT must be a 5-digit code")
    overrides = _load_rule_config(db, CPT_RULE_CONFIG_ID)
    current = overrides.get(clean, {})
    if not isinstance(current, dict):
        current = {}
    if recognized is not None:
        current["recognized"] = bool(recognized)
    if desc is not None:
        current["desc"] = desc.strip()
    if work_rvu is not None:
        current["work_rvu"] = round(float(work_rvu), 2)
    if pe_nonfac_rvu is not None:
        current["pe_nonfac_rvu"] = round(float(pe_nonfac_rvu), 2)
    if pe_fac_rvu is not None:
        current["pe_fac_rvu"] = round(float(pe_fac_rvu), 2)
    if mp_rvu is not None:
        current["mp_rvu"] = round(float(mp_rvu), 2)
    if clear_builtin_override is not None:
        current["clear_builtin_override"] = bool(clear_builtin_override)
    if added_by_admin_id is not None and current.get("added_by_admin_id") is None:
        current["added_by_admin_id"] = int(added_by_admin_id)
    if added_by_admin_name and not current.get("added_by_admin_name"):
        current["added_by_admin_name"] = added_by_admin_name.strip()
    if updated_at:
        current["updated_at"] = updated_at
    overrides[clean] = current
    _save_rule_config(db, CPT_RULE_CONFIG_ID, overrides)
    return get_effective_cpt_catalog(db)[clean]


def delete_cpt_rule(db: Session, cpt: str) -> dict[str, Any]:
    clean = _clean_cpt(cpt)
    if len(clean) != 5:
        raise ValueError("CPT must be a 5-digit code")
    overrides = _load_rule_config(db, CPT_RULE_CONFIG_ID)
    if clean in PRACTICE_RVU_OVERRIDES or clean in COMMERCIAL_CONSULT_OVERRIDES:
        overrides[clean] = {
            "clear_builtin_override": True,
            "recognized": True,
        }
    else:
        overrides.pop(clean, None)
    _save_rule_config(db, CPT_RULE_CONFIG_ID, overrides)
    catalog = get_effective_cpt_catalog(db)
    if clean in catalog:
        return catalog[clean]
    return {
        "cpt": clean,
        "deleted": True,
    }
