"""Charge capture + text extraction via Anthropic and/or OpenAI (no local Ollama)."""
from __future__ import annotations

import base64
import io
import json
import os
import re
from collections import Counter
import time
import urllib.error
import urllib.request
from typing import Any

from PIL import Image

from app.services.rvu_payment_service import RvuPaymentService

_AGENT_DEBUG_LOG_PATH = os.environ.get(
    "RVU_AGENT_DEBUG_LOG_PATH",
    "/Users/donnaile/dev/rvu/.cursor/debug-b09ef5.log",
)


def _agent_debug(payload: dict) -> None:
    # #region agent log
    try:
        rec = {"sessionId": "b09ef5", "timestamp": int(time.time() * 1000), **payload}
        with open(_AGENT_DEBUG_LOG_PATH, "a", encoding="utf-8") as lf:
            lf.write(json.dumps(rec) + "\n")
    except Exception:
        pass
    # #endregion


def _cloud_model_from_env(*, explicit: str, legacy: str, default: str) -> str:
    """Use ANTHROPIC_*_MODEL when set; only accept VISION_MODEL/TEXT_MODEL if they look like cloud API ids."""
    e = (explicit or "").strip()
    if e:
        return e
    leg = (legacy or "").strip()
    if leg.startswith(("claude-", "gpt-", "o1", "o3")):
        return leg
    return default


_VISION_MODEL = _cloud_model_from_env(
    explicit=os.environ.get("ANTHROPIC_VISION_MODEL", "") or "",
    legacy=os.environ.get("VISION_MODEL", "") or "",
    default="claude-haiku-4-5-20251001",
)
_TEXT_MODEL = _cloud_model_from_env(
    explicit=os.environ.get("ANTHROPIC_TEXT_MODEL", "") or "",
    legacy=os.environ.get("TEXT_MODEL", "") or "",
    default="claude-haiku-4-5-20251001",
)
_IMAGE_MAX_DIM = int(os.environ.get("RVU_IMAGE_MAX_DIM", "1600"))
_OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "").strip()
_OPENAI_VISION_MODEL = os.environ.get("OPENAI_VISION_MODEL", "gpt-4o-mini").strip()
_OPENAI_TIMEOUT = int(os.environ.get("OPENAI_TIMEOUT_SECS", "90"))
_OPENAI_TEXT_MODEL = os.environ.get("OPENAI_TEXT_MODEL", "gpt-4o-mini").strip()
_ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "").strip()
_ANTHROPIC_VISION_MODEL = _VISION_MODEL
_ANTHROPIC_TIMEOUT = int(os.environ.get("ANTHROPIC_TIMEOUT_SECS", "90"))
_LOCK_LOCAL_ONLY = os.environ.get("RVU_LOCK_LOCAL_ONLY", "true").lower() in ("1", "true", "yes")
_ANTHROPIC_FALLBACK_MODELS = [
    "claude-haiku-4-5-20251001",
    "claude-sonnet-4-5-20250929",
    "claude-sonnet-4-6",
]


def _pipeline_stages(csv: str) -> list[str]:
    return [x.strip().lower() for x in csv.split(",") if x.strip()]


def _cloud_vision_pipeline(csv: str) -> list[str]:
    """Anthropic + OpenAI only; strips ollama/legacy names from env."""
    raw = _pipeline_stages(csv)
    allowed = [x for x in raw if x in ("anthropic", "openai")]
    return allowed if allowed else ["anthropic", "openai"]


_RVU_VISION_PIPELINE = _cloud_vision_pipeline(os.environ.get("RVU_VISION_PIPELINE", "anthropic,openai"))


def first_resolvable_pipeline_stage(
    anthropic_key: str | None,
    openai_key: str | None,
) -> str:
    for stage in _RVU_VISION_PIPELINE:
        if stage == "anthropic" and (anthropic_key or "").strip():
            return "anthropic"
        if stage == "openai" and (openai_key or "").strip():
            return "openai"
    return "none"


_op_csv = os.environ.get("RVU_OP_NOTE_PIPELINE", "").strip()
_RVU_OP_NOTE_PIPELINE = _cloud_vision_pipeline(_op_csv) if _op_csv else list(_RVU_VISION_PIPELINE)

_OP_NOTE_MAX_DIM = int(os.environ.get("RVU_OP_NOTE_MAX_DIM", "1536"))
_ANTHROPIC_OP_NOTE_MAX_TOKENS = min(16384, int(os.environ.get("RVU_ANTHROPIC_OP_NOTE_MAX_TOKENS", "8192")))
_ANTHROPIC_OP_NOTE_TIMEOUT_SECS = float(
    os.environ.get("ANTHROPIC_OP_NOTE_TIMEOUT_SECS", os.environ.get("OPENAI_OP_NOTE_TIMEOUT_SECS", "180"))
)
_OPENAI_OP_NOTE_TIMEOUT_SECS = int(os.environ.get("OPENAI_OP_NOTE_TIMEOUT_SECS", "180"))
_OPENAI_OP_NOTE_MAX_TOKENS = min(16384, int(os.environ.get("OPENAI_OP_NOTE_MAX_TOKENS", "8192")))

_VISION_API_FALLBACK_ORDER = [s for s in _RVU_VISION_PIPELINE if s in ("anthropic", "openai")] or ["anthropic", "openai"]

_STRUCTURE_PROMPT = """You are reading a photo of a hospital charge screen (Epic or similar), fee sheet, or operative report.

Task: list every distinct 5-digit CPT / procedure code printed on this image. Charge screens often show several lines (primary, add-on, anesthesia, etc.) — include all numeric 5-digit codes you can read. Scan top to bottom.

Important reading order: scan the ENTIRE image left-to-right and top-to-bottom, including all table columns.
Do not focus only on the left side.
If present, explicitly read columns like:
- Code
- Description
- Service Provider
- Billing Provider
- Modifier

Read CPT digits carefully, character by character. Hospital subsequent-visit codes 99231, 99232, 99233 are often confused with 99223 — check the 4th and 5th digits against the screen (9923x vs 9922x).

Output: one JSON object only, no markdown, no explanation. Use double quotes. Valid empty template:
{"service_date":"","patient_name":"","mrn":"","surgeon_name":"","lines":[]}

How to fill it:
- "surgeon_name": surgeon/attending name if visible, else "".
- "patient_name": patient name if visible anywhere on the image, else "".
- "lines": add one object per charge line read from the image. Each object must have:
  - "cpt" (string, exactly five digits)
  - "procedure_name" (string, may be empty)
  - "provider_name" (string, may be empty) — the **rendering / billing provider shown for THAT row** (Epic "Service Provider" or similar). If one screenshot lists charges for multiple attendings (e.g. first rows for Dr A, later row for Dr B on rounds), each row MUST carry the correct visible name for that row; never copy one name down the whole table.
  - "provider_role" (one of: "surgeon","pa","assistant","unknown")
  - "modifier" (string, may be empty, e.g. "AS")
  - "is_assist" (boolean; true if AS/assistant line)
  - "line_service_date" (string, ISO YYYY-MM-DD): when this **row** has its own date of service or date column (multi-day hospital stays, per-line DOS columns), set it; use "" if the row uses the same global date as the block or no per-row date is printed.
- "service_date": top-level date for the charge **block** when a single shared DOS applies to all listed lines (header date). Use ISO YYYY-MM-DD. Use "" if only per-row dates exist (then rely on line_service_date per line).
- "mrn": patient MRN or account ID if visible, else "". MRN is numeric only: output digits only and prefer digits over lookalike letters (for example S->5, O->0).
- If the same CPT appears twice for different providers (example surgeon + PA assist), keep BOTH line objects.
- Modifiers like -50 or -LT: keep only the five-digit procedure number.
- Ignore codes that are not plain 5 digits (letter-prefixed HCPCS, revenue codes, etc.).

If the image truly shows no 5-digit procedure codes, keep "lines" as [].
"""

_TEXT_STRUCTURE_PROMPT = """You are a medical billing assistant. The user text may list multiple procedures or charge lines.

Extract every distinct 5-digit CPT code that appears in the text below. Return ONE JSON object only, no markdown:
{{"service_date":"","patient_name":"","mrn":"","surgeon_name":"","lines":[]}}

Fill "lines" with one object per charge line; each object has:
"cpt" (five digits from text), "procedure_name", "provider_name", "provider_role", "modifier", "is_assist", "line_service_date" (ISO per row when the text shows different DOS per line, else "").
If an "AS" modifier or PA/assistant name appears, mark is_assist=true and provider_role="pa" or "assistant".

Text:
{raw_text}
"""

_REFINE_VISION_PROMPT = """First extraction already found these CPT codes (JSON array): {known_json}

Look at this SAME image again (headers, line items, footnotes).

1) List ONLY additional distinct 5-digit CPT codes VISIBLY PRINTED that are NOT in the array above (same JSON shape as before).
2) If the first pass missed the date of service for the charge block, set "service_date" to YYYY-MM-DD (convert from US dates like 3/24/2026 → 2026-03-24). If already known or not visible, use "".

Return ONE JSON object only (no markdown), for example:
{{"additional_lines":[],"service_date":"","patient_name":"","mrn":""}}
Rules: cpt must be exactly 5 digits; skip codes already in the first list; ignore non-numeric HCPCS.
"""

