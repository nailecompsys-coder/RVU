#!/usr/bin/env python3
"""Create local layout and review queues from an exported RVU OCR image dataset.

This does not call external AI. It uses saved scan metadata plus cheap image features
to decide what subset should be reviewed or re-run through Claude/OpenAI.
"""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageOps


@dataclass
class ScanRecord:
    scan_id: int
    image_path: Path
    metadata_path: Path
    metadata: dict[str, Any]
    width: int
    height: int
    orientation: str
    aspect_bucket: str
    brightness_bucket: str
    edge_bucket: str
    layout_key: str
    issues: list[str]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dataset",
        type=Path,
        default=Path("prod-rvu/_backup_codex/ocr_dataset_live"),
    )
    parser.add_argument("--sample-per-group", type=int, default=12)
    return parser.parse_args()


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text())


def line_items(meta: dict[str, Any]) -> list[dict[str, Any]]:
    value = meta.get("line_items")
    return value if isinstance(value, list) else []


def cpt_values(meta: dict[str, Any]) -> list[str]:
    out: list[str] = []
    for item in meta.get("cpts") or []:
        text = str(item or "").strip()
        if text:
            out.append(text)
    for line in line_items(meta):
        text = str(line.get("cpt") or "").strip()
        if text and text not in out:
            out.append(text)
    return out


def record_issues(meta: dict[str, Any]) -> list[str]:
    issues: list[str] = []
    if not str(meta.get("mrn") or "").strip():
        issues.append("missing_mrn")
    if not str(meta.get("patient_name") or "").strip():
        issues.append("missing_patient")
    if not cpt_values(meta):
        issues.append("missing_cpt")
    if str(meta.get("scan_status") or "") != "verified":
        issues.append(f"status_{meta.get('scan_status') or 'unknown'}")
    if str(meta.get("review_reason") or "").strip():
        issues.append("has_review_reason")
    items = line_items(meta)
    if len(items) > 1:
        issues.append("multi_line")
    if any(not str(line.get("line_service_date") or meta.get("service_date") or "").strip() for line in items):
        issues.append("missing_line_dos")
    if any(not str(line.get("provider_name") or "").strip() for line in items):
        issues.append("missing_provider")
    if any(str(line.get("provider_role") or "").strip().lower() in ("", "unknown") for line in items):
        issues.append("unknown_provider_role")
    return issues


def image_buckets(path: Path) -> tuple[int, int, str, str, str, str]:
    with Image.open(path) as raw:
        img = ImageOps.exif_transpose(raw).convert("L")
        width, height = img.size
        orientation = "portrait" if height > width else "landscape"
        aspect = width / max(height, 1)
        if aspect < 0.8:
            aspect_bucket = "tall"
        elif aspect > 1.25:
            aspect_bucket = "wide"
        else:
            aspect_bucket = "standard"

        small = img.resize((96, 96))
        pixels = list(small.getdata())
        mean = sum(pixels) / len(pixels)
        if mean < 95:
            brightness_bucket = "dark"
        elif mean > 180:
            brightness_bucket = "bright"
        else:
            brightness_bucket = "normal"

        # Crude edge/detail proxy: average absolute neighbor difference.
        diffs = []
        for y in range(96):
            row = y * 96
            for x in range(95):
                diffs.append(abs(pixels[row + x] - pixels[row + x + 1]))
        edge = sum(diffs) / max(len(diffs), 1)
        if edge < 8:
            edge_bucket = "soft"
        elif edge > 20:
            edge_bucket = "busy"
        else:
            edge_bucket = "medium"
        return width, height, orientation, aspect_bucket, brightness_bucket, edge_bucket


def read_records(dataset: Path) -> list[ScanRecord]:
    records: list[ScanRecord] = []
    for meta_path in sorted((dataset / "metadata").glob("*.json")):
        meta = load_json(meta_path)
        image_file = str(meta.get("image_file") or "")
        image_path = dataset / image_file
        if not image_path.exists():
            image_path = dataset / "images" / Path(image_file).name
        if not image_path.exists():
            continue
        width, height, orientation, aspect_bucket, brightness_bucket, edge_bucket = image_buckets(image_path)
        issues = record_issues(meta)
        line_count = len(line_items(meta))
        cpt_count = len(cpt_values(meta))
        layout_key = "|".join(
            [
                orientation,
                aspect_bucket,
                brightness_bucket,
                edge_bucket,
                f"lines_{min(line_count, 4)}",
                f"cpts_{min(cpt_count, 4)}",
                str(meta.get("scan_status") or "unknown"),
            ]
        )
        records.append(
            ScanRecord(
                scan_id=int(meta["scan_id"]),
                image_path=image_path,
                metadata_path=meta_path,
                metadata=meta,
                width=width,
                height=height,
                orientation=orientation,
                aspect_bucket=aspect_bucket,
                brightness_bucket=brightness_bucket,
                edge_bucket=edge_bucket,
                layout_key=layout_key,
                issues=issues,
            )
        )
    return records


