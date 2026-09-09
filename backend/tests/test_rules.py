import unittest

from backend.rules import evaluate_plan


class EvaluatePlanTests(unittest.TestCase):
    def test_walk_only_is_valid_under_walk_limit(self):
        plan = {
            "segments": [{"mode": "walk", "duration_min": 28}],
            "total_duration_min": 28,
        }
        rules = {
            "walk_max_min": 30,
            "bike_or_subway_max_min": 20,
            "mixed_max_min": 20,
        }

        result = evaluate_plan(plan, rules)

        self.assertTrue(result["is_compliant"])
        self.assertEqual(result["reason"], "walk_within_limit")

    def test_partial_bike_plus_subway_is_rejected_by_route_whitelist(self):
        plan = {
            "segments": [
                {"mode": "bike", "duration_min": 6},
                {"mode": "subway", "duration_min": 11},
            ],
            "total_duration_min": 17,
        }
        rules = {
            "walk_max_min": 30,
            "bike_or_subway_max_min": 20,
            "mixed_max_min": 20,
        }

        result = evaluate_plan(plan, rules)

        self.assertFalse(result["is_compliant"])
        self.assertFalse(result["template_allowed"])
        self.assertEqual(result["reason"], "route_template_not_allowed")

    def test_bike_subway_bike_uses_mixed_limit_and_rule_version(self):
        plan = {
            "template": "bike->subway->bike",
            "segments": [
                {"mode": "bike", "duration_min": 4},
                {"mode": "subway", "duration_min": 10},
                {"mode": "bike", "duration_min": 4},
            ],
            "total_duration_min": 18,
        }
        result = evaluate_plan(plan, {"walk_max_min": 30, "bike_or_subway_max_min": 20, "mixed_max_min": 20})
        self.assertTrue(result["is_compliant"])
        self.assertEqual(result["rule_version"], "commute-r1.0")
        self.assertEqual(result["compliance_level"], "boundary")

    def test_non_compliant_plan_reports_margin(self):
        plan = {
            "segments": [{"mode": "subway", "duration_min": 24}],
            "total_duration_min": 24,
        }
        rules = {
            "walk_max_min": 30,
            "bike_or_subway_max_min": 20,
            "mixed_max_min": 20,
        }

        result = evaluate_plan(plan, rules)

        self.assertFalse(result["is_compliant"])
        self.assertEqual(result["over_limit_min"], 4)


if __name__ == "__main__":
    unittest.main()
