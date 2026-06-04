import json
import unittest
from datetime import date, datetime
from types import SimpleNamespace

from app.api.routes_rvu import (
    _build_best_day_this_month,
    _build_top_cpt_contribution,
    _scan_work_payment,
    _sum_surgeon_value,
    _trend_delta,
    _trend_percent,
)


def scan(
    *,
    service_date: date,
    status: str = "verified",
    cf: float = 41.0,
    total_rvu: float = 0.0,
    lines: list[dict] | None = None,
):
    return SimpleNamespace(
        service_date=service_date,
        scanned_at=datetime.combine(service_date, datetime.min.time()),
        scan_status=status,
        cf=cf,
        total_rvu=total_rvu,
        line_items=json.dumps(lines or []),
        main_cpt=(lines or [{}])[0].get("cpt") if lines else None,
    )


class DashboardStatsHelperTests(unittest.TestCase):
    def test_scan_work_payment_prefers_stored_line_payment(self):
        row = scan(
            service_date=date(2026, 6, 1),
            lines=[
                {"cpt": "47562", "work_rvu": 10.0, "work_payment": 500.0},
                {"cpt": "47563", "work_rvu": 5.0, "work_payment": 250.0},
            ],
        )

        self.assertEqual(_scan_work_payment(row, 41.0), 750.0)

    def test_scan_work_payment_falls_back_to_configured_cf(self):
        row = scan(service_date=date(2026, 6, 1), total_rvu=8.0)

        self.assertEqual(_scan_work_payment(row, 50.0), 400.0)

    def test_sum_surgeon_value_excludes_pending_review(self):
        verified = scan(service_date=date(2026, 6, 1), total_rvu=10.0)
        pending = scan(service_date=date(2026, 6, 2), status="pending_review", total_rvu=100.0)

        self.assertEqual(_sum_surgeon_value([verified, pending], 41.0), 410.0)

    def test_best_day_uses_verified_wrvu_and_case_tiebreaker(self):
        rows = [
            scan(service_date=date(2026, 6, 1), total_rvu=10.0),
            scan(service_date=date(2026, 6, 2), total_rvu=5.0),
            scan(service_date=date(2026, 6, 2), total_rvu=5.0),
            scan(service_date=date(2026, 6, 3), status="pending_review", total_rvu=99.0),
        ]

        best = _build_best_day_this_month(rows, date(2026, 6, 4))

        self.assertEqual(best["date"], "2026-06-02")
        self.assertEqual(best["cases"], 2)
        self.assertEqual(best["wrvu"], 10.0)

    def test_top_cpt_contribution_uses_estimated_payment_percent(self):
        rows = [
            scan(
                service_date=date(2026, 6, 1),
                lines=[
                    {"cpt": "47562", "procedure_name": "Lap chole", "work_rvu": 10.0, "work_payment": 500.0},
                    {"cpt": "44970", "procedure_name": "Lap appendix", "work_rvu": 5.0, "work_payment": 250.0},
                ],
            )
        ]

        top = _build_top_cpt_contribution(rows, total_payment=1000.0)

        self.assertEqual(top[0]["cpt"], "47562")
        self.assertEqual(top[0]["est_payment"], 500.0)
        self.assertEqual(top[0]["revenue_percent"], 50.0)

    def test_trend_helpers_return_delta_and_percent(self):
        self.assertEqual(_trend_delta(120.0, 100.0), 20.0)
        self.assertEqual(_trend_percent(120.0, 100.0), 20.0)
        self.assertEqual(_trend_percent(120.0, 0.0), 0.0)


if __name__ == "__main__":
    unittest.main()