def write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def make_contact_sheet(path: Path, records: list[ScanRecord], title: str, max_items: int = 36) -> None:
    if not records:
        return
    sample = records[:max_items]
    thumb_w, thumb_h = 220, 165
    cols = 6
    rows = (len(sample) + cols - 1) // cols
    header_h = 34
    sheet = Image.new("RGB", (cols * thumb_w, header_h + rows * (thumb_h + 30)), "white")
    draw = ImageDraw.Draw(sheet)
    draw.text((8, 8), title[:120], fill=(0, 0, 0))
    for idx, record in enumerate(sample):
        x = (idx % cols) * thumb_w
        y = header_h + (idx // cols) * (thumb_h + 30)
        try:
            with Image.open(record.image_path) as raw:
                img = ImageOps.exif_transpose(raw).convert("RGB")
                img.thumbnail((thumb_w, thumb_h))
                ox = x + (thumb_w - img.width) // 2
                oy = y + (thumb_h - img.height) // 2
                sheet.paste(img, (ox, oy))
        except Exception:
            draw.text((x + 4, y + 20), "image error", fill=(180, 0, 0))
        label = f"{record.scan_id} {record.orientation} {','.join(record.issues[:2])}"
        draw.text((x + 4, y + thumb_h + 6), label[:34], fill=(0, 0, 0))
    sheet.save(path, quality=88)


def main() -> None:
    args = parse_args()
    dataset = args.dataset.resolve()
    out_dir = dataset / "analysis"
    sheets_dir = out_dir / "contact_sheets"
    out_dir.mkdir(parents=True, exist_ok=True)
    sheets_dir.mkdir(parents=True, exist_ok=True)

    records = read_records(dataset)
    by_status = Counter(str(r.metadata.get("scan_status") or "unknown") for r in records)
    by_issue = Counter(issue for record in records for issue in record.issues)
    by_layout = Counter(r.layout_key for r in records)
    by_dimension = Counter(f"{r.width}x{r.height}" for r in records)
    by_model = Counter(str(r.metadata.get("ai_model") or "unknown") for r in records)

    layout_rows = []
    grouped: dict[str, list[ScanRecord]] = defaultdict(list)
    for record in records:
        grouped[record.layout_key].append(record)
    for key, group in sorted(grouped.items(), key=lambda item: (-len(item[1]), item[0])):
        issues = Counter(issue for record in group for issue in record.issues)
        layout_rows.append(
            {
                "layout_key": key,
                "count": len(group),
                "top_issues": ";".join(f"{name}:{count}" for name, count in issues.most_common(8)),
                "example_scan_ids": ",".join(str(record.scan_id) for record in group[:10]),
            }
        )
        make_contact_sheet(
            sheets_dir / f"layout_{len(layout_rows):02d}.jpg",
            group[: args.sample_per_group],
            f"{key} ({len(group)} scans)",
            max_items=args.sample_per_group,
        )

    review_records = sorted(
        [r for r in records if r.issues],
        key=lambda r: (
            "status_pending_review" not in r.issues,
            "missing_cpt" not in r.issues,
            "missing_mrn" not in r.issues,
            -len(r.issues),
            -r.scan_id,
        ),
    )
    review_rows = [
        {
            "scan_id": r.scan_id,
            "image_file": str(r.image_path.relative_to(dataset)),
            "metadata_file": str(r.metadata_path.relative_to(dataset)),
            "layout_key": r.layout_key,
            "issues": ";".join(r.issues),
            "scan_status": r.metadata.get("scan_status") or "",
            "review_reason": r.metadata.get("review_reason") or "",
            "service_date": r.metadata.get("service_date") or "",
            "mrn_present": bool(str(r.metadata.get("mrn") or "").strip()),
            "patient_present": bool(str(r.metadata.get("patient_name") or "").strip()),
            "cpts": ",".join(cpt_values(r.metadata)),
            "line_count": len(line_items(r.metadata)),
            "ai_model": r.metadata.get("ai_model") or "",
        }
        for r in review_records
    ]

    write_csv(
        out_dir / "layout_groups.csv",
        layout_rows,
        ["layout_key", "count", "top_issues", "example_scan_ids"],
    )
    write_csv(
        out_dir / "review_queue.csv",
        review_rows,
        [
            "scan_id",
            "image_file",
            "metadata_file",
            "layout_key",
            "issues",
            "scan_status",
            "review_reason",
            "service_date",
            "mrn_present",
            "patient_present",
            "cpts",
            "line_count",
            "ai_model",
        ],
    )
    make_contact_sheet(
        out_dir / "review_queue_top36.jpg",
        review_records[:36],
        "Top review queue samples",
        max_items=36,
    )

    summary = {
        "dataset": str(dataset),
        "record_count": len(records),
        "by_status": dict(by_status.most_common()),
        "by_issue": dict(by_issue.most_common()),
        "by_layout_top20": dict(by_layout.most_common(20)),
        "by_dimension_top20": dict(by_dimension.most_common(20)),
        "by_model": dict(by_model.most_common()),
        "review_queue_count": len(review_rows),
        "outputs": {
            "layout_groups": str(out_dir / "layout_groups.csv"),
            "review_queue": str(out_dir / "review_queue.csv"),
            "review_contact_sheet": str(out_dir / "review_queue_top36.jpg"),
            "layout_contact_sheets": str(sheets_dir),
        },
    }
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
