import time
import unittest

from backend.config import ProviderConfig
import backend.providers as providers_module
from backend.providers import (
    _amap_input_tips,
    _amap_nearby_subway_stations,
    _amap_resolve_place,
    _amap_route,
    _mock_routes,
    build_live_provider_options,
    load_provider_payload,
)


class LiveProviderOptionTests(unittest.TestCase):
    def test_amap_input_tips_returns_poi_candidates(self):
        def fake_fetch_json(url):
            self.assertIn("assistant/inputtips", url)
            return {
                "status": "1",
                "tips": [
                    {
                        "id": "B0FF123",
                        "name": "中海雅园",
                        "district": "北京市海淀区",
                        "address": "北洼西里",
                        "location": "116.305,39.932",
                    }
                ],
            }

        suggestions = _amap_input_tips("中海雅园", "amap-key", fake_fetch_json)

        self.assertEqual(len(suggestions), 1)
        self.assertEqual(suggestions[0]["name"], "中海雅园")
        self.assertEqual(suggestions[0]["location"], "116.305,39.932")

    def test_amap_resolve_place_falls_back_to_poi_search_for_fuzzy_address(self):
        calls = []

        def fake_fetch_json(url):
            calls.append(url)
            if "assistant/inputtips" in url:
                return {"status": "1", "tips": []}
            if "v5/place/text" in url:
                return {
                    "status": "1",
                    "pois": [
                        {
                            "id": "B0FF123",
                            "name": "海淀区北洼西里中海雅园",
                            "address": "海淀区北洼西里",
                            "location": "116.305,39.932",
                            "adcode": "110108",
                            "cityname": "北京市",
                            "pname": "北京市",
                        }
                    ],
                }
            raise AssertionError(f"unexpected url: {url}")

        point = _amap_resolve_place("海淀区北洼西里中海雅园", "amap-key", fake_fetch_json)

        self.assertEqual(point["label"], "海淀区北洼西里中海雅园")
        self.assertEqual(point["lng"], 116.305)
        self.assertTrue(any("assistant/inputtips" in call for call in calls))
        self.assertTrue(any("v5/place/text" in call for call in calls))

    def test_amap_nearby_subway_stations_returns_sorted_candidates(self):
        def fake_fetch_json(url):
            self.assertIn("v5/place/around", url)
            self.assertIn("%E5%9C%B0%E9%93%81%E7%AB%99%E5%87%BA%E5%85%A5%E5%8F%A3", url)
            self.assertIn("page_size=5", url)
            return {
                "status": "1",
                "pois": [
                    {
                        "name": "海淀黄庄站",
                        "location": "116.317,39.976",
                        "distance": "220",
                    },
                    {
                        "name": "知春里站",
                        "location": "116.329,39.982",
                        "distance": "540",
                    },
                ],
            }

        stations = _amap_nearby_subway_stations(
            {"lng": 116.305, "lat": 39.932, "citycode": "010", "label": "中海雅园"},
            "amap-key",
            fake_fetch_json,
        )

        self.assertEqual([item["label"] for item in stations], ["海淀黄庄站", "知春里站"])
        self.assertEqual(stations[0]["distance_m"], 220)

    def test_amap_nearby_subway_stations_filters_non_station_pois(self):
        def fake_fetch_json(url):
            self.assertIn("v5/place/around", url)
            return {
                "status": "1",
                "pois": [
                    {
                        "name": "紫竹桥南",
                        "location": "116.315,39.944",
                        "distance": "180",
                    },
                    {
                        "name": "慈寿寺站",
                        "location": "116.316,39.947",
                        "distance": "260",
                    },
                ],
            }

        stations = _amap_nearby_subway_stations(
            {"lng": 116.305, "lat": 39.932, "citycode": "010", "label": "中海雅园"},
            "amap-key",
            fake_fetch_json,
        )

        self.assertEqual([item["label"] for item in stations], ["慈寿寺站"])

    def test_mock_routes_do_not_invent_gate_labels_when_user_left_fields_blank(self):
        routes = _mock_routes(
            {
                "office": "丽金智地西塔",
                "home": "海淀区北洼西里中海雅园",
                "office_aliases": [],
                "home_gates": [],
                "stations": [],
            }
        )

        labels = {
            value
            for route in routes
            for segment in route["segments"]
            for value in (segment["from_name"], segment["to_name"])
        }

        self.assertNotIn("东门", labels)
        self.assertNotIn("办公楼北门", labels)

    def test_live_mode_builds_real_options_for_available_providers(self):
        payload = {
            "office": "字节跳动深圳湾工区",
            "home": "南山区示例花园",
        }
        config = ProviderConfig(
            mode="live",
            amap_key="amap-key",
            baidu_key="",
            qq_key="",
        )

        def fake_fetch_json(url):
            if "assistant/inputtips" in url:
                return {
                    "status": "1",
                    "tips": [
                        {
                            "id": "poi-1",
                            "name": "字节跳动深圳湾工区",
                            "district": "深圳市南山区",
                            "address": "科苑南路",
                            "location": "113.95,22.54",
                        }
                    ],
                }
            if "v5/place/around" in url:
                return {
                    "status": "1",
                    "pois": [
                        {"name": "后海站", "location": "113.949,22.539", "distance": "180"},
                        {"name": "科苑站", "location": "113.960,22.541", "distance": "320"},
                    ],
                }
            if "restapi.amap.com/v5/direction/walking" in url:
                return {"route": {"paths": [{"cost": {"duration": 480}, "distance": 1100}]}}
            if "restapi.amap.com/v5/direction/bicycling" in url:
                return {
                    "errcode": 0,
                    "data": {
                        "paths": [{"duration": 1320, "distance": 1800}],
                    },
                }
            if "restapi.amap.com/v5/direction/transit/integrated" in url:
                return {
                    "route": {
                        "transits": [
                            {
                                "cost": {"duration": 720},
                                "distance": 5200,
                                "segments": [
                                    {"walking": {"duration": 120}},
                                    {
                                        "bus": {
                                            "buslines": [
                                                {
                                                    "name": "11号线",
                                                    "departure_stop": {"name": "后海"},
                                                    "arrival_stop": {"name": "科苑"},
                                                }
                                            ]
                                        }
                                    },
                                    {"walking": {"duration": 60}},
                                ],
                            }
                        ],
                    }
                }
            raise AssertionError(f"unexpected url: {url}")

        results = build_live_provider_options(payload, config, fake_fetch_json)

        providers = {item["provider"] for item in results}
        templates = {item["template"] for item in results}

        self.assertEqual(providers, {"amap"})
        self.assertIn("subway", templates)
        self.assertNotIn("walk", templates)
        self.assertTrue(all(item["segments"] for item in results))

    def test_live_mode_skips_walk_when_integrated_is_compliant(self):
        payload = {
            "office": "字节跳动深圳湾工区",
            "home": "南山区示例花园",
        }
        config = ProviderConfig(
            mode="live",
            amap_key="amap-key",
            baidu_key="",
            qq_key="",
        )

        def fake_fetch_json(url):
            if "assistant/inputtips" in url:
                return {
                    "status": "1",
                    "tips": [{"name": "地点", "location": "113.95,22.54", "adcode": "440305"}],
                }
            if "v5/place/around" in url:
                return {
                    "status": "1",
                    "pois": [
                        {"name": "后海站", "location": "113.949,22.539", "distance": "180"},
                        {"name": "科苑站", "location": "113.960,22.541", "distance": "320"},
                    ],
                }
            if "v5/direction/bicycling" in url:
                return {"status": "1", "route": {"paths": [{"cost": {"duration": 1320}, "distance": 1800}]}}
            if "v5/direction/transit/integrated" in url:
                return {
                    "route": {
                        "transits": [
                            {
                                "cost": {"duration": 720},
                                "distance": 5200,
                                "segments": [
                                    {"walking": {"duration": 120}},
                                    {
                                        "bus": {
                                            "buslines": [
                                                {
                                                    "name": "11号线",
                                                    "departure_stop": {"name": "后海"},
                                                    "arrival_stop": {"name": "科苑"},
                                                }
                                            ]
                                        }
                                    },
                                    {"walking": {"duration": 60}},
                                ],
                            }
                        ],
                    }
                }
            if "v5/direction/walking" in url:
                raise AssertionError(f"walking should be skipped when integrated is compliant: {url}")
            raise AssertionError(f"unexpected url: {url}")

        results = build_live_provider_options(payload, config, fake_fetch_json)

        templates = {item["template"] for item in results}
        self.assertIn("subway", templates)
        self.assertNotIn("walk", templates)

    def test_exact_integrated_uses_single_app_default_strategy(self):
        payload = {
            "office": "字节跳动深圳湾工区",
            "home": "南山区示例花园",
        }
        config = ProviderConfig(
            mode="live",
            amap_key="amap-key",
            baidu_key="",
            qq_key="",
        )
        calls = []

        def fake_fetch_json(url):
            calls.append(url)
            if "assistant/inputtips" in url:
                return {
                    "status": "1",
                    "tips": [
                        {
                            "id": "poi-1",
                            "name": "字节跳动深圳湾工区",
                            "district": "深圳市南山区",
                            "address": "科苑南路",
                            "location": "113.95,22.54",
                        }
                    ],
                }
            if "v5/place/around" in url:
                return {
                    "status": "1",
                    "pois": [
                        {"name": "后海站", "location": "113.949,22.539", "distance": "180"},
                        {"name": "科苑站", "location": "113.960,22.541", "distance": "320"},
                    ],
                }
            if "restapi.amap.com/v5/direction/walking" in url:
                return {"route": {"paths": [{"cost": {"duration": 480}, "distance": 1100}]}}
            if "restapi.amap.com/v5/direction/bicycling" in url:
                return {"status": "1", "route": {"paths": [{"cost": {"duration": 1320}, "distance": 1800}]}}
            if "restapi.amap.com/v5/direction/transit/integrated" in url:
                duration = 900
                return {
                    "route": {
                        "transits": [
                            {
                                "cost": {"duration": duration},
                                "distance": 5200,
                                "segments": [
                                    {"walking": {"duration": 120}},
                                    {
                                        "bus": {
                                            "buslines": [
                                                {
                                                    "name": "11号线",
                                                    "departure_stop": {"name": "后海"},
                                                    "arrival_stop": {"name": "科苑"},
                                                }
                                            ]
                                        }
                                    },
                                    {"walking": {"duration": 60}},
                                ],
                            }
                        ],
                    }
                }
            raise AssertionError(f"unexpected url: {url}")

        results = build_live_provider_options(payload, config, fake_fetch_json)
        integrated_plan = next(item for item in results if item["route_source"] == "integrated")

        self.assertEqual(integrated_plan["transit_strategy_label"], "高德默认策略")
        self.assertEqual(sum(segment["duration_min"] for segment in integrated_plan["segments"]), 15)
        self.assertTrue(any("strategy=0" in call for call in calls if "transit/integrated" in call))
        self.assertFalse(any("strategy=8" in call for call in calls if "transit/integrated" in call))
        self.assertFalse(any("v3/direction/transit/integrated" in call for call in calls))

    def test_exact_bike_over_limit_still_generates_exact_bike_subway_bike_candidate_without_alias_fallback(self):
        payload = {
            "office": "字节跳动深圳湾工区",
            "home": "南山区示例花园",
        }
        config = ProviderConfig(
            mode="live",
            amap_key="amap-key",
            baidu_key="",
            qq_key="",
        )
        calls = []

        def fake_fetch_json(url):
            calls.append(url)
            if "assistant/inputtips" in url:
                return {
                    "status": "1",
                    "tips": [
                        {
                            "id": "poi-1",
                            "name": "字节跳动深圳湾工区",
                            "district": "深圳市南山区",
                            "address": "科苑南路",
                            "location": "113.95,22.54",
                        }
                    ],
                }
            if "v5/place/around" in url:
                return {
                    "status": "1",
                    "pois": [
                        {"name": "后海站", "location": "113.949,22.539", "distance": "180"},
                        {"name": "科苑站", "location": "113.960,22.541", "distance": "320"},
                    ],
                }
            if "restapi.amap.com/v5/direction/walking" in url:
                return {"route": {"paths": [{"cost": {"duration": 480}, "distance": 1100}]}}
            if "restapi.amap.com/v5/direction/bicycling" in url:
                if "origin=113.950000%2C22.540000" in url and "destination=113.960000%2C22.541000" in url:
                    return {"status": "1", "route": {"paths": [{"cost": {"duration": 180}, "distance": 900}]}}
                return {"status": "1", "route": {"paths": [{"cost": {"duration": 1320}, "distance": 1800}]}}
            if "restapi.amap.com/v5/direction/transit/integrated" in url:
                return {
                    "route": {
                        "transits": [
                            {
                                "cost": {"duration": 720},
                                "distance": 5200,
                                "segments": [
                                    {"walking": {"duration": 120}},
                                    {
                                        "bus": {
                                            "buslines": [
                                                {
                                                    "name": "11号线",
                                                    "departure_stop": {"name": "后海"},
                                                    "arrival_stop": {"name": "科苑"},
                                                }
                                            ]
                                        }
                                    },
                                    {"walking": {"duration": 60}},
                                ],
                            }
                        ],
                    }
                }
            raise AssertionError(f"unexpected url: {url}")

        results = build_live_provider_options(payload, config, fake_fetch_json)

        exact_split = next(item for item in results if item["template"] == "bike->subway->bike")
        self.assertEqual(exact_split["station_source"], "nearby_station_search")
        self.assertFalse(exact_split["used_alias_fallback"])
        self.assertEqual(exact_split["segments"][0]["to_name"], "后海站")
        self.assertEqual(exact_split["segments"][2]["from_name"], "科苑站")
        self.assertFalse(any("%E5%8C%97%E9%97%A8" in call or "%E8%A5%BF%E5%A1%94" in call for call in calls))

    def test_exact_bike_subway_bike_can_use_integrated_station_names_when_nearby_station_search_is_empty(self):
        payload = {
            "office": "字节跳动深圳湾工区",
            "home": "南山区示例花园",
        }
        config = ProviderConfig(
            mode="live",
            amap_key="amap-key",
            baidu_key="",
            qq_key="",
        )

        def fake_fetch_json(url):
            if "assistant/inputtips" in url:
                if "%E5%90%8E%E6%B5%B7%E7%AB%99" in url:
                    return {"status": "1", "tips": [{"name": "后海站", "location": "113.949,22.539", "adcode": "440305"}]}
                if "%E7%A7%91%E8%8B%91%E7%AB%99" in url:
                    return {"status": "1", "tips": [{"name": "科苑站", "location": "113.960,22.541", "adcode": "440305"}]}
                return {
                    "status": "1",
                    "tips": [
                        {
                            "id": "poi-1",
                            "name": "字节跳动深圳湾工区",
                            "district": "深圳市南山区",
                            "address": "科苑南路",
                            "location": "113.95,22.54",
                        }
                    ],
                }
            if "v5/place/around" in url:
                raise AssertionError(f"nearby station lookup should be skipped: {url}")
            if "restapi.amap.com/v5/direction/walking" in url:
                return {"route": {"paths": [{"cost": {"duration": 480}, "distance": 1100}]}}
            if "restapi.amap.com/v5/direction/bicycling" in url:
                if "origin=113.949000%2C22.539000" in url and "destination=113.950000%2C22.540000" in url:
                    return {"status": "1", "route": {"paths": [{"cost": {"duration": 180}, "distance": 700}]}}
                if "origin=113.960000%2C22.541000" in url and "destination=113.950000%2C22.540000" in url:
                    return {"status": "1", "route": {"paths": [{"cost": {"duration": 180}, "distance": 800}]}}
                return {"status": "1", "route": {"paths": [{"cost": {"duration": 1320}, "distance": 1800}]}}
            if "restapi.amap.com/v5/direction/transit/integrated" in url:
                return {
                    "route": {
                        "transits": [
                            {
                                "cost": {"duration": 720},
                                "distance": 5200,
                                "segments": [
                                    {"walking": {"duration": 120}},
                                    {
                                        "bus": {
                                            "buslines": [
                                                {
                                                    "name": "11号线",
                                                    "departure_stop": {"name": "后海"},
                                                    "arrival_stop": {"name": "科苑"},
                                                }
                                            ]
                                        }
                                    },
                                    {"walking": {"duration": 60}},
                                ],
                            }
                        ],
                    }
                }
            if "restapi.amap.com/v3/direction/transit/integrated" in url:
                return {
                    "status": "1",
                    "route": {
                        "transits": [
                            {
                                "duration": 720,
                                "distance": 5200,
                                "segments": [
                                    {
                                        "bus": {
                                            "buslines": [
                                                {
                                                    "name": "11号线",
                                                    "departure_stop": {"name": "后海"},
                                                    "arrival_stop": {"name": "科苑"},
                                                }
                                            ]
                                        }
                                    }
                                ],
                            }
                        ]
                    },
                }
            raise AssertionError(f"unexpected url: {url}")

        results = build_live_provider_options(payload, config, fake_fetch_json)

        exact_split = next(item for item in results if item["template"] == "bike->subway->bike")
        self.assertEqual(exact_split["station_source"], "integrated_station_match")
        self.assertEqual(exact_split["segments"][0]["to_name"], "后海站")
        self.assertEqual(exact_split["segments"][2]["from_name"], "科苑站")
        self.assertEqual(exact_split["segments"][1]["duration_min"], 9)

    def test_exact_compliant_bike_subway_bike_blocks_alias_fallback_even_if_integrated_is_over_limit(self):
        payload = {
            "office": "丽金智地中心",
            "home": "中海雅园",
        }
        config = ProviderConfig(
            mode="live",
            amap_key="amap-key",
            baidu_key="",
            qq_key="",
        )
        calls = []

        def fake_fetch_json(url):
            calls.append(url)
            if "assistant/inputtips" in url:
                if "keywords=%E4%B8%BD%E9%87%91%E6%99%BA%E5%9C%B0%E4%B8%AD%E5%BF%83" in url:
                    return {"status": "1", "tips": [{"name": "丽金智地中心", "location": "116.300,39.940", "adcode": "110108"}]}
                return {"status": "1", "tips": [{"name": "中海雅园", "location": "116.305,39.932", "adcode": "110108"}]}
            if "v5/place/around" in url:
                return {
                    "status": "1",
                    "pois": [
                        {"name": "慈寿寺站", "location": "116.317,39.926", "distance": "220"},
                        {"name": "魏公村站", "location": "116.322,39.953", "distance": "320"},
                    ],
                }
            if "v5/direction/walking" in url:
                return {"route": {"paths": [{"cost": {"duration": 1800}, "distance": 2600}]}}
            if "v5/direction/bicycling" in url:
                if "origin=116.305000%2C39.932000" in url and "destination=116.300000%2C39.940000" in url:
                    return {"status": "1", "route": {"paths": [{"cost": {"duration": 1500}, "distance": 4000}]}}
                if "origin=116.305000%2C39.932000" in url and "destination=116.317000%2C39.926000" in url:
                    return {"status": "1", "route": {"paths": [{"cost": {"duration": 180}, "distance": 800}]}}
                if "origin=116.322000%2C39.953000" in url and "destination=116.300000%2C39.940000" in url:
                    return {"status": "1", "route": {"paths": [{"cost": {"duration": 180}, "distance": 900}]}}
                return {"status": "1", "route": {"paths": [{"cost": {"duration": 960}, "distance": 2800}]}}
            if "v5/direction/transit/integrated" in url or "v3/direction/transit/integrated" in url:
                if "origin=116.317000%2C39.926000" in url and "destination=116.322000%2C39.953000" in url:
                    return {
                        "route": {
                            "transits": [
                                {
                                    "cost": {"duration": 600},
                                    "segments": [
                                        {
                                            "bus": {
                                                "buslines": [
                                                    {
                                                        "name": "10号线",
                                                        "departure_stop": {"name": "慈寿寺"},
                                                        "arrival_stop": {"name": "魏公村"},
                                                    }
                                                ]
                                            }
                                        }
                                    ],
                                }
                            ]
                        },
                        "status": "1",
                    }
                return {
                    "route": {
                        "transits": [
                            {
                                "cost": {"duration": 1320},
                                "segments": [
                                    {"walking": {"duration": 300}},
                                    {
                                        "bus": {
                                            "buslines": [
                                                {
                                                    "name": "10号线",
                                                    "departure_stop": {"name": "慈寿寺"},
                                                    "arrival_stop": {"name": "魏公村"},
                                                }
                                            ]
                                        }
                                    },
                                    {"walking": {"duration": 240}},
                                ],
                            }
                        ]
                    },
                    "status": "1",
                }
            raise AssertionError(f"unexpected url: {url}")

        results = build_live_provider_options(payload, config, fake_fetch_json)

        exact_split = next(item for item in results if item["template"] == "bike->subway->bike")
        self.assertEqual(sum(segment["duration_min"] for segment in exact_split["segments"]), 19)
        self.assertFalse(exact_split["used_alias_fallback"])
        self.assertFalse(any("%E5%8C%97%E9%97%A8" in call or "%E8%A5%BF%E5%A1%94" in call for call in calls))
        self.assertFalse(
            any(
                item["template"] == "subway"
                and not item["used_alias_fallback"]
                and item.get("route_source") == "stitched_station_combo"
                for item in results
            )
        )

    def test_expands_aliases_after_exact_bike_integrated_and_bike_subway_bike_are_all_over_limit(self):
        payload = {
            "office": "丽金智地中心",
            "home": "中海雅园",
        }
        config = ProviderConfig(
            mode="live",
            amap_key="amap-key",
            baidu_key="",
            qq_key="",
        )
        calls = []

        def fake_fetch_json(url):
            calls.append(url)
            if "assistant/inputtips" in url:
                if "%E4%B8%AD%E6%B5%B7%E9%9B%85%E5%9B%AD%E5%8C%97%E9%97%A8" in url:
                    return {"status": "1", "tips": [{"name": "中海雅园北门", "location": "116.306,39.933", "adcode": "110108"}]}
                if "keywords=%E4%B8%BD%E9%87%91%E6%99%BA%E5%9C%B0%E4%B8%AD%E5%BF%83%E8%A5%BF%E5%A1%94" in url:
                    return {"status": "1", "tips": [{"name": "丽金智地中心西塔", "location": "116.301,39.941", "adcode": "110108"}]}
                if "keywords=%E4%B8%BD%E9%87%91%E6%99%BA%E5%9C%B0%E4%B8%AD%E5%BF%83" in url:
                    return {"status": "1", "tips": [{"name": "丽金智地中心", "location": "116.300,39.940", "adcode": "110108"}]}
                return {"status": "1", "tips": [{"name": "中海雅园", "location": "116.305,39.932", "adcode": "110108"}]}
            if "v5/place/around" in url:
                if "location=116.305000%2C39.932000" in url or "location=116.306000%2C39.933000" in url:
                    return {
                        "status": "1",
                        "pois": [
                            {"name": "慈寿寺站", "location": "116.317,39.926", "distance": "220"},
                        ],
                    }
                return {
                    "status": "1",
                    "pois": [
                        {"name": "魏公村站", "location": "116.322,39.953", "distance": "320"},
                    ],
                }
            if "v5/direction/walking" in url:
                return {"route": {"paths": [{"cost": {"duration": 1800}, "distance": 2600}]}}
            if "v5/direction/bicycling" in url:
                if "origin=116.305000%2C39.932000" in url and "destination=116.300000%2C39.940000" in url:
                    return {"status": "1", "route": {"paths": [{"cost": {"duration": 1500}, "distance": 4000}]}}
                if "origin=116.305000%2C39.932000" in url and "destination=116.317000%2C39.926000" in url:
                    return {"status": "1", "route": {"paths": [{"cost": {"duration": 300}, "distance": 1000}]}}
                if "origin=116.322000%2C39.953000" in url and "destination=116.300000%2C39.940000" in url:
                    return {"status": "1", "route": {"paths": [{"cost": {"duration": 360}, "distance": 1100}]}}
                if "origin=116.306000%2C39.933000" in url and "destination=116.317000%2C39.926000" in url:
                    return {"status": "1", "route": {"paths": [{"cost": {"duration": 180}, "distance": 700}]}}
                if "origin=116.322000%2C39.953000" in url and "destination=116.301000%2C39.941000" in url:
                    return {"status": "1", "route": {"paths": [{"cost": {"duration": 180}, "distance": 800}]}}
                return {"status": "1", "route": {"paths": [{"cost": {"duration": 960}, "distance": 2800}]}}
            if "v5/direction/transit/integrated" in url or "v3/direction/transit/integrated" in url:
                if "origin=116.317000%2C39.926000" in url and "destination=116.322000%2C39.953000" in url:
                    return {
                        "route": {
                            "transits": [
                                {
                                    "cost": {"duration": 720},
                                    "segments": [
                                        {
                                            "bus": {
                                                "buslines": [
                                                    {
                                                        "name": "10号线",
                                                        "departure_stop": {"name": "慈寿寺"},
                                                        "arrival_stop": {"name": "魏公村"},
                                                    }
                                                ]
                                            }
                                        }
                                    ],
                                }
                            ]
                        },
                        "status": "1",
                    }
                return {
                    "route": {
                        "transits": [
                            {
                                "cost": {"duration": 1320},
                                "segments": [
                                    {"walking": {"duration": 60}},
                                    {
                                        "bus": {
                                            "buslines": [
                                                {
                                                    "name": "10号线",
                                                    "departure_stop": {"name": "慈寿寺"},
                                                    "arrival_stop": {"name": "魏公村"},
                                                }
                                            ]
                                        }
                                    },
                                    {"walking": {"duration": 60}},
                                ],
                            }
                        ]
                    },
                    "status": "1",
                }
            raise AssertionError(f"unexpected url: {url}")

        results = build_live_provider_options(payload, config, fake_fetch_json)

        alias_results = [item for item in results if item["used_alias_fallback"]]
        self.assertTrue(alias_results)
        self.assertTrue(any("%E5%8C%97%E9%97%A8" in call for call in calls))
        self.assertTrue(any("%E8%A5%BF%E5%A1%94" in call for call in calls))
        best_bike = next(item for item in results if item["template"] == "bike")
        self.assertTrue(best_bike["used_alias_fallback"])
        self.assertIn(best_bike["segments"][0]["from_name"], {"中海雅园", "中海雅园北门"})
        self.assertIn(best_bike["segments"][0]["to_name"], {"丽金智地中心", "丽金智地中心西塔"})
        self.assertEqual(best_bike["segments"][0]["duration_min"], 16)

    def test_alias_bike_compliance_skips_extra_integrated_call_for_that_alias_pair(self):
        payload = {
            "office": "丽金智地中心",
            "home": "中海雅园",
        }
        config = ProviderConfig(
            mode="live",
            amap_key="amap-key",
            baidu_key="",
            qq_key="",
        )
        calls = []

        def fake_fetch_json(url):
            calls.append(url)
            if "assistant/inputtips" in url:
                if "%E4%B8%AD%E6%B5%B7%E9%9B%85%E5%9B%AD%E5%8C%97%E9%97%A8" in url:
                    return {"status": "1", "tips": [{"name": "中海雅园北门", "location": "116.306,39.933", "adcode": "110108"}]}
                if "keywords=%E4%B8%BD%E9%87%91%E6%99%BA%E5%9C%B0%E4%B8%AD%E5%BF%83%E8%A5%BF%E5%A1%94" in url:
                    return {"status": "1", "tips": [{"name": "丽金智地中心西塔", "location": "116.301,39.941", "adcode": "110108"}]}
                if "keywords=%E4%B8%BD%E9%87%91%E6%99%BA%E5%9C%B0%E4%B8%AD%E5%BF%83" in url:
                    return {"status": "1", "tips": [{"name": "丽金智地中心", "location": "116.300,39.940", "adcode": "110108"}]}
                return {"status": "1", "tips": [{"name": "中海雅园", "location": "116.305,39.932", "adcode": "110108"}]}
            if "v5/place/around" in url:
                return {"status": "1", "pois": []}
            if "v5/direction/walking" in url:
                return {"route": {"paths": [{"cost": {"duration": 1800}, "distance": 2600}]}}
            if "v5/direction/bicycling" in url:
                if "origin=116.305000%2C39.932000" in url and "destination=116.300000%2C39.940000" in url:
                    return {"status": "1", "route": {"paths": [{"cost": {"duration": 1500}, "distance": 4000}]}}
                if "origin=116.305000%2C39.932000" in url and "destination=116.317000%2C39.926000" in url:
                    return {"status": "1", "route": {"paths": [{"cost": {"duration": 300}, "distance": 1000}]}}
                if "origin=116.322000%2C39.953000" in url and "destination=116.300000%2C39.940000" in url:
                    return {"status": "1", "route": {"paths": [{"cost": {"duration": 360}, "distance": 1100}]}}
                if "origin=116.306000%2C39.933000" in url and "destination=116.301000%2C39.941000" in url:
                    return {"status": "1", "route": {"paths": [{"cost": {"duration": 1140}, "distance": 800}]}}
                if "origin=116.306000%2C39.933000" in url and "destination=116.300000%2C39.940000" in url:
                    return {"status": "1", "route": {"paths": [{"cost": {"duration": 1260}, "distance": 1000}]}}
                if "origin=116.322000%2C39.953000" in url and "destination=116.301000%2C39.941000" in url:
                    return {"status": "1", "route": {"paths": [{"cost": {"duration": 1260}, "distance": 1100}]}}
                return {"status": "1", "route": {"paths": [{"cost": {"duration": 960}, "distance": 2800}]}}
            if "v5/direction/transit/integrated" in url:
                return {
                    "route": {
                        "transits": [
                            {
                                "cost": {"duration": 1320},
                                "segments": [
                                    {"walking": {"duration": 60}},
                                    {
                                        "bus": {
                                            "buslines": [
                                                {
                                                    "name": "11号线",
                                                    "departure_stop": {"name": "后海"},
                                                    "arrival_stop": {"name": "科苑"},
                                                }
                                            ]
                                        }
                                    },
                                    {"walking": {"duration": 60}},
                                ],
                            }
                        ]
                    }
                }
            raise AssertionError(f"unexpected url: {url}")

        build_live_provider_options(payload, config, fake_fetch_json)

        self.assertFalse(
            any(
                "origin=116.306000%2C39.933000" in call
                and "destination=116.301000%2C39.941000" in call
                and "transit/integrated" in call
                for call in calls
            )
        )

    def test_live_results_do_not_include_direct_or_partial_subway_templates(self):
        payload = {
            "office": "字节跳动深圳湾工区",
            "home": "南山区示例花园",
        }
        config = ProviderConfig(
            mode="live",
            amap_key="amap-key",
            baidu_key="",
            qq_key="",
        )

        def fake_fetch_json(url):
            if "assistant/inputtips" in url:
                return {
                    "status": "1",
                    "tips": [{"name": "地点", "location": "113.95,22.54"}],
                }
            if "v5/place/around" in url:
                return {
                    "status": "1",
                    "pois": [
                        {"name": "后海站", "location": "113.949,22.539", "distance": "180"},
                    ],
                }
            if "transit/integrated" in url:
                return {
                    "route": {
                        "transits": [
                            {
                                "cost": {"duration": 600},
                                "segments": [
                                    {"walking": {"duration": 120}},
                                    {
                                        "bus": {
                                            "buslines": [
                                                {
                                                    "name": "11号线",
                                                    "departure_stop": {"name": "后海"},
                                                    "arrival_stop": {"name": "科苑"},
                                                }
                                            ]
                                        }
                                    },
                                    {"walking": {"duration": 60}},
                                ],
                            }
                        ]
                    }
                }
            if "bicycling" in url:
                return {"errcode": 0, "data": {"paths": [{"duration": 1260, "distance": 1000}]}}
            if "walking" in url:
                return {"route": {"paths": [{"cost": {"duration": 300}, "distance": 500}]}}
            raise AssertionError(f"unexpected url: {url}")

        results = build_live_provider_options(payload, config, fake_fetch_json)
        templates = {item["template"] for item in results}

        self.assertIn("subway", templates)
        self.assertNotIn("walk->subway", templates)
        self.assertNotIn("bike->subway", templates)
        self.assertNotIn("walk->subway->walk", templates)

    def test_live_results_expose_integrated_transit_as_subway_template(self):
        payload = {
            "office": "丽金智地中心西塔",
            "home": "中海雅园",
        }
        config = ProviderConfig(
            mode="live",
            amap_key="amap-key",
            baidu_key="",
            qq_key="",
        )

        def fake_fetch_json(url):
            if "assistant/inputtips" in url:
                return {
                    "status": "1",
                    "tips": [{"name": "地点", "location": "116.31,39.93", "adcode": "110108"}],
                }
            if "v5/place/around" in url:
                return {
                    "status": "1",
                    "pois": [
                        {"name": "慈寿寺站", "location": "116.316,39.947", "distance": "260"},
                        {"name": "魏公村站", "location": "116.322,39.953", "distance": "320"},
                    ],
                }
            if "v5/direction/bicycling" in url:
                return {"status": "1", "route": {"paths": [{"cost": {"duration": 1320}, "distance": 1800}]}}
            if "v5/direction/transit/integrated" in url:
                return {
                    "route": {
                        "transits": [
                            {
                                "cost": {"duration": 1200},
                                "distance": 5200,
                                "segments": [
                                    {
                                        "walking": {"duration": 180},
                                        "bus": {
                                            "buslines": [
                                                {
                                                    "name": "10号线",
                                                    "departure_stop": {"name": "慈寿寺"},
                                                    "arrival_stop": {"name": "魏公村"},
                                                }
                                            ]
                                        },
                                    },
                                    {"walking": {"duration": 120}},
                                ],
                            }
                        ]
                    }
                }
            raise AssertionError(f"unexpected url: {url}")

        results = build_live_provider_options(payload, config, fake_fetch_json)
        templates = {item["template"] for item in results}

        self.assertIn("subway", templates)
        self.assertNotIn("walk->subway->walk", templates)

    def test_provider_failure_does_not_block_other_live_results(self):
        payload = {
            "office": "字节跳动深圳湾工区",
            "home": "南山区示例花园",
        }
        config = ProviderConfig(
            mode="live",
            amap_key="amap-key",
            baidu_key="",
            qq_key="qq-key",
        )

        def fake_fetch_json(url):
            if "assistant/inputtips" in url:
                return {
                    "status": "1",
                    "tips": [{"name": "字节跳动深圳湾工区", "location": "113.95,22.54"}],
                }
            if "v5/place/around" in url:
                return {"status": "1", "pois": []}
            if "restapi.amap.com/v5/direction/transit/integrated" in url:
                return {"route": {"transits": [{"cost": {"duration": 700}, "distance": 5000}]}}
            if "restapi.amap.com/v5/direction/bicycling" in url:
                return {
                    "errcode": 0,
                    "data": {"paths": [{"duration": 480, "distance": 1600}]},
                }
            if "restapi.amap.com/v5/direction/" in url:
                return {"route": {"paths": [{"cost": {"duration": 600}, "distance": 1000}]}}
            raise AssertionError(f"unexpected url: {url}")

        results = build_live_provider_options(payload, config, fake_fetch_json)

        self.assertGreater(len(results), 0)
        self.assertEqual({item["provider"] for item in results}, {"amap"})

    def test_bike_route_failure_does_not_block_subway_and_mixed_plans(self):
        payload = {
            "office": "丽金智地中心西塔",
            "home": "中海雅园",
        }
        config = ProviderConfig(
            mode="live",
            amap_key="amap-key",
            baidu_key="",
            qq_key="",
        )

        def fake_fetch_json(url):
            if "assistant/inputtips" in url:
                if "%E4%B8%BD%E9%87%91%E6%99%BA%E5%9C%B0%E4%B8%AD%E5%BF%83%E8%A5%BF%E5%A1%94" in url:
                    return {"status": "1", "tips": [{"name": "丽金智地中心西塔", "location": "116.300,39.940"}]}
                return {"status": "1", "tips": [{"name": "中海雅园", "location": "116.305,39.932"}]}
            if "v5/place/around" in url:
                return {
                    "status": "1",
                    "pois": [
                        {"name": "海淀黄庄站", "location": "116.317,39.976", "distance": "220"},
                        {"name": "知春里站", "location": "116.329,39.982", "distance": "540"},
                    ],
                }
            if "v5/direction/bicycling" in url:
                return {"errcode": 30000}
            if "v5/direction/transit/integrated" in url:
                return {
                    "route": {
                        "transits": [
                            {
                                "cost": {"duration": 900},
                                "distance": 4800,
                                "segments": [
                                    {
                                        "bus": {
                                            "buslines": [
                                                {
                                                    "name": "10号线",
                                                    "departure_stop": {"name": "海淀黄庄"},
                                                    "arrival_stop": {"name": "知春里"},
                                                }
                                            ]
                                        }
                                    }
                                ],
                            }
                        ]
                    }
                }
            if "v5/direction/walking" in url:
                return {"route": {"paths": [{"cost": {"duration": 420}, "distance": 900}]}}
            raise AssertionError(f"unexpected url: {url}")

        payload = load_provider_payload(payload, config=config, fetch_json=fake_fetch_json)
        templates = {item["template"] for item in payload["options"]}

        self.assertIn("subway", templates)
        self.assertNotIn("bike", templates)
        self.assertTrue(any("bicycling failed" in item["message"] for item in payload["provider_errors"]))

    def test_live_search_limits_upstream_request_count(self):
        payload = {
            "office": "字节跳动深圳湾工区",
            "home": "南山区示例花园",
        }
        config = ProviderConfig(
            mode="live",
            amap_key="amap-key",
            baidu_key="",
            qq_key="",
        )
        calls = []

        def fake_fetch_json(url):
            calls.append(url)
            if "assistant/inputtips" in url:
                return {"status": "1", "tips": [{"name": "字节跳动深圳湾工区", "location": "113.95,22.54"}]}
            if "v5/place/around" in url:
                return {
                    "status": "1",
                    "pois": [
                        {"name": "后海站", "location": "113.949,22.539", "distance": "180"},
                        {"name": "科苑站", "location": "113.960,22.541", "distance": "320"},
                    ],
                }
            if "restapi.amap.com/v5/direction/transit/integrated" in url:
                return {
                    "route": {
                        "transits": [
                            {
                                "cost": {"duration": 700},
                                "distance": 5000,
                                "segments": [
                                    {
                                        "bus": {
                                            "buslines": [
                                                {
                                                    "name": "11号线",
                                                    "departure_stop": {"name": "后海"},
                                                    "arrival_stop": {"name": "科苑"},
                                                }
                                            ]
                                        }
                                    }
                                ],
                            }
                        ]
                    }
                }
            if "restapi.amap.com/v5/direction/bicycling" in url:
                return {"errcode": 0, "data": {"paths": [{"duration": 480, "distance": 1600}]}}
            if "restapi.amap.com/v5/direction/" in url:
                return {"route": {"paths": [{"cost": {"duration": 600}, "distance": 1000}]}}
            raise AssertionError(f"unexpected url: {url}")

        results = build_live_provider_options(payload, config, fake_fetch_json)

        self.assertGreater(len(results), 0)
        self.assertLessEqual(len(calls), 12)

    def test_exact_split_reuses_integrated_transit_snapshot_without_second_station_to_station_transit_call(self):
        payload = {
            "office": "字节跳动深圳湾工区",
            "home": "南山区示例花园",
        }
        config = ProviderConfig(
            mode="live",
            amap_key="amap-key",
            baidu_key="",
            qq_key="",
        )
        calls = []

        def fake_fetch_json(url):
            calls.append(url)
            if "assistant/inputtips" in url:
                if "%E5%90%8E%E6%B5%B7%E7%AB%99" in url:
                    return {"status": "1", "tips": [{"name": "后海站", "location": "113.949,22.539", "adcode": "440305"}]}
                if "%E7%A7%91%E8%8B%91%E7%AB%99" in url:
                    return {"status": "1", "tips": [{"name": "科苑站", "location": "113.960,22.541", "adcode": "440305"}]}
                return {
                    "status": "1",
                    "tips": [{"name": "地点", "location": "113.950,22.540", "adcode": "440305"}],
                }
            if "v5/direction/bicycling" in url:
                if "origin=113.949000%2C22.539000" in url and "destination=113.950000%2C22.540000" in url:
                    return {"status": "1", "route": {"paths": [{"cost": {"duration": 180}, "distance": 700}]}}
                if "origin=113.960000%2C22.541000" in url and "destination=113.950000%2C22.540000" in url:
                    return {"status": "1", "route": {"paths": [{"cost": {"duration": 180}, "distance": 800}]}}
                return {"status": "1", "route": {"paths": [{"cost": {"duration": 1320}, "distance": 1800}]}}
            if "v5/direction/transit/integrated" in url:
                return {
                    "route": {
                        "transits": [
                            {
                                "cost": {"duration": 720},
                                "distance": 5200,
                                "segments": [
                                    {"walking": {"duration": 120}},
                                    {
                                        "bus": {
                                            "buslines": [
                                                {
                                                    "name": "11号线",
                                                    "departure_stop": {"name": "后海"},
                                                    "arrival_stop": {"name": "科苑"},
                                                }
                                            ]
                                        }
                                    },
                                    {"walking": {"duration": 60}},
                                ],
                            }
                        ],
                    }
                }
            raise AssertionError(f"unexpected url: {url}")

        results = build_live_provider_options(payload, config, fake_fetch_json)

        exact_split = next(item for item in results if item["template"] == "bike->subway->bike")
        integrated_calls = [call for call in calls if "v5/direction/transit/integrated" in call]

        self.assertEqual(len(integrated_calls), 1)
        self.assertEqual(exact_split["segments"][1]["duration_min"], 9)

    def test_blank_station_input_in_live_mode_does_not_use_default_station_pool(self):
        payload = {
            "office": "字节跳动深圳湾工区",
            "home": "南山区示例花园",
        }
        config = ProviderConfig(
            mode="live",
            amap_key="amap-key",
            baidu_key="",
            qq_key="",
        )

        def fake_fetch_json(url):
            if "assistant/inputtips" in url:
                self.assertNotIn("%E5%90%8E%E6%B5%B7%E7%AB%99", url)
                self.assertNotIn("%E7%A7%91%E8%8B%91%E7%AB%99", url)
                self.assertNotIn("%E9%AB%98%E6%96%B0%E5%9B%AD%E7%AB%99", url)
                return {"status": "1", "tips": [{"name": "字节跳动深圳湾工区", "location": "113.95,22.54"}]}
            if "v5/place/around" in url:
                return {"status": "1", "pois": []}
            if "restapi.amap.com/v5/direction/transit/integrated" in url:
                return {"route": {"transits": [{"cost": {"duration": 700}, "distance": 5000}]}}
            if "restapi.amap.com/v5/direction/bicycling" in url:
                return {"errcode": 0, "data": {"paths": [{"duration": 480, "distance": 1600}]}}
            if "restapi.amap.com/v5/direction/" in url:
                return {"route": {"paths": [{"cost": {"duration": 600}, "distance": 1000}]}}
            raise AssertionError(f"unexpected url: {url}")

        results = build_live_provider_options(payload, config, fake_fetch_json)

        self.assertTrue(results)
        self.assertTrue(all(item["template"] in {"walk", "bike", "subway"} for item in results))

    def test_live_mode_without_real_results_does_not_fallback_to_mock(self):
        config = ProviderConfig(
            mode="live",
            amap_key="amap-key",
            baidu_key="",
            qq_key="",
        )

        def fake_fetch_json(url):
            raise RuntimeError(f"upstream unavailable: {url}")

        payload = load_provider_payload(
            {"office": "字节跳动深圳湾工区", "home": "南山区示例花园"},
            config=config,
            fetch_json=fake_fetch_json,
        )

        self.assertEqual(payload["data_source"], "live")
        self.assertEqual(payload["options"], [])
        self.assertTrue(payload["live_failed"])
        self.assertTrue(payload["warnings"])
        self.assertTrue(payload["provider_errors"])
        self.assertEqual(payload["provider_errors"][0]["provider"], "amap")

    def test_amap_subway_route_extracts_station_pair(self):
        def fake_fetch_json(url):
            self.assertIn("transit/integrated", url)
            self.assertIn("show_fields=cost", url)
            self.assertIn("AlternativeRoute=5", url)
            return {
                "route": {
                    "transits": [
                        {
                            "cost": {"duration": 900},
                            "distance": 6600,
                            "segments": [
                                {
                                    "walking": {"distance": 400},
                                    "bus": {
                                        "buslines": [
                                            {
                                                "name": "2号线",
                                                "departure_stop": {"name": "红树湾"},
                                                "arrival_stop": {"name": "世界之窗"},
                                            }
                                        ]
                                    },
                                }
                            ],
                        },
                        {
                            "cost": {"duration": 780},
                            "distance": 5600,
                            "segments": [
                                {
                                    "walking": {"distance": 220},
                                    "bus": {
                                        "buslines": [
                                            {
                                                "name": "11号线",
                                                "departure_stop": {"name": "后海"},
                                                "arrival_stop": {"name": "科苑"},
                                            }
                                        ]
                                    },
                                }
                            ],
                        }
                    ]
                }
            }

        route = _amap_route(
            "subway",
            {"lat": 22.54, "lng": 113.95, "citycode": "0755"},
            {"lat": 22.55, "lng": 113.96, "citycode": "0755"},
            "amap-key",
            fake_fetch_json,
        )

        self.assertEqual(route["duration_min"], 13)
        self.assertEqual(route["transit_entry_name"], "后海站")
        self.assertEqual(route["transit_exit_name"], "科苑站")

    def test_amap_subway_route_ignores_bus_only_transit_plans(self):
        def fake_fetch_json(url):
            self.assertIn("transit/integrated", url)
            return {
                "route": {
                    "transits": [
                        {
                            "cost": {"duration": 600},
                            "distance": 4300,
                            "segments": [
                                {
                                    "walking": {"duration": 60},
                                    "bus": {
                                        "buslines": [
                                            {
                                                "name": "特4路",
                                                "departure_stop": {"name": "紫竹桥南"},
                                                "arrival_stop": {"name": "魏公村路"},
                                            }
                                        ]
                                    },
                                }
                            ],
                        },
                        {
                            "cost": {"duration": 1200},
                            "distance": 5200,
                            "segments": [
                                {
                                    "walking": {"duration": 180},
                                    "bus": {
                                        "buslines": [
                                            {
                                                "name": "10号线",
                                                "departure_stop": {"name": "慈寿寺"},
                                                "arrival_stop": {"name": "魏公村"},
                                            }
                                        ]
                                    },
                                }
                            ],
                        },
                    ]
                }
            }

        route = _amap_route(
            "subway",
            {"lat": 39.927007, "lng": 116.31594, "citycode": "110000"},
            {"lat": 39.957483, "lng": 116.3157, "citycode": "110000"},
            "amap-key",
            fake_fetch_json,
        )

        self.assertEqual(route["duration_min"], 20)
        self.assertEqual(route["transit_entry_name"], "慈寿寺站")
        self.assertEqual(route["transit_exit_name"], "魏公村站")
        self.assertEqual(route["transit_line_name"], "10号线")

    def test_amap_subway_route_supports_v3_segment_object_shape(self):
        def fake_fetch_json(url):
            self.assertIn("v3/direction/transit/integrated", url)
            return {
                "status": "1",
                "route": {
                    "transits": [
                        {
                            "duration": "780",
                            "distance": "5600",
                            "segments": {
                                "bus": {
                                    "buslines": [
                                        {
                                            "name": "11号线",
                                            "departure_stop": {"name": "后海"},
                                            "arrival_stop": {"name": "科苑"},
                                        }
                                    ]
                                }
                            },
                        }
                    ]
                },
            }

        route = _amap_route(
            "subway",
            {"lat": 22.54, "lng": 113.95, "citycode": "0755"},
            {"lat": 22.55, "lng": 113.96, "citycode": "0755"},
            "amap-key",
            fake_fetch_json,
            route_options={"transit_profile": {"date": "2026-08-03", "time": "08:30"}},
        )

        self.assertEqual(route["duration_min"], 13)
        self.assertEqual(route["transit_entry_name"], "后海站")
        self.assertEqual(route["transit_exit_name"], "科苑站")
        self.assertEqual(route["transit_line_name"], "11号线")

    def test_amap_subway_route_supports_v3_string_cost_shape(self):
        def fake_fetch_json(url):
            self.assertIn("v3/direction/transit/integrated", url)
            return {
                "status": "1",
                "route": {
                    "transits": [
                        {
                            "cost": "2.0",
                            "duration": "2276",
                            "distance": "4972",
                            "segments": [
                                {
                                    "walking": {"duration": "684"},
                                    "bus": {
                                        "buslines": [
                                            {
                                                "name": "2号线",
                                                "departure_stop": {"name": "慈寿寺"},
                                                "arrival_stop": {"name": "魏公村"},
                                            }
                                        ]
                                    },
                                }
                            ],
                        }
                    ]
                },
            }

        route = _amap_route(
            "subway",
            {"lat": 39.927007, "lng": 116.31594, "citycode": "110000"},
            {"lat": 39.957483, "lng": 116.3157, "citycode": "110000"},
            "amap-key",
            fake_fetch_json,
            route_options={"transit_profile": {"date": "2026-08-03", "time": "08:30"}},
        )

        self.assertEqual(route["duration_min"], 38)
        self.assertEqual(route["transit_entry_name"], "慈寿寺站")
        self.assertEqual(route["transit_exit_name"], "魏公村站")
        self.assertEqual(route["transit_line_name"], "2号线")

    def test_amap_bike_route_supports_v5_route_paths_shape(self):
        def fake_fetch_json(url):
            self.assertIn("direction/bicycling", url)
            self.assertIn("show_fields=cost", url)
            self.assertIn("alternative_route=3", url)
            return {
                "status": "1",
                "info": "OK",
                "infocode": "10000",
                "route": {
                    "paths": [
                        {
                            "distance": "2500",
                            "cost": {"duration": "600"},
                        },
                        {
                            "distance": "1800",
                            "cost": {"duration": "420"},
                        }
                    ]
                },
            }

        route = _amap_route(
            "bike",
            {"lat": 22.54, "lng": 113.95, "citycode": "0755"},
            {"lat": 22.55, "lng": 113.96, "citycode": "0755"},
            "amap-key",
            fake_fetch_json,
        )

        self.assertEqual(route["duration_min"], 7)
        self.assertEqual(route["distance_m"], 1800)

    def test_transit_and_mixed_route_errors_are_deduplicated(self):
        payload = {
            "office": "丽金智地中心西塔",
            "home": "中海雅园",
        }
        config = ProviderConfig(
            mode="live",
            amap_key="amap-key",
            baidu_key="",
            qq_key="",
        )

        def fake_fetch_json(url):
            if "assistant/inputtips" in url:
                if "%E4%B8%BD%E9%87%91%E6%99%BA%E5%9C%B0%E4%B8%AD%E5%BF%83%E8%A5%BF%E5%A1%94" in url:
                    return {"status": "1", "tips": [{"name": "丽金智地中心西塔", "location": "116.300,39.940"}]}
                return {"status": "1", "tips": [{"name": "中海雅园", "location": "116.305,39.932"}]}
            if "v5/place/around" in url:
                return {
                    "status": "1",
                    "pois": [
                        {"name": "海淀黄庄站", "location": "116.317,39.976", "distance": "220"},
                        {"name": "知春里站", "location": "116.329,39.982", "distance": "540"},
                    ],
                }
            if "v5/direction/bicycling" in url:
                return {"errcode": 30000}
            if "v5/direction/transit/integrated" in url:
                return {"route": {"transits": [{"distance": 4800}]}}
            if "v5/direction/walking" in url:
                return {"route": {"paths": [{"cost": {"duration": 420}, "distance": 900}]}}
            raise AssertionError(f"unexpected url: {url}")

        result = load_provider_payload(payload, config=config, fetch_json=fake_fetch_json)
        error_messages = [item["message"] for item in result["provider_errors"]]

        self.assertEqual(len(error_messages), len(set(error_messages)))

    def test_amap_route_error_preserves_upstream_error_fields(self):
        def fake_fetch_json(url):
            return {
                "status": "0",
                "info": "USER_DAILY_OVER_LIMIT",
                "infocode": "10021",
                "errmsg": "daily quota exceeded",
            }

        with self.assertRaisesRegex(
            ValueError,
            r"errmsg=daily quota exceeded.*info=USER_DAILY_OVER_LIMIT.*infocode=10021.*status=0",
        ):
            _amap_route(
                "walk",
                {"lat": 22.54, "lng": 113.95, "citycode": "0755"},
                {"lat": 22.55, "lng": 113.96, "citycode": "0755"},
                "amap-key",
                fake_fetch_json,
            )

    def test_mixed_route_failures_are_reported_by_mode_once(self):
        payload = {
            "office": "丽金智地中心西塔",
            "home": "中海雅园",
        }
        config = ProviderConfig(
            mode="live",
            amap_key="amap-key",
            baidu_key="",
            qq_key="",
        )

        def fake_fetch_json(url):
            if "assistant/inputtips" in url:
                return {"status": "1", "tips": [{"name": "地点", "location": "116.300,39.940"}]}
            if "v5/place/around" in url:
                return {
                    "status": "1",
                    "pois": [{"name": "海淀黄庄站", "location": "116.317,39.976", "distance": "220"}],
                }
            if "bicycling" in url:
                return {"errcode": 30000, "errmsg": "bicycling unsupported"}
            if "transit/integrated" in url:
                return {"route": {"transits": [{"distance": 4800}]}}
            if "walking" in url:
                return {"route": {"paths": [{"cost": {"duration": 420}, "distance": 900}]}}
            raise AssertionError(f"unexpected url: {url}")

        result = load_provider_payload(payload, config=config, fetch_json=fake_fetch_json)
        error_messages = [item["message"] for item in result["provider_errors"]]

        self.assertEqual(sum("bike" in message for message in error_messages), 1)
        self.assertEqual(sum("subway" in message for message in error_messages), 1)
        self.assertTrue(all("->" not in message for message in error_messages))
        self.assertTrue(any("bicycling unsupported" in message for message in error_messages))

    def test_live_results_attach_station_pair_to_subway_segments(self):
        payload = {
            "office": "字节跳动深圳湾工区",
            "home": "南山区示例花园",
        }
        config = ProviderConfig(
            mode="live",
            amap_key="amap-key",
            baidu_key="",
            qq_key="",
        )

        def fake_fetch_json(url):
            if "assistant/inputtips" in url:
                return {"status": "1", "tips": [{"name": "字节跳动深圳湾工区", "location": "113.95,22.54"}]}
            if "v5/place/around" in url:
                return {
                    "status": "1",
                    "pois": [
                        {"name": "后海站", "location": "113.949,22.539", "distance": "180"},
                        {"name": "科苑站", "location": "113.960,22.541", "distance": "320"},
                    ],
                }
            if "restapi.amap.com/v5/direction/transit/integrated" in url:
                return {
                    "route": {
                        "transits": [
                            {
                                "cost": {"duration": 720},
                                "distance": 5200,
                                "segments": [
                                    {"walking": {"duration": 120}},
                                    {
                                        "bus": {
                                            "buslines": [
                                                {
                                                    "name": "11号线",
                                                    "departure_stop": {"name": "后海"},
                                                    "arrival_stop": {"name": "科苑"},
                                                }
                                            ]
                                        }
                                    },
                                    {"walking": {"duration": 60}},
                                ],
                            }
                        ]
                    }
                }
            if "restapi.amap.com/v5/direction/bicycling" in url:
                return {
                    "errcode": 0,
                    "data": {
                        "paths": [{"duration": 1320, "distance": 1800}],
                    },
                }
            if "restapi.amap.com/v5/direction/walking" in url:
                return {
                    "route": {
                        "paths": [{"cost": {"duration": 480}, "distance": 1100}],
                    }
                }
            raise AssertionError(f"unexpected url: {url}")

        results = build_live_provider_options(payload, config, fake_fetch_json)
        subway_segments = [
            segment
            for item in results
            for segment in item["segments"]
            if segment["mode"] == "subway"
        ]

        self.assertTrue(subway_segments)
        self.assertTrue(
            any(
                segment.get("transit_entry_name") == "后海站"
                and segment.get("transit_exit_name") == "科苑站"
                for segment in subway_segments
            )
        )

    def test_mixed_plan_uses_single_realtime_snapshot_and_static_time_comparisons(self):
        payload = {
            "office": "字节跳动深圳湾工区",
            "home": "南山区示例花园",
        }
        config = ProviderConfig(
            mode="live",
            amap_key="amap-key",
            baidu_key="",
            qq_key="",
        )
        transit_profiles = [
            {"id": "weekday_morning", "label": "工作日早高峰", "date": "2026-08-03", "time": "08:30"},
            {"id": "weekday_midday", "label": "工作日平峰", "date": "2026-08-03", "time": "11:00"},
            {"id": "weekend_daytime", "label": "周末白天", "date": "2026-08-08", "time": "10:00"},
        ]

        def fake_fetch_json(url):
            if "assistant/inputtips" in url:
                return {"status": "1", "tips": [{"name": "地点", "location": "113.95,22.54", "adcode": "440305"}]}
            if "v5/place/around" in url:
                return {
                    "status": "1",
                    "pois": [
                        {"name": "后海站", "location": "113.949,22.539", "distance": "180"},
                        {"name": "科苑站", "location": "113.960,22.541", "distance": "320"},
                    ],
                }
            if "v5/direction/bicycling" in url:
                return {"status": "1", "route": {"paths": [{"cost": {"duration": 1260}, "distance": 1200}]}}
            if "v5/direction/walking" in url:
                return {"route": {"paths": [{"cost": {"duration": 240}, "distance": 600}]}}
            if "v5/direction/transit/integrated" in url:
                return {
                    "route": {
                        "transits": [
                            {
                                "cost": {"duration": 900},
                                "distance": 5200,
                                "segments": [
                                    {"walking": {"duration": 180}},
                                    {
                                        "bus": {
                                            "buslines": [
                                                {
                                                    "name": "11号线",
                                                    "departure_stop": {"name": "后海"},
                                                    "arrival_stop": {"name": "科苑"},
                                                }
                                            ]
                                        }
                                    },
                                    {"walking": {"duration": 60}},
                                ],
                            }
                        ]
                    },
                }
            raise AssertionError(f"unexpected url: {url}")

        results = build_live_provider_options(payload, config, fake_fetch_json, transit_profiles=transit_profiles)
        mixed_plan = next(item for item in results if item["template"] == "subway")

        self.assertEqual(mixed_plan["total_duration_min"] if "total_duration_min" in mixed_plan else None, None)
        self.assertEqual(mixed_plan["timing_recommendation"]["label"], "工作日早高峰")
        self.assertEqual(mixed_plan["timing_recommendation"]["time"], "08:30")
        self.assertEqual(mixed_plan["segments"][0]["duration_min"], 3)
        self.assertEqual(mixed_plan["segments"][1]["duration_min"], 11)
        self.assertEqual(mixed_plan["segments"][2]["duration_min"], 1)
        self.assertEqual(len(mixed_plan["time_comparisons"]), 3)
        self.assertEqual(
            [item["label"] for item in mixed_plan["time_comparisons"]],
            ["工作日早高峰", "工作日平峰", "周末白天"],
        )
        self.assertEqual(
            [item["total_duration_min"] for item in mixed_plan["time_comparisons"]],
            [15, 15, 15],
        )
        self.assertTrue(
            all("实时路线快照" in (item.get("note") or "") for item in mixed_plan["time_comparisons"])
        )

    def test_direct_bike_plan_exposes_time_comparisons_and_skips_walk_when_bike_compliant(self):
        payload = {
            "office": "字节跳动深圳湾工区",
            "home": "南山区示例花园",
        }
        config = ProviderConfig(
            mode="live",
            amap_key="amap-key",
            baidu_key="",
            qq_key="",
        )
        transit_profiles = [
            {"id": "weekday_morning", "label": "工作日早高峰", "date": "2026-08-03", "time": "08:30"},
            {"id": "weekday_midday", "label": "工作日平峰", "date": "2026-08-03", "time": "11:00"},
            {"id": "weekend_daytime", "label": "周末白天", "date": "2026-08-08", "time": "10:00"},
        ]

        def fake_fetch_json(url):
            if "assistant/inputtips" in url:
                return {"status": "1", "tips": [{"name": "地点", "location": "113.95,22.54", "adcode": "440305"}]}
            if "v5/place/around" in url:
                return {"status": "1", "pois": []}
            if "v5/direction/bicycling" in url:
                return {"status": "1", "route": {"paths": [{"cost": {"duration": 360}, "distance": 1400}]}}
            if "v5/direction/walking" in url:
                return {"route": {"paths": [{"cost": {"duration": 600}, "distance": 900}]}}
            raise AssertionError(f"unexpected url: {url}")

        results = build_live_provider_options(payload, config, fake_fetch_json, transit_profiles=transit_profiles)
        bike_plan = next(item for item in results if item["template"] == "bike")

        self.assertEqual(len(bike_plan["time_comparisons"]), 3)
        self.assertTrue(all(item["total_duration_min"] == 6 for item in bike_plan["time_comparisons"]))
        self.assertEqual(bike_plan["timing_recommendation"]["label"], "工作日早高峰")
        self.assertFalse(any(item["template"] == "walk" for item in results))

    def test_live_mode_skips_walk_when_exact_bike_is_compliant(self):
        payload = {
            "office": "字节跳动深圳湾工区",
            "home": "南山区示例花园",
        }
        config = ProviderConfig(
            mode="live",
            amap_key="amap-key",
            baidu_key="",
            qq_key="",
        )

        def fake_fetch_json(url):
            if "assistant/inputtips" in url:
                return {"status": "1", "tips": [{"name": "地点", "location": "113.95,22.54", "adcode": "440305"}]}
            if "v5/direction/bicycling" in url:
                return {"status": "1", "route": {"paths": [{"cost": {"duration": 360}, "distance": 1400}]}}
            if "v5/direction/walking" in url:
                raise AssertionError(f"walking should be skipped when bike is compliant: {url}")
            if "v5/direction/transit/integrated" in url:
                raise AssertionError(f"integrated should be skipped when bike is compliant: {url}")
            raise AssertionError(f"unexpected url: {url}")

        results = build_live_provider_options(payload, config, fake_fetch_json)

        self.assertEqual({item["template"] for item in results}, {"bike"})

    def test_live_mode_expands_aliases_after_exact_routes_are_over_limit(self):
        payload = {
            "office": "丽金智地中心",
            "home": "中海雅园",
        }
        config = ProviderConfig(
            mode="live",
            amap_key="amap-key",
            baidu_key="",
            qq_key="",
        )
        calls = []

        def fake_fetch_json(url):
            calls.append(url)
            if "assistant/inputtips" in url:
                if "keywords=%E4%B8%AD%E6%B5%B7%E9%9B%85%E5%9B%AD%E5%8C%97%E9%97%A8" in url:
                    return {"status": "1", "tips": [{"name": "中海雅园北门", "location": "113.941,22.531", "adcode": "440305"}]}
                if "keywords=%E4%B8%BD%E9%87%91%E6%99%BA%E5%9C%B0%E4%B8%AD%E5%BF%83%E8%A5%BF%E5%A1%94" in url:
                    return {"status": "1", "tips": [{"name": "丽金智地中心西塔", "location": "113.951,22.541", "adcode": "440305"}]}
                if "keywords=%E4%B8%BD%E9%87%91%E6%99%BA%E5%9C%B0%E4%B8%AD%E5%BF%83" in url:
                    return {"status": "1", "tips": [{"name": "丽金智地中心", "location": "116.300,39.940", "adcode": "110108"}]}
                return {"status": "1", "tips": [{"name": "中海雅园", "location": "113.940,22.530", "adcode": "440305"}]}
            if "keywords=%E9%97%A8" in url:
                raise AssertionError(f"unexpected gate lookup: {url}")
            if "v5/place/around" in url:
                return {"status": "1", "pois": []}
            if "v5/direction/walking" in url:
                return {"route": {"paths": [{"cost": {"duration": 1740}, "distance": 1400}]}}
            if "v5/direction/bicycling" in url:
                if "origin=113.940000%2C22.530000" in url and "destination=116.300000%2C39.940000" in url:
                    return {"status": "1", "route": {"paths": [{"cost": {"duration": 1260}, "distance": 1200}]}}
                if "origin=113.941000%2C22.531000" in url and "destination=113.951000%2C22.541000" in url:
                    return {"status": "1", "route": {"paths": [{"cost": {"duration": 1140}, "distance": 1100}]}}
                raise AssertionError(f"unexpected biking route: {url}")
            if "v5/direction/transit/integrated" in url:
                return {
                    "route": {
                        "transits": [
                            {
                                "cost": {"duration": 1320},
                                "segments": [
                                    {"walking": {"duration": 180}},
                                    {
                                        "bus": {
                                            "buslines": [
                                                {
                                                    "departure_stop": {"name": "后海"},
                                                    "arrival_stop": {"name": "科苑"},
                                                }
                                            ]
                                        }
                                    },
                                    {"walking": {"duration": 120}},
                                ],
                            }
                        ]
                    }
                }
            raise AssertionError(f"unexpected url: {url}")

        results = build_live_provider_options(payload, config, fake_fetch_json)
        bike_plan = next(item for item in results if item["template"] == "bike")

        self.assertEqual(bike_plan["origin_name"], "中海雅园")
        self.assertEqual(bike_plan["destination_name"], "丽金智地中心")
        self.assertEqual(bike_plan["segments"][0]["from_name"], "中海雅园北门")
        self.assertEqual(bike_plan["segments"][0]["to_name"], "丽金智地中心西塔")
        self.assertEqual(bike_plan["segments"][0]["duration_min"], 19)
        self.assertTrue(bike_plan["used_alias_fallback"])
        self.assertTrue(any("%E5%8C%97%E9%97%A8" in call for call in calls))
        self.assertTrue(any("%E8%A5%BF%E5%A1%94" in call for call in calls))

    def test_live_mode_does_not_compare_same_query_suggestions_as_formal_candidates(self):
        payload = {
            "office": "丽金智地中心",
            "home": "中海雅园",
        }
        config = ProviderConfig(
            mode="live",
            amap_key="amap-key",
            baidu_key="",
            qq_key="",
        )

        def fake_fetch_json(url):
            if "assistant/inputtips" in url:
                if "keywords=%E4%B8%AD%E6%B5%B7%E9%9B%85%E5%9B%AD" in url and "%E5%8C%97%E9%97%A8" not in url:
                    return {
                        "status": "1",
                        "tips": [
                            {"name": "中海雅园", "location": "116.301581,39.935618", "adcode": "110108"},
                            {"name": "中海雅园(南门)", "location": "116.300717,39.933733", "adcode": "110108"},
                            {"name": "中海雅园(东门)", "location": "116.302463,39.934879", "adcode": "110108"},
                        ],
                    }
                if "keywords=%E4%B8%BD%E9%87%91%E6%99%BA%E5%9C%B0%E4%B8%AD%E5%BF%83" in url and "%E8%A5%BF%E5%A1%94" not in url:
                    return {
                        "status": "1",
                        "tips": [
                            {"name": "丽金智地中心", "location": "116.320104,39.956309", "adcode": "110108"},
                            {"name": "丽金智地中心西塔", "location": "116.319455,39.956320", "adcode": "110108"},
                        ],
                    }
                return {"status": "1", "tips": []}
            if "v5/place/around" in url:
                return {"status": "1", "pois": []}
            if "v5/direction/walking" in url:
                return {"route": {"paths": [{"cost": {"duration": 3300}, "distance": 4200}]}}
            if "v5/direction/bicycling" in url:
                if "origin=116.301581%2C39.935618" in url and "destination=116.320104%2C39.956309" in url:
                    return {"status": "1", "route": {"paths": [{"cost": {"duration": 1320}, "distance": 5900}]}}
                if "origin=116.300717%2C39.933733" in url and "destination=116.319455%2C39.956320" in url:
                    return {"status": "1", "route": {"paths": [{"cost": {"duration": 1140}, "distance": 5200}]}}
                if "origin=116.302463%2C39.934879" in url and "destination=116.319455%2C39.956320" in url:
                    return {"status": "1", "route": {"paths": [{"cost": {"duration": 1260}, "distance": 5600}]}}
                return {"status": "1", "route": {"paths": [{"cost": {"duration": 1380}, "distance": 6000}]}}
            raise AssertionError(f"unexpected url: {url}")

        results = build_live_provider_options(payload, config, fake_fetch_json)
        bike_plan = next(item for item in results if item["template"] == "bike")

        self.assertEqual(bike_plan["segments"][0]["from_name"], "中海雅园")
        self.assertEqual(bike_plan["segments"][0]["to_name"], "丽金智地中心")
        self.assertEqual(bike_plan["segments"][0]["duration_min"], 22)
        self.assertFalse(bike_plan["used_alias_fallback"])

    def test_live_mode_only_queries_exact_places_once_within_one_search(self):
        payload = {
            "office": "丽金智地中心",
            "home": "中海雅园",
        }
        config = ProviderConfig(
            mode="live",
            amap_key="amap-key",
            baidu_key="",
            qq_key="",
        )
        calls = []

        def fake_fetch_json(url):
            calls.append(url)
            if "assistant/inputtips" in url:
                if "keywords=%E4%B8%AD%E6%B5%B7%E9%9B%85%E5%9B%AD" in url and "%E5%8C%97%E9%97%A8" not in url:
                    return {
                        "status": "1",
                        "tips": [
                            {"name": "中海雅园", "location": "116.301581,39.935618", "adcode": "110108"},
                            {"name": "中海雅园(南门)", "location": "116.300717,39.933733", "adcode": "110108"},
                        ],
                    }
                if "keywords=%E4%B8%BD%E9%87%91%E6%99%BA%E5%9C%B0%E4%B8%AD%E5%BF%83" in url and "%E8%A5%BF%E5%A1%94" not in url:
                    return {
                        "status": "1",
                        "tips": [
                            {"name": "丽金智地中心", "location": "116.320104,39.956309", "adcode": "110108"},
                            {"name": "丽金智地中心西塔", "location": "116.319455,39.956320", "adcode": "110108"},
                        ],
                    }
                return {"status": "1", "tips": []}
            if "v5/place/around" in url:
                return {"status": "1", "pois": []}
            if "v5/direction/walking" in url:
                return {"route": {"paths": [{"cost": {"duration": 3300}, "distance": 4200}]}}
            if "v5/direction/bicycling" in url:
                return {"status": "1", "route": {"paths": [{"cost": {"duration": 1320}, "distance": 5900}]}}
            raise AssertionError(f"unexpected url: {url}")

        build_live_provider_options(payload, config, fake_fetch_json)

        self.assertEqual(
            sum(
                1
                for url in calls
                if "assistant/inputtips" in url
                and "keywords=%E4%B8%AD%E6%B5%B7%E9%9B%85%E5%9B%AD" in url
                and "%E5%8C%97%E9%97%A8" not in url
            ),
            1,
        )
        self.assertEqual(
            sum(
                1
                for url in calls
                if "assistant/inputtips" in url
                and "keywords=%E4%B8%BD%E9%87%91%E6%99%BA%E5%9C%B0%E4%B8%AD%E5%BF%83" in url
                and "%E8%A5%BF%E5%A1%94" not in url
            ),
            1,
        )

    def test_live_mode_skips_alias_expansion_when_exact_route_is_safely_compliant(self):
        payload = {
            "office": "丽金智地中心",
            "home": "中海雅园",
        }
        config = ProviderConfig(
            mode="live",
            amap_key="amap-key",
            baidu_key="",
            qq_key="",
        )
        calls = []

        def fake_fetch_json(url):
            calls.append(url)
            if "assistant/inputtips" in url:
                if "keywords=%E4%B8%AD%E6%B5%B7%E9%9B%85%E5%9B%AD" in url:
                    return {"status": "1", "tips": [{"name": "中海雅园", "location": "116.301,39.935", "adcode": "110108"}]}
                if "keywords=%E4%B8%BD%E9%87%91%E6%99%BA%E5%9C%B0%E4%B8%AD%E5%BF%83" in url:
                    return {"status": "1", "tips": [{"name": "丽金智地中心", "location": "116.320,39.956", "adcode": "110108"}]}
                raise AssertionError(f"unexpected alias lookup: {url}")
            if "v5/place/around" in url:
                return {"status": "1", "pois": []}
            if "v5/direction/bicycling" in url:
                return {"status": "1", "route": {"paths": [{"cost": {"duration": 600}, "distance": 1400}]}}
            if "v5/direction/walking" in url:
                return {"route": {"paths": [{"cost": {"duration": 1200}, "distance": 900}]}}
            raise AssertionError(f"unexpected url: {url}")

        results = build_live_provider_options(payload, config, fake_fetch_json)
        bike_plan = next(item for item in results if item["template"] == "bike")

        self.assertEqual(bike_plan["segments"][0]["duration_min"], 10)
        self.assertFalse(any("%E5%8C%97%E9%97%A8" in url or "%E8%A5%BF%E5%A1%94" in url for url in calls))

    def test_live_mode_does_not_expand_aliases_when_exact_bike_is_compliant(self):
        payload = {
            "office": "丽金智地中心",
            "home": "中海雅园",
        }
        config = ProviderConfig(
            mode="live",
            amap_key="amap-key",
            baidu_key="",
            qq_key="",
        )
        calls = []

        def fake_fetch_json(url):
            calls.append(url)
            if "assistant/inputtips" in url:
                if "keywords=%E4%B8%BD%E9%87%91%E6%99%BA%E5%9C%B0%E4%B8%AD%E5%BF%83%E8%A5%BF%E5%A1%94" in url:
                    return {"status": "1", "tips": [{"name": "丽金智地中心西塔", "location": "116.301,39.941", "adcode": "110108"}]}
                if "keywords=%E4%B8%AD%E6%B5%B7%E9%9B%85%E5%9B%AD%E5%8C%97%E9%97%A8" in url:
                    return {"status": "1", "tips": [{"name": "中海雅园北门", "location": "116.306,39.933", "adcode": "110108"}]}
                if "keywords=%E4%B8%BD%E9%87%91%E6%99%BA%E5%9C%B0%E4%B8%AD%E5%BF%83" in url:
                    return {"status": "1", "tips": [{"name": "丽金智地中心", "location": "116.300,39.940", "adcode": "110108"}]}
                return {"status": "1", "tips": [{"name": "中海雅园", "location": "116.305,39.932", "adcode": "110108"}]}
            if "keywords=%E9%97%A8" in url:
                raise AssertionError(f"unexpected gate lookup: {url}")
            if "v5/place/around" in url:
                return {"status": "1", "pois": []}
            if "v5/direction/walking" in url:
                if "origin=116.305000%2C39.932000" in url and "destination=116.300000%2C39.940000" in url:
                    return {"route": {"paths": [{"cost": {"duration": 1740}, "distance": 2600}]}}
                if "origin=116.306000%2C39.933000" in url and "destination=116.301000%2C39.941000" in url:
                    return {"route": {"paths": [{"cost": {"duration": 1680}, "distance": 2200}]}}
                raise AssertionError(f"unexpected walking route: {url}")
            if "v5/direction/bicycling" in url:
                return {"status": "1", "route": {"paths": [{"cost": {"duration": 900}, "distance": 1200}]}}
            raise AssertionError(f"unexpected url: {url}")

        results = build_live_provider_options(payload, config, fake_fetch_json)

        self.assertFalse(any("keywords=%E4%B8%AD%E6%B5%B7%E9%9B%85%E5%9B%AD%E5%8C%97%E9%97%A8" in call for call in calls))
        self.assertFalse(any("keywords=%E4%B8%BD%E9%87%91%E6%99%BA%E5%9C%B0%E4%B8%AD%E5%BF%83%E8%A5%BF%E5%A1%94" in call for call in calls))
        self.assertFalse(any(item["template"] == "walk" for item in results))

    def test_live_mode_falls_back_to_baidu_after_amap_soft_timeout(self):
        config = ProviderConfig(
            mode="live",
            amap_key="amap-key",
            baidu_key="baidu-key",
            qq_key="",
        )
        original_timeout = getattr(providers_module, "AMAP_SOFT_TIMEOUT_SEC", None)

        try:
            providers_module.AMAP_SOFT_TIMEOUT_SEC = 0.01

            def fake_fetch_json(url):
                if "restapi.amap.com/v3/assistant/inputtips" in url:
                    time.sleep(0.02)
                    if "%E4%B8%BD%E9%87%91%E6%99%BA%E5%9C%B0%E4%B8%AD%E5%BF%83%E8%A5%BF%E5%A1%94" in url:
                        return {"status": "1", "tips": [{"name": "丽金智地中心西塔", "location": "116.300,39.940"}]}
                    return {"status": "1", "tips": [{"name": "中海雅园", "location": "116.305,39.932"}]}
                if "restapi.amap.com/v5/direction/bicycling" in url:
                    return {"status": "1", "route": {"paths": [{"cost": {"duration": 780}, "distance": 3200}]}}
                if "restapi.amap.com/v5/direction/walking" in url:
                    return {"route": {"paths": [{"cost": {"duration": 1980}, "distance": 4200}]}}
                if "restapi.amap.com/v5/direction/transit/integrated" in url:
                    return {
                        "route": {
                            "transits": [
                                {
                                    "cost": {"duration": 1140},
                                    "segments": [
                                        {
                                            "bus": {
                                                "buslines": [
                                                    {
                                                        "name": "10号线",
                                                        "departure_stop": {"name": "慈寿寺"},
                                                        "arrival_stop": {"name": "魏公村"},
                                                    }
                                                ]
                                            }
                                        }
                                    ],
                                }
                            ]
                        }
                    }
                if "api.map.baidu.com/geocoding/v3/" in url:
                    if "%E4%B8%BD%E9%87%91%E6%99%BA%E5%9C%B0%E4%B8%AD%E5%BF%83%E8%A5%BF%E5%A1%94" in url:
                        return {"status": 0, "result": {"location": {"lng": 116.300, "lat": 39.940}}}
                    return {"status": 0, "result": {"location": {"lng": 116.305, "lat": 39.932}}}
                if "api.map.baidu.com/directionlite/v1/riding" in url:
                    return {"status": 0, "result": {"routes": [{"duration": 660, "distance": 2800}]}}
                if "api.map.baidu.com/directionlite/v1/walking" in url:
                    return {"status": 0, "result": {"routes": [{"duration": 2100, "distance": 4200}]}}
                if "api.map.baidu.com/directionlite/v1/transit" in url:
                    return {
                        "status": 0,
                        "result": {
                            "routes": [
                                {
                                    "duration": 1020,
                                    "distance": 5600,
                                    "steps": [
                                        {
                                            "vehicle_info": {"name": "10号线"},
                                            "departure_stop": {"name": "慈寿寺"},
                                            "arrival_stop": {"name": "魏公村"},
                                        }
                                    ],
                                }
                            ]
                        },
                    }
                raise AssertionError(f"unexpected url: {url}")

            payload = load_provider_payload(
                {"office": "丽金智地中心西塔", "home": "中海雅园"},
                config=config,
                fetch_json=fake_fetch_json,
            )

            self.assertFalse(payload["live_failed"])
            self.assertEqual({item["provider"] for item in payload["options"]}, {"baidu"})
            self.assertTrue(any(item["provider"] == "amap" for item in payload["provider_errors"]))
        finally:
            if original_timeout is None:
                delattr(providers_module, "AMAP_SOFT_TIMEOUT_SEC")
            else:
                providers_module.AMAP_SOFT_TIMEOUT_SEC = original_timeout

    def test_live_mode_drops_station_combo_when_integrated_station_pair_cannot_be_matched(self):
        payload = {
            "office": "丽金智地中心西塔",
            "home": "中海雅园",
        }
        config = ProviderConfig(
            mode="live",
            amap_key="amap-key",
            baidu_key="",
            qq_key="",
        )

        def fake_fetch_json(url):
            if "assistant/inputtips" in url:
                if "%E6%85%88%E5%AF%BF%E5%AF%BA%E7%AB%99" in url or "%E9%AD%8F%E5%85%AC%E6%9D%91%E7%AB%99" in url:
                    return {"status": "1", "tips": []}
                if "%E4%B8%BD%E9%87%91%E6%99%BA%E5%9C%B0%E4%B8%AD%E5%BF%83%E8%A5%BF%E5%A1%94" in url:
                    return {"status": "1", "tips": [{"name": "丽金智地中心西塔", "location": "116.300,39.940", "adcode": "110108"}]}
                return {"status": "1", "tips": [{"name": "中海雅园", "location": "116.305,39.932", "adcode": "110108"}]}
            if "v5/place/text" in url:
                return {"status": "1", "pois": []}
            if "v5/place/around" in url:
                if "location=116.305000%2C39.932000" in url:
                    return {
                        "status": "1",
                        "pois": [{"name": "慈寿寺站", "location": "116.317,39.926", "distance": "220"}],
                    }
                return {
                    "status": "1",
                    "pois": [{"name": "苏州桥站", "location": "116.312,39.975", "distance": "180"}],
                }
            if "v5/direction/bicycling" in url:
                return {"status": "1", "route": {"paths": [{"cost": {"duration": 1560}, "distance": 4000}]}}
            if "v5/direction/walking" in url:
                return {"route": {"paths": [{"cost": {"duration": 2040}, "distance": 4300}]}}
            if "v5/direction/transit/integrated" in url:
                return {
                    "route": {
                        "transits": [
                            {
                                "cost": {"duration": 1140},
                                "segments": [
                                    {"walking": {"duration": 180}},
                                    {
                                        "bus": {
                                            "buslines": [
                                                {
                                                    "name": "10号线",
                                                    "departure_stop": {"name": "慈寿寺"},
                                                    "arrival_stop": {"name": "魏公村"},
                                                }
                                            ]
                                        }
                                    },
                                    {"walking": {"duration": 120}},
                                ],
                            }
                        ]
                    }
                }
            raise AssertionError(f"unexpected url: {url}")

        results = build_live_provider_options(payload, config, fake_fetch_json)

        self.assertFalse(any(item["template"] == "bike->subway->bike" for item in results))
        self.assertFalse(
            any(
                segment.get("to_name") == "苏州桥站"
                for item in results
                for segment in item.get("segments", [])
                if segment.get("mode") == "subway"
            )
        )

    def test_live_mode_returns_provider_level_errors(self):
        config = ProviderConfig(
            mode="live",
            amap_key="amap-key",
            baidu_key="baidu-key",
            qq_key="qq-key",
        )

        def fake_fetch_json(url):
            if "restapi.amap.com" in url:
                raise RuntimeError("INVALID_USER_KEY")
            if "api.map.baidu.com" in url:
                raise RuntimeError("AK error")
            if "apis.map.qq.com" in url:
                raise RuntimeError("key invalid")
            raise AssertionError(f"unexpected url: {url}")

        payload = load_provider_payload(
            {"office": "字节跳动深圳湾工区", "home": "南山区示例花园"},
            config=config,
            fetch_json=fake_fetch_json,
        )

        self.assertEqual(payload["options"], [])
        self.assertEqual({item["provider"] for item in payload["provider_errors"]}, {"amap"})
        self.assertTrue(any("INVALID_USER_KEY" in item["message"] for item in payload["provider_errors"]))


if __name__ == "__main__":
    unittest.main()
