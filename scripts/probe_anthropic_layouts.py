#!/usr/bin/env python3
"""Run a small, targeted Anthropic layout probe on exported RVU scan images.

This sends PHI-containing screenshots to Anthropic. Use only when approved for the
current environment. Results are written inside the local/private dataset folder.
"""

from __future__ import annotations

import argparse
import base64
import csv
import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from dotenv import load_dotenv


PROMPT = """You are analyzing an Epic/hospital charge-capture screenshot for RVU billing accuracy.

Do not guess. Return one JSON object only.

Goal:
1. Identify the screen layout family.
2. Extract only visible billing fields.
3. Explain any ambiguity that could cause a wrong payment capture.

Field rules:
- MRN is the value next to a visible MRN label. Do not use CSN, account number, age, room, dates, or CPT as MRN.
- CPT is a plain 5-digit professional billing code visible in a charge row or charge summary. It often appears near Code, CPT, PR, Description, or a professional fee row.
- DOS is the date of service for the charge line. If a table has per-line dates, attach dates per line.
- Patient is the patient name from the patient banner/header, not a provider/author.
- Provider is the service/rendering/billing provider for that charge line, not merely author, logged-in user, deceased family member, or unrelated care-team text.
- If multiple charge rows are visible, return multiple line objects and keep each line's CPT, DOS, provider, role, and modifier separate.

Return this JSON shape:
{
  "layout_family": "short name",
  "image_quality": "good|glare|angled|blurry|cropped|too_noisy",
  "patient_name": "",
  "mrn": "",
  "global_service_date": "",
  "charge_lines": [
    {
      "cpt": "",
      "dos": "",
      "provider_name": "",
      "provider_role": "surgeon|pa|assistant|unknown",
      "modifier": "",
      "evidence": "brief visible text"
    }
  ],
  "visible_but_ignored": [
    {"text": "", "reason": "why it is not MRN/CPT/DOS/provider"}
  ],
  "ambiguities": [
    "specific uncertainty"
  ],
  "recommended_crop": "patient_header|charge_table|full_screen|none"
}
"""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=Path("prod-rvu/_backup_codex/ocr_dataset_live"))
    parser.add_argument("--env-file", type=Path, default=Path("api/.env"))
    parser.add_argument("--limit", type=int, default=8)
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--model", default="")
    parser.add_argument("--review-queue", type=Path, default=None)
    return parser.parse_args()


def media_type(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in (".jpg", ".jpeg"):
        return "image/jpeg"
    if suffix == ".png":
        return "image/png"
    if suffix == ".webp":
        return "image/webp"
    return "image/jpeg"


def load_review_rows(dataset: Path, queue_path: Path | None) -> list[dict[str, str]]:
    path = queue_path or dataset / "analysis" / "review_queue.csv"
    with path.open() as f:
        return list(csv.DictReader(f))


def anthropic_message(api_key: str, model: str, image_path: Path) -> dict[str, Any]:
    image_b64 = base64.b64encode(image_path.read_bytes()).decode()
    payload = {
        "model": model,
        "max_tokens": 1800,
        "temperature": 0,
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": media_type(image_path),
                            "data": image_b64,
                        },
                    },
                    {"type": "text", "text": PROMPT},
                ],
            }
        ],
    }
    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=json.dumps(payload).encode(),
        headers={
            "content-type": "application/json",
            "anthropic-version": "2023-06-01",
            "x-api-key": api_key,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")
        raise RuntimeError(f"Anthropic HTTP {exc.code}: {detail[:1000]}") from exc


def parse_text_response(response: dict[str, Any]) -> tuple[str, Any]:
    parts = response.get("content") or []
    text = "\n".join(part.get("text", "") for part in parts if part.get("type") == "text").strip()
    parsed: Any = None
    if text:
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            start = text.find("{")
            end = text.rfind("}")
            if start >= 0 and end > start:
                try:
                    parsed = json.loads(text[start : end + 1])
                except json.JSONDecodeError:
                    parsed = None
    return text, parsed


def expected_from_metadata(meta_path: Path) -> dict[str, Any]:
    meta = json.loads(meta_path.read_text())
    lines = meta.get("line_items") if isinstance(meta.get("line_items"), list) else []
    return {
        "scan_id": meta.get("scan_id"),
        "patient_name": meta.get("patient_name"),
        "mrn": meta.get("mrn"),
        "service_date": meta.get("service_date"),
        "cpts": meta.get("cpts"),
        "line_items": lines,
        "scan_status": meta.get("scan_status"),
        "review_reason": meta.get("review_reason"),
    }


def main() -> None:
    args = parse_args()
    load_dotenv(args.env_file, override=True)
    api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        raise SystemExit(f"ANTHROPIC_API_KEY is not set after loading {args.env_file}")
    model = args.model or os.environ.get("ANTHROPIC_VISION_MODEL", "").strip() or "claude-haiku-4-5-20251001"

    dataset = args.dataset.resolve()
    out_dir = dataset / "analysis" / "anthropic_probe"
    out_dir.mkdir(parents=True, exist_ok=True)
    output_path = out_dir / f"probe_{int(time.time())}.jsonl"
    rows = load_review_rows(dataset, args.review_queue)
    selected = rows[args.offset : args.offset + args.limit]

    with output_path.open("w") as out:
        for idx, row in enumerate(selected, start=1):
            image_path = dataset / row["image_file"]
            metadata_path = dataset / row["metadata_file"]
            print(f"[{idx}/{len(selected)}] scan {row['scan_id']} {row['issues']}")
            started = time.time()
            try:
                response = anthropic_message(api_key, model, image_path)
                text, parsed = parse_text_response(response)
                record = {
                    "scan_id": row["scan_id"],
                    "image_file": row["image_file"],
                    "issues": row["issues"],
                    "model": model,
                    "elapsed_secs": round(time.time() - started, 2),
                    "expected": expected_from_metadata(metadata_path),
                    "raw_text": text,
                    "parsed": parsed,
                    "error": "",
                }
            except Exception as exc:
                record = {
                    "scan_id": row["scan_id"],
                    "image_file": row["image_file"],
                    "issues": row["issues"],
                    "model": model,
                    "elapsed_secs": round(time.time() - started, 2),
                    "expected": expected_from_metadata(metadata_path),
                    "raw_text": "",
                    "parsed": None,
                    "error": str(exc),
                }
            out.write(json.dumps(record, default=str) + "\n")
            out.flush()

    print(f"Wrote {len(selected)} probe rows to {output_path}")


if __name__ == "__main__":
    main()