_REFINE_TEXT_PROMPT = """First pass found these CPTs: {known_json}

Read the SAME user text again. List ONLY additional distinct 5-digit CPT codes that appear in the text and are NOT in that list.

Return ONE JSON object only (no markdown): {{"additional_lines": [], "patient_name": "", "mrn": ""}} with the array filled only from the text (each item {{"cpt": "<five digits from text>", "procedure_name": ""}}). If none, keep additional_lines empty. If patient name or MRN are visible in the text and were missed before, include them. MRN is digits only. Do not invent codes.
"""

_TABLE_FOCUS_PROMPT = """Read this hospital charge screenshot as a TABLE.

Scan full width and full height, left-to-right and top-to-bottom.
Always read the patient banner/header separately from the charge table. If the header shows a
patient name, MRN, account number, or service date, return those fields even if the charge rows
are too blurry or cropped to read.
Pay special attention to columns:
- Code
- Description
- Service Provider
- Billing Provider
- Modifier

Return ONE JSON object only (no markdown):
{"service_date":"","patient_name":"","mrn":"","surgeon_name":"","lines":[]}

For each visible charge row, include one object in "lines" with:
- cpt (5 digits)
- procedure_name
- provider_name (exactly as printed for that row — multiple physicians on one screen each get their own lines with distinct names)
- provider_role (surgeon|pa|assistant|unknown)
- modifier (ex: AS)
- is_assist (true/false)
- line_service_date (ISO or "" if this row shares the block header date only)

If same CPT appears on multiple rows with different provider, modifier, or **different DOS**, keep separate rows and set line_service_date when dates differ.
MRN is digits only if visible.
"""

_DEMOGRAPHICS_FOCUS_PROMPT = """Read only the patient demographics/header area of this hospital charge screenshot.

Return ONE JSON object only (no markdown):
{"service_date":"","patient_name":"","mrn":"","surgeon_name":"","lines":[]}

Rules:
- Focus on patient name, MRN/account number, and top-level service date if visible.
- MRN must be the full visible identifier, digits only, minimum 8 digits and maximum 14 digits.
- If you cannot clearly see a full 8-14 digit MRN, return "" for mrn.
- Do not invent CPT rows.
- Leave lines empty.
"""

_MODIFIER_FOCUS_PROMPT = """You are reading the RIGHT SIDE of the same hospital charge screenshot.

Known charge rows from the first pass:
{known_json}

Task: improve ONLY those known rows by reading columns such as:
- Service Provider
- Billing Provider
- Modifier
- per-line Date of Service

Return ONE JSON object only (no markdown):
{{"service_date":"","patient_name":"","mrn":"","surgeon_name":"","lines":[]}}

Rules:
- Only return rows for CPT codes already present in the known rows above.
- Do not invent new CPT codes.
- If a known row's modifier is visible, include it.
- If provider name is visible for that same row, include it.
- MRN is digits only if present.
- If a field is not visible, leave it empty.
- If multiple known rows share a CPT, use provider name / DOS / modifier only when you can actually see them.
"""

_RAW_TRANSCRIPT_PROMPT = """You are reading one full screenshot of a medical charge screen.

Transcribe everything visible in the image as raw text.

Rules:
- Read the full image from top-left to bottom-right.
- Do not summarize.
- Do not normalize.
- Preserve visible wording, dates, times, CPT codes, provider names, modifiers, quantities, and row text.
- Include charge rows exactly as shown when possible.
- Output plain text only.
"""

_OP_NOTE_PROMPT = """You are reading a photo of an operative note, procedure dictation, or clinical document.
Transcribe all readable text. Preserve paragraph breaks using \\n inside the JSON string.

Return ONE JSON object only (no markdown):
{{"full_text": "<paste the document text here, escaped for JSON>"}}
The full_text value must be ONLY what you read from this image (not boilerplate). If the image is blank or unreadable, {{"full_text": ""}}.
"""

_OP_NOTE_STRUCTURED_PROMPT = """You may be reading one long image that contains several stacked pages of an operative note (laparoscopic gallbladder, hernia repair, etc.).

Goal: extract BOTH a faithful transcript AND structured clinical/document fields. Do not invent content; use "" or [] if not present.

Return ONE JSON object only, no markdown fences. Use double quotes. Schema:
{{
  "full_text": "<entire readable document, newlines as \\\\n>",
  "patient_name": "",
  "procedure_date": "",
  "pre_op_diagnosis": "",
  "post_op_diagnosis": "",
  "procedure_performed": "",
  "findings": {{
    "abdomen": "",
    "gallbladder": "",
    "hernia": "",
    "other": ""
  }},
  "cpt_codes": [],
  "devices_implants": "",
  "mesh": "",
  "suture": "",
  "specimens": "",
  "procedure_steps": [],
  "complications": "",
  "estimated_blood_loss": "",
  "needles_instruments_count_confirmed": "",
  "operative_note_excerpt": "<short summary of key operative paragraph if useful>"
}}

"cpt_codes": list of strings, each exactly five digits if visible (no HCPCS letter codes). "procedure_steps": array of short bullet strings in order. If a field truly does not appear anywhere, keep it empty.
"""

def _normalize_mrn_digits(value: Any) -> str | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    digits = "".join(ch for ch in raw if ch.isdigit())
    return digits[:64] or None


def _valid_mrn_or_none(value: Any) -> str | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    digits = "".join(ch for ch in raw if ch.isdigit())
    if 8 <= len(digits) <= 14:
        return digits
    return None


def _split_modifier_codes(text: str) -> tuple[str, ...]:
    parts = [
        re.sub(r"[^A-Z0-9]", "", p.strip().upper())
        for p in str(text or "").replace("/", ",").split(",")
        if p.strip()
    ]
    return tuple(dict.fromkeys(p for p in parts if re.fullmatch(r"[A-Z0-9]{1,4}", p)))


def _normalize_modifier_text(text: str) -> str:
    return ",".join(_split_modifier_codes(text))


def _parse_datetime_bits(text: str) -> tuple[str | None, str | None, str | None]:
    raw = str(text or "").strip()
    if not raw:
        return None, None, None
    m = re.search(r"(\d{1,2}[/-]\d{1,2}[/-]\d{4})(?:\s+(\d{1,2}:\d{2}\s*[AP]M))?", raw, re.I)
    if not m:
        return None, None, None
    date_raw = m.group(1)
    time_raw = (m.group(2) or "").upper().replace("  ", " ").strip()
    iso_date = RvuPaymentService.coerce_service_date_iso(date_raw)
    if not iso_date:
        return None, None, None
    full_raw = f"{date_raw} {time_raw}".strip() if time_raw else date_raw
    return iso_date, time_raw or None, full_raw


def _parse_visible_quantity(text: str) -> int | None:
    raw = str(text or "").strip()
    if not raw:
        return None
    m = re.fullmatch(r"\d+", raw)
    return int(raw) if m else None


def _parse_provider_role_from_visible_text(provider_name: str, procedure_name: str, modifier: str) -> str:
    merged = " ".join(x for x in (provider_name, procedure_name, modifier) if x).upper()
    if " AS" in f" {merged}" or re.search(r"\bPA(?:-C)?\b", merged):
        return "pa"
    if re.search(r"\bASSIST", merged):
        return "assistant"
    return "unknown"


def _parse_transcript_patient_name(raw_text: str) -> str | None:
    match = re.search(
        r"\b([A-Z][A-Za-z'`.-]+,\s*[A-Z][A-Za-z'`.-]+(?:\s+[A-Z][A-Za-z'`.-]+){0,2})\s*\|\s*Patient Lookup\b",
        raw_text,
    )
    if match:
        return match.group(1).strip()[:255]
    return _patient_name_from_model(None, raw_text)


