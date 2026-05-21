"""
Scan history — surgeon sees their own scans.
Admin report is a simple page gated by the shared surgeon admin (future).
"""
import json
from datetime import datetime

from fastapi import APIRouter, Depends
from fastapi.responses import HTMLResponse
from sqlalchemy import desc
from sqlalchemy.orm import Session

from ..auth import get_current_surgeon
from ..database import get_db
from ..models import RvuScan, Surgeon

router = APIRouter(tags=["history"])


@router.get("/history", response_class=HTMLResponse)
def history_page(
    surgeon_device=Depends(get_current_surgeon),
    db: Session = Depends(get_db),
):
    surgeon, _ = surgeon_device
    scans = (
        db.query(RvuScan)
        .filter(RvuScan.surgeon_id == surgeon.id)
        .order_by(desc(RvuScan.scanned_at))
        .all()
    )
    return _history_html(surgeon, scans)


def _history_html(surgeon: Surgeon, scans: list[RvuScan]) -> str:
    if not scans:
        rows_html = "<tr><td colspan='6' style='text-align:center;color:#64748b;padding:2rem'>No scans yet — tap the scanner to get started.</td></tr>"
    else:
        rows_html = ""
        for s in scans:
            cpts = ", ".join(json.loads(s.cpts or "[]"))
            fac  = "Facility" if s.facility else "Non-Fac"
            dt   = s.scanned_at.strftime("%m/%d/%y %H:%M") if s.scanned_at else "—"
            rows_html += (
                f"<tr>"
                f"<td>{dt}</td>"
                f"<td style='font-size:.8rem'>{cpts or '—'}</td>"
                f"<td>{s.locality_name or s.locality_num or '—'}</td>"
                f"<td>{fac}</td>"
                f"<td style='text-align:right'>{s.total_rvu or 0:.2f}</td>"
                f"<td style='text-align:right'><strong>${s.total_payment or 0:,.2f}</strong></td>"
                f"</tr>"
            )

    return f"""<!doctype html><html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>My Scan History — RVU Estimator</title>
<style>
*{{box-sizing:border-box}}
body{{margin:0;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;
  background:#f4f7fb;color:#1a2540;padding-bottom:40px}}
header{{background:#fff;border-bottom:1px solid #e2e8f0;padding:.9rem 1.5rem;
  display:flex;align-items:center;gap:1rem;position:sticky;top:0;z-index:10}}
header h1{{margin:0;font-size:1rem;font-weight:700;flex:1}}
header a{{font-size:.85rem;color:#2563eb;text-decoration:none;white-space:nowrap}}
.wrap{{padding:1.2rem;overflow-x:auto}}
table{{width:100%;border-collapse:collapse;background:#fff;border-radius:12px;
  overflow:hidden;box-shadow:0 4px 16px rgba(0,0,0,.07);min-width:560px}}
th{{background:#1a2540;color:#fff;padding:.7rem 1rem;text-align:left;font-size:.78rem}}
td{{padding:.65rem 1rem;border-bottom:1px solid #f1f5f9;font-size:.83rem}}
tr:last-child td{{border-bottom:none}}
tr:hover td{{background:#f8fafc}}
</style></head><body>
<header>
  <h1>Dr. {surgeon.full_name} — Scan History</h1>
  <a href="/">← Scanner</a>
</header>
<div class="wrap">
<table>
<tr><th>Date</th><th>CPTs</th><th>Locality</th><th>Setting</th>
<th style="text-align:right">Total RVU</th><th style="text-align:right">Payment</th></tr>
{rows_html}
</table>
</div></body></html>"""
