"""2026 CMS MPFS lookup — full RVU components + GPCI by locality."""
import csv
from functools import lru_cache
from pathlib import Path

_DATA = Path(__file__).resolve().parent / "data"

CF_2026 = 32.3465


@lru_cache(maxsize=1)
def _load_rvu() -> dict:
    table = {}
    with open(_DATA / "cpt_rvu_full.csv", newline="") as f:
        for row in csv.DictReader(f):
            table[row["cpt"].strip()] = {
                "desc":          row["desc"],
                "work_rvu":      float(row["work_rvu"] or 0),
                "pe_nonfac_rvu": float(row["pe_nonfac_rvu"] or 0),
                "pe_fac_rvu":    float(row["pe_fac_rvu"] or 0),
                "mp_rvu":        float(row["mp_rvu"] or 0),
            }
    return table


@lru_cache(maxsize=1)
def _load_gpci() -> list:
    rows = []
    with open(_DATA / "gpci2026.csv", newline="") as f:
        for row in csv.DictReader(f):
            rows.append({
                "state":         row["state"],
                "locality_num":  row["locality_num"],
                "locality_name": row["locality_name"],
                "pw_gpci":       float(row["pw_gpci"] or 1),
                "pe_gpci":       float(row["pe_gpci"] or 1),
                "mp_gpci":       float(row["mp_gpci"] or 1),
            })
    return rows


def get_localities() -> list:
    return sorted(_load_gpci(), key=lambda r: (r["state"], r["locality_name"]))


def get_gpci(locality_num: str) -> dict:
    for r in _load_gpci():
        if r["locality_num"] == locality_num:
            return r
    return {"pw_gpci": 1.0, "pe_gpci": 1.0, "mp_gpci": 1.0,
            "locality_name": "National Average", "state": ""}


def get_rvu(cpt: str) -> dict:
    return _load_rvu().get(cpt.strip(), {
        "desc": "", "work_rvu": 0.0,
        "pe_nonfac_rvu": 0.0, "pe_fac_rvu": 0.0, "mp_rvu": 0.0,
    })


def calc_payment(cpt: str, locality_num: str, facility: bool, cf: float = CF_2026) -> dict:
    rvu  = get_rvu(cpt)
    gpci = get_gpci(locality_num)
    pe   = rvu["pe_fac_rvu"] if facility else rvu["pe_nonfac_rvu"]
    adjusted = (
        rvu["work_rvu"] * gpci["pw_gpci"] +
        pe              * gpci["pe_gpci"] +
        rvu["mp_rvu"]   * gpci["mp_gpci"]
    )
    return {
        "cpt":           cpt,
        "desc":          rvu["desc"],
        "work_rvu":      round(rvu["work_rvu"], 2),
        "pe_rvu":        round(pe, 2),
        "pe_nonfac_rvu": round(rvu["pe_nonfac_rvu"], 2),
        "pe_fac_rvu":    round(rvu["pe_fac_rvu"], 2),
        "mp_rvu":        round(rvu["mp_rvu"], 2),
        "total_rvu":     round(adjusted, 2),
        "pw_gpci":       gpci["pw_gpci"],
        "pe_gpci":       gpci["pe_gpci"],
        "mp_gpci":       gpci["mp_gpci"],
        "locality":      gpci["locality_name"],
        "facility":      facility,
        "cf":            cf,
        "payment":       round(adjusted * cf, 2),
    }
