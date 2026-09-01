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
    # After hot streak, a zero day is skipped — series needle unchanged.
    # Month-end projection drops because one remaining calendar day is gone.
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
    assert pace.pace_series[-1].tracking_to_wrvu == 930.0
    assert pace.projected_month_end_wrvu == 900.0
    assert pace.is_on_pace is True
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
    # 75 already in + 25/day × 27 remaining days = 750, not 25 × 31.
    assert pace.projected_month_end_wrvu == 750.0
    assert pace.tracking_delta_vs_goal_wrvu == 0.0
    assert pace.is_on_pace is True


def test_monthly_goal_pace_goal_met():
    pace = monthly_goal_pace(
        today=date(2026, 8, 10),
        annual_goal=9000,
        month_to_date_wrvu=750,
        daily_wrvu_by_date={date(2026, 8, 10): 750.0},
    )

    assert pace.is_goal_met is True
    assert pace.is_on_pace is True


def test_last_day_behind_goal_is_not_on_pace():
    # Screenshot case: 575 of 700 on Aug 31. Working-day average × 31 would
    # project ~891 and falsely say "On pace"; remaining days are 0 so finish = MTD.
    daily = {date(2026, 8, day): 28.75 for day in range(1, 21)}
    pace = monthly_goal_pace(
        today=date(2026, 8, 31),
        annual_goal=8400,
        month_to_date_wrvu=575,
        daily_wrvu_by_date=daily,
    )

    assert pace.goal_wrvu == 700.0
    assert pace.month_to_date_wrvu == 575.0
    assert pace.elapsed_days == 31
    assert pace.active_pace_days == 20
    assert pace.daily_run_rate_wrvu == 28.75
    assert pace.projected_month_end_wrvu == 575.0
    assert pace.gap_wrvu == 125.0
    assert pace.is_goal_met is False
    assert pace.is_on_pace is False


def test_one_remaining_day_cannot_cover_a_large_gap():
    daily = {date(2026, 8, day): 28.75 for day in range(1, 21)}
    pace = monthly_goal_pace(
        today=date(2026, 8, 30),
        annual_goal=8400,
        month_to_date_wrvu=575,
        daily_wrvu_by_date=daily,
    )

    assert pace.projected_month_end_wrvu == 603.75
    assert pace.is_on_pace is False


def test_last_day_on_pace_when_goal_already_met():
    pace = monthly_goal_pace(
        today=date(2026, 8, 31),
        annual_goal=8400,
        month_to_date_wrvu=700,
        daily_wrvu_by_date={date(2026, 8, 1): 700.0},
    )

    assert pace.is_goal_met is True
    assert pace.is_on_pace is True
    assert pace.projected_month_end_wrvu == 700.0
