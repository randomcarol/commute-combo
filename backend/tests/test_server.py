import os
import subprocess
import sys
import unittest
from unittest.mock import patch

from backend.server import (
    metrics_payload,
    _server_bind_address,
    build_handler,
    experiment_payload,
    feedback_payload,
    review_payload,
    search_payload,
    stats_payload,
    suggest_payload,
)


class ServerApiTests(unittest.TestCase):
    def test_search_payload_records_analytics(self):
        with patch(
            "backend.server.record_search_analytics",
        ) as mock_record:
            payload = search_payload(
                {
                    "office": "字节跳动深圳湾工区",
                    "home": "南山区示例花园",
                }
            )

        mock_record.assert_called_once()
        self.assertIn("results", payload)

    def test_server_bind_address_reads_host_and_port_from_env(self):
        with patch.dict(
            os.environ,
            {
                "COMMUTE_SERVER_HOST": "0.0.0.0",
                "COMMUTE_SERVER_PORT": "9000",
            },
            clear=False,
        ):
            self.assertEqual(_server_bind_address(), ("0.0.0.0", 9000))

    def test_search_endpoint_returns_ranked_results(self):
        payload = search_payload(
            {
                "office": "ByteDance Shenzhen Bay",
                "home": "Nanshan Example Garden",
                "rules": {
                    "walk_max_min": 30,
                    "bike_or_subway_max_min": 20,
                    "mixed_max_min": 20,
                },
            }
        )

        self.assertIn("results", payload)
        self.assertGreater(len(payload["results"]), 0)
        self.assertTrue(payload["results"][0]["evaluation"]["is_compliant"])

    def test_search_payload_exposes_data_source_and_warnings(self):
        with patch(
            "backend.server.load_provider_payload",
            return_value={
                "options": [],
                "data_source": "live",
                "provider_mode": "live",
                "live_failed": True,
                "warnings": ["当前未获取到真实地图结果，请检查 API key、配额或输入地址。"],
                "provider_errors": [
                    {"provider": "baidu", "message": "AK error"},
                ],
            },
        ):
            payload = search_payload(
                {
                    "office": "字节跳动深圳湾工区",
                    "home": "南山区示例花园",
                }
            )

        self.assertEqual(payload["results"], [])
        self.assertEqual(payload["meta"]["data_source"], "live")
        self.assertTrue(payload["meta"]["live_failed"])
        self.assertTrue(payload["meta"]["warnings"])
        self.assertEqual(payload["meta"]["provider_errors"][0]["provider"], "baidu")
        self.assertTrue(payload["meta"]["request_id"])
        self.assertEqual(payload["meta"]["rule_version"], "commute-r1.0")
        self.assertIn("latency_ms", payload["meta"])
        self.assertIn("provider_request_count", payload["meta"])

    def test_review_payload_requires_and_links_outcomes(self):
        with patch("backend.server.record_review", return_value={"request_id": "req-1"}) as mock_record:
            response = review_payload({"request_id": "req-1", "outcomes": ["map_consistent"]})
        self.assertEqual(response, {"status": "ok", "request_id": "req-1"})
        mock_record.assert_called_once()

    def test_experiment_payload_returns_refreshed_summary(self):
        with patch("backend.server.record_experiment", return_value={"case_id": "CASE-001"}), patch("backend.server.load_experiment_summary", return_value={"case_count": 1}):
            response = experiment_payload({"case_id": "CASE-001"})
        self.assertEqual(response["summary"]["case_count"], 1)

    def test_suggest_payload_returns_amap_candidates(self):
        with patch(
            "backend.server.load_place_suggestions",
            return_value={
                "provider": "amap",
                "suggestions": [
                    {
                        "id": "poi-1",
                        "name": "中海雅园",
                        "address": "北洼西里",
                        "district": "北京市海淀区",
                        "location": "116.305,39.932",
                    }
                ],
                "warning": "",
            },
        ):
            payload = suggest_payload({"query": "中海雅园"})

        self.assertEqual(payload["provider"], "amap")
        self.assertEqual(payload["suggestions"][0]["name"], "中海雅园")

    def test_server_script_can_bootstrap_package_imports_when_run_directly(self):
        project_root = "/Users/dengzhilei/Documents/Codex/2026-08-01/ai"
        server_path = f"{project_root}/backend/server.py"
        env = dict(os.environ)
        env["COMMUTE_SERVER_IMPORT_ONLY"] = "1"

        result = subprocess.run(
            [sys.executable, server_path],
            cwd="/private/tmp",
            env=env,
            capture_output=True,
            text=True,
        )

        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn("Commute Combo import check OK", result.stdout)

    def test_handler_supports_health_check(self):
        handler_factory = build_handler()

        class FakeSocket:
            def __init__(self):
                import io

                self._read_buffer = io.BytesIO(b"GET /healthz HTTP/1.1\r\nHost: localhost\r\n\r\n")
                self._write_buffer = io.BytesIO()

            def makefile(self, mode, *args, **kwargs):
                if "r" in mode:
                    return self._read_buffer
                return self._write_buffer

            def sendall(self, data):
                self._write_buffer.write(data)

        class FakeServer:
            pass

        fake_socket = FakeSocket()
        handler = handler_factory(fake_socket, ("127.0.0.1", 12345), FakeServer())
        raw = fake_socket._write_buffer.getvalue().decode("utf-8")

        self.assertIn("200 OK", raw)
        self.assertIn('"status": "ok"', raw)

    def test_handler_returns_json_error_when_search_crashes(self):
        handler_factory = build_handler()

        class FakeSocket:
            def __init__(self):
                import io

                body = b'{"office":"\xe4\xb8\xbd\xe9\x87\x91","home":"\xe4\xb8\xad\xe6\xb5\xb7"}'
                request = (
                    b"POST /api/search HTTP/1.1\r\n"
                    b"Host: localhost\r\n"
                    b"Content-Type: application/json\r\n"
                    + f"Content-Length: {len(body)}\r\n\r\n".encode("utf-8")
                    + body
                )
                self._read_buffer = io.BytesIO(request)
                self._write_buffer = io.BytesIO()

            def makefile(self, mode, *args, **kwargs):
                if "r" in mode:
                    return self._read_buffer
                return self._write_buffer

            def sendall(self, data):
                self._write_buffer.write(data)

        class FakeServer:
            pass

        with patch("backend.server.search_payload", side_effect=RuntimeError("boom")):
            fake_socket = FakeSocket()
            handler_factory(fake_socket, ("127.0.0.1", 12345), FakeServer())

        raw = fake_socket._write_buffer.getvalue().decode("utf-8")
        self.assertIn("500 Internal Server Error", raw)
        self.assertIn('"error": "search_failed"', raw)
        self.assertIn('"detail": "boom"', raw)

    def test_metrics_payload_requires_valid_token(self):
        with patch.dict(
            os.environ,
            {
                "COMMUTE_METRICS_TOKEN": "secret-token",
            },
            clear=False,
        ):
            with self.assertRaises(PermissionError):
                metrics_payload("")

    def test_metrics_payload_returns_summary_when_token_matches(self):
        with patch.dict(
            os.environ,
            {
                "COMMUTE_METRICS_TOKEN": "secret-token",
            },
            clear=False,
        ):
            with patch(
                "backend.server.load_metrics_summary",
                return_value={"total_searches": 3},
            ):
                payload = metrics_payload("secret-token")

        self.assertEqual(payload["total_searches"], 3)

    def test_feedback_payload_validates_and_writes_feedback(self):
        with patch("backend.server.record_feedback") as mock_record:
            payload = feedback_payload({"helpful": True, "note": "结果有帮助"})

        recorded = mock_record.call_args.args[0]
        self.assertTrue(recorded["request_id"])
        self.assertEqual(recorded["rule_version"], "commute-r1.0")
        self.assertEqual(recorded["note"], "结果有帮助")
        self.assertEqual(payload["status"], "ok")

    def test_feedback_payload_rejects_invalid_helpful_type(self):
        with self.assertRaises(ValueError):
            feedback_payload({"helpful": "yes", "note": "not valid"})

    def test_stats_payload_returns_combined_summary(self):
        expected = {
            "total_searches": 5,
            "feedback_total": 2,
            "recent_searches": [],
        }
        with patch("backend.server.load_stats_summary", return_value=expected):
            payload = stats_payload()

        self.assertEqual(payload, expected)


if __name__ == "__main__":
    unittest.main()
