import json
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.analytics import (
    load_metrics_summary,
    load_experiment_summary,
    load_stats_summary,
    record_experiment,
    record_feedback,
    record_result_shown,
    record_review,
    record_search_analytics,
    record_search_submit,
)


class AnalyticsTests(unittest.TestCase):
    def test_dashboard_environment_filter_excludes_demo_and_test(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            log_path = Path(tmp_dir) / "events.jsonl"
            events = [
                {"event_type": "search_completed", "environment": "self_test", "result_count": 1, "compliant_result_count": 1},
                {"event_type": "search_completed", "environment": "test", "result_count": 1, "compliant_result_count": 1},
                {"event_type": "search_completed", "environment": "dev", "data_source": "mock", "result_count": 1, "compliant_result_count": 1},
            ]
            log_path.write_text("\n".join(json.dumps(item) for item in events) + "\n", encoding="utf-8")
            with patch.dict(os.environ, {"COMMUTE_ANALYTICS_LOG_PATH": str(log_path)}, clear=False):
                summary = load_stats_summary(("self_test", "prod"))
        self.assertEqual(summary["total_searches"], 1)
        self.assertEqual(summary["selected_environments"], ["prod", "self_test"])

    def test_review_links_to_request_and_completes_core_metric(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            log_path = Path(tmp_dir) / "events.jsonl"
            context = {"request_id": "req-001", "anonymous_session_id": "session-1", "environment": "self_test"}
            with patch.dict(os.environ, {"COMMUTE_ANALYTICS_LOG_PATH": str(log_path)}, clear=False):
                record_search_analytics(context, {"results": [{"template": "bike", "total_duration_min": 18, "evaluation": {"is_compliant": True}}], "meta": {"data_source": "live"}})
                record_review({**context, "outcomes": ["map_consistent", "screenshot_usable"], "actual_minutes": 18})
                summary = load_metrics_summary(("self_test",))
        self.assertEqual(summary["effective_measurement_completed"], 1)
        self.assertEqual(summary["false_compliance_count"], 0)

    def test_experiment_summary_uses_latest_record_per_anonymous_case(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "experiments.jsonl"
            with patch.dict(os.environ, {"COMMUTE_EXPERIMENT_LOG_PATH": str(path)}, clear=False):
                record_experiment({"case_id": "CASE-001", "environment": "self_test", "data_source": "live", "manual_search_seconds": 100, "tool_search_seconds": 20, "manual_best_minutes": 20, "tool_best_minutes": 22})
                record_experiment({"case_id": "CASE-001", "environment": "self_test", "data_source": "live", "manual_search_seconds": 90, "tool_search_seconds": 20, "manual_best_minutes": 20, "tool_best_minutes": 20, "tool_search_success": True, "matches_manual": True, "top1_valid": True, "alias_improved": True})
                summary = load_experiment_summary()
        self.assertEqual(summary["case_count"], 1)
        self.assertEqual(summary["manual_match_rate"], 1.0)
        self.assertEqual(summary["average_abs_best_difference_min"], 0.0)
        self.assertTrue(summary["small_sample"])
    def test_search_submit_and_result_shown_events_are_written_without_raw_address(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            log_path = Path(tmp_dir) / "events.jsonl"
            payload = {
                "office": "丽金智地中心西塔",
                "home": "中海雅园北门",
            }
            result = {
                "provider": "amap",
                "template": "bike->subway->walk",
                "total_duration_min": 19,
                "evaluation": {"is_compliant": True},
            }
            with patch.dict(
                os.environ,
                {
                    "COMMUTE_ANALYTICS_LOG_PATH": str(log_path),
                },
                clear=False,
            ):
                record_search_submit(payload)
                record_result_shown(result)
                raw_log = log_path.read_text(encoding="utf-8")

            lines = [json.loads(line) for line in raw_log.splitlines() if line.strip()]

        self.assertEqual(lines[0]["event_type"], "search_submit")
        self.assertEqual(lines[1]["event_type"], "result_shown")
        self.assertEqual(lines[1]["provider"], "amap")
        self.assertEqual(lines[1]["template"], "bike->subway->walk")
        self.assertEqual(lines[1]["total_duration_min"], 19)
        self.assertTrue(lines[1]["is_compliant"])
        self.assertNotIn("中海雅园北门", raw_log)
        self.assertNotIn("丽金智地中心西塔", raw_log)

    def test_record_search_analytics_writes_redacted_event_without_raw_address(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            log_path = Path(tmp_dir) / "events.jsonl"
            payload = {
                "office": "丽金智地中心西塔",
                "home": "中海雅园北门",
            }
            response = {
                "results": [
                    {
                        "provider": "amap",
                        "template": "bike",
                        "used_alias_fallback": True,
                        "total_duration_min": 19,
                        "evaluation": {"is_compliant": True},
                    }
                ],
                "meta": {
                    "data_source": "live",
                    "provider_mode": "live",
                    "live_failed": False,
                    "warnings": [],
                    "provider_errors": [],
                },
            }
            with patch.dict(
                os.environ,
                {
                    "COMMUTE_ANALYTICS_LOG_PATH": str(log_path),
                },
                clear=False,
            ):
                record_search_analytics(payload, response)

            raw_log = log_path.read_text(encoding="utf-8")
            event = json.loads(raw_log.strip())

            self.assertEqual(event["event_type"], "search_completed")
            self.assertEqual(event["result_count"], 1)
            self.assertEqual(event["compliant_result_count"], 1)
            self.assertTrue(event["has_alias_result"])
            self.assertEqual(event["route_type_distribution"]["walk"]["matched"], False)
            self.assertEqual(event["route_type_distribution"]["bike"]["matched"], True)
            self.assertEqual(event["route_type_distribution"]["bike"]["total_duration_min"], 19)
            self.assertNotIn("中海雅园北门", raw_log)
            self.assertNotIn("丽金智地中心西塔", raw_log)
            self.assertIn("home_hash", event)
            self.assertIn("office_hash", event)

    def test_load_metrics_summary_aggregates_search_outcomes(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            log_path = Path(tmp_dir) / "events.jsonl"
            log_path.write_text(
                "\n".join(
                    [
                        json.dumps(
                            {
                                "event_type": "search_completed",
                                "result_count": 2,
                                "compliant_result_count": 1,
                                "has_alias_result": True,
                                "live_failed": False,
                                "best_template": "bike",
                            },
                            ensure_ascii=False,
                        ),
                        json.dumps(
                            {
                                "event_type": "search_completed",
                                "result_count": 0,
                                "compliant_result_count": 0,
                                "has_alias_result": False,
                                "live_failed": True,
                                "best_template": None,
                            },
                            ensure_ascii=False,
                        ),
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            with patch.dict(
                os.environ,
                {
                    "COMMUTE_ANALYTICS_LOG_PATH": str(log_path),
                },
                clear=False,
            ):
                summary = load_metrics_summary()

        self.assertEqual(summary["total_searches"], 2)
        self.assertEqual(summary["successful_searches"], 1)
        self.assertEqual(summary["empty_searches"], 1)
        self.assertEqual(summary["compliant_searches"], 1)
        self.assertEqual(summary["alias_searches"], 1)
        self.assertEqual(summary["live_failed_searches"], 1)
        self.assertEqual(summary["template_breakdown"]["bike"], 1)

    def test_record_feedback_persists_into_sqlite(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "feedback.db"
            with patch.dict(
                os.environ,
                {
                    "COMMUTE_FEEDBACK_DB_PATH": str(db_path),
                },
                clear=False,
            ):
                record_feedback({"helpful": False, "note": "地铁站选得不准"})

            self.assertTrue(db_path.exists())
            with sqlite3.connect(db_path) as connection:
                row = connection.execute("select helpful, note from feedback_events").fetchone()

        self.assertEqual(row, (0, "地铁站选得不准"))

    def test_load_stats_summary_combines_search_metrics_feedback_and_recent_searches(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            log_path = Path(tmp_dir) / "events.jsonl"
            db_path = Path(tmp_dir) / "feedback.db"
            records = []
            for index in range(12):
                records.append(
                    json.dumps(
                        {
                            "event_type": "search_completed",
                            "timestamp": f"2026-08-0{index % 9 + 1}T08:00:00+00:00",
                            "home_hash": f"home-{index}",
                            "office_hash": f"office-{index}",
                            "result_count": 1 if index % 2 == 0 else 0,
                            "compliant_result_count": 1 if index % 3 == 0 else 0,
                            "has_alias_result": index % 4 == 0,
                            "live_failed": index % 5 == 0,
                            "best_template": "bike" if index % 2 == 0 else "walk",
                            "best_provider": "amap",
                            "best_total_duration_min": 18 + index,
                            "route_type_distribution": {
                                "bike": {
                                    "matched": index % 2 == 0,
                                    "total_duration_min": 18 + index if index % 2 == 0 else None,
                                }
                            },
                        },
                        ensure_ascii=False,
                    )
                )
            log_path.write_text("\n".join(records) + "\n", encoding="utf-8")

            with patch.dict(
                os.environ,
                {
                    "COMMUTE_ANALYTICS_LOG_PATH": str(log_path),
                    "COMMUTE_FEEDBACK_DB_PATH": str(db_path),
                },
                clear=False,
            ):
                record_feedback({"helpful": True, "note": "很好用"})
                record_feedback({"helpful": False, "note": "还差门口识别"})
                summary = load_stats_summary()

        self.assertEqual(summary["total_searches"], 12)
        self.assertEqual(summary["feedback_total"], 2)
        self.assertEqual(summary["feedback_helpful_count"], 1)
        self.assertEqual(summary["feedback_unhelpful_count"], 1)
        self.assertEqual(len(summary["recent_searches"]), 10)
        self.assertEqual(summary["recent_searches"][0]["home_hash"], "home-11")
        self.assertIn("bike", summary["route_type_distribution"])
        self.assertEqual(summary["route_type_distribution"]["bike"]["matched_count"], 6)
        self.assertEqual(summary["route_type_distribution"]["bike"]["average_duration_min"], 23.0)

    def test_load_stats_summary_builds_iteration_signals_for_dashboard(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            log_path = Path(tmp_dir) / "events.jsonl"
            db_path = Path(tmp_dir) / "feedback.db"
            log_path.write_text(
                "\n".join(
                    [
                        json.dumps(
                            {
                                "event_type": "search_completed",
                                "timestamp": "2026-08-10T08:00:00+00:00",
                                "home_hash": "home-a",
                                "office_hash": "office-a",
                                "result_count": 0,
                                "compliant_result_count": 0,
                                "has_alias_result": False,
                                "best_used_alias_fallback": False,
                                "best_provider": None,
                                "best_is_compliant": False,
                                "warning_count": 1,
                                "provider_error_count": 1,
                                "live_failed": True,
                                "route_type_distribution": {},
                            },
                            ensure_ascii=False,
                        ),
                        json.dumps(
                            {
                                "event_type": "search_completed",
                                "timestamp": "2026-08-10T08:10:00+00:00",
                                "home_hash": "home-b",
                                "office_hash": "office-b",
                                "result_count": 1,
                                "compliant_result_count": 0,
                                "has_alias_result": False,
                                "best_used_alias_fallback": False,
                                "best_provider": "amap",
                                "best_is_compliant": False,
                                "warning_count": 0,
                                "provider_error_count": 0,
                                "live_failed": False,
                                "best_template": "bike",
                                "best_total_duration_min": 22,
                                "route_type_distribution": {
                                    "bike": {"matched": True, "total_duration_min": 22}
                                },
                            },
                            ensure_ascii=False,
                        ),
                        json.dumps(
                            {
                                "event_type": "search_completed",
                                "timestamp": "2026-08-10T08:20:00+00:00",
                                "home_hash": "home-c",
                                "office_hash": "office-c",
                                "result_count": 2,
                                "compliant_result_count": 1,
                                "has_alias_result": True,
                                "best_used_alias_fallback": True,
                                "best_provider": "baidu",
                                "best_is_compliant": True,
                                "warning_count": 0,
                                "provider_error_count": 0,
                                "live_failed": False,
                                "best_template": "bike",
                                "best_total_duration_min": 19,
                                "best_exact_duration_min": 23,
                                "best_alias_duration_min": 19,
                                "route_type_distribution": {
                                    "bike": {"matched": True, "total_duration_min": 19}
                                },
                            },
                            ensure_ascii=False,
                        ),
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            with patch.dict(
                os.environ,
                {
                    "COMMUTE_ANALYTICS_LOG_PATH": str(log_path),
                    "COMMUTE_FEEDBACK_DB_PATH": str(db_path),
                },
                clear=False,
            ):
                record_feedback({"helpful": False, "note": "地铁站选得不准"})
                record_feedback({"helpful": False, "note": "结果太慢，等太久"})
                record_feedback({"helpful": True, "note": "门口别名比较有帮助"})
                summary = load_stats_summary()

        self.assertEqual(summary["result_without_compliant_searches"], 1)
        self.assertEqual(summary["warning_searches"], 1)
        self.assertEqual(summary["provider_breakdown"]["baidu"], 1)
        self.assertEqual(summary["provider_breakdown"]["amap"], 1)
        self.assertEqual(summary["alias_uplift"]["count"], 1)
        self.assertEqual(summary["alias_uplift"]["average_saved_min"], 4.0)
        self.assertEqual(summary["feedback_theme_breakdown"]["station_accuracy"], 1)
        self.assertEqual(summary["feedback_theme_breakdown"]["speed_or_latency"], 1)
        self.assertEqual(summary["feedback_theme_breakdown"]["alias_coverage"], 1)


if __name__ == "__main__":
    unittest.main()
