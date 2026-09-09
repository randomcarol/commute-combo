import json
import mimetypes
import os
import sys
import time
import traceback
from functools import partial
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

if __package__ in {None, ""}:
    project_root = Path(__file__).resolve().parent.parent
    project_root_str = str(project_root)
    if project_root_str not in sys.path:
        sys.path.insert(0, project_root_str)

from backend.engine import search_best_plans
from backend.providers import load_place_suggestions, load_provider_payload
from backend.rules import APP_VERSION, RULE_VERSION, normalize_rules
from backend.analytics import (
    DEFAULT_DASHBOARD_ENVIRONMENTS,
    load_experiment_summary,
    load_metrics_summary,
    load_stats_summary,
    metrics_token,
    record_experiment,
    record_feedback,
    record_review,
    record_result_shown,
    record_search_analytics,
    record_search_submit,
    tracking_context,
)

ROOT_DIR = Path(__file__).resolve().parent.parent
APP_DIR = ROOT_DIR / "app"


def _json_response(handler, payload, status=HTTPStatus.OK):
    raw = json.dumps(payload).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(raw)))
    handler.end_headers()
    handler.wfile.write(raw)


def _serve_file(handler, file_path):
    if not file_path.exists() or not file_path.is_file():
        handler.send_error(HTTPStatus.NOT_FOUND)
        return

    content_type, _ = mimetypes.guess_type(str(file_path))
    body = file_path.read_bytes()
    handler.send_response(HTTPStatus.OK)
    handler.send_header("Content-Type", f"{content_type or 'application/octet-stream'}")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


# 中文注释：云服务器部署时需要通过环境变量控制监听地址和端口，本地默认仍然走 127.0.0.1:8000。
def _server_bind_address():
    host = os.getenv("COMMUTE_SERVER_HOST", "127.0.0.1").strip() or "127.0.0.1"
    try:
        port = int(os.getenv("COMMUTE_SERVER_PORT", "8000"))
    except ValueError:
        port = 8000
    return host, port


def _health_payload():
    return {"status": "ok", "service": "commute-combo", "app_version": APP_VERSION, "rule_version": RULE_VERSION}


def _error_payload(error, default_code="internal_error"):
    message = str(error).strip() or default_code
    return {"error": default_code, "detail": message}


def metrics_payload(token):
    expected = metrics_token()
    if not expected or token != expected:
        raise PermissionError("invalid metrics token")
    return load_metrics_summary()


def stats_payload(environments=None):
    return load_stats_summary(environments or DEFAULT_DASHBOARD_ENVIRONMENTS)


def search_payload(payload):
    started_at = time.monotonic()
    rules = normalize_rules(payload.get("rules"))
    context = tracking_context({**payload, "rule_version": rules["rule_version"]})
    tracked_payload = {**payload, **context, "rules": rules}
    print(
        f"[commute] search start office_len={len(str(payload.get('office', '')).strip())} "
        f"home_len={len(str(payload.get('home', '')).strip())}",
        flush=True,
    )
    try:
        record_search_submit(tracked_payload)
    except Exception:
        pass
    try:
        provider_payload = load_provider_payload(tracked_payload)
        evaluated_results = search_best_plans(provider_payload["options"], rules)
    except Exception as error:
        failure_response = {
            "results": [],
            "meta": {
                **context,
                "data_source": "unknown",
                "provider_mode": "unknown",
                "live_failed": True,
                "warnings": [],
                "provider_errors": [],
                "provider_request_count": 0,
                "latency_ms": int((time.monotonic() - started_at) * 1000),
                "result_type": "error",
                "error_type": error.__class__.__name__,
            },
        }
        try:
            record_search_analytics(tracked_payload, failure_response)
        except Exception:
            pass
        raise
    results = [item for item in evaluated_results if item["evaluation"]["template_allowed"]]
    excluded_results = [item for item in evaluated_results if not item["evaluation"]["is_compliant"]]
    elapsed_ms = int((time.monotonic() - started_at) * 1000)
    compliant_results = [item for item in results if item["evaluation"]["is_compliant"]]
    if not results:
        result_type = "no_route"
    elif not compliant_results:
        result_type = "route_found_noncompliant"
    elif compliant_results[0]["evaluation"]["compliance_level"] == "boundary":
        result_type = "compliant_boundary"
    else:
        result_type = "compliant_clear"
    error_type = None
    if provider_payload["live_failed"]:
        error_type = "live_search_failed"
    elif provider_payload["provider_errors"]:
        error_type = "partial_provider_error"
    response = {
        "query": tracked_payload,
        "results": results,
        "meta": {
            **context,
            "app_version": APP_VERSION,
            "rule_version": rules["rule_version"],
            "data_source": provider_payload["data_source"],
            "provider_mode": provider_payload["provider_mode"],
            "live_failed": provider_payload["live_failed"],
            "warnings": provider_payload["warnings"],
            "provider_errors": provider_payload["provider_errors"],
            "provider_request_count": int(provider_payload.get("provider_request_count", 0) or 0),
            "latency_ms": elapsed_ms,
            "result_type": result_type,
            "error_type": error_type,
            "route_found": bool(results),
            "compliant_route_found": bool(compliant_results),
            "excluded_routes": [
                {
                    "template": item.get("template"),
                    "total_duration_min": item.get("total_duration_min"),
                    "reason": item["evaluation"].get("reason"),
                    "over_limit_min": item["evaluation"].get("over_limit_min"),
                }
                for item in excluded_results[:8]
            ],
        },
    }
    # 中文注释：搜索埋点只记录脱敏统计；即使埋点写入异常，也不能影响主流程返回。
    try:
        record_search_analytics(tracked_payload, response)
    except Exception:
        pass
    print(
        f"[commute] search done cost_ms={elapsed_ms} results={len(results)} "
        f"warnings={len(response['meta']['warnings'])} live_failed={response['meta']['live_failed']}",
        flush=True,
    )
    return response


