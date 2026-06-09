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

    def test_multiple_modifiers_are_combined_for_payment(self):
        row = calc_payment("49650", "99", True, 41.0, modifier="AS,50")

        self.assertEqual(row.modifier, "AS,50")
        self.assertEqual(row.modifier_code, "AS,50")
        self.assertAlmostEqual(row.modifier_factor, 0.3)
        self.assertEqual(row.work_rvu, 2.79)
        self.assertEqual(row.work_payment, 114.39)

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

    def test_service_rows_keep_as_modifier_lines(self):
        svc = RvuPaymentService()

        rows, total = svc.build_rows_from_lines(
            [{"cpt": "49650", "modifier": "AS,50", "provider_role": "pa"}],
            "99",
            True,
            41.0,
        )

        self.assertEqual(rows[0]["modifier"], "AS,50")
        self.assertEqual(rows[0]["modifier_code"], "AS,50")
        self.assertEqual(rows[0]["work_rvu"], 2.79)
        self.assertEqual(total, 114.39)

    def test_alphanumeric_modifier_rule_is_supported(self):
        row = calc_payment(
            "27871",
            "99",
            False,
            41.0,
            modifier="1P",
            modifier_rules={"1P": {"factor": 0.75, "desc": "Performance measure exclusion"}},
        )

        self.assertEqual(row.modifier_code, "1P")
        self.assertEqual(row.modifier_factor, 0.75)
        self.assertEqual(row.work_rvu, 6.98)

    def test_modifier_normalization_keeps_letters_and_numbers(self):
        svc = RvuPaymentService()

        rows, total = svc.build_rows(
            ["27871"],
            "99",
            False,
            41.0,
            modifiers={"27871": "-1p"},
            modifier_rules={"1P": {"factor": 0.75, "desc": "Performance measure exclusion"}},
        )

        self.assertEqual(rows[0]["modifier"], "1P")
        self.assertEqual(rows[0]["modifier_code"], "1P")
        self.assertEqual(total, 285.98)


if __name__ == "__main__":
    unittest.main()
