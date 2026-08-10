from datetime import date

from app.services.rvu_scorecard_service import (
    build_scorecard,
    weighted_rolling_expected,
)


def test_weighted_expected_prefers_recent_months():
    expected = weighted_rolling_expected([100, 200, 300], fallback=750)
    assert expected == 233.33


def test_weighted_expected_falls_back_without_history():
    assert weighted_rolling_expected([], fallback=750) == 750.0


def test_scorecard_marks_miss_and_beat_and_footer_language_fields():
    # Aug 15 → last complete month is July
    today = date(2026, 8, 15)
    actuals = {
        "2026-02": 500.0,
        "2026-03": 500.0,
        "2026-04": 500.0,
        "2026-05": 500.0,
        "2026-06": 500.0,
        "2026-07": 800.0,
    }
    payload = build_scorecard(
        today=today,
        actual_by_month=actuals,
        cf=41.0,
        monthly_goal_fallback=600.0,
        months=6,
    )

    assert len(payload["series"]) == 6
    latest = payload["series"][-1]
    assert latest["month"] == "2026-07"
    assert latest["status"] == "beat"
    assert latest["actual_wrvu"] == 800.0
    assert payload["footer"]["above_months"] + payload["footer"]["below_months"] == 6
    assert "above_months" in payload["footer"]
    assert "below_months" in payload["footer"]
    assert payload["yearly"]["actual_comp"] == round(payload["yearly"]["actual_wrvu"] * 41.0, 2)
    assert payload["projection"]["month"] == "2026-08"
    assert payload["methodology"]["dollars"].startswith("estimated_compensation")


def test_scorecard_skips_incomplete_current_month_and_flat_empties():
    today = date(2026, 8, 10)
    actuals = {
        "2026-05": 600.0,
        "2026-06": 620.0,
        "2026-07": 640.0,
        "2026-08": 0.0,  # in progress — must not appear
    }
    payload = build_scorecard(
        today=today,
        actual_by_month=actuals,
        cf=41.0,
        monthly_goal_fallback=600.0,
        months=3,
    )
    months = [row["month"] for row in payload["series"]]
    assert months == ["2026-05", "2026-06", "2026-07"]
    assert payload["hero"]["surprise"]["month"] == "2026-07"
    assert payload["projection"]["month"] == "2026-08"
