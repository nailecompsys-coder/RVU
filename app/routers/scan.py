"""
Scan router — vision/text OCR streams → CPT extraction → RVU payment table.
Saves scan to rvu_scans for history/reporting.
"""
import base64
import io
import json
import os
import re
import urllib.request
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import StreamingResponse
from PIL import Image
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..auth import get_current_surgeon
from ..database import get_db
from ..lookup import CF_2026, calc_payment, get_localities
from ..models import RvuScan, Surgeon

router = APIRouter(tags=["scan"])

OLLAMA_BASE    = os.environ.get("OLLAMA_BASE", "http://192.168.5.67:11434")
VISION_MODEL   = os.environ.get("VISION_MODEL", "qwen2.5vl:7b")
TEXT_MODEL     = os.environ.get("TEXT_MODEL", "llama3.2:3b")
OLLAMA_TIMEOUT = 180

_VISION_PROMPT = (
    "You are a medical billing assistant reading an Epic EHR charge screen.\n"
    "Extract every valid CPT billing code visible in this image.\n"
    "Rules:\n"
    "- A valid CPT code is exactly 5 digits (e.g. 99223, 47562).\n"
    "- Ignore placeholder codes like PBSUR, S-codes, modifiers, and non-5-digit text.\n"
    "- Return ONLY a JSON array of strings. Example: [\"99223\",\"47562\"]\n"
    "If no valid CPT codes are found, return []."
)

_TEXT_PROMPT = (
    "You are a medical billing assistant. Extract all valid CPT procedure codes from the text below.\n"
    "Rules:\n"
    "- A valid CPT code is exactly 5 digits (e.g. 99223, 47562).\n"
    "- Ignore placeholder codes like PBSUR, modifiers, and non-numeric text.\n"
    "- Return ONLY a JSON array of strings. Example: [\"99223\",\"47562\"]\n\n"
    "Text:\n{raw_text}"
)


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


def _shrink(image_bytes: bytes, max_dim: int = 900) -> bytes:
    img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    w, h = img.size
    if max(w, h) > max_dim:
        scale = max_dim / max(w, h)
        img = img.resize((int(w * scale), int(h * scale)), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85)
    return buf.getvalue()


def _ollama_stream(endpoint: str, payload: dict):
    payload = {**payload, "stream": True}
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        f"{OLLAMA_BASE}{endpoint}",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=OLLAMA_TIMEOUT) as resp:
            for line in resp:
                line = line.strip()
                if line:
                    yield json.loads(line)
    except Exception as exc:
        yield {"error": str(exc)}


def _parse_cpts(text: str) -> list[str]:
    m = re.search(r"\[.*?\]", text, re.DOTALL)
    if not m:
        return []
    try:
        cpts = json.loads(m.group(0))
    except json.JSONDecodeError:
        return []
    return [c.strip() for c in cpts if isinstance(c, str) and re.fullmatch(r"\d{5}", c.strip())]


def _build_rows(cpts: list[str], locality: str, facility: bool, cf: float):
    rows, total = [], 0.0
    for cpt in cpts:
        r = calc_payment(cpt, locality, facility, cf)
        rows.append({
            "CPT": cpt, "desc": r["desc"],
            "work_rvu": r["work_rvu"], "pe_rvu": r["pe_rvu"],
            "pe_nonfac_rvu": r["pe_nonfac_rvu"], "pe_fac_rvu": r["pe_fac_rvu"],
            "mp_rvu": r["mp_rvu"], "total_rvu": r["total_rvu"],
            "payment": r["payment"],
        })
        total += r["payment"]
    return rows, total


def _save_scan(surgeon: Surgeon, cpts: list[str], locality: str, locality_name: str,
               facility: bool, total_rvu: float, total_payment: float,
               cf: float, model: str, image_kb: int, elapsed: float, db: Session):
    scan = RvuScan(
        surgeon_id=surgeon.id,
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
    )
    db.add(scan)
    db.commit()


# ── Vision stream endpoint ────────────────────────────────────────────────────

