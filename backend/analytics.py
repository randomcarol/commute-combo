import hashlib
import json
import math
import os
import re
import sqlite3
import statistics
import threading
import uuid
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from backend.rules import APP_VERSION, RULE_VERSION


_WRITE_LOCK = threading.Lock()
VALID_ENVIRONMENTS = ("dev", "test", "demo", "self_test", "prod")
DEFAULT_DASHBOARD_ENVIRONMENTS = ("self_test", "prod")
_ROUTE_TEMPLATES = ("walk", "bike", "subway", "bike->subway->bike")
_REVIEW_OUTCOMES = {
    "map_consistent", "tool_shorter", "tool_longer", "station_or_exit_wrong",
    "alias_effective", "screenshot_usable", "no_compliant_plan",
}
_EXPERIMENT_FIELDS = {
    "request_id", "environment", "data_source", "test_date", "time_period", "case_id", "rule_version",
    "manual_search_seconds", "manual_attempt_count", "manual_best_minutes",
    "tool_search_seconds", "tool_best_minutes", "tool_search_success",
    "found_compliant_plan", "matches_manual", "top1_valid", "alias_improved",
    "false_compliance", "note",
}
_FEEDBACK_THEMES = {
    "station_accuracy": ("地铁站", "站点", "站名", "接驳", "换乘", "出入口"),
    "speed_or_latency": ("太慢", "很慢", "慢", "等太久", "耗时", "卡", "延迟", "超时"),
    "alias_coverage": ("门口", "北门", "南门", "西塔", "东塔", "楼栋", "别名"),
    "empty_or_compliance": ("无结果", "搜不到", "不合规", "超范围", "没方案", "不显示"),
    "explanation_or_screenshot": ("截图", "解释", "说明", "看不懂", "复核"),
}


def _project_root():
    return Path(__file__).resolve().parent.parent


def analytics_log_path():
    configured = os.getenv("COMMUTE_ANALYTICS_LOG_PATH", "").strip()
    return Path(configured) if configured else _project_root() / "local-data" / "analytics" / "commute-events.jsonl"


def feedback_db_path():
    configured = os.getenv("COMMUTE_FEEDBACK_DB_PATH", "").strip()
    return Path(configured) if configured else _project_root() / "local-data" / "feedback" / "commute-feedback.db"


def experiment_log_path():
    configured = os.getenv("COMMUTE_EXPERIMENT_LOG_PATH", "").strip()
    return Path(configured) if configured else _project_root() / "local-data" / "experiments" / "case-records.jsonl"


def metrics_token():
    return os.getenv("COMMUTE_METRICS_TOKEN", "").strip()


def _utc_now_iso():
    return datetime.now(timezone.utc).isoformat()


def _hash_text(value):
    normalized = str(value or "").strip()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16] if normalized else ""


def _clean_identifier(value, *, fallback="", max_length=80):
    normalized = str(value or "").strip() or fallback
    if not normalized:
        return ""
    if len(normalized) > max_length or not re.fullmatch(r"[A-Za-z0-9._:-]+", normalized):
        raise ValueError("invalid identifier")
    return normalized


def normalize_environment(value, data_source=None):
    if data_source == "mock":
        return "demo"
    normalized = str(value or os.getenv("COMMUTE_ENVIRONMENT", "dev")).strip().lower()
    if normalized not in VALID_ENVIRONMENTS:
        raise ValueError(f"invalid environment: {normalized}")
    return normalized


def tracking_context(payload=None, *, data_source=None):
    payload = payload if isinstance(payload, dict) else {}
    return {
        "request_id": _clean_identifier(payload.get("request_id"), fallback=str(uuid.uuid4())),
        "anonymous_session_id": _clean_identifier(payload.get("anonymous_session_id"), fallback="anonymous"),
        "environment": normalize_environment(payload.get("environment"), data_source=data_source),
        "app_version": _clean_identifier(payload.get("app_version"), fallback=APP_VERSION, max_length=32),
        "rule_version": _clean_identifier(payload.get("rule_version") or (payload.get("rules") or {}).get("rule_version"), fallback=RULE_VERSION, max_length=48),
    }


def _append_jsonl(path, event):
    path.parent.mkdir(parents=True, exist_ok=True)
    with _WRITE_LOCK:
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, ensure_ascii=False) + "\n")


def _append_event(event):
    _append_jsonl(analytics_log_path(), event)


