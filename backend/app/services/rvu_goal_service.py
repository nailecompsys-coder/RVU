"""Goal and pacing helpers for RVU dashboards.

The database stores the goal annually for backward compatibility, while the
mobile dashboard presents a monthly goal. Keep conversion and projection math in
one place so route handlers stay focused on request/response assembly.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date


DEFAULT_ANNUAL_WRVU_GOAL = 9000.0


def annual_goal_or_default(value: float | None, *, default: float = DEFAULT_ANNUAL_WRVU_GOAL) -> float:
    return float(value or default)


def annual_to_monthly_goal(annual_goal: float) -> float:
    return round(max(float(annual_goal), 0.0) / 12, 2)


def monthly_to_annual_goal(monthly_goal: float) -> float:
    return round(max(float(monthly_goal), 0.0) * 12, 2)


@dataclass(frozen=True)
class MonthlyGoalPace:
    goal_wrvu: float
    month_to_date_wrvu: float
    progress_percent: float
    gap_wrvu: float
    projected_month_end_wrvu: float
    days_in_month: int
    elapsed_days: int
    daily_pace_wrvu: float
    expected_to_date_wrvu: float
    pace_progress_percent: float
    is_on_pace: bool
    is_goal_met: bool


def monthly_goal_pace(*, today: date, annual_goal: float, month_to_date_wrvu: float) -> MonthlyGoalPace:
    monthly_goal = annual_to_monthly_goal(annual_goal)
    month_start = date(today.year, today.month, 1)
    next_month_start = date(today.year + 1, 1, 1) if today.month == 12 else date(today.year, today.month + 1, 1)
    days_in_month = (next_month_start - month_start).days
    elapsed_days = max(today.day, 1)
    mtd = round(float(month_to_date_wrvu), 2)
    daily_pace = round(monthly_goal / days_in_month, 2) if days_in_month else 0.0
    expected_to_date = round(daily_pace * elapsed_days, 2)
    remaining_days = max(days_in_month - elapsed_days, 0)
    # Banked plan: keep earning the original daily target for remaining days.
    # Ahead today raises tracking above goal; behind drops it below.
    projected_month_end = round(mtd + daily_pace * remaining_days, 2)
    progress_percent = round((mtd / monthly_goal) * 100, 1) if monthly_goal > 0 else 0.0
    pace_progress_percent = round((mtd / expected_to_date) * 100, 1) if expected_to_date > 0 else 0.0
    is_goal_met = monthly_goal > 0 and mtd >= monthly_goal
    is_on_pace = is_goal_met or (monthly_goal > 0 and projected_month_end + 1e-9 >= monthly_goal)

    return MonthlyGoalPace(
        goal_wrvu=monthly_goal,
        month_to_date_wrvu=mtd,
        progress_percent=progress_percent,
        gap_wrvu=round(monthly_goal - mtd, 2),
        projected_month_end_wrvu=projected_month_end,
        days_in_month=days_in_month,
        elapsed_days=elapsed_days,
        daily_pace_wrvu=daily_pace,
        expected_to_date_wrvu=expected_to_date,
        pace_progress_percent=pace_progress_percent,
        is_on_pace=is_on_pace,
        is_goal_met=is_goal_met,
    )
