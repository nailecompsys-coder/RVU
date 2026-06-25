from app.services import rvu_retention_policy


def test_charge_scan_images_are_never_retained(monkeypatch):
    monkeypatch.setenv("RVU_STORE_CHARGE_IMAGES", "true")

    assert rvu_retention_policy.charge_scan_images_enabled() is False


def test_op_note_image_retention_remains_explicit(monkeypatch):
    monkeypatch.setenv("RVU_STORE_OP_NOTE_IMAGES", "true")

    assert rvu_retention_policy.op_note_images_enabled() is True
