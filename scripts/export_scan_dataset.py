#!/usr/bin/env python3
"""Export stored RVU charge-capture images and metadata for local OCR audits.

The images contain PHI. Keep the output directory local/private and do not commit it.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
from datetime import date, datetime
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from sqlalchemy import create_engine, text


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ENV = ROOT / ".env"
DEFAULT_OUT = ROOT / "_backup_codex" / "ocr_dataset"


def json_default(value: Any) -> str:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return str(value)


def safe_json_loads(raw: str | None) -> Any:
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return raw


def image_extension(image_bytes: bytes) -> str:
    if image_bytes.startswith(b"\xff\xd8\xff"):
        return ".jpg"
    if image_bytes.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png"
    if image_bytes[4:12] in (b"ftypheic", b"ftypheix", b"ftyphevc", b"ftypmif1"):
        return ".heic"
    return ".bin"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, default=DEFAULT_ENV)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--limit", type=int, default=0, help="0 exports all rows with image_data.")
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--status", default="", help="Optional scan_status filter.")
    parser.add_argument("--include-unverified", action="store_true", help="Include non-verified scans.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    load_dotenv(args.env_file, override=False)
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise SystemExit("DATABASE_URL is not set after loading env file.")

    out_dir = args.out.expanduser().resolve()
    image_dir = out_dir / "images"
    meta_dir = out_dir / "metadata"
    image_dir.mkdir(parents=True, exist_ok=True)
    meta_dir.mkdir(parents=True, exist_ok=True)

    where = ["image_data IS NOT NULL", "octet_length(image_data) > 0"]
    params: dict[str, Any] = {"offset": args.offset}
    if args.status:
        where.append("scan_status = :status")
        params["status"] = args.status
    elif not args.include_unverified:
        where.append("(scan_status IS NULL OR scan_status = 'verified')")

    limit_sql = ""
    if args.limit and args.limit > 0:
        limit_sql = " LIMIT :limit"
        params["limit"] = args.limit

    sql = text(
        f"""
        SELECT
            id, surgeon_id, scanned_at, service_date, patient_name, mrn,
            cpts, line_items, scan_status, main_cpt, main_cpt_status,
            review_reason, total_rvu, total_payment, ai_model, image_kb,
            elapsed_secs, facility, locality_num, locality_name, image_data
        FROM rvu_scans
        WHERE {" AND ".join(where)}
        ORDER BY scanned_at DESC, id DESC
        {limit_sql} OFFSET :offset
        """
    )

    engine = create_engine(database_url, pool_pre_ping=True)
    manifest_path = out_dir / "manifest.csv"
    exported = 0

    with engine.connect() as conn, manifest_path.open("w", newline="") as manifest_file:
        writer = csv.DictWriter(
            manifest_file,
            fieldnames=[
                "scan_id",
                "image_file",
                "metadata_file",
                "sha256",
                "scanned_at",
                "service_date",
                "scan_status",
                "main_cpt",
                "patient_name_present",
                "mrn_present",
                "line_count",
                "image_kb",
                "ai_model",
            ],
        )
        writer.writeheader()

        for row in conn.execute(sql, params).mappings():
            image_bytes = bytes(row["image_data"])
            digest = hashlib.sha256(image_bytes).hexdigest()
            ext = image_extension(image_bytes)
            stem = f"scan_{row['id']}_{digest[:12]}"
            image_path = image_dir / f"{stem}{ext}"
            metadata_path = meta_dir / f"{stem}.json"

            if not image_path.exists():
                image_path.write_bytes(image_bytes)

            cpts = safe_json_loads(row["cpts"])
            line_items = safe_json_loads(row["line_items"])
            line_count = len(line_items) if isinstance(line_items, list) else 0
            metadata = {
                "scan_id": row["id"],
                "surgeon_id": row["surgeon_id"],
                "scanned_at": row["scanned_at"],
                "service_date": row["service_date"],
                "patient_name": row["patient_name"],
                "mrn": row["mrn"],
                "cpts": cpts,
                "line_items": line_items,
                "scan_status": row["scan_status"],
                "main_cpt": row["main_cpt"],
                "main_cpt_status": row["main_cpt_status"],
                "review_reason": row["review_reason"],
                "total_rvu": row["total_rvu"],
                "total_payment": row["total_payment"],
                "ai_model": row["ai_model"],
                "image_kb": row["image_kb"],
                "elapsed_secs": row["elapsed_secs"],
                "facility": row["facility"],
                "locality_num": row["locality_num"],
                "locality_name": row["locality_name"],
                "image_file": str(image_path),
                "sha256": digest,
            }
            metadata_path.write_text(json.dumps(metadata, indent=2, default=json_default))

            writer.writerow(
                {
                    "scan_id": row["id"],
                    "image_file": image_path.name,
                    "metadata_file": metadata_path.name,
                    "sha256": digest,
                    "scanned_at": json_default(row["scanned_at"]),
                    "service_date": json_default(row["service_date"]),
                    "scan_status": row["scan_status"],
                    "main_cpt": row["main_cpt"] or "",
                    "patient_name_present": bool(row["patient_name"]),
                    "mrn_present": bool(row["mrn"]),
                    "line_count": line_count,
                    "image_kb": row["image_kb"] or "",
                    "ai_model": row["ai_model"] or "",
                }
            )
            exported += 1

    print(f"Exported {exported} scan images to {out_dir}")
    print(f"Manifest: {manifest_path}")


if __name__ == "__main__":
    main()
