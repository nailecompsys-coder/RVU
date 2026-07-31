from unittest.mock import MagicMock

from app.services.rvu_rules_service import get_effective_cpt_catalog


def _empty_db_session():
    db = MagicMock()
    query = db.query.return_value
    filtered = query.filter.return_value
    filtered.first.return_value = None
    return db


def test_49650_uses_cms_published_work_rvu_without_practice_override():
    catalog = get_effective_cpt_catalog(_empty_db_session())

    row = catalog["49650"]

    assert row["cpt"] == "49650"
    assert row["work_rvu"] == 6.2
    assert row["has_override"] is False
    assert row["override_source"] in (None, "", "cms")
    assert row["status"] != "override"