def feedback_payload(payload):
    helpful = payload.get("helpful")
    if not isinstance(helpful, bool):
        raise ValueError("helpful must be a boolean")
    note = str(payload.get("note", "")).strip()
    context = tracking_context(payload)
    record_feedback({**context, "helpful": helpful, "note": note})
    return {"status": "ok"}


def review_payload(payload):
    event = record_review(payload)
    return {"status": "ok", "request_id": event["request_id"]}


def experiment_payload(payload):
    record = record_experiment(payload)
    return {"status": "ok", "case_id": record["case_id"], "summary": load_experiment_summary()}


def event_payload(payload):
    event_type = str(payload.get("event_type", "")).strip()
    if event_type != "result_shown":
        raise ValueError("unsupported event_type")
    record_result_shown(payload)
    return {"status": "ok"}


def suggest_payload(payload):
    query = str(payload.get("query", "")).strip()
    suggestions_payload = load_place_suggestions(query)
    return {
        "query": query,
        "provider": suggestions_payload["provider"],
        "suggestions": suggestions_payload["suggestions"],
        "warning": suggestions_payload["warning"],
    }


class CommuteHandler(BaseHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        self.app_dir = kwargs.pop("app_dir", APP_DIR)
        super().__init__(*args, **kwargs)

    def do_GET(self):
        if self.path == "/healthz":
            _json_response(self, _health_payload())
            return
        parsed = urlparse(self.path)
        if parsed.path == "/stats":
            _serve_file(self, self.app_dir / "stats.html")
            return
        if parsed.path == "/metrics":
            _serve_file(self, self.app_dir / "metrics.html")
            return
        if parsed.path == "/api/metrics":
            token = parse_qs(parsed.query).get("token", [""])[0]
            try:
                _json_response(self, metrics_payload(token))
            except PermissionError:
                _json_response(self, {"error": "forbidden"}, status=HTTPStatus.FORBIDDEN)
            return
        if parsed.path == "/api/stats":
            environments = parse_qs(parsed.query).get("environment", [""])[0]
            try:
                _json_response(self, stats_payload(environments or None))
            except ValueError as error:
                _json_response(self, {"error": str(error)}, status=HTTPStatus.BAD_REQUEST)
            return
        path = "index.html" if self.path in {"/", ""} else self.path.lstrip("/")
        _serve_file(self, self.app_dir / path)

    def do_POST(self):
        if self.path not in {"/api/search", "/api/suggest", "/api/feedback", "/api/event", "/api/review", "/api/experiment"}:
            self.send_error(HTTPStatus.NOT_FOUND)
            return

        try:
            content_length = int(self.headers.get("Content-Length", "0"))
            raw_body = self.rfile.read(content_length)
            payload = json.loads(raw_body.decode("utf-8") or "{}")
        except json.JSONDecodeError as error:
            _json_response(
                self,
                _error_payload(error, "invalid_json"),
                status=HTTPStatus.BAD_REQUEST,
            )
            return
        if self.path == "/api/suggest":
            try:
                _json_response(self, suggest_payload(payload))
            except Exception as error:
                print(f"[commute] suggest failed: {error}", flush=True)
                traceback.print_exc()
                _json_response(
                    self,
                    _error_payload(error, "suggest_failed"),
                    status=HTTPStatus.INTERNAL_SERVER_ERROR,
                )
            return
        if self.path == "/api/feedback":
            try:
                _json_response(self, feedback_payload(payload))
            except ValueError as error:
                _json_response(self, {"error": str(error)}, status=HTTPStatus.BAD_REQUEST)
            return
        if self.path == "/api/review":
            try:
                _json_response(self, review_payload(payload))
            except ValueError as error:
                _json_response(self, {"error": str(error)}, status=HTTPStatus.BAD_REQUEST)
            return
        if self.path == "/api/experiment":
            try:
                _json_response(self, experiment_payload(payload))
            except ValueError as error:
                _json_response(self, {"error": str(error)}, status=HTTPStatus.BAD_REQUEST)
            return
        if self.path == "/api/event":
            try:
                _json_response(self, event_payload(payload))
            except ValueError as error:
                _json_response(self, {"error": str(error)}, status=HTTPStatus.BAD_REQUEST)
            return
        try:
            _json_response(self, search_payload(payload))
        except Exception as error:
            print(f"[commute] search failed: {error}", flush=True)
            traceback.print_exc()
            _json_response(
                self,
                _error_payload(error, "search_failed"),
                status=HTTPStatus.INTERNAL_SERVER_ERROR,
            )

    def log_message(self, format, *args):
        return


def build_handler(app_dir=APP_DIR):
    return partial(CommuteHandler, app_dir=app_dir)


def main():
    if os.getenv("COMMUTE_SERVER_IMPORT_ONLY") == "1":
        print("Commute Combo import check OK")
        return
    bind_host, bind_port = _server_bind_address()
    server = ThreadingHTTPServer((bind_host, bind_port), build_handler())
    print(f"Serving Commute Combo on http://{bind_host}:{bind_port}")
    server.serve_forever()


if __name__ == "__main__":
    main()