def _parse_transcript_modifier_summary(raw_text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in raw_text.splitlines():
        if "Mods" not in line or not re.search(r"\b\d{5}\b", line):
            continue
        cpt_match = re.search(r"\b(\d{5})\b", line)
        mod_match = re.search(r"\bMods?\s+([A-Z0-9,\/ ]+)$", line, re.I)
        if not cpt_match or not mod_match:
            continue
        codes = _split_modifier_codes(mod_match.group(1))
        if codes and cpt_match.group(1) not in out:
            out[cpt_match.group(1)] = ",".join(codes)
    return out


def _parse_transcript_charge_rows(raw_text: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    in_charge_table = False
    summary_mods = _parse_transcript_modifier_summary(raw_text)
    for raw_line in raw_text.splitlines():
        line = raw_line.strip()
        if not line:
            if in_charge_table:
                in_charge_table = False
            continue
        normalized = re.sub(r"\s+", " ", line)
        if "Description | Code |" in normalized and "Service Date" in normalized:
            in_charge_table = True
            continue
        if not in_charge_table or "|" not in normalized:
            continue
        if normalized.startswith("Associated Dx:") or normalized.startswith("My Specialty"):
            in_charge_table = False
            continue
        cols = [c.strip() for c in normalized.split("|")]
        cpt_idx = next((idx for idx, col in enumerate(cols) if re.search(r"\b\d{5}\b", col)), None)
        if cpt_idx is None or cpt_idx == 0:
            continue
        cpt_match = re.search(r"\b(\d{5})\b", cols[cpt_idx])
        if not cpt_match:
            continue
        cpt = cpt_match.group(1)
        procedure_name = cols[cpt_idx - 1].strip()
        service_dt_raw = cols[cpt_idx + 2].strip() if len(cols) > cpt_idx + 2 else ""
        provider_name = cols[cpt_idx + 3].strip() if len(cols) > cpt_idx + 3 else ""
        modifier_text = cols[cpt_idx + 4].strip() if len(cols) > cpt_idx + 4 else ""
        quantity_text = cols[cpt_idx + 5].strip() if len(cols) > cpt_idx + 5 else ""
        modifier_codes = _split_modifier_codes(modifier_text)
        if not modifier_codes and cpt in summary_mods:
            modifier_codes = tuple(summary_mods[cpt].split(","))
        line_service_date, line_time_raw, line_datetime_raw = _parse_datetime_bits(service_dt_raw)
        modifier = ",".join(modifier_codes)
        rows.append(
            {
                "cpt": cpt,
                "procedure_name": procedure_name,
                "provider_name": provider_name,
                "provider_role": _parse_provider_role_from_visible_text(provider_name, procedure_name, modifier),
                "modifier": modifier,
                "is_assist": "AS" in modifier,
                "line_service_date": line_service_date or "",
                "line_service_time_raw": line_time_raw or "",
                "line_service_datetime_raw": line_datetime_raw or service_dt_raw,
                "quantity": _parse_visible_quantity(quantity_text),
                "raw_row_text": normalized,
            }
        )
    return rows


def _build_capture_from_raw_transcript(raw_text: str) -> dict[str, Any]:
    lines = _parse_transcript_charge_rows(raw_text)
    cpts = _cpts_for_surgeon_lines(lines)
    mrn = _normalize_mrn_digits(re.search(r"\bMRN[:#]?\s*([A-Z0-9-]+)", raw_text, re.I).group(1)) if re.search(r"\bMRN[:#]?\s*([A-Z0-9-]+)", raw_text, re.I) else None
    patient_name = _parse_transcript_patient_name(raw_text)
    service_date = next((str(line.get("line_service_date") or "").strip() for line in lines if str(line.get("line_service_date") or "").strip()), None)
    surgeon_name = None
    for line in lines:
        provider_name = str(line.get("provider_name") or "").strip()
        if provider_name:
            surgeon_name = provider_name
            break
    return {
        "cpts": cpts,
        "service_date": service_date,
        "patient_name": patient_name,
        "mrn": mrn,
        "surgeon_name": surgeon_name,
        "lines": lines,
        "raw_transcript": raw_text,
    }


def _service_date_and_mrn_from_model(obj: dict[str, Any] | None, raw_text: str) -> tuple[str | None, str | None]:
    """Coerce service_date from model JSON + loose patterns in raw output; Epic often uses M/D/YYYY."""
    sd_out: str | None = None
    mrn_out: str | None = None
    if obj:
        for key in ("service_date", "date_of_service", "dos", "DOS", "charge_date"):
            val = obj.get(key)
            if val is not None and str(val).strip():
                sd_out = RvuPaymentService.coerce_service_date_iso(str(val)) or sd_out
                if sd_out:
                    break
        for key in ("mrn", "MRN", "patient_mrn", "medical_record_number"):
            val = obj.get(key)
            if val is not None and str(val).strip():
                mrn_out = _normalize_mrn_digits(val)
                break
    if not sd_out:
        for pat in (
            r'"service_date"\s*:\s*"([^"]+)"',
            r'"date_of_service"\s*:\s*"([^"]+)"',
            r"'service_date'\s*:\s*'([^']+)'",
        ):
            m = re.search(pat, raw_text, re.I)
            if m:
                sd_out = RvuPaymentService.coerce_service_date_iso(m.group(1))
                if sd_out:
                    break
    return sd_out, mrn_out


def _patient_name_from_model(obj: dict[str, Any] | None, raw_text: str) -> str | None:
    if obj:
        for key in ("patient_name", "patientName", "patient", "name"):
            val = obj.get(key)
            if isinstance(val, str) and val.strip():
                return val.strip()[:255]
            if isinstance(val, dict):
                nested = val.get("name")
                if isinstance(nested, str) and nested.strip():
                    return nested.strip()[:255]
    match = re.search(
        r"\bPatient(?:\s+Name)?[:\s-]+([A-Z][A-Za-z'`.-]+(?:\s+[A-Z][A-Za-z'`.-]+){1,3})\b",
        raw_text,
        re.I,
    )
    if match:
        return match.group(1).strip()[:255]
    return None


def _norm_cpt_from_row(row: dict) -> str:
    """Pull a 5-digit CPT from a model line object (various key spellings)."""
    for k in ("cpt", "CPT", "code", "Code", "procedure_code", "ProcedureCode", "procedureCode"):
        if k not in row:
            continue
        raw = str(row[k] or "").strip()
        m = re.search(r"\d{5}", raw)
        if m:
            return m.group(0)
    return ""


def _line_service_date_from_row(row: dict) -> str | None:
    """Per-row DOS from OCR (multi-day stays); prefer explicit line_service_date key."""
    for key in ("line_service_date", "service_date", "dos", "date_of_service", "charge_date"):
        v = row.get(key)
        if v:
            iso = RvuPaymentService.coerce_service_date_iso(str(v))
            if iso:
                return iso
    return None


def _line_from_row(row: dict) -> dict[str, Any] | None:
    cpt = _norm_cpt_from_row(row)
    if not re.fullmatch(r"\d{5}", cpt):
        return None
    proc = str(row.get("procedure_name") or row.get("description") or "").strip()
    provider_name = str(row.get("provider_name") or row.get("name") or "").strip()
    provider_role = str(row.get("provider_role") or row.get("role") or "unknown").strip().lower()
    if provider_role not in ("surgeon", "pa", "assistant", "unknown"):
        provider_role = "unknown"
    modifier = _normalize_modifier_text(str(row.get("modifier") or row.get("modifiers") or ""))
    is_assist = bool(row.get("is_assist")) or ("AS" in modifier) or (" AS" in proc.upper()) or provider_role in ("pa", "assistant")
    line_sd = _line_service_date_from_row(row)
    out: dict[str, Any] = {
        "cpt": cpt,
        "procedure_name": proc,
        "provider_name": provider_name,
        "provider_role": provider_role,
        "modifier": modifier,
        "is_assist": is_assist,
    }
    if line_sd:
        out["line_service_date"] = line_sd
    if str(row.get("line_service_datetime_raw") or "").strip():
        out["line_service_datetime_raw"] = str(row.get("line_service_datetime_raw") or "").strip()
    if str(row.get("line_service_time_raw") or "").strip():
        out["line_service_time_raw"] = str(row.get("line_service_time_raw") or "").strip()
    if str(row.get("raw_row_text") or "").strip():
        out["raw_row_text"] = str(row.get("raw_row_text") or "").strip()
    if row.get("quantity") not in (None, ""):
        out["quantity"] = row.get("quantity")
    return out


def _line_dedupe_key(line: dict[str, Any]) -> tuple[str, str, str, bool, str]:
    """Treat same CPT + provider as distinct rows when per-line DOS differs (multi-day captures)."""
    cpt = str(line.get("cpt") or "").strip()
    prov = str(line.get("provider_name") or "").strip().lower()
    role = str(line.get("provider_role") or "unknown").strip().lower()
    is_a = bool(line.get("is_assist"))
    lsd = str(line.get("line_service_date") or "").strip()
    if not lsd:
        for key in ("service_date", "dos", "date_of_service", "charge_date"):
            v = line.get(key)
            if v:
                lsd = (RvuPaymentService.coerce_service_date_iso(str(v)) or "").strip()
                break
    return (cpt, prov, role, is_a, lsd)


def _modifier_tokens(value: str) -> tuple[str, ...]:
    parts = [
        re.sub(r"[^A-Z0-9]", "", p.strip().upper())
        for p in str(value or "").replace("/", ",").split(",")
        if p.strip()
    ]
    return tuple(dict.fromkeys(parts))


def _clean_line_text(value: Any) -> str:
    return str(value or "").strip()


def _normalized_provider_role(value: Any) -> str:
    role = _clean_line_text(value).lower() or "unknown"
    return role if role in ("surgeon", "pa", "assistant", "unknown") else "unknown"


def _row_is_sparse(line: dict[str, Any]) -> bool:
    return (
        not _clean_line_text(line.get("provider_name"))
        or _normalized_provider_role(line.get("provider_role")) == "unknown"
        or not _clean_line_text(line.get("procedure_name"))
    )


def _merge_line_details(existing: dict[str, Any], incoming: dict[str, Any]) -> bool:
    changed = False

    def fill(field: str) -> None:
        nonlocal changed
        if not str(existing.get(field) or "").strip() and str(incoming.get(field) or "").strip():
            existing[field] = incoming[field]
            changed = True

    fill("procedure_name")
    fill("provider_name")

    existing_role = str(existing.get("provider_role") or "unknown").strip().lower()
    incoming_role = str(incoming.get("provider_role") or "unknown").strip().lower()
    if existing_role == "unknown" and incoming_role in ("surgeon", "pa", "assistant"):
        existing["provider_role"] = incoming_role
        changed = True

    if not bool(existing.get("is_assist")) and bool(incoming.get("is_assist")):
        existing["is_assist"] = True
        changed = True

    existing_mods = _modifier_tokens(existing.get("modifier") or "")
    incoming_mods = _modifier_tokens(incoming.get("modifier") or "")
    if incoming_mods and not existing_mods:
        existing["modifier"] = ",".join(incoming_mods)
        changed = True

    if not str(existing.get("line_service_date") or "").strip() and str(incoming.get("line_service_date") or "").strip():
        existing["line_service_date"] = incoming["line_service_date"]
        changed = True

    for field in ("line_service_datetime_raw", "line_service_time_raw", "raw_row_text", "quantity"):
        if existing.get(field) in (None, "") and incoming.get(field) not in (None, ""):
            existing[field] = incoming[field]
            changed = True

    return changed


def _rows_can_merge(existing: dict[str, Any], incoming: dict[str, Any]) -> bool:
    existing_mods = _modifier_tokens(existing.get("modifier") or "")
    incoming_mods = _modifier_tokens(incoming.get("modifier") or "")
    if existing_mods and incoming_mods and existing_mods != incoming_mods:
        return False
    return True


def _merge_candidate_score(existing: dict[str, Any], incoming: dict[str, Any]) -> int | None:
    if str(existing.get("cpt") or "").strip() != str(incoming.get("cpt") or "").strip():
        return None
    if bool(existing.get("is_assist")) != bool(incoming.get("is_assist")):
        return None
    if not _rows_can_merge(existing, incoming):
        return None

    score = 0

    existing_sd = _clean_line_text(existing.get("line_service_date"))
    incoming_sd = _clean_line_text(incoming.get("line_service_date"))
    if existing_sd and incoming_sd:
        if existing_sd != incoming_sd:
            return None
        score += 4
    elif existing_sd or incoming_sd:
        score += 1

    existing_provider = _clean_line_text(existing.get("provider_name")).lower()
    incoming_provider = _clean_line_text(incoming.get("provider_name")).lower()
    if existing_provider and incoming_provider:
        if existing_provider != incoming_provider:
            return None
        score += 8
    elif existing_provider or incoming_provider:
        score += 2

    existing_role = _normalized_provider_role(existing.get("provider_role"))
    incoming_role = _normalized_provider_role(incoming.get("provider_role"))
    if existing_role != "unknown" and incoming_role != "unknown":
        if existing_role != incoming_role:
            return None
        score += 4
    elif existing_role != "unknown" or incoming_role != "unknown":
        score += 1

    existing_proc = _clean_line_text(existing.get("procedure_name")).lower()
    incoming_proc = _clean_line_text(incoming.get("procedure_name")).lower()
    if existing_proc and incoming_proc:
        if existing_proc != incoming_proc:
            return None
        score += 2
    elif existing_proc or incoming_proc:
        score += 1

    return score


def _best_merge_candidate(lines: list[dict[str, Any]], incoming: dict[str, Any]) -> tuple[int | None, bool]:
    best_idx: int | None = None
    best_score: int | None = None
    ambiguous = False
    for idx, existing in enumerate(lines):
        score = _merge_candidate_score(existing, incoming)
        if score is None:
            continue
        if best_score is None or score > best_score:
            best_idx = idx
            best_score = score
            ambiguous = False
            continue
        if score == best_score:
            ambiguous = True
    return best_idx, ambiguous


def _append_or_merge_line(
    lines_out: list[dict[str, Any]],
    seen_lines: dict[tuple[str, str, str, bool, str], list[int]],
    row: dict[str, Any],
) -> tuple[dict[str, Any] | None, bool]:
    line = _line_from_row(row)
    if not line:
        return None, False

    key = _line_dedupe_key(line)
    match_indexes = seen_lines.get(key, [])
    for idx in match_indexes:
        existing = lines_out[idx]
        if _rows_can_merge(existing, line):
            _merge_line_details(existing, line)
            return existing, False

    candidate_idx, ambiguous = _best_merge_candidate(lines_out, line)
    if candidate_idx is not None and not ambiguous:
        _merge_line_details(lines_out[candidate_idx], line)
        return lines_out[candidate_idx], False

    if ambiguous and _row_is_sparse(line):
        return None, True

    lines_out.append(line)
    seen_lines.setdefault(key, []).append(len(lines_out) - 1)
    return line, False


def _cpts_for_surgeon_lines(lines: list[Any]) -> list[str]:
    """Ordered CPT list for payment rows — one entry per surgeon line (allows duplicate CPT codes)."""
    out: list[str] = []
    for line in lines or []:
        if not isinstance(line, dict):
            continue
        if line.get("is_assist"):
            continue
        if str(line.get("provider_role") or "").strip().lower() in ("pa", "assistant"):
            continue
        cpt = str(line.get("cpt") or "").strip()
        if re.fullmatch(r"\d{5}", cpt):
            out.append(cpt)
    return out


def _json_roundtrip(value: Any) -> Any:
    try:
        return json.loads(json.dumps(value, default=str))
    except Exception:
        return value


class RvuCptExtractionService:
    """Anthropic / OpenAI vision and text → structured charge capture (no local LLM)."""

    vision_model = _VISION_MODEL
    text_model = _TEXT_MODEL
    vision_provider = "anthropic"
    openai_api_key = _OPENAI_API_KEY
    anthropic_api_key = _ANTHROPIC_API_KEY
    last_charge_capture_backend: str | None = None

    @staticmethod
    def _record_ai_run(
        artifacts: list[dict[str, Any]],
        *,
        stage: str,
        provider: str,
        model: str,
        raw_response: str | None = None,
        parsed_json: Any = None,
        error_text: str | None = None,
    ) -> None:
        artifacts.append(
            {
                "stage": stage,
                "provider": provider,
                "model": model,
                "raw_response": str(raw_response or ""),
                "parsed_json": _json_roundtrip(parsed_json) if parsed_json is not None else None,
                "error_text": str(error_text or ""),
            }
        )

    def get_vision_config(self) -> dict[str, str]:
        first = first_resolvable_pipeline_stage(self.anthropic_api_key, self.openai_api_key)
        last_used = self.last_charge_capture_backend or ""
        return {
            "provider": self.vision_provider,
            "vision_model": self.vision_model,
            "text_model": self.text_model,
            "openai_key_set": "yes" if bool(self.openai_api_key) else "no",
            "anthropic_key_set": "yes" if bool(self.anthropic_api_key) else "no",
            "local_only_lock": "yes" if _LOCK_LOCAL_ONLY else "no",
            "vision_api_fallback_order": ",".join(_VISION_API_FALLBACK_ORDER),
            "vision_pipeline": ",".join(_RVU_VISION_PIPELINE),
            "charge_capture_first_stage": first,
            "charge_capture_hint": (
                f"Each scan tries stages in order ({','.join(_RVU_VISION_PIPELINE)}); "
                f"first success wins. Next scan will start at: {first}"
                + (f"; last completed scan used: {last_used}" if last_used else "")
            ),
            "last_charge_capture_backend": last_used,
            "op_note_pipeline": ",".join(_RVU_OP_NOTE_PIPELINE),
        }

    def set_vision_config(
        self,
        provider: str | None = None,
        model: str | None = None,
        openai_api_key: str | None = None,
        anthropic_api_key: str | None = None,
    ) -> dict[str, str]:
        def _validate_model_name(name: str) -> str:
            v = (name or "").strip()
            if not v:
                raise ValueError("vision_model cannot be empty")
            if "@" in v or " " in v:
                raise ValueError("vision_model looks invalid (do not use email/whitespace)")
            if len(v) > 120:
                raise ValueError("vision_model is too long")
            return v

        if openai_api_key is not None:
            self.openai_api_key = openai_api_key.strip()
        if anthropic_api_key is not None:
            self.anthropic_api_key = anthropic_api_key.strip()
        if provider:
            p = provider.strip().lower()
            if p not in ("anthropic", "openai"):
                raise ValueError("vision provider must be 'anthropic' or 'openai'")
            self.vision_provider = p
            if model:
                self.vision_model = _validate_model_name(model)
            else:
                self.vision_model = _VISION_MODEL
        elif model:
            self.vision_model = _validate_model_name(model)

        return self.get_vision_config()

    def shrink_image(self, image_bytes: bytes, max_dim: int = 1600) -> bytes:
        if max_dim == 1600:
            max_dim = _IMAGE_MAX_DIM
        img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        w, h = img.size
        if max(w, h) > max_dim:
            scale = max_dim / max(w, h)
            img = img.resize((int(w * scale), int(h * scale)), Image.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=85)
        return buf.getvalue()

    @staticmethod
    def right_table_crop(image_bytes: bytes) -> bytes:
        """
        Crop the right-side table columns (provider/modifier often live there).
        Keeps full vertical range and most of horizontal right half.
        """
        img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        w, h = img.size
        x0 = int(w * 0.35)
        crop = img.crop((x0, 0, w, h))
        buf = io.BytesIO()
        crop.save(buf, format="JPEG", quality=85)
        return buf.getvalue()

    @staticmethod
    def demographics_crop(image_bytes: bytes) -> bytes:
        """
        Crop the top demographics/header band where patient name, MRN,
        and shared DOS usually appear.
        """
        img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        w, h = img.size
        crop = img.crop((0, 0, w, int(h * 0.42)))
        buf = io.BytesIO()
        crop.save(buf, format="JPEG", quality=85)
        return buf.getvalue()

    @staticmethod
    def _has_provider_context(cap: dict[str, Any]) -> bool:
        if cap.get("surgeon_name"):
            return True
        for row in cap.get("lines") or []:
            if not isinstance(row, dict):
                continue
            if str(row.get("provider_name") or "").strip():
                return True
            if str(row.get("modifier") or "").strip():
                return True
            if row.get("is_assist"):
                return True
        return False

    @staticmethod
    def _needs_modifier_retry(cap: dict[str, Any]) -> bool:
        surgeon_lines = [
            row
            for row in (cap.get("lines") or [])
            if isinstance(row, dict)
            and not bool(row.get("is_assist"))
            and str(row.get("provider_role") or "").strip().lower() not in ("pa", "assistant")
            and re.fullmatch(r"\d{5}", str(row.get("cpt") or "").strip())
        ]
        if not surgeon_lines:
            return False
        missing_modifier_lines = [
            row for row in surgeon_lines if not _modifier_tokens(row.get("modifier") or "")
        ]
        if not missing_modifier_lines:
            return False
        # The main OCR pass found charge rows, but the rightmost modifier column is easy to miss.
        return any(
            str(row.get("procedure_name") or row.get("provider_name") or "").strip()
            for row in missing_modifier_lines
        )

    @staticmethod
    def _needs_demographics_retry(cap: dict[str, Any]) -> bool:
        return _valid_mrn_or_none(cap.get("mrn")) is None

    def _augment_with_full_transcript(
        self,
        cap: dict[str, Any],
        image_jpeg_bytes: bytes,
        *,
        provider: str,
        artifacts: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        # Disabled in the hot path for now. It adds latency and has been
        # introducing noisy top-level fields in field testing.
        return cap
        b64 = base64.b64encode(image_jpeg_bytes).decode()
        if provider == "anthropic":
            raw_text = self.anthropic_generate_once(_RAW_TRANSCRIPT_PROMPT, b64, max_tokens=4096)
            model = self.vision_model
        else:
            raw_text = self.openai_generate_once(_RAW_TRANSCRIPT_PROMPT, b64, max_tokens=4096)
            model = _OPENAI_VISION_MODEL
        transcript_cap = _build_capture_from_raw_transcript(raw_text)
        if artifacts is not None:
            self._record_ai_run(
                artifacts,
                stage="vision_transcript",
                provider=provider,
                model=model,
                raw_response=raw_text,
                parsed_json=transcript_cap,
            )
        return self.merge_captures(cap, transcript_cap)

    @staticmethod
    def _modifier_retry_prompt(cap: dict[str, Any]) -> str:
        known_rows: list[dict[str, Any]] = []
        for row in cap.get("lines") or []:
            if not isinstance(row, dict):
                continue
            cpt = str(row.get("cpt") or "").strip()
            if not re.fullmatch(r"\d{5}", cpt):
                continue
            known_rows.append(
                {
                    "cpt": cpt,
                    "procedure_name": str(row.get("procedure_name") or "").strip(),
                    "provider_name": str(row.get("provider_name") or "").strip(),
                    "provider_role": str(row.get("provider_role") or "unknown").strip().lower(),
                    "modifier": _normalize_modifier_text(str(row.get("modifier") or "")),
                    "line_service_date": str(row.get("line_service_date") or "").strip(),
                }
            )
        return _MODIFIER_FOCUS_PROMPT.format(known_json=json.dumps(known_rows))

    def _run_demographics_retry(
        self,
        merged: dict[str, Any],
        image_jpeg_bytes: bytes,
        *,
        provider: str,
        artifacts: list[dict[str, Any]],
    ) -> dict[str, Any]:
        if not self._needs_demographics_retry(merged):
            return merged
        try:
            focus_image = self.demographics_crop(image_jpeg_bytes)
            focus_b64 = base64.b64encode(focus_image).decode()
        except Exception:
            return merged

        providers: list[str] = []
        if provider == "anthropic":
            providers.append("anthropic")
            if self.openai_api_key:
                providers.append("openai")
        else:
            providers.append("openai")
            if self.anthropic_api_key:
                providers.append("anthropic")

        out = merged
        for stage_provider in providers:
            try:
                if stage_provider == "anthropic":
                    raw_text = self.anthropic_generate_once(_DEMOGRAPHICS_FOCUS_PROMPT, focus_b64)
                    model = self.vision_model
                else:
                    raw_text = self.openai_generate_once(_DEMOGRAPHICS_FOCUS_PROMPT, focus_b64)
                    model = _OPENAI_VISION_MODEL
                parsed = self.parse_demographics_response(raw_text)
                parsed["mrn"] = _valid_mrn_or_none(parsed.get("mrn"))
                self._record_ai_run(
                    artifacts,
                    stage="vision_demographics_retry",
                    provider=stage_provider,
                    model=model,
                    raw_response=raw_text,
                    parsed_json=parsed,
                )
                out = self.merge_captures(out, parsed)
                if _valid_mrn_or_none(out.get("mrn")):
                    break
            except Exception:
                continue
        return out

    def openai_generate_once(
        self,
        prompt: str,
        image_b64: str,
        *,
        max_tokens: int = 2048,
        http_timeout_sec: float | None = None,
    ) -> str:
        if not self.openai_api_key:
            raise RuntimeError("OPENAI_API_KEY is not set")
        ot = float(http_timeout_sec) if http_timeout_sec is not None else float(_OPENAI_TIMEOUT)
        payload = {
            "model": _OPENAI_VISION_MODEL,
            "temperature": 0,
            "max_tokens": max_tokens,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"}},
                    ],
                }
            ],
        }
        req = urllib.request.Request(
            "https://api.openai.com/v1/chat/completions",
            data=json.dumps(payload).encode(),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.openai_api_key}",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=ot) as resp:
                data = json.loads(resp.read().decode())
        except urllib.error.HTTPError as exc:
            body = exc.read().decode(errors="ignore")
            raise RuntimeError(f"OpenAI HTTP {exc.code}: {body[:400]}") from exc
        except Exception as exc:
            raise RuntimeError(f"OpenAI request failed: {exc}") from exc

        try:
            return str(data["choices"][0]["message"]["content"] or "")
        except Exception as exc:
            raise RuntimeError("OpenAI returned unexpected response format") from exc

    def anthropic_generate_once(
        self,
        prompt: str,
        image_b64: str,
        *,
        max_tokens: int = 2048,
        http_timeout_sec: float | None = None,
    ) -> str:
        if not self.anthropic_api_key:
            raise RuntimeError("ANTHROPIC_API_KEY is not set")
        requested = (self.vision_model or _ANTHROPIC_VISION_MODEL).strip()
        model_candidates = [requested] + [m for m in _ANTHROPIC_FALLBACK_MODELS if m != requested]
        last_err = ""
        read_timeout = float(http_timeout_sec) if http_timeout_sec is not None else float(_ANTHROPIC_TIMEOUT)
        for model_name in model_candidates:
            payload = {
                "model": model_name,
                "max_tokens": max_tokens,
                "temperature": 0,
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": prompt},
                            {
                                "type": "image",
                                "source": {
                                    "type": "base64",
                                    "media_type": "image/jpeg",
                                    "data": image_b64,
                                },
                            },
                        ],
                    }
                ],
            }
            req = urllib.request.Request(
                "https://api.anthropic.com/v1/messages",
                data=json.dumps(payload).encode(),
                headers={
                    "Content-Type": "application/json",
                    "x-api-key": self.anthropic_api_key,
                    "anthropic-version": "2023-06-01",
                },
                method="POST",
            )
            try:
                with urllib.request.urlopen(req, timeout=read_timeout) as resp:
                    data = json.loads(resp.read().decode())
                # If a fallback succeeded, keep the working model for next requests.
                self.vision_model = model_name
                content = data.get("content") or []
                texts = [str(c.get("text") or "") for c in content if isinstance(c, dict) and c.get("type") == "text"]
                return "\n".join(t for t in texts if t).strip()
            except urllib.error.HTTPError as exc:
                body = exc.read().decode(errors="ignore")
                last_err = f"HTTP {exc.code} using model '{model_name}'"
                # Try next model on not-found style errors.
                if exc.code in (400, 404):
                    continue
                raise RuntimeError(f"Anthropic {last_err}: {body[:300]}") from exc
            except Exception as exc:
                raise RuntimeError(f"Anthropic request failed: {exc}") from exc
        raise RuntimeError(
            f"Anthropic model unavailable ({last_err}). Set a valid Claude model in Vision model."
        )

    def anthropic_text_once(
        self,
        prompt: str,
        *,
        max_tokens: int = 4096,
        http_timeout_sec: float | None = None,
    ) -> str:
        if not self.anthropic_api_key:
            raise RuntimeError("ANTHROPIC_API_KEY is not set")
        requested = (self.text_model or _TEXT_MODEL).strip()
        model_candidates = [requested] + [m for m in _ANTHROPIC_FALLBACK_MODELS if m != requested]
        last_err = ""
        read_timeout = float(http_timeout_sec) if http_timeout_sec is not None else float(_ANTHROPIC_TIMEOUT)
        for model_name in model_candidates:
            payload = {
                "model": model_name,
                "max_tokens": max_tokens,
                "temperature": 0,
                "messages": [
                    {
                        "role": "user",
                        "content": [{"type": "text", "text": prompt}],
                    }
                ],
            }
            req = urllib.request.Request(
                "https://api.anthropic.com/v1/messages",
                data=json.dumps(payload).encode(),
                headers={
                    "Content-Type": "application/json",
                    "x-api-key": self.anthropic_api_key,
                    "anthropic-version": "2023-06-01",
                },
                method="POST",
            )
            try:
                with urllib.request.urlopen(req, timeout=read_timeout) as resp:
                    data = json.loads(resp.read().decode())
                self.text_model = model_name
                content = data.get("content") or []
                texts = [str(c.get("text") or "") for c in content if isinstance(c, dict) and c.get("type") == "text"]
                return "\n".join(t for t in texts if t).strip()
            except urllib.error.HTTPError as exc:
                body = exc.read().decode(errors="ignore")
                last_err = f"HTTP {exc.code} using model '{model_name}'"
                if exc.code in (400, 404):
                    continue
                raise RuntimeError(f"Anthropic {last_err}: {body[:300]}") from exc
            except Exception as exc:
                raise RuntimeError(f"Anthropic request failed: {exc}") from exc
        raise RuntimeError(f"Anthropic text model unavailable ({last_err}).")

    def openai_text_once(
        self,
        prompt: str,
        *,
        max_tokens: int = 4096,
        http_timeout_sec: float | None = None,
    ) -> str:
        if not self.openai_api_key:
            raise RuntimeError("OPENAI_API_KEY is not set")
        ot = float(http_timeout_sec) if http_timeout_sec is not None else float(_OPENAI_TIMEOUT)
        payload = {
            "model": _OPENAI_TEXT_MODEL,
            "temperature": 0,
            "max_tokens": max_tokens,
            "messages": [{"role": "user", "content": prompt}],
        }
        req = urllib.request.Request(
            "https://api.openai.com/v1/chat/completions",
            data=json.dumps(payload).encode(),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.openai_api_key}",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=ot) as resp:
                data = json.loads(resp.read().decode())
        except urllib.error.HTTPError as exc:
            body = exc.read().decode(errors="ignore")
            raise RuntimeError(f"OpenAI HTTP {exc.code}: {body[:400]}") from exc
        except Exception as exc:
            raise RuntimeError(f"OpenAI request failed: {exc}") from exc
        try:
            return str(data["choices"][0]["message"]["content"] or "")
        except Exception as exc:
            raise RuntimeError("OpenAI returned unexpected response format") from exc

    @staticmethod
    def merge_captures(primary: dict[str, Any], extra: dict[str, Any]) -> dict[str, Any]:
        """Append extra CPT lines to primary; primary wins for service_date / mrn."""
        lines_out: list[dict[str, Any]] = []
        cpts_out: list[str] = []
        seen_lines: dict[tuple[str, str, str, bool, str], list[int]] = {}

        def add_row(row: dict) -> None:
            line, dropped = _append_or_merge_line(lines_out, seen_lines, row)
            if dropped or not line:
                return
            if lines_out and lines_out[-1] is line and not line.get("is_assist") and str(line.get("provider_role") or "").strip().lower() != "pa":
                cpts_out.append(line["cpt"])

        def append_surgeon_stub(code: str) -> None:
            """Bare CPT from model top-level array — no dedupe key (may repeat same code)."""
            line = _line_from_row(
                {"cpt": code, "procedure_name": "", "provider_role": "surgeon", "is_assist": False}
            )
            if not line:
                return
            lines_out.append(line)
            cpts_out.append(line["cpt"])

        for row in primary.get("lines") or []:
            if isinstance(row, dict):
                add_row(row)
        want_p = Counter(
            c.strip()
            for c in (primary.get("cpts") or [])
            if isinstance(c, str) and re.fullmatch(r"\d{5}", c.strip())
        )
        have_p = Counter(_cpts_for_surgeon_lines(lines_out))
        for code, need in (want_p - have_p).items():
            for _ in range(need):
                append_surgeon_stub(code)

        for row in extra.get("lines") or []:
            if isinstance(row, dict):
                add_row(row)
        want_e = Counter(
            c.strip()
            for c in (extra.get("cpts") or [])
            if isinstance(c, str) and re.fullmatch(r"\d{5}", c.strip())
        )
        have_e = Counter(_cpts_for_surgeon_lines(lines_out))
        for code, need in (want_e - have_e).items():
            for _ in range(need):
                append_surgeon_stub(code)

        def _sd(m: dict[str, Any]) -> str | None:
            v = m.get("service_date")
            if v is None or not str(v).strip():
                return None
            return RvuPaymentService.coerce_service_date_iso(str(v))

        def _mrn(m: dict[str, Any]) -> str | None:
            v = m.get("mrn")
            if v is None or not str(v).strip():
                return None
            return _normalize_mrn_digits(v)

        p_sd, e_sd = _sd(primary), _sd(extra)
        p_mrn, e_mrn = _mrn(primary), _mrn(extra)
        p_patient_name = _patient_name_from_model(primary, "")
        e_patient_name = _patient_name_from_model(extra, "")
        merged = {
            "cpts": _cpts_for_surgeon_lines(lines_out) or cpts_out,
            "lines": lines_out,
            "service_date": p_sd or e_sd,
            "patient_name": p_patient_name or e_patient_name,
            "mrn": p_mrn or e_mrn,
            "surgeon_name": str(primary.get("surgeon_name") or extra.get("surgeon_name") or "").strip() or None,
        }
        raw_transcript = str(primary.get("raw_transcript") or extra.get("raw_transcript") or "").strip()
        if raw_transcript:
            merged["raw_transcript"] = raw_transcript
        merged_runs = []
        for source in (primary, extra):
            runs = source.get("_ai_runs")
            if isinstance(runs, list):
                merged_runs.extend(_json_roundtrip(runs) or [])
        if merged_runs:
            merged["_ai_runs"] = merged_runs
        return merged

    def parse_refine_additional(self, text: str) -> dict[str, Any]:
        """Parse second-pass JSON with additional_lines (or lines) only."""
        obj = self._extract_json_object(text)
        if not obj:
            return {"cpts": [], "lines": [], "service_date": None, "patient_name": None, "mrn": None}
        raw = obj.get("additional_lines")
        if raw is None:
            raw = obj.get("lines") or []
        lines: list[dict[str, Any]] = []
        cpts: list[str] = []
        seen_lines: dict[tuple[str, str, str, bool, str], list[int]] = {}
        for row in raw:
            if not isinstance(row, dict):
                continue
            line, dropped = _append_or_merge_line(lines, seen_lines, row)
            if dropped or not line:
                continue
        cpts = _cpts_for_surgeon_lines(lines)
        if not cpts:
            seen_surgeon_cpts: set[str] = set()
            for m in re.finditer(r'["\']cpt["\']\s*:\s*["\'](\d{5})["\']', text, re.I):
                code = m.group(1)
                if code not in seen_surgeon_cpts:
                    seen_surgeon_cpts.add(code)
                    cpts.append(code)
                    lines.append({"cpt": code, "procedure_name": "", "provider_name": "", "provider_role": "surgeon", "modifier": "", "is_assist": False})
        sd, mrn = _service_date_and_mrn_from_model(obj, text)
        patient_name = _patient_name_from_model(obj, text)
        surgeon_name = str((obj or {}).get("surgeon_name") or "").strip() if obj else ""
        return {"cpts": cpts, "lines": lines, "service_date": sd, "patient_name": patient_name, "mrn": mrn, "surgeon_name": surgeon_name or None}

    def refine_vision_additional(
        self,
        image_jpeg_bytes: bytes,
        first_cap: dict[str, Any],
        *,
        artifact_sink: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        known = first_cap.get("cpts") or []
        b64 = base64.b64encode(image_jpeg_bytes).decode()
        prompt = _REFINE_VISION_PROMPT.format(known_json=json.dumps(known))
        empty = {"cpts": [], "lines": [], "service_date": None, "patient_name": None, "mrn": None}
        for stage in _RVU_VISION_PIPELINE:
            if stage == "anthropic" and self.anthropic_api_key:
                try:
                    text = self.anthropic_generate_once(prompt, b64, max_tokens=2048)
                    parsed = self.parse_refine_additional(text)
                    if artifact_sink is not None:
                        self._record_ai_run(
                            artifact_sink,
                            stage="vision_refine_additional",
                            provider="anthropic",
                            model=self.vision_model,
                            raw_response=text,
                            parsed_json=parsed,
                        )
                    return parsed
                except Exception:
                    continue
            if stage == "openai" and self.openai_api_key:
                try:
                    text = self.openai_generate_once(prompt, b64, max_tokens=2048)
                    parsed = self.parse_refine_additional(text)
                    if artifact_sink is not None:
                        self._record_ai_run(
                            artifact_sink,
                            stage="vision_refine_additional",
                            provider="openai",
                            model=_OPENAI_VISION_MODEL,
                            raw_response=text,
                            parsed_json=parsed,
                        )
                    return parsed
                except Exception:
                    continue
        return empty

    def refine_text_additional(
        self,
        raw_text: str,
        first_cap: dict[str, Any],
        *,
        artifact_sink: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        known = first_cap.get("cpts") or []
        prompt = _REFINE_TEXT_PROMPT.format(known_json=json.dumps(known)) + "\n\nText:\n" + raw_text[:8000]
        empty = {"cpts": [], "lines": [], "service_date": None, "patient_name": None, "mrn": None}
        for stage in _RVU_VISION_PIPELINE:
            if stage == "anthropic" and self.anthropic_api_key:
                try:
                    text = self.anthropic_text_once(prompt, max_tokens=4096)
                    parsed = self.parse_refine_additional(text)
                    if artifact_sink is not None:
                        self._record_ai_run(
                            artifact_sink,
                            stage="text_refine_additional",
                            provider="anthropic",
                            model=self.text_model,
                            raw_response=text,
                            parsed_json=parsed,
                        )
                    return parsed
                except Exception:
                    continue
            if stage == "openai" and self.openai_api_key:
                try:
                    text = self.openai_text_once(prompt, max_tokens=4096)
                    parsed = self.parse_refine_additional(text)
                    if artifact_sink is not None:
                        self._record_ai_run(
                            artifact_sink,
                            stage="text_refine_additional",
                            provider="openai",
                            model=_OPENAI_TEXT_MODEL,
                            raw_response=text,
                            parsed_json=parsed,
                        )
                    return parsed
                except Exception:
                    continue
        return empty

    @staticmethod
    def _first_balanced_json_object(text: str) -> str | None:
        """Extract the first {...} block with brace/string-aware matching (greedy regex breaks on nested {})."""
        start = text.find("{")
        if start < 0:
            return None
        depth = 0
        in_str = False
        esc = False
        for i in range(start, len(text)):
            c = text[i]
            if in_str:
                if esc:
                    esc = False
                elif c == "\\":
                    esc = True
                elif c == '"':
                    in_str = False
                continue
            if c == '"':
                in_str = True
                continue
            if c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    return text[start : i + 1]
        return None

    def _extract_json_object(self, text: str) -> dict[str, Any] | None:
        text = text.strip()
        try:
            obj = json.loads(text)
            if isinstance(obj, dict):
                return obj
        except json.JSONDecodeError:
            pass
        chunk = self._first_balanced_json_object(text)
        if chunk:
            try:
                obj = json.loads(chunk)
                if isinstance(obj, dict):
                    return obj
            except json.JSONDecodeError:
                pass
        return None

    def parse_demographics_response(self, text: str) -> dict[str, Any]:
        obj = self._extract_json_object(text)
        if not obj:
            return {"cpts": [], "service_date": None, "patient_name": None, "mrn": None, "surgeon_name": None, "lines": []}
        sd, mrn = _service_date_and_mrn_from_model(obj, text)
        patient_name = _patient_name_from_model(obj, text)
        surgeon_name = str(obj.get("surgeon_name") or "").strip() or None
        return {
            "cpts": [],
            "service_date": sd,
            "patient_name": patient_name,
            "mrn": mrn,
            "surgeon_name": surgeon_name,
            "lines": [],
        }

    def parse_capture_response(self, text: str) -> dict[str, Any]:
        """
        Returns { cpts, service_date, mrn, surgeon_name, lines }.
        """
        obj = self._extract_json_object(text)
        lines: list[dict[str, Any]] = []
        cpts: list[str] = []
        seen_lines: dict[tuple[str, str, str, bool, str], list[int]] = {}
        if obj:
            raw_lines = obj.get("lines") or []

            for row in raw_lines:
                if not isinstance(row, dict):
                    continue
                line, dropped = _append_or_merge_line(lines, seen_lines, row)
                if dropped or not line:
                    continue

            # Some models return a top-level "cpts" array without filling "lines"
            raw_cpts = obj.get("cpts")
            if isinstance(raw_cpts, list):
                have_c = Counter(_cpts_for_surgeon_lines(lines))
                want_c = Counter(
                    c.strip()
                    for c in raw_cpts
                    if isinstance(c, str) and re.fullmatch(r"\d{5}", c.strip())
                )
                for code, need in (want_c - have_c).items():
                    for _ in range(need):
                        lines.append(
                            {
                                "cpt": code,
                                "procedure_name": "",
                                "provider_name": "",
                                "provider_role": "surgeon",
                                "modifier": "",
                                "is_assist": False,
                            }
                        )

            cpts = _cpts_for_surgeon_lines(lines)
            sd, mrn = _service_date_and_mrn_from_model(obj, text)
            patient_name = _patient_name_from_model(obj, text)
            surgeon_name = str((obj or {}).get("surgeon_name") or "").strip()
            if cpts or lines or sd or mrn or patient_name or surgeon_name:
                return {
                    "cpts": cpts,
                    "service_date": sd,
                    "patient_name": patient_name,
                    "mrn": mrn,
                    "surgeon_name": surgeon_name or None,
                    "lines": lines,
                }

        # Recover cpt fields from messy / truncated JSON in the raw model string
        seen_surgeon_cpts: set[str] = set()
        for m in re.finditer(r'["\']cpt["\']\s*:\s*["\'](\d{5})["\']', text, re.I):
            code = m.group(1)
            if code not in seen_surgeon_cpts:
                seen_surgeon_cpts.add(code)
                cpts.append(code)
                lines.append({"cpt": code, "procedure_name": "", "provider_name": "", "provider_role": "surgeon", "modifier": "", "is_assist": False})
        if cpts:
            sd, mrn = _service_date_and_mrn_from_model(obj, text)
            patient_name = _patient_name_from_model(obj, text)
            return {"cpts": cpts, "service_date": sd, "patient_name": patient_name, "mrn": mrn, "surgeon_name": None, "lines": lines}

        # Legacy: JSON array of CPT strings
        m = re.search(r"\[.*?\]", text, re.DOTALL)
        if m:
            try:
                arr = json.loads(m.group(0))
                if isinstance(arr, list):
                    cpts = [c.strip() for c in arr if isinstance(c, str) and re.fullmatch(r"\d{5}", c.strip())]
                    return {
                        "cpts": cpts,
                        "service_date": None,
                        "mrn": None,
                        "surgeon_name": None,
                        "lines": [{"cpt": c, "procedure_name": "", "provider_name": "", "provider_role": "surgeon", "modifier": "", "is_assist": False} for c in cpts],
                    }
            except json.JSONDecodeError:
                pass
        return {"cpts": [], "service_date": None, "patient_name": None, "mrn": None, "surgeon_name": None, "lines": []}

    def _stream_vision_openai(self, image_jpeg_bytes: bytes):
        artifacts: list[dict[str, Any]] = []
        b64 = base64.b64encode(image_jpeg_bytes).decode()
        try:
            text = self.openai_generate_once(_STRUCTURE_PROMPT, b64)
        except Exception as exc:
            yield "error", str(exc)
            return
        if text:
            yield "token", text
        merged = self.parse_capture_response(text)
        self._record_ai_run(
            artifacts,
            stage="vision_primary",
            provider="openai",
            model=_OPENAI_VISION_MODEL,
            raw_response=text,
            parsed_json=merged,
        )
        if not self._has_provider_context(merged):
            try:
                yield "token", "\n[OpenAI table OCR pass]"
                text2 = self.openai_generate_once(_TABLE_FOCUS_PROMPT, b64)
                if text2:
                    yield "token", text2
                parsed2 = self.parse_capture_response(text2)
                self._record_ai_run(
                    artifacts,
                    stage="vision_table_focus",
                    provider="openai",
                    model=_OPENAI_VISION_MODEL,
                    raw_response=text2,
                    parsed_json=parsed2,
                )
                merged = self.merge_captures(merged, parsed2)
            except Exception:
                pass
        merged["_ai_runs"] = artifacts
        yield "done", merged

    def _stream_vision_anthropic(self, image_jpeg_bytes: bytes):
        artifacts: list[dict[str, Any]] = []
        b64 = base64.b64encode(image_jpeg_bytes).decode()
        try:
            text = self.anthropic_generate_once(_STRUCTURE_PROMPT, b64)
        except Exception as exc:
            yield "error", str(exc)
            return
        if text:
            yield "token", text
        merged = self.parse_capture_response(text)
        self._record_ai_run(
            artifacts,
            stage="vision_primary",
            provider="anthropic",
            model=self.vision_model,
            raw_response=text,
            parsed_json=merged,
        )
        if not self._has_provider_context(merged):
            try:
                yield "token", "\n[Anthropic table OCR pass]"
                text2 = self.anthropic_generate_once(_TABLE_FOCUS_PROMPT, b64)
                if text2:
                    yield "token", text2
                parsed2 = self.parse_capture_response(text2)
                self._record_ai_run(
                    artifacts,
                    stage="vision_table_focus",
                    provider="anthropic",
                    model=self.vision_model,
                    raw_response=text2,
                    parsed_json=parsed2,
                )
                merged = self.merge_captures(merged, parsed2)
            except Exception:
                pass
        merged["_ai_runs"] = artifacts
        yield "done", merged

    def stream_vision(self, image_jpeg_bytes: bytes, scan_mode: str = "balanced"):
        """Ordered providers from RVU_VISION_PIPELINE (anthropic → openai by default)."""
        _ = scan_mode  # scan modes applied only to legacy local vision; cloud paths use internal table pass.
        self.last_charge_capture_backend = None
        _agent_debug(
            {
                "location": "rvu_cpt_service.stream_vision:entry",
                "hypothesisId": "H1-config",
                "message": "stream_vision_start",
                "data": {
                    "vision_model": self.vision_model,
                    "scan_mode": scan_mode,
                    "image_bytes": len(image_jpeg_bytes),
                    "vision_pipeline": _RVU_VISION_PIPELINE,
                    "anthropic_key_set": bool(self.anthropic_api_key),
                    "openai_key_set": bool(self.openai_api_key),
                    "first_stage_would_be": first_resolvable_pipeline_stage(self.anthropic_api_key, self.openai_api_key),
                },
            }
        )

        cloud_errors: list[str] = []

        for stage in _RVU_VISION_PIPELINE:
            if stage == "anthropic" and self.anthropic_api_key:
                yield "status", "Using Claude for charge capture…"
                for item in self._stream_vision_anthropic(image_jpeg_bytes):
                    if item[0] == "done":
                        self.last_charge_capture_backend = "anthropic"
                    yield item
                    if item[0] == "done":
                        return
                    if item[0] == "error":
                        cloud_errors.append(f"Anthropic: {item[1]}")
                        break
                continue

            if stage == "openai" and self.openai_api_key:
                yield "status", "Using OpenAI for charge capture…"
                for item in self._stream_vision_openai(image_jpeg_bytes):
                    if item[0] == "done":
                        self.last_charge_capture_backend = "openai"
                    yield item
                    if item[0] == "done":
                        return
                    if item[0] == "error":
                        cloud_errors.append(f"OpenAI: {item[1]}")
                        break
                continue

        parts = [p for p in cloud_errors if p]
        final_err = "; ".join(parts) if parts else "Vision pipeline produced no usable result"
        _agent_debug(
            {
                "location": "rvu_cpt_service.stream_vision:fatal",
                "hypothesisId": "H4-all-failed",
                "message": "vision_pipeline_exhausted",
                "data": {"final_error": final_err[:500]},
            }
        )
        yield "error", final_err

    def stream_text(self, raw_text: str):
        artifacts: list[dict[str, Any]] = []
        prompt = _TEXT_STRUCTURE_PROMPT.format(raw_text=raw_text[:8000])
        errs: list[str] = []
        for stage in _RVU_VISION_PIPELINE:
            if stage == "anthropic" and self.anthropic_api_key:
                try:
                    text = self.anthropic_text_once(prompt, max_tokens=4096)
                    for i in range(0, len(text), 100):
                        yield "token", text[i : i + 100]
                    parsed = self.parse_capture_response(text)
                    self._record_ai_run(
                        artifacts,
                        stage="text_primary",
                        provider="anthropic",
                        model=self.text_model,
                        raw_response=text,
                        parsed_json=parsed,
                    )
                    parsed["_ai_runs"] = artifacts
                    yield "done", parsed
                    return
                except Exception as exc:
                    errs.append(f"Anthropic: {exc}")
                    continue
            if stage == "openai" and self.openai_api_key:
                try:
                    text = self.openai_text_once(prompt, max_tokens=4096)
                    for i in range(0, len(text), 100):
                        yield "token", text[i : i + 100]
                    parsed = self.parse_capture_response(text)
                    self._record_ai_run(
                        artifacts,
                        stage="text_primary",
                        provider="openai",
                        model=_OPENAI_TEXT_MODEL,
                        raw_response=text,
                        parsed_json=parsed,
                    )
                    parsed["_ai_runs"] = artifacts
                    yield "done", parsed
                    return
                except Exception as exc:
                    errs.append(f"OpenAI: {exc}")
                    continue
        yield "error", "; ".join(errs) if errs else "No API key for text extraction (ANTHROPIC_API_KEY or OPENAI_API_KEY)"

    def _normalize_op_note_extraction(self, raw: str, model_tag: str) -> tuple[str | None, str]:
        stripped = (raw or "").strip()
        if not stripped:
            return None, model_tag
        obj = self._extract_json_object(stripped)
        if isinstance(obj, dict) and obj:
            full_text = str(obj.get("full_text") or "").strip()
            if len(full_text) > 48 or len(obj) > 2:
                try:
                    return json.dumps(obj, indent=2, ensure_ascii=False), model_tag
                except Exception:
                    return stripped, model_tag
        return stripped, model_tag

    def extract_op_note_best(self, image_jpeg_bytes: bytes) -> tuple[str, float, str, bytes]:
        """Multi-provider op-note OCR (RVU_OP_NOTE_PIPELINE); returns (text_or_empty, secs, model_label, jpeg_stored)."""
        t0 = time.monotonic()
        small = self.shrink_image(image_jpeg_bytes, max_dim=_OP_NOTE_MAX_DIM)
        b64 = base64.b64encode(small).decode()
        failures: list[str] = []

        for stage in _RVU_OP_NOTE_PIPELINE:
            if stage == "anthropic" and self.anthropic_api_key:
                prev_vm = self.vision_model
                try:
                    raw = self.anthropic_generate_once(
                        _OP_NOTE_STRUCTURED_PROMPT,
                        b64,
                        max_tokens=_ANTHROPIC_OP_NOTE_MAX_TOKENS,
                        http_timeout_sec=_ANTHROPIC_OP_NOTE_TIMEOUT_SECS,
                    )
                    used_vm = self.vision_model
                    text, label = self._normalize_op_note_extraction(raw, f"anthropic:{used_vm}")
                    if text:
                        return text, round(time.monotonic() - t0, 2), label, small
                except Exception as exc:
                    failures.append(f"anthropic:{exc}")
                finally:
                    self.vision_model = prev_vm
                continue

            if stage == "openai" and self.openai_api_key:
                try:
                    raw = self.openai_generate_once(
                        _OP_NOTE_STRUCTURED_PROMPT,
                        b64,
                        max_tokens=_OPENAI_OP_NOTE_MAX_TOKENS,
                        http_timeout_sec=float(_OPENAI_OP_NOTE_TIMEOUT_SECS),
                    )
                    text, label = self._normalize_op_note_extraction(raw, f"openai:{_OPENAI_VISION_MODEL}")
                    if text:
                        return text, round(time.monotonic() - t0, 2), label, small
                except Exception as exc:
                    failures.append(f"openai:{exc}")
                continue

        elapsed = round(time.monotonic() - t0, 2)
        err_txt = "; ".join(failures[:4])[:1500] if failures else "op_note_pipeline_exhausted"
        _agent_debug(
            {
                "location": "rvu_cpt_service.extract_op_note_best:fatal",
                "hypothesisId": "H-opnote-pipe",
                "message": "op_note_pipeline_failed",
                "data": {"errors": err_txt[:500], "pipeline": _RVU_OP_NOTE_PIPELINE},
            }
        )
        return "", elapsed, "pipeline_failed", small

    def extract_op_note_text(self, image_jpeg_bytes: bytes) -> tuple[str, float, str]:
        """Backward-compatible wrapper; prefers extract_op_note_best()."""
        text, elapsed, model, _ = self.extract_op_note_best(image_jpeg_bytes)
        return text, elapsed, model
