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
- "mrn": patient MRN or account ID if visible, else "". (The API may also send MRN typed by the clinician on the device; when present, the server keeps that value instead of OCR.)
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

Return ONE JSON object only (no markdown): {{"additional_lines": [], "patient_name": "", "mrn": ""}} with the array filled only from the text (each item {{"cpt": "<five digits from text>", "procedure_name": ""}}). If none, keep additional_lines empty. If patient name or MRN are visible in the text and were missed before, include them. Do not invent codes.
"""

_TABLE_FOCUS_PROMPT = """Read this hospital charge screenshot as a TABLE.

Scan full width and full height, left-to-right and top-to-bottom.
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
                mrn_out = str(val).strip()[:64]
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
    modifier = str(row.get("modifier") or row.get("modifiers") or "").strip().upper()
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


class RvuCptExtractionService:
    """Anthropic / OpenAI vision and text → structured charge capture (no local LLM)."""

    vision_model = _VISION_MODEL
    text_model = _TEXT_MODEL
    vision_provider = "anthropic"
    openai_api_key = _OPENAI_API_KEY
    anthropic_api_key = _ANTHROPIC_API_KEY
    last_charge_capture_backend: str | None = None

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
        seen_lines: set[tuple[str, str, str, bool, str]] = set()

        def add_row(row: dict) -> None:
            line = _line_from_row(row)
            if not line:
                return
            key = _line_dedupe_key(line)
            if key in seen_lines:
                return
            seen_lines.add(key)
            lines_out.append(line)
            if not line.get("is_assist") and str(line.get("provider_role") or "").strip().lower() != "pa":
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
            return str(v).strip()[:64]

        p_sd, e_sd = _sd(primary), _sd(extra)
        p_mrn, e_mrn = _mrn(primary), _mrn(extra)
        p_patient_name = _patient_name_from_model(primary, "")
        e_patient_name = _patient_name_from_model(extra, "")
        return {
            "cpts": _cpts_for_surgeon_lines(lines_out) or cpts_out,
            "lines": lines_out,
            "service_date": p_sd or e_sd,
            "patient_name": p_patient_name or e_patient_name,
            "mrn": p_mrn or e_mrn,
            "surgeon_name": str(primary.get("surgeon_name") or extra.get("surgeon_name") or "").strip() or None,
        }

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
        seen_lines: set[tuple[str, str, str, bool, str]] = set()
        for row in raw:
            if not isinstance(row, dict):
                continue
            line = _line_from_row(row)
            if not line:
                continue
            key = _line_dedupe_key(line)
            if key in seen_lines:
                continue
            seen_lines.add(key)
            lines.append(line)
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

    def refine_vision_additional(self, image_jpeg_bytes: bytes, first_cap: dict[str, Any]) -> dict[str, Any]:
        known = first_cap.get("cpts") or []
        b64 = base64.b64encode(image_jpeg_bytes).decode()
        prompt = _REFINE_VISION_PROMPT.format(known_json=json.dumps(known))
        empty = {"cpts": [], "lines": [], "service_date": None, "patient_name": None, "mrn": None}
        for stage in _RVU_VISION_PIPELINE:
            if stage == "anthropic" and self.anthropic_api_key:
                try:
                    text = self.anthropic_generate_once(prompt, b64, max_tokens=2048)
                    return self.parse_refine_additional(text)
                except Exception:
                    continue
            if stage == "openai" and self.openai_api_key:
                try:
                    text = self.openai_generate_once(prompt, b64, max_tokens=2048)
                    return self.parse_refine_additional(text)
                except Exception:
                    continue
        return empty

    def refine_text_additional(self, raw_text: str, first_cap: dict[str, Any]) -> dict[str, Any]:
        known = first_cap.get("cpts") or []
        prompt = _REFINE_TEXT_PROMPT.format(known_json=json.dumps(known)) + "\n\nText:\n" + raw_text[:8000]
        empty = {"cpts": [], "lines": [], "service_date": None, "patient_name": None, "mrn": None}
        for stage in _RVU_VISION_PIPELINE:
            if stage == "anthropic" and self.anthropic_api_key:
                try:
                    text = self.anthropic_text_once(prompt, max_tokens=4096)
                    return self.parse_refine_additional(text)
                except Exception:
                    continue
            if stage == "openai" and self.openai_api_key:
                try:
                    text = self.openai_text_once(prompt, max_tokens=4096)
                    return self.parse_refine_additional(text)
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

    def parse_capture_response(self, text: str) -> dict[str, Any]:
        """
        Returns { cpts, service_date, mrn, surgeon_name, lines }.
        """
        obj = self._extract_json_object(text)
        lines: list[dict[str, Any]] = []
        cpts: list[str] = []
        seen_lines: set[tuple[str, str, str, bool, str]] = set()
        if obj:
            raw_lines = obj.get("lines") or []

            for row in raw_lines:
                if not isinstance(row, dict):
                    continue
                line = _line_from_row(row)
                if not line:
                    continue
                key = _line_dedupe_key(line)
                if key in seen_lines:
                    continue
                seen_lines.add(key)
                lines.append(line)

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
            if cpts or lines:
                sd, mrn = _service_date_and_mrn_from_model(obj, text)
                patient_name = _patient_name_from_model(obj, text)
                surgeon_name = str((obj or {}).get("surgeon_name") or "").strip()
                return {"cpts": cpts, "service_date": sd, "patient_name": patient_name, "mrn": mrn, "surgeon_name": surgeon_name or None, "lines": lines}

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
        b64 = base64.b64encode(image_jpeg_bytes).decode()
        try:
            text = self.openai_generate_once(_STRUCTURE_PROMPT, b64)
        except Exception as exc:
            yield "error", str(exc)
            return
        if text:
            yield "token", text
        merged = self.parse_capture_response(text)
        if not self._has_provider_context(merged):
            try:
                yield "token", "\n[OpenAI table OCR pass]"
                text2 = self.openai_generate_once(_TABLE_FOCUS_PROMPT, b64)
                if text2:
                    yield "token", text2
                merged = self.merge_captures(merged, self.parse_capture_response(text2))
            except Exception:
                pass
        yield "done", merged

    def _stream_vision_anthropic(self, image_jpeg_bytes: bytes):
        b64 = base64.b64encode(image_jpeg_bytes).decode()
        try:
            text = self.anthropic_generate_once(_STRUCTURE_PROMPT, b64)
        except Exception as exc:
            yield "error", str(exc)
            return
        if text:
            yield "token", text
        merged = self.parse_capture_response(text)
        if not self._has_provider_context(merged):
            try:
                yield "token", "\n[Anthropic table OCR pass]"
                text2 = self.anthropic_generate_once(_TABLE_FOCUS_PROMPT, b64)
                if text2:
                    yield "token", text2
                merged = self.merge_captures(merged, self.parse_capture_response(text2))
            except Exception:
                pass
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
        prompt = _TEXT_STRUCTURE_PROMPT.format(raw_text=raw_text[:8000])
        errs: list[str] = []
        for stage in _RVU_VISION_PIPELINE:
            if stage == "anthropic" and self.anthropic_api_key:
                try:
                    text = self.anthropic_text_once(prompt, max_tokens=4096)
                    for i in range(0, len(text), 100):
                        yield "token", text[i : i + 100]
                    yield "done", self.parse_capture_response(text)
                    return
                except Exception as exc:
                    errs.append(f"Anthropic: {exc}")
                    continue
            if stage == "openai" and self.openai_api_key:
                try:
                    text = self.openai_text_once(prompt, max_tokens=4096)
                    for i in range(0, len(text), 100):
                        yield "token", text[i : i + 100]
                    yield "done", self.parse_capture_response(text)
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