def _read_jsonl(path):
    if not path.exists():
        return []
    events = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            try:
                event = json.loads(line)
            except (json.JSONDecodeError, TypeError):
                continue
            if isinstance(event, dict):
                events.append(event)
    return events


def _route_type_distribution(results):
    best_by_template = {}
    for item in results:
        template = item.get("template")
        if template not in _ROUTE_TEMPLATES:
            continue
        current = best_by_template.get(template)
        if current is None or int(item.get("total_duration_min") or 0) < int(current.get("total_duration_min") or 0):
            best_by_template[template] = item
    return {
        template: {"matched": template in best_by_template, "total_duration_min": best_by_template.get(template, {}).get("total_duration_min")}
        for template in _ROUTE_TEMPLATES
    }


def _result_type(results, meta):
    if meta.get("error_type"):
        return "error"
    if not results:
        return "no_route"
    compliant = [item for item in results if item.get("evaluation", {}).get("is_compliant")]
    if not compliant:
        return "route_found_noncompliant"
    if compliant[0].get("evaluation", {}).get("compliance_level") == "boundary":
        return "compliant_boundary"
    return "compliant_clear"


def record_search_submit(payload):
    context = tracking_context(payload)
    _append_event({
        "event_type": "search_submit", "timestamp": _utc_now_iso(), **context,
        "office_hash": _hash_text(payload.get("office")), "home_hash": _hash_text(payload.get("home")),
        "office_length": len(str(payload.get("office", "")).strip()), "home_length": len(str(payload.get("home", "")).strip()),
    })
    return context


def record_result_shown(result):
    evaluation = result.get("evaluation", {}) if isinstance(result, dict) else {}
    context = tracking_context(result, data_source=result.get("data_source"))
    _append_event({
        "event_type": "result_shown", "timestamp": _utc_now_iso(), **context,
        "provider": result.get("provider"), "best_template": result.get("template"),
        "template": result.get("template"), "total_duration_min": result.get("total_duration_min"),
        "best_total_duration_min": result.get("total_duration_min"),
        "alias_used": bool(result.get("alias_used") or result.get("used_alias_fallback")),
        "result_type": result.get("result_type") or (
            "compliant_boundary" if evaluation.get("compliance_level") == "boundary" else
            "compliant_clear" if evaluation.get("is_compliant") else "route_found_noncompliant"
        ),
        "is_compliant": bool(evaluation.get("is_compliant")), "error_type": None,
    })


def _search_event(payload, response):
    results = response.get("results", [])
    meta = response.get("meta", {})
    context = tracking_context(payload, data_source=meta.get("data_source"))
    compliant_count = sum(1 for item in results if item.get("evaluation", {}).get("is_compliant"))
    alias_count = sum(1 for item in results if item.get("used_alias_fallback"))
    best = results[0] if results else {}
    return {
        "event_type": "search_completed", "timestamp": _utc_now_iso(), **context,
        "office_hash": _hash_text(payload.get("office")), "home_hash": _hash_text(payload.get("home")),
        "office_length": len(str(payload.get("office", "")).strip()), "home_length": len(str(payload.get("home", "")).strip()),
        "latency_ms": int(meta.get("latency_ms") or 0), "provider_request_count": int(meta.get("provider_request_count") or 0),
        "result_type": meta.get("result_type") or _result_type(results, meta), "error_type": meta.get("error_type"),
        "route_found": bool(results), "compliant_route_found": compliant_count > 0,
        "result_count": len(results), "compliant_result_count": compliant_count,
        "has_alias_result": alias_count > 0, "alias_result_count": alias_count,
        "alias_used": bool(best.get("used_alias_fallback")), "best_used_alias_fallback": bool(best.get("used_alias_fallback")),
        "best_alias_type": best.get("alias_type"), "best_exact_duration_min": best.get("exact_total_duration_min"),
        "best_alias_duration_min": best.get("alias_total_duration_min"), "data_source": meta.get("data_source"),
        "provider_mode": meta.get("provider_mode"), "live_failed": bool(meta.get("live_failed")),
        "warning_count": len(meta.get("warnings", [])), "provider_error_count": len(meta.get("provider_errors", [])),
        "result_without_compliant": bool(results) and compliant_count == 0,
        "best_template": best.get("template"), "best_provider": best.get("provider"),
        "best_total_duration_min": best.get("total_duration_min"), "best_is_compliant": bool(best.get("evaluation", {}).get("is_compliant")),
        "best_alias_saved_min": max(0, int(best.get("exact_total_duration_min") or 0) - int(best.get("alias_total_duration_min") or 0)) if best.get("used_alias_fallback") else None,
        "route_type_distribution": _route_type_distribution(results),
    }


