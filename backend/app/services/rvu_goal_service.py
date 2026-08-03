"""Goal and pacing helpers for RVU dashboards.

The database stores the goal annually for backward compatibility, while the
mobile dashboard presents a monthly goal. Keep conversion and projection math in
one place so route handlers stay focused on request/response assembly.

Pace needle (tracking_to):
  daily_bar = month_goal / days_in_month
  active days = calendar days with captured wRVU > 0 (empty days skipped)
  run_rate = MTD / active_days
  tracking_to = run_rate * days_in_month
  Starts on the goal line when there are no captures yet.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Mapping


DEFAULT_ANNUAL_WRVU_GOAL = 9000.0


def annual_goal_or_default(value: float | None, *, default: float = DEFAULT_ANNUAL_WRVU_GOAL) -> float:
    return float(value or default)


def annual_to_monthly_goal(annual_goal: float) -> float:
    return round(max(float(annual_goal), 0.0) / 12, 2)


def monthly_to_annual_goal(monthly_goal: float) -> float:
    return round(max(float(monthly_goal), 0.0) * 12, 2)


@dataclass(frozen=True)
class PaceSeriesPoint:
    date: str
    day_wrvu: float
    tracking_to_wrvu: float
    delta_vs_goal_wrvu: float


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
    active_pace_days: int
    daily_run_rate_wrvu: float
    tracking_delta_vs_goal_wrvu: float
    pace_series: tuple[PaceSeriesPoint, ...]


def monthly_goal_pace(
    *,
    today: date,
    annual_goal: float,
    month_to_date_wrvu: float,
    daily_wrvu_by_date: Mapping[date, float] | None = None,
) -> MonthlyGoalPace:
    monthly_goal = annual_to_monthly_goal(annual_goal)
    month_start = date(today.year, today.month, 1)
    next_month_start = date(today.year + 1, 1, 1) if today.month == 12 else date(today.year, today.month + 1, 1)
    days_in_month = (next_month_start - month_start).days
    elapsed_days = max(today.day, 1)
    mtd = round(float(month_to_date_wrvu), 2)
    daily_bar = round(monthly_goal / days_in_month, 2) if days_in_month else 0.0
    expected_to_date = round(daily_bar * elapsed_days, 2)

    series: list[PaceSeriesPoint] = []
    running = 0.0
    active_days = 0
    daily_map = daily_wrvu_by_date or {}
    for day in sorted(day for day, value in daily_map.items() if day <= today and float(value) > 0):
        day_wrvu = round(float(daily_map[day]), 2)
        running = round(running + day_wrvu, 2)
        active_days += 1
        run_rate = round(running / active_days, 2)
        tracking = round(run_rate * days_in_month, 2) if days_in_month else 0.0
        series.append(
            PaceSeriesPoint(
                date=day.isoformat(),
                day_wrvu=day_wrvu,
                tracking_to_wrvu=tracking,
                delta_vs_goal_wrvu=round(tracking - monthly_goal, 2),
            )
        )

    if active_days > 0 and series:
        daily_run_rate = round(running / active_days, 2)
        tracking_to = series[-1].tracking_to_wrvu
        # Prefer summed active days when a series exists; keep caller MTD if series empty.
        mtd = running
    else:
        daily_run_rate = daily_bar
        tracking_to = monthly_goal

    tracking_delta = round(tracking_to - monthly_goal, 2)
    progress_percent = round((mtd / monthly_goal) * 100, 1) if monthly_goal > 0 else 0.0
    pace_progress_percent = round((tracking_to / monthly_goal) * 100, 1) if monthly_goal > 0 else 0.0
    is_goal_met = monthly_goal > 0 and mtd >= monthly_goal
    # Half-wRVU tolerance so rounded daily-bar days still read as on the goal line.
    is_on_pace = is_goal_met or (monthly_goal > 0 and tracking_to + 0.5 >= monthly_goal)

    return MonthlyGoalPace(
        goal_wrvu=monthly_goal,
        month_to_date_wrvu=mtd,
        progress_percent=progress_percent,
        gap_wrvu=round(monthly_goal - mtd, 2),
        projected_month_end_wrvu=tracking_to,
        days_in_month=days_in_month,
        elapsed_days=elapsed_days,
        daily_pace_wrvu=daily_bar,
        expected_to_date_wrvu=expected_to_date,
        pace_progress_percent=pace_progress_percent,
        is_on_pace=is_on_pace,
        is_goal_met=is_goal_met,
        active_pace_days=active_days,
        daily_run_rate_wrvu=daily_run_rate,
        tracking_delta_vs_goal_wrvu=tracking_delta,
        pace_series=tuple(series),
    )
