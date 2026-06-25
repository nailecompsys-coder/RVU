from unittest.mock import MagicMock

from app.services.rvu_rules_service import get_effective_cpt_catalog


def _empty_db_session():
    db = MagicMock()
    query = db.query.return_value
    filtered = query.filter.return_value
    filtered.first.return_value = None
    return db


def test_builtin_practice_override_is_flagged_in_catalog():
    catalog = get_effective_cpt_catalog(_empty_db_session())

    row = catalog["49650"]

    assert row["cpt"] == "49650"
    assert row["has_override"] is True
    assert row["override_source"] == "practice"
    assert row["status"] == "override"
