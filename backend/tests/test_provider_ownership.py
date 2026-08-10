from types import SimpleNamespace
from unittest.mock import MagicMock

from app.api.routes_rvu import (
    _apply_credited_surgeon_ownership,
    _credited_surgeon_from_lines,
    _staff_can_access_scan,
)


def _staff(*, staff_id: int, first: str, last: str, staff_type: str = "physician", suffix: str = "MD") -> SimpleNamespace:
    return SimpleNamespace(
        id=staff_id,
        first_name=first,
        last_name=last,
        full_name=f"{first} {last}",
        staff_type=staff_type,
        suffix=suffix,
        is_active=True,
        display_order=None,
    )


def test_credited_surgeon_moves_to_unique_primary_physician():
    capturer = _staff(staff_id=1, first="Alex", last="Admin", staff_type="staff", suffix="")
    schroeder = _staff(staff_id=2, first="Mark", last="Schroeder")
    db = MagicMock()
    db.query.return_value.filter.return_value.all.return_value = [capturer, schroeder]

    credited = _credited_surgeon_from_lines(
        db,
        [
            {
                "cpt": "47562",
                "provider_name": "Mark Schroeder",
                "provider_role": "surgeon",
                "is_assist": False,
            }
        ],
        fallback=capturer,
    )

    assert credited.id == schroeder.id


def test_credited_surgeon_keeps_fallback_when_providers_conflict():
    capturer = _staff(staff_id=1, first="Alex", last="Admin", staff_type="staff", suffix="")
    one = _staff(staff_id=2, first="Mark", last="Schroeder")
    two = _staff(staff_id=3, first="Chris", last="Johnson")
    db = MagicMock()
    db.query.return_value.filter.return_value.all.return_value = [capturer, one, two]

    credited = _credited_surgeon_from_lines(
        db,
        [
            {"cpt": "47562", "provider_name": "Mark Schroeder", "provider_role": "surgeon", "is_assist": False},
            {"cpt": "44970", "provider_name": "Chris Johnson", "provider_role": "surgeon", "is_assist": False},
        ],
        fallback=capturer,
    )

    assert credited.id == capturer.id


def test_apply_credited_surgeon_ownership_rewrites_scan_owner_and_preserves_entered_by():
    capturer = _staff(staff_id=1, first="Alex", last="Admin", staff_type="staff", suffix="")
    schroeder = _staff(staff_id=2, first="Mark", last="Schroeder")
    scan = SimpleNamespace(id=99, surgeon_id=capturer.id, entered_by_staff_id=None)
    db = MagicMock()
    db.query.return_value.filter.return_value.all.return_value = [capturer, schroeder]

    owner = _apply_credited_surgeon_ownership(
        db,
        scan,
        [{"cpt": "47562", "provider_name": "Mark Schroeder", "provider_role": "surgeon", "is_assist": False}],
        fallback=capturer,
        entered_by=capturer,
    )

    assert owner.id == schroeder.id
    assert scan.surgeon_id == schroeder.id
    assert scan.entered_by_staff_id == capturer.id


def test_staff_can_access_scan_as_owner_or_enterer():
    owner = _staff(staff_id=2, first="Mark", last="Schroeder")
    capturer = _staff(staff_id=1, first="Alex", last="Admin", staff_type="staff", suffix="")
    stranger = _staff(staff_id=3, first="Other", last="Person", staff_type="staff", suffix="")
    scan = SimpleNamespace(surgeon_id=owner.id, entered_by_staff_id=capturer.id)

    assert _staff_can_access_scan(scan, owner) is True
    assert _staff_can_access_scan(scan, capturer) is True
    assert _staff_can_access_scan(scan, stranger) is False
