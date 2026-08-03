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


def test_pace_starts_on_goal_with_no_captures():
    pace = monthly_goal_pace(today=date(2026, 8, 3), annual_goal=9000, month_to_date_wrvu=0)

    assert pace.goal_wrvu == 750.0
    assert pace.days_in_month == 31
    assert pace.daily_pace_wrvu == 24.19
    assert pace.active_pace_days == 0
    assert pace.projected_month_end_wrvu == 750.0
    assert pace.tracking_delta_vs_goal_wrvu == 0.0
    assert pace.is_on_pace is True
    assert pace.pace_series == ()


def test_exact_daily_bar_keeps_needle_on_goal():
    # 750/31 ≈ 24.19; one day at that rate tracks to ~750.
    day = date(2026, 8, 1)
    pace = monthly_goal_pace(
        today=date(2026, 8, 1),
        annual_goal=9000,
        month_to_date_wrvu=24.19,
        daily_wrvu_by_date={day: 24.19},
    )

    assert pace.active_pace_days == 1
    assert pace.daily_run_rate_wrvu == 24.19
    assert pace.projected_month_end_wrvu == 749.89
    assert abs(pace.tracking_delta_vs_goal_wrvu) < 0.2
    assert pace.is_on_pace is True


def test_hot_day_moves_needle_above_goal_by_run_rate():
    # Day1 25, day2 35 → avg 30 × 31 = 930, not goal+10.
    pace = monthly_goal_pace(
        today=date(2026, 8, 2),
        annual_goal=9000,
        month_to_date_wrvu=60,
        daily_wrvu_by_date={
            date(2026, 8, 1): 25.0,
            date(2026, 8, 2): 35.0,
        },
    )

    assert pace.active_pace_days == 2
    assert pace.daily_run_rate_wrvu == 30.0
    assert pace.projected_month_end_wrvu == 930.0
    assert pace.tracking_delta_vs_goal_wrvu == 180.0
    assert pace.is_on_pace is True
    assert len(pace.pace_series) == 2
    assert pace.pace_series[0].tracking_to_wrvu == 775.0
    assert pace.pace_series[1].tracking_to_wrvu == 930.0


def test_empty_day_does_not_enter_average():
    # After hot streak, a zero day is skipped — needle unchanged.
    pace = monthly_goal_pace(
        today=date(2026, 8, 3),
        annual_goal=9000,
        month_to_date_wrvu=60,
        daily_wrvu_by_date={
            date(2026, 8, 1): 25.0,
            date(2026, 8, 2): 35.0,
            date(2026, 8, 3): 0.0,
        },
    )

    assert pace.active_pace_days == 2
    assert pace.projected_month_end_wrvu == 930.0
    assert len(pace.pace_series) == 2


def test_cold_day_pulls_needle_back_toward_goal():
    pace = monthly_goal_pace(
        today=date(2026, 8, 4),
        annual_goal=9000,
        month_to_date_wrvu=75,
        daily_wrvu_by_date={
            date(2026, 8, 1): 25.0,
            date(2026, 8, 2): 35.0,
            date(2026, 8, 4): 15.0,
        },
    )

    assert pace.active_pace_days == 3
    assert pace.daily_run_rate_wrvu == 25.0
    assert pace.projected_month_end_wrvu == 775.0
    assert pace.tracking_delta_vs_goal_wrvu == 25.0


def test_monthly_goal_pace_goal_met():
    pace = monthly_goal_pace(
        today=date(2026, 8, 10),
        annual_goal=9000,
        month_to_date_wrvu=750,
        daily_wrvu_by_date={date(2026, 8, 10): 750.0},
    )

    assert pace.is_goal_met is True
    assert pace.is_on_pace is True
