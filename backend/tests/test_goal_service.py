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


def test_monthly_goal_pace_projects_to_calendar_month_end():
    pace = monthly_goal_pace(today=date(2026, 6, 15), annual_goal=9000, month_to_date_wrvu=300)

    assert pace.goal_wrvu == 750.0
    assert pace.month_to_date_wrvu == 300
    assert pace.progress_percent == 40.0
    assert pace.gap_wrvu == 450.0
    assert pace.projected_month_end_wrvu == 600.0
