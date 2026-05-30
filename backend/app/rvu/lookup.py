"""2026 CMS Medicare Physician Fee Schedule lookup and RVU app payment calculations."""

import csv
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
import re

_DATA = Path(__file__).resolve().parent / "data"

CF_2026: float = 32.3465

# Product reconciliation rules for RVU review and reporting.
DEFAULT_MODIFIER_FACTORS: dict[str, float] = {
    "22": 1.00,   # Increased services (flag only; no automatic RVU change)
    "50": 1.50,   # Bilateral procedure
    "51": 1.00,   # Multiple procedures handled at encounter level
    "52": 0.50,   # Reduced services
    "53": 0.50,   # Discontinued procedure
    "62": 0.625,  # Two primary surgeons / co-surgery
    "66": 1.00,   # Team surgery
    "78": 0.70,   # Unplanned return to OR
    "79": 1.00,   # Unrelated procedure during postop period
    "80": 0.16,   # Assistant surgeon
    "81": 0.10,   # Minimum assistant surgeon
    "82": 0.16,   # Assistant when qualified resident unavailable
    "AS": 0.20,   # PA/NP assistant at surgery
}

DEFAULT_MODIFIER_DESC: dict[str, str] = {
    "22": "Increased Procedural Services",
    "50": "Bilateral Procedure",
    "51": "Multiple Procedures",
    "52": "Reduced Services",
    "53": "Discontinued Procedure",
    "62": "Co-Surgeons",
    "66": "Team Surgery",
    "78": "Unplanned Return to OR",
    "79": "Unrelated Procedure",
    "80": "Assistant Surgeon",
    "81": "Minimum Assistant Surgeon",
    "82": "Assistant (No Resident)",
    "AS": "PA/NP Assistant at Surgery",
}


def _resolve_modifier(
    modifier_str: str,
    modifier_rules: dict[str, dict[str, object]] | None = None,
) -> tuple[str, float, str]:
    """
    Parse a modifier string like "50", "AS", or "LT,50" and return
    the first payment-affecting modifier as (code, factor, description).
    """
    if not modifier_str:
        return "", 1.0, ""
    effective_rules = modifier_rules or {
        code: {"factor": factor, "desc": DEFAULT_MODIFIER_DESC.get(code, code)}
        for code, factor in DEFAULT_MODIFIER_FACTORS.items()
    }
    codes = [
        re.sub(r"[^A-Z0-9]", "", c.strip().upper())
        for c in modifier_str.replace("/", ",").split(",")
        if c.strip()
    ]
    for code in codes:
        if code in effective_rules:
            rule = effective_rules.get(code) or {}
            factor = float(rule.get("factor") or 1.0)
            desc = str(rule.get("desc") or code)
            return code, factor, desc
    return "", 1.0, ""


def _normalize_modifier_str(modifier_str: str) -> str:
    codes = [
        re.sub(r"[^A-Z0-9]", "", c.strip().upper())
        for c in str(modifier_str or "").replace("/", ",").split(",")
        if c.strip()
    ]
    return ",".join(dict.fromkeys(c for c in codes if c))


@dataclass(frozen=True)
class RvuRow:
    desc: str
    work_rvu: float
    pe_nonfac_rvu: float
    pe_fac_rvu: float
    mp_rvu: float


@dataclass(frozen=True)
class GpciRow:
    state: str
    locality_num: str
    locality_name: str
    pw_gpci: float
    pe_gpci: float
    mp_gpci: float


COMMERCIAL_CONSULT_OVERRIDES: dict[str, RvuRow] = {
    # Commercial-only inpatient consultation codes retained for beta reconciliation.
    # CMS removed these Medicare consult codes in 2010, so they are maintained as
    # explicit overrides instead of being mixed into the 2026 Medicare RVU source CSV.
    "99252": RvuRow("Inpatient consultation, straightforward / low complexity", 1.80, 0.0, 0.0, 0.0),
    "99253": RvuRow("Inpatient consultation, low complexity", 2.50, 0.0, 0.0, 0.0),
    "99254": RvuRow("Inpatient consultation, moderate complexity", 3.60, 0.0, 0.0, 0.0),
    "99255": RvuRow("Inpatient consultation, high complexity", 4.50, 0.0, 0.0, 0.0),
}

PRACTICE_RVU_OVERRIDES: dict[str, RvuRow] = {
    # MFS compensation reconciliation uses 9.30 wRVU for laparoscopic initial
    # inguinal hernia repair; modifier -50 is applied on top of that base.
    "49650": RvuRow("Lap ing hernia repair init", 9.30, 4.87, 4.87, 1.63),
}


