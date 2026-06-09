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


def monthly_goal_pace(*, today: date, annual_goal: float, month_to_date_wrvu: float) -> MonthlyGoalPace:
    monthly_goal = annual_to_monthly_goal(annual_goal)
    month_start = date(today.year, today.month, 1)
    next_month_start = date(today.year + 1, 1, 1) if today.month == 12 else date(today.year, today.month + 1, 1)
    days_in_month = (next_month_start - month_start).days
    elapsed_days = max(today.day, 1)
    progress_percent = round((month_to_date_wrvu / monthly_goal) * 100, 1) if monthly_goal > 0 else 0.0

    return MonthlyGoalPace(
        goal_wrvu=monthly_goal,
        month_to_date_wrvu=round(float(month_to_date_wrvu), 2),
        progress_percent=progress_percent,
        gap_wrvu=round(monthly_goal - month_to_date_wrvu, 2),
        projected_month_end_wrvu=round((month_to_date_wrvu / elapsed_days) * days_in_month, 2) if elapsed_days else 0.0,
    )
