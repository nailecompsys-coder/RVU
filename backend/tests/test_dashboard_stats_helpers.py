import json
import unittest
from datetime import date, datetime
from types import SimpleNamespace

from app.api.routes_rvu import (
    _build_best_day_this_month,
    _build_monthly_trend,
    _build_setting_breakdown,
    _build_top_cpt_contribution,
    _period_bounds,
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
        facility=True,
    )


class DashboardStatsHelperTests(unittest.TestCase):
    def test_month_period_bounds_are_calendar_month_to_date(self):
        start, end, prev_start, prev_end = _period_bounds("month", date(2026, 7, 6))

        self.assertEqual(start, date(2026, 7, 1))
        self.assertEqual(end, date(2026, 7, 6))
        self.assertEqual(prev_start, date(2026, 6, 1))
        self.assertEqual(prev_end, date(2026, 6, 30))

    def test_scan_work_payment_uses_wrvu_times_cf_not_stored_payment(self):
        row = scan(
            service_date=date(2026, 6, 1),
            lines=[
                {"cpt": "47562", "work_rvu": 10.0, "work_payment": 500.0},
                {"cpt": "47563", "work_rvu": 5.0, "work_payment": 250.0},
            ],
        )

        # Stale stored payments (750) must not win over live CF math (15 × 41).
        self.assertEqual(_scan_work_payment(row, 41.0), 615.0)

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

    def test_top_cpt_contribution_uses_wrvu_times_cf(self):
        rows = [
            scan(
                service_date=date(2026, 6, 1),
                lines=[
                    {"cpt": "47562", "procedure_name": "Lap chole", "work_rvu": 10.0, "work_payment": 999.0},
                    {"cpt": "44970", "procedure_name": "Lap appendix", "work_rvu": 5.0, "work_payment": 999.0},
                ],
            )
        ]

        top = _build_top_cpt_contribution(rows, total_payment=615.0, cf=41.0)

        self.assertEqual(top[0]["cpt"], "47562")
        self.assertEqual(top[0]["est_payment"], 410.0)
        self.assertEqual(top[0]["revenue_percent"], 66.7)

    def test_setting_breakdown_returns_dollars_with_wrvu(self):
        facility = scan(
            service_date=date(2026, 7, 1),
            lines=[{"cpt": "47562", "work_rvu": 10.0, "work_payment": 999.0}],
        )
        non_facility = scan(
            service_date=date(2026, 7, 2),
            lines=[{"cpt": "99214", "work_rvu": 2.0, "work_payment": 999.0}],
        )
        non_facility.facility = False
        pending = scan(
            service_date=date(2026, 7, 3),
            status="pending_review",
            lines=[{"cpt": "99215", "work_rvu": 99.0, "work_payment": 999.0}],
        )

        breakdown = _build_setting_breakdown([facility, non_facility, pending], cf=41.0)

        self.assertEqual(breakdown[0]["label"], "Facility")
        self.assertEqual(breakdown[0]["count"], 1)
        self.assertEqual(breakdown[0]["wrvu"], 10.0)
        self.assertEqual(breakdown[0]["compensation"], 410.0)
        self.assertEqual(breakdown[1]["label"], "Non-Facility")
        self.assertEqual(breakdown[1]["count"], 1)
        self.assertEqual(breakdown[1]["wrvu"], 2.0)
        self.assertEqual(breakdown[1]["compensation"], 82.0)

    def test_monthly_trend_returns_compensation(self):
        scans = [
            scan(
                service_date=date(2026, 6, 1),
                lines=[{"cpt": "47562", "work_rvu": 10.0, "work_payment": 410.0}],
            ),
            scan(
                service_date=date(2026, 7, 1),
                lines=[{"cpt": "99214", "work_rvu": 2.0, "work_payment": 82.0}],
            ),
            scan(
                service_date=date(2026, 7, 2),
                status="pending_review",
                lines=[{"cpt": "99215", "work_rvu": 99.0, "work_payment": 999.0}],
            ),
        ]

        trend = _build_monthly_trend(scans, date(2026, 7, 6))
        july = next(row for row in trend if row["month"] == "2026-07")
        june = next(row for row in trend if row["month"] == "2026-06")

        self.assertEqual(july["cases"], 1)
        self.assertEqual(july["wrvu"], 2.0)
        self.assertEqual(july["compensation"], 82.0)
        self.assertEqual(june["cases"], 1)
        self.assertEqual(june["wrvu"], 10.0)
        self.assertEqual(june["compensation"], 410.0)

    def test_trend_helpers_return_delta_and_percent(self):
        self.assertEqual(_trend_delta(120.0, 100.0), 20.0)
        self.assertEqual(_trend_percent(120.0, 100.0), 20.0)
        self.assertEqual(_trend_percent(120.0, 0.0), 0.0)


if __name__ == "__main__":
    unittest.main()