@dataclass
class PaymentResult:
    cpt: str
    desc: str
    modifier: str
    modifier_code: str
    modifier_factor: float
    modifier_desc: str
    work_rvu: float
    pe_rvu: float
    pe_nonfac_rvu: float
    pe_fac_rvu: float
    mp_rvu: float
    pw_gpci: float
    pe_gpci: float
    mp_gpci: float
    total_rvu: float
    locality: str
    facility: bool
    cf: float
    work_payment: float
    pe_payment: float
    mp_payment: float
    payment: float

    def to_dict(self) -> dict:
        return self.__dict__.copy()


@lru_cache(maxsize=1)
def _rvu_table() -> dict[str, RvuRow]:
    table: dict[str, RvuRow] = {}
    with open(_DATA / "cpt_rvu_full.csv", newline="") as f:
        for row in csv.DictReader(f):
            table[row["cpt"].strip()] = RvuRow(
                desc=row["desc"],
                work_rvu=float(row["work_rvu"] or 0),
                pe_nonfac_rvu=float(row["pe_nonfac_rvu"] or 0),
                pe_fac_rvu=float(row["pe_fac_rvu"] or 0),
                mp_rvu=float(row["mp_rvu"] or 0),
            )
    table.update(COMMERCIAL_CONSULT_OVERRIDES)
    table.update(PRACTICE_RVU_OVERRIDES)
    return table


@lru_cache(maxsize=1)
def _gpci_table() -> list[GpciRow]:
    rows: list[GpciRow] = []
    with open(_DATA / "gpci2026.csv", newline="") as f:
        for row in csv.DictReader(f):
            rows.append(
                GpciRow(
                    state=row["state"],
                    locality_num=row["locality_num"],
                    locality_name=row["locality_name"],
                    pw_gpci=float(row["pw_gpci"] or 1),
                    pe_gpci=float(row["pe_gpci"] or 1),
                    mp_gpci=float(row["mp_gpci"] or 1),
                )
            )
    return rows


def get_localities() -> list[GpciRow]:
    return sorted(_gpci_table(), key=lambda r: (r.state, r.locality_name))


def get_gpci(locality_num: str) -> GpciRow:
    for row in _gpci_table():
        if row.locality_num == locality_num:
            return row
    return GpciRow("", "00", "National Average", 1.0, 1.0, 1.0)


def get_rvu(cpt: str) -> RvuRow:
    return _rvu_table().get(cpt.strip(), RvuRow("", 0.0, 0.0, 0.0, 0.0))


def get_rvu_catalog() -> dict[str, RvuRow]:
    return dict(_rvu_table())


def calc_payment(
    cpt: str,
    locality_num: str,
    facility: bool,
    cf: float = CF_2026,
    modifier: str = "",
    *,
    rvu_override: RvuRow | None = None,
    modifier_rules: dict[str, dict[str, object]] | None = None,
) -> PaymentResult:
    rvu = rvu_override or get_rvu(cpt)
    gpci = get_gpci(locality_num)
    pe = rvu.pe_fac_rvu if facility else rvu.pe_nonfac_rvu

    adj_work = rvu.work_rvu * gpci.pw_gpci
    adj_pe = pe * gpci.pe_gpci
    adj_mp = rvu.mp_rvu * gpci.mp_gpci
    modifier = _normalize_modifier_str(modifier)
    mod_code, mod_factor, mod_desc = _resolve_modifier(modifier, modifier_rules=modifier_rules)

    adjusted_work_rvu = rvu.work_rvu * mod_factor
    work_payment = round(adjusted_work_rvu * cf, 2)
    pe_payment = round(adj_pe * cf * mod_factor, 2)
    mp_payment = round(adj_mp * cf * mod_factor, 2)
    payment = work_payment

    return PaymentResult(
        cpt=cpt,
        desc=rvu.desc,
        modifier=modifier,
        modifier_code=mod_code,
        modifier_factor=mod_factor,
        modifier_desc=mod_desc,
        work_rvu=round(adjusted_work_rvu, 2),
        pe_rvu=round(pe * mod_factor, 2),
        pe_nonfac_rvu=round(rvu.pe_nonfac_rvu, 2),
        pe_fac_rvu=round(rvu.pe_fac_rvu, 2),
        mp_rvu=round(rvu.mp_rvu * mod_factor, 2),
        pw_gpci=gpci.pw_gpci,
        pe_gpci=gpci.pe_gpci,
        mp_gpci=gpci.mp_gpci,
        total_rvu=round(adjusted_work_rvu, 2),
        locality=gpci.locality_name,
        facility=facility,
        cf=cf,
        work_payment=work_payment,
        pe_payment=pe_payment,
        mp_payment=mp_payment,
        payment=payment,
    )
