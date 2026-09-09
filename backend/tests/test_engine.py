import unittest

from backend.engine import search_best_plans


class SearchBestPlansTests(unittest.TestCase):
    def test_prefers_fewer_segments_when_multiple_plans_are_compliant(self):
        provider_options = [
            {
                "provider": "baidu",
                "template": "bike->subway->walk",
                "segments": [
                    {"mode": "bike", "duration_min": 2},
                    {"mode": "subway", "duration_min": 7},
                    {"mode": "walk", "duration_min": 1},
                ],
            },
            {
                "provider": "qq",
                "template": "bike",
                "segments": [{"mode": "bike", "duration_min": 18}],
            },
        ]
        rules = {
            "walk_max_min": 30,
            "bike_or_subway_max_min": 20,
            "mixed_max_min": 20,
        }

        results = search_best_plans(provider_options, rules)

        self.assertEqual(results[0]["template"], "bike")
        self.assertEqual(results[0]["provider"], "qq")

    def test_returns_fastest_compliant_plan_first(self):
        provider_options = [
            {
                "provider": "amap",
                "template": "bike->subway->bike",
                "segments": [
                    {"mode": "bike", "duration_min": 4},
                    {"mode": "subway", "duration_min": 11},
                    {"mode": "bike", "duration_min": 4},
                ],
            },
            {
                "provider": "qq",
                "template": "bike->subway->bike",
                "segments": [
                    {"mode": "bike", "duration_min": 3},
                    {"mode": "subway", "duration_min": 11},
                    {"mode": "bike", "duration_min": 3},
                ],
            },
            {
                "provider": "baidu",
                "template": "walk",
                "segments": [{"mode": "walk", "duration_min": 33}],
            },
        ]
        rules = {
            "walk_max_min": 30,
            "bike_or_subway_max_min": 20,
            "mixed_max_min": 20,
        }

        results = search_best_plans(provider_options, rules)

        self.assertEqual(results[0]["provider"], "qq")
        self.assertTrue(results[0]["evaluation"]["is_compliant"])
        self.assertEqual(results[0]["total_duration_min"], 17)

    def test_keeps_non_compliant_plans_after_compliant_ones(self):
        provider_options = [
            {
                "provider": "amap",
                "template": "subway",
                "segments": [{"mode": "subway", "duration_min": 22}],
            },
            {
                "provider": "qq",
                "template": "bike",
                "segments": [{"mode": "bike", "duration_min": 19}],
            },
        ]
        rules = {
            "walk_max_min": 30,
            "bike_or_subway_max_min": 20,
            "mixed_max_min": 20,
        }

        results = search_best_plans(provider_options, rules)

        self.assertEqual(results[0]["provider"], "qq")
        self.assertFalse(results[1]["evaluation"]["is_compliant"])

    def test_prefers_shorter_alias_fallback_when_it_is_faster_than_exact_match(self):
        provider_options = [
            {
                "provider": "amap",
                "template": "bike",
                "used_alias_fallback": True,
                "segments": [{"mode": "bike", "duration_min": 19}],
            },
            {
                "provider": "amap",
                "template": "bike",
                "used_alias_fallback": False,
                "segments": [{"mode": "bike", "duration_min": 20}],
            },
        ]
        rules = {
            "walk_max_min": 30,
            "bike_or_subway_max_min": 20,
            "mixed_max_min": 20,
        }

        results = search_best_plans(provider_options, rules)

        self.assertTrue(results[0]["used_alias_fallback"])
        self.assertEqual(results[0]["total_duration_min"], 19)

    def test_prefers_integrated_over_stitched_when_duration_and_segments_match(self):
        provider_options = [
            {
                "provider": "amap",
                "template": "walk->subway->walk",
                "route_source": "stitched_station_combo",
                "segments": [
                    {"mode": "walk", "duration_min": 3},
                    {"mode": "subway", "duration_min": 10},
                    {"mode": "walk", "duration_min": 2},
                ],
            },
            {
                "provider": "amap",
                "template": "walk->subway->walk",
                "route_source": "integrated",
                "segments": [
                    {"mode": "walk", "duration_min": 3},
                    {"mode": "subway", "duration_min": 10},
                    {"mode": "walk", "duration_min": 2},
                ],
            },
        ]
        rules = {
            "walk_max_min": 30,
            "bike_or_subway_max_min": 20,
            "mixed_max_min": 20,
        }

        results = search_best_plans(provider_options, rules)

        self.assertEqual(results[0]["route_source"], "integrated")

    def test_prefers_more_bike_segments_when_mixed_plan_duration_matches(self):
        provider_options = [
            {
                "provider": "amap",
                "template": "walk->subway->walk",
                "route_source": "integrated",
                "segments": [
                    {"mode": "walk", "duration_min": 3},
                    {"mode": "subway", "duration_min": 10},
                    {"mode": "walk", "duration_min": 2},
                ],
            },
            {
                "provider": "amap",
                "template": "bike->subway->bike",
                "route_source": "stitched_station_combo",
                "segments": [
                    {"mode": "bike", "duration_min": 3},
                    {"mode": "subway", "duration_min": 10},
                    {"mode": "bike", "duration_min": 2},
                ],
            },
        ]
        rules = {
            "walk_max_min": 30,
            "bike_or_subway_max_min": 20,
            "mixed_max_min": 20,
        }

        results = search_best_plans(provider_options, rules)

        self.assertEqual(results[0]["template"], "bike->subway->bike")


if __name__ == "__main__":
    unittest.main()
