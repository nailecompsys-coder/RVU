"""RVU Scorecard — 12-month expected vs actual performance math."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Sequence


def _shift_month(year: int, month: int, delta: int) -> tuple[int, int]:
    """Shift calendar month by delta (negative = past)."""
    idx = year * 12 + (month - 1) + delta
    return idx // 12, idx % 12 + 1


def month_keys_ending(today: date, count: int) -> list[str]:
    """Return YYYY-MM keys for `count` months ending at today's month (oldest first)."""
    keys: list[str] = []
    year, month = today.year, today.month
    for _ in range(count):
        keys.append(f"{year:04d}-{month:02d}")
        year, month = _shift_month(year, month, -1)
    keys.reverse()
    return keys


def month_label(year: int, month: int) -> str:
    return date(year, month, 1).strftime("%b '%y")


def weighted_rolling_expected(prior_actuals: Sequence[float], *, fallback: float) -> float:
    """6-month rolling average weighted toward recent months (weights 1..n).

    `prior_actuals` are oldest→newest months strictly before the target month.
    Uses up to the last 6 values. Falls back when no history.
    """
    window = [float(v) for v in prior_actuals[-6:] if v is not None]
    if not window:
        return round(float(fallback), 2)
    weights = list(range(1, len(window) + 1))
    total_w = float(sum(weights))
    return round(sum(value * weight for value, weight in zip(window, weights)) / total_w, 2)


def consensus_band(expected: float, *, fraction: float = 0.10) -> tuple[float, float]:
    low = round(max(expected * (1.0 - fraction), 0.0), 2)
    high = round(expected * (1.0 + fraction), 2)
    return low, high


@dataclass(frozen=True)
class ScorecardMonth:
    month: str
    label: str
    expected_wrvu: float
    actual_wrvu: float
    status: str
    delta_wrvu: float
    delta_percent: float
    consensus_low_wrvu: float
    consensus_high_wrvu: float
    actual_comp: float
    expected_comp: float


def build_scorecard(
    *,
    today: date,
    actual_by_month: dict[str, float],
    cf: float,
    monthly_goal_fallback: float,
    months: int = 12,
    history_pad: int = 6,
) -> dict[str, object]:
    """Build scorecard payload from monthly actual wRVU map (YYYY-MM → wrvu)."""
    display_keys = month_keys_ending(today, months)
    # Extra history so early display months have a rolling baseline.
    history_keys = month_keys_ending(today, months + history_pad)

    series: list[ScorecardMonth] = []
    prior: list[float] = []

    for key in history_keys:
        year = int(key[:4])
        month = int(key[5:7])
        actual = round(float(actual_by_month.get(key, 0.0) or 0.0), 2)
        expected = weighted_rolling_expected(prior, fallback=monthly_goal_fallback)
        if key in display_keys:
            delta = round(actual - expected, 2)
            delta_pct = round((delta / expected) * 100, 1) if expected else 0.0
            status = "beat" if delta >= 0 else "miss"
            low, high = consensus_band(expected)
            series.append(
                ScorecardMonth(
                    month=key,
                    label=month_label(year, month),
                    expected_wrvu=expected,
                    actual_wrvu=actual,
                    status=status,
                    delta_wrvu=delta,
                    delta_percent=delta_pct,
                    consensus_low_wrvu=low,
                    consensus_high_wrvu=high,
                    actual_comp=round(actual * cf, 2),
                    expected_comp=round(expected * cf, 2),
                )
            )
        prior.append(actual)

    expected_total = round(sum(row.expected_wrvu for row in series), 2)
    actual_total = round(sum(row.actual_wrvu for row in series), 2)
    beat_total = round(actual_total - expected_total, 2)
    beat_pct = round((beat_total / expected_total) * 100, 1) if expected_total else 0.0

    above = sum(1 for row in series if row.status == "beat")
    below = len(series) - above
    above_rate = round((above / len(series)) * 100, 1) if series else 0.0

    latest = series[-1] if series else None
    surprise = None
    if latest is not None:
        surprise = {
            "month": latest.month,
            "label": latest.label,
            "beat_wrvu": latest.delta_wrvu,
            "beat_percent": latest.delta_percent,
            "status": latest.status,
        }

    # Projection: weighted expected for next calendar month using all history including current.
    next_year, next_month = _shift_month(today.year, today.month, 1)
    projected = weighted_rolling_expected(prior, fallback=monthly_goal_fallback)

    actual_comp = round(actual_total * cf, 2)
    expected_comp = round(expected_total * cf, 2)

    return {
        "period_label": f"Last {months} Months",
        "cf": round(float(cf), 4),
        "hero": {
            "expected_wrvu": expected_total,
            "actual_wrvu": actual_total,
            "beat_wrvu": beat_total,
            "beat_percent": beat_pct,
            "surprise": surprise,
        },
        "series": [
            {
                "month": row.month,
                "label": row.label,
                "expected_wrvu": row.expected_wrvu,
                "actual_wrvu": row.actual_wrvu,
                "status": row.status,
                "delta_wrvu": row.delta_wrvu,
                "delta_percent": row.delta_percent,
                "consensus_low_wrvu": row.consensus_low_wrvu,
                "consensus_high_wrvu": row.consensus_high_wrvu,
                "actual_comp": row.actual_comp,
                "expected_comp": row.expected_comp,
            }
            for row in series
        ],
        "projection": {
            "month": f"{next_year:04d}-{next_month:02d}",
            "label": month_label(next_year, next_month),
            "projected_wrvu": projected,
        },
        "footer": {
            "above_months": above,
            "below_months": below,
            "above_rate_percent": above_rate,
            "total_beat_wrvu": beat_total,
            "total_beat_percent": beat_pct,
        },
        "yearly": {
            "expected_wrvu": expected_total,
            "actual_wrvu": actual_total,
            "actual_comp": actual_comp,
            "expected_comp": expected_comp,
            "comp_delta": round(actual_comp - expected_comp, 2),
        },
        "methodology": {
            "expected": "6-month rolling average, weights 1..n toward recent months",
            "consensus": "±10% of expected (placeholder until peer data)",
            "dollars": "estimated_compensation = wRVU × CF (not collections)",
        },
    }
