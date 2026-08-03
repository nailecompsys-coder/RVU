from datetime import date

from app.services.rvu_goal_service import (
    annual_goal_or_default,
    annual_to_monthly_goal,
    monthly_goal_pace,
    monthly_to_annual_goal,
)


def test_goal_conversions_preserve_existing_annual_storage_contract():
    assert annual_goal_or_default(None) == 9000.0
    assert annual_to_monthly_goal(9000) == 750.0
    assert monthly_to_annual_goal(750) == 9000.0


def test_monthly_goal_pace_banks_surplus_against_remaining_daily_target():
    # Behind through day 15: 300 vs expected 375 → tracking 675 if remaining days stay at 25/day.
    pace = monthly_goal_pace(today=date(2026, 6, 15), annual_goal=9000, month_to_date_wrvu=300)

    assert pace.goal_wrvu == 750.0
    assert pace.month_to_date_wrvu == 300
    assert pace.progress_percent == 40.0
    assert pace.gap_wrvu == 450.0
    assert pace.daily_pace_wrvu == 25.0
    assert pace.expected_to_date_wrvu == 375.0
    assert pace.projected_month_end_wrvu == 675.0
    assert pace.days_in_month == 30
    assert pace.elapsed_days == 15
    assert pace.pace_progress_percent == 80.0
    assert pace.is_on_pace is False
    assert pace.is_goal_met is False


def test_monthly_goal_pace_extra_today_raises_tracking_above_goal():
    # Day 1: need 25, did 30 → bank +5 → tracking 755.
    pace = monthly_goal_pace(today=date(2026, 6, 1), annual_goal=9000, month_to_date_wrvu=30)

    assert pace.daily_pace_wrvu == 25.0
    assert pace.expected_to_date_wrvu == 25.0
    assert pace.projected_month_end_wrvu == 755.0
    assert pace.is_on_pace is True


def test_monthly_goal_pace_miss_next_day_drops_tracking_below_goal():
    # Day 2: after 30 then 15 (MTD 45) → bank -5 → tracking 745.
    pace = monthly_goal_pace(today=date(2026, 6, 2), annual_goal=9000, month_to_date_wrvu=45)

    assert pace.daily_pace_wrvu == 25.0
    assert pace.expected_to_date_wrvu == 50.0
    assert pace.projected_month_end_wrvu == 745.0
    assert pace.is_on_pace is False


def test_monthly_goal_pace_exact_daily_keeps_tracking_at_goal():
    pace = monthly_goal_pace(today=date(2026, 6, 1), annual_goal=9000, month_to_date_wrvu=25)

    assert pace.projected_month_end_wrvu == 750.0
    assert pace.is_on_pace is True


def test_monthly_goal_pace_goal_met():
    pace = monthly_goal_pace(today=date(2026, 8, 10), annual_goal=9000, month_to_date_wrvu=750)

    assert pace.is_goal_met is True
    assert pace.is_on_pace is True
