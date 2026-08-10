import json
from types import SimpleNamespace
from unittest.mock import MagicMock

from app.rvu.lookup import DEFAULT_MODIFIER_FACTORS
from app.services.rvu_rules_service import get_effective_modifier_rules, patch_modifier_rule


def _db_with_overrides(overrides: dict | None) -> MagicMock:
    db = MagicMock()
    if overrides is None:
        db.query.return_value.filter.return_value.first.return_value = None
        return db
    config = SimpleNamespace(rule_id="rvu_modifier_rules", config=json.dumps(overrides), enabled=True)
    db.query.return_value.filter.return_value.first.return_value = config
    return db


def test_mobile_factor_one_does_not_clobber_known_bilateral_rule():
    db = _db_with_overrides(None)

    rule = patch_modifier_rule(
        db,
        "50",
        factor=1.0,
        desc="Mobile-added modifier",
        source="mobile",
        needs_review=True,
    )

    assert rule["factor"] == DEFAULT_MODIFIER_FACTORS["50"]
    assert rule["factor"] == 1.5
    assert "Mobile-added" not in str(rule["desc"])


def test_effective_rules_ignore_poisoned_mobile_override():
    db = _db_with_overrides(
        {
            "80": {"factor": 1.0, "desc": "Mobile-added modifier", "source": "mobile"},
            "50": {"factor": 1.0, "desc": "Mobile-added modifier", "source": "mobile"},
        }
    )

    rules = get_effective_modifier_rules(db)

    assert rules["80"]["factor"] == 0.2
    assert rules["50"]["factor"] == 1.5
    assert rules["80"]["desc"] == "Assistant Surgeon"