def record_search_analytics(payload, response):
    event = _search_event(payload, response)
    _append_event(event)
    return event


def _match_feedback_themes(note):
    normalized = str(note or "").strip()
    if not normalized:
        return []
    themes = [theme for theme, keywords in _FEEDBACK_THEMES.items() if any(word in normalized for word in keywords)]
    return themes or ["other"]


def _init_feedback_db(connection):
    connection.execute("""
        create table if not exists feedback_events (
            id integer primary key autoincrement, created_at text not null,
            helpful integer not null, note text not null default '', request_id text not null default '',
            anonymous_session_id text not null default '', environment text not null default 'dev',
            app_version text not null default '', rule_version text not null default ''
        )
    """)
    existing = {row[1] for row in connection.execute("pragma table_info(feedback_events)")}
    columns = {
        "request_id": "text not null default ''", "anonymous_session_id": "text not null default ''",
        "environment": "text not null default 'dev'", "app_version": "text not null default ''",
        "rule_version": "text not null default ''",
    }
    for name, definition in columns.items():
        if name not in existing:
            connection.execute(f"alter table feedback_events add column {name} {definition}")
    connection.commit()


def record_feedback(payload):
    context = tracking_context(payload)
    path = feedback_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as connection:
        _init_feedback_db(connection)
        connection.execute("""
            insert into feedback_events
                (created_at, helpful, note, request_id, anonymous_session_id, environment, app_version, rule_version)
            values (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            _utc_now_iso(), 1 if payload.get("helpful") else 0, str(payload.get("note", "")).strip()[:300],
            context["request_id"], context["anonymous_session_id"], context["environment"], context["app_version"], context["rule_version"],
        ))
        connection.commit()


def record_review(payload):
    context = tracking_context(payload)
    outcomes = payload.get("outcomes") or []
    if not isinstance(outcomes, list) or not outcomes or any(item not in _REVIEW_OUTCOMES for item in outcomes):
        raise ValueError("invalid review outcomes")
    actual_minutes = payload.get("actual_minutes")
    if actual_minutes not in (None, ""):
        actual_minutes = int(actual_minutes)
        if actual_minutes < 0 or actual_minutes > 600:
            raise ValueError("invalid actual_minutes")
    event = {
        "event_type": "result_reviewed", "timestamp": _utc_now_iso(), **context,
        "outcomes": list(dict.fromkeys(outcomes)), "actual_minutes": actual_minutes if actual_minutes not in (None, "") else None,
        "issue_category": _clean_identifier(payload.get("issue_category"), fallback="none", max_length=48),
        "note": str(payload.get("note", "")).strip()[:300],
    }
    _append_event(event)
    return event


def record_experiment(payload):
    sanitized = {key: payload.get(key) for key in _EXPERIMENT_FIELDS}
    if payload.get("environment") != "self_test" or payload.get("data_source") != "live":
        raise ValueError("experiments require self_test environment and live data")
    case_id = str(sanitized.get("case_id") or "").strip().upper()
    if not re.fullmatch(r"CASE-[0-9]{3,6}", case_id):
        raise ValueError("case_id must look like CASE-001")
    sanitized["case_id"] = case_id
    sanitized["request_id"] = _clean_identifier(sanitized.get("request_id"), fallback="")
    sanitized["rule_version"] = _clean_identifier(sanitized.get("rule_version"), fallback=RULE_VERSION, max_length=48)
    for field in ("manual_search_seconds", "manual_attempt_count", "manual_best_minutes", "tool_search_seconds", "tool_best_minutes"):
        value = sanitized.get(field)
        sanitized[field] = None if value in (None, "") else float(value)
        if sanitized[field] is not None and sanitized[field] < 0:
            raise ValueError(f"invalid {field}")
    for field in ("tool_search_success", "found_compliant_plan", "matches_manual", "top1_valid", "alias_improved", "false_compliance"):
        sanitized[field] = bool(sanitized.get(field))
    sanitized["note"] = str(sanitized.get("note") or "").strip()[:300]
    sanitized["recorded_at"] = _utc_now_iso()
    sanitized["environment"] = "self_test"
    sanitized["data_source"] = "live"
    _append_jsonl(experiment_log_path(), sanitized)
    return sanitized


def _environment_set(environments):
    if environments is None:
        return None
    if isinstance(environments, str):
        environments = [item.strip() for item in environments.split(",") if item.strip()]
    invalid = set(environments) - set(VALID_ENVIRONMENTS)
    if invalid:
        raise ValueError(f"invalid environments: {','.join(sorted(invalid))}")
    return set(environments)


def _event_environment(event):
    return "demo" if event.get("data_source") == "mock" else event.get("environment") or "legacy"


def _filtered_events(environments=None):
    selected = _environment_set(environments)
    events = _read_jsonl(analytics_log_path())
    return events if selected is None else [event for event in events if _event_environment(event) in selected]


def _percentile(values, percentile):
    if not values:
        return None
    ordered = sorted(float(value) for value in values)
    return round(ordered[max(0, math.ceil((percentile / 100) * len(ordered)) - 1)], 1)


def _empty_metrics_summary():
    return {
        "total_searches": 0, "successful_searches": 0, "empty_searches": 0, "compliant_searches": 0,
        "result_without_compliant_searches": 0, "warning_searches": 0, "alias_searches": 0,
        "live_failed_searches": 0, "effective_measurement_completed": 0, "false_compliance_count": 0,
        "provider_breakdown": {}, "result_type_breakdown": {}, "environment_breakdown": {}, "feedback_theme_breakdown": {},
        "alias_uplift": {"count": 0, "average_saved_min": None, "max_saved_min": None}, "template_breakdown": {},
        "latency_p50_ms": None, "latency_p95_ms": None, "provider_request_count_total": 0,
    }


def _feedback_summary(environments=None):
    path = feedback_db_path()
    empty = {"feedback_total": 0, "feedback_helpful_count": 0, "feedback_unhelpful_count": 0, "feedback_helpful_rate": 0.0, "feedback_theme_breakdown": {}}
    if not path.exists():
        return empty
    selected = _environment_set(environments)
    with sqlite3.connect(path) as connection:
        _init_feedback_db(connection)
        rows = connection.execute("select helpful, note, environment from feedback_events").fetchall()
    if selected is not None:
        rows = [row for row in rows if row[2] in selected]
    total = len(rows)
    helpful = sum(int(row[0] or 0) for row in rows)
    themes = Counter(theme for _, note, _ in rows for theme in _match_feedback_themes(note))
    return {
        "feedback_total": total, "feedback_helpful_count": helpful, "feedback_unhelpful_count": max(0, total - helpful),
        "feedback_helpful_rate": round(helpful / total, 4) if total else 0.0, "feedback_theme_breakdown": dict(themes),
    }


def load_metrics_summary(environments=None):
    events = _filtered_events(environments)
    searches = [event for event in events if event.get("event_type") == "search_completed"]
    reviews = {event.get("request_id"): event for event in events if event.get("event_type") == "result_reviewed"}
    summary = _empty_metrics_summary()
    templates, providers, result_types, environment_counts = Counter(), Counter(), Counter(), Counter()
    alias_saved_minutes, latencies = [], []
    for event in searches:
        result_count = int(event.get("result_count", 0) or 0)
        compliant_count = int(event.get("compliant_result_count", 0) or 0)
        summary["total_searches"] += 1
        summary["successful_searches"] += int(result_count > 0)
        summary["empty_searches"] += int(result_count == 0)
        summary["compliant_searches"] += int(compliant_count > 0)
        summary["result_without_compliant_searches"] += int(result_count > 0 and compliant_count == 0)
        summary["warning_searches"] += int(int(event.get("warning_count", 0) or 0) > 0 or int(event.get("provider_error_count", 0) or 0) > 0)
        summary["alias_searches"] += int(bool(event.get("has_alias_result")))
        summary["live_failed_searches"] += int(bool(event.get("live_failed")))
        summary["provider_request_count_total"] += int(event.get("provider_request_count", 0) or 0)
        templates.update([event.get("best_template")] if event.get("best_template") else [])
        providers.update([event.get("best_provider")] if event.get("best_provider") else [])
        result_types.update([event.get("result_type") or ("route_found" if result_count else "no_route")])
        environment_counts.update([_event_environment(event)])
        latency = event.get("latency_ms")
        if isinstance(latency, (int, float)) and latency >= 0:
            latencies.append(float(latency))
        saved = event.get("best_alias_saved_min")
        if not isinstance(saved, (int, float)) and event.get("best_used_alias_fallback"):
            exact = event.get("best_exact_duration_min")
            alias = event.get("best_alias_duration_min")
            if isinstance(exact, (int, float)) and isinstance(alias, (int, float)):
                saved = float(exact) - float(alias)
        if isinstance(saved, (int, float)) and saved > 0:
            alias_saved_minutes.append(float(saved))
        outcomes = set(reviews.get(event.get("request_id"), {}).get("outcomes") or [])
        if compliant_count > 0 and {"map_consistent", "screenshot_usable"}.issubset(outcomes) and "no_compliant_plan" not in outcomes:
            summary["effective_measurement_completed"] += 1
        if compliant_count > 0 and "no_compliant_plan" in outcomes:
            summary["false_compliance_count"] += 1
    summary.update({
        "provider_breakdown": dict(providers), "result_type_breakdown": dict(result_types),
        "environment_breakdown": dict(environment_counts), "template_breakdown": dict(templates),
        "latency_p50_ms": _percentile(latencies, 50), "latency_p95_ms": _percentile(latencies, 95),
        "alias_uplift": {
            "count": len(alias_saved_minutes), "average_saved_min": round(statistics.fmean(alias_saved_minutes), 1) if alias_saved_minutes else None,
            "max_saved_min": round(max(alias_saved_minutes), 1) if alias_saved_minutes else None,
        },
    })
    summary.update(_feedback_summary(environments))
    return summary


def load_experiment_summary():
    latest_by_case = {}
    for record in _read_jsonl(experiment_log_path()):
        if record.get("case_id"):
            latest_by_case[record["case_id"]] = record
    records = list(latest_by_case.values())
    differences = [abs(float(item["tool_best_minutes"]) - float(item["manual_best_minutes"])) for item in records if item.get("tool_best_minutes") is not None and item.get("manual_best_minutes") is not None]
    time_changes = [float(item["manual_search_seconds"]) - float(item["tool_search_seconds"]) for item in records if item.get("manual_search_seconds") is not None and item.get("tool_search_seconds") is not None]
    count = len(records)
    rate = lambda numerator: round(numerator / count, 4) if count else 0.0
    return {
        "case_count": count, "live_search_success_rate": rate(sum(bool(item.get("tool_search_success")) for item in records)),
        "manual_match_rate": rate(sum(bool(item.get("matches_manual")) for item in records)),
        "top1_valid_rate": rate(sum(bool(item.get("top1_valid")) for item in records)),
        "average_abs_best_difference_min": round(statistics.fmean(differences), 1) if differences else None,
        "median_abs_best_difference_min": round(statistics.median(differences), 1) if differences else None,
        "average_task_time_change_seconds": round(statistics.fmean(time_changes), 1) if time_changes else None,
        "alias_effective_case_count": sum(bool(item.get("alias_improved")) for item in records),
        "false_compliance_case_count": sum(bool(item.get("false_compliance")) for item in records),
        "small_sample": count < 20,
        "sample_note": "样本量较小，仅用于探索性验证" if count < 20 else "已达到首轮 20 个地址样本基准",
    }


def load_stats_summary(environments=None):
    summary = load_metrics_summary(environments)
    searches = [event for event in _filtered_events(environments) if event.get("event_type") == "search_completed"]
    route_distribution = {}
    for event in searches:
        for template, detail in (event.get("route_type_distribution") or {}).items():
            bucket = route_distribution.setdefault(template, {"matched_count": 0, "shown_count": 0, "duration_sum": 0.0})
            bucket["shown_count"] += 1
            if detail.get("matched"):
                bucket["matched_count"] += 1
                if isinstance(detail.get("total_duration_min"), (int, float)):
                    bucket["duration_sum"] += float(detail["total_duration_min"])
    summary["route_type_distribution"] = {
        template: {"matched_count": values["matched_count"], "shown_count": values["shown_count"], "average_duration_min": round(values["duration_sum"] / values["matched_count"], 1) if values["matched_count"] else None}
        for template, values in route_distribution.items()
    }
    summary["recent_searches"] = [{
        "timestamp": event.get("timestamp"), "request_id": event.get("request_id"), "environment": _event_environment(event),
        "home_hash": event.get("home_hash"), "office_hash": event.get("office_hash"), "template": event.get("best_template"),
        "provider": event.get("best_provider"), "total_duration_min": event.get("best_total_duration_min"),
        "is_compliant": bool(event.get("best_is_compliant")), "result_type": event.get("result_type"),
    } for event in reversed(searches[-10:])]
    summary["selected_environments"] = sorted(_environment_set(environments) or [])
    summary["experiment_summary"] = load_experiment_summary()
    return summary
