import unittest

from app.rvu.lookup import calc_payment
from app.services.rvu_payment_service import RvuPaymentService


class RvuCalculationTests(unittest.TestCase):
    def test_49650_modifier_50_matches_capture_editor_expected_value(self):
        row = calc_payment("49650", "99", True, 41.0, modifier="50")

        self.assertEqual(row.work_rvu, 13.95)
        self.assertEqual(row.total_rvu, 13.95)
        self.assertEqual(row.work_payment, 571.95)
        self.assertEqual(row.payment, 571.95)
        self.assertEqual(row.modifier_code, "50")

    def test_modifier_50_uses_work_rvu_compensation(self):
        row = calc_payment("27871", "99", False, 41.0, modifier="50")

        self.assertEqual(row.work_rvu, 13.95)
        self.assertEqual(row.total_rvu, 13.95)
        self.assertEqual(row.work_payment, 571.95)
        self.assertEqual(row.payment, 571.95)
        self.assertEqual(row.modifier_code, "50")
        self.assertEqual(row.modifier_factor, 1.5)

    def test_service_rows_sum_modified_work_payment(self):
        svc = RvuPaymentService()

        rows, total = svc.build_rows_from_lines(
            [{"cpt": "27871", "modifier": "50"}],
            "99",
            False,
            41.0,
        )

        self.assertEqual(rows[0]["work_rvu"], 13.95)
        self.assertEqual(rows[0]["total_rvu"], 13.95)
        self.assertEqual(rows[0]["payment"], 571.95)
        self.assertEqual(total, 571.95)


if __name__ == "__main__":
    unittest.main()