@router.post("/api/vision-stream")
async def vision_stream(
    request: Request,
    image: UploadFile = File(...),
    locality: str = Form("00"),
    facility: str = Form("false"),
    cf: float = Form(CF_2026),
    db: Session = Depends(get_db),
    surgeon_device=Depends(get_current_surgeon),
):
    surgeon, device = surgeon_device
    image_bytes = await image.read()
    if len(image_bytes) > 30 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Image too large (max 30 MB)")
    orig_kb = len(image_bytes) // 1024
    image_bytes = _shrink(image_bytes)
    small_kb = len(image_bytes) // 1024
    b64 = base64.b64encode(image_bytes).decode()
    fac = facility.lower() == "true"
    t_start = datetime.now(timezone.utc)

    def generate():
        yield _sse("status", {"msg": f"Resized {orig_kb} KB → {small_kb} KB — sending to AI…"})
        full = ""
        for chunk in _ollama_stream("/api/generate",
                                    {"model": VISION_MODEL, "prompt": _VISION_PROMPT, "images": [b64]}):
            if "error" in chunk:
                yield _sse("error", {"msg": chunk["error"]}); return
            tok = chunk.get("response", "")
            if tok:
                full += tok
                yield _sse("token", {"t": tok})
            if chunk.get("done"):
                break

        cpts = _parse_cpts(full)
        if not cpts:
            yield _sse("done", {"cpts": [], "rows": [], "total_payment": 0, "ai_model": VISION_MODEL})
            return

        rows, total = _build_rows(cpts, locality, fac, cf)
        elapsed = (datetime.now(timezone.utc) - t_start).total_seconds()
        locs = get_localities()
        loc_name = next((l["locality_name"] for l in locs if l["locality_num"] == locality), locality)
        _save_scan(surgeon, cpts, locality, loc_name, fac,
                   sum(r["total_rvu"] for r in rows), total,
                   cf, VISION_MODEL, small_kb, elapsed, db)

        yield _sse("done", {"cpts": cpts, "rows": rows,
                            "total_payment": round(total, 2), "ai_model": VISION_MODEL})

    return StreamingResponse(generate(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# ── Text stream endpoint ──────────────────────────────────────────────────────

class TextScanRequest(BaseModel):
    raw_text: str
    locality: str = "00"
    facility: bool = False
    cf: float = CF_2026


@router.post("/api/text-stream")
def text_stream(
    req: TextScanRequest,
    db: Session = Depends(get_db),
    surgeon_device=Depends(get_current_surgeon),
):
    surgeon, device = surgeon_device
    t_start = datetime.now(timezone.utc)

    def generate():
        yield _sse("status", {"msg": "Sending text to AI…"})
        full = ""
        for chunk in _ollama_stream("/api/generate",
                                    {"model": TEXT_MODEL,
                                     "prompt": _TEXT_PROMPT.format(raw_text=req.raw_text[:4000])}):
            if "error" in chunk:
                yield _sse("error", {"msg": chunk["error"]}); return
            tok = chunk.get("response", "")
            if tok:
                full += tok
                yield _sse("token", {"t": tok})
            if chunk.get("done"):
                break

        cpts = _parse_cpts(full)
        if not cpts:
            yield _sse("done", {"cpts": [], "rows": [], "total_payment": 0, "ai_model": TEXT_MODEL})
            return

        rows, total = _build_rows(cpts, req.locality, req.facility, req.cf)
        elapsed = (datetime.now(timezone.utc) - t_start).total_seconds()
        locs = get_localities()
        loc_name = next((l["locality_name"] for l in locs if l["locality_num"] == req.locality), req.locality)
        _save_scan(surgeon, cpts, req.locality, loc_name, req.facility,
                   sum(r["total_rvu"] for r in rows), total,
                   req.cf, TEXT_MODEL, 0, elapsed, db)

        yield _sse("done", {"cpts": cpts, "rows": rows,
                            "total_payment": round(total, 2), "ai_model": TEXT_MODEL})

    return StreamingResponse(generate(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# ── Localities lookup ─────────────────────────────────────────────────────────

@router.get("/api/localities")
def localities(surgeon_device=Depends(get_current_surgeon)):
    return {"localities": get_localities(), "cf": CF_2026}
