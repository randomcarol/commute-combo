import json
import re
import threading
import time
from datetime import date, timedelta
from urllib.parse import urlencode, urlparse
from urllib.request import urlopen

from backend.config import load_config
from backend.rules import DEFAULT_RULES, LEGAL_ROUTE_TEMPLATES, evaluate_plan, normalize_rules

PROVIDER_PROFILES = {
    "amap": {"offset": 0, "hint": "高德主算路会自动识别地点和附近地铁站"},
}
PROVIDER_LABELS = {
    "amap": "高德地图",
    "baidu": "百度地图",
    "qq": "腾讯地图",
}

MAX_OFFICE_CANDIDATES = 1
MAX_HOME_CANDIDATES = 1
MAX_STATION_CANDIDATES = 5
LIVE_TEMPLATES = LEGAL_ROUTE_TEMPLATES
AMAP_SUGGEST_LIMIT = 5
AMAP_NEARBY_STATION_LIMIT = 5
TRANSIT_STRATEGIES = (
    {"id": "app_default", "value": "0", "label": "高德默认策略"},
)
HOME_ALIAS_SUFFIXES = ("北门", "南门", "西门")
OFFICE_ALIAS_SUFFIXES = ("西塔", "东塔", "T2栋")
KNOWN_ALIAS_SUFFIXES = tuple(dict.fromkeys(HOME_ALIAS_SUFFIXES + OFFICE_ALIAS_SUFFIXES + ("东门", "1门", "2门")))

TEMPLATE_LIBRARY = {
    "walk": [{"mode": "walk", "duration_min": 29}],
    "bike": [{"mode": "bike", "duration_min": 19}],
    "subway": [
        {"mode": "subway", "duration_min": 10},
    ],
    "bike->subway->bike": [
        {"mode": "bike", "duration_min": 5},
        {"mode": "subway", "duration_min": 10},
        {"mode": "bike", "duration_min": 4},
    ],
}

DEMO_WARNING = "当前展示的是演示数据，不代表真实地图时间。"
LIVE_EMPTY_WARNING = "当前未获取到真实地图结果，请检查 API key、配额或输入地址。"
LIVE_KEY_WARNING = "已切到实时模式，但还没有配置可用的地图 API key。"
AMAP_MIN_REQUEST_INTERVAL_SEC = 0.38
AMAP_SOFT_TIMEOUT_SEC = 1.5
ALIAS_EXPANSION_MARGIN_MIN = 3
_FETCH_LOCK = threading.Lock()
_NEXT_AMAP_FETCH_AT = 0.0


class _AmapSoftTimeoutError(TimeoutError):
    pass


def _debug_log(message):
    print(f"[commute] {message}", flush=True)


def _split_candidates(raw_value, fallback):
    if not raw_value:
        return fallback
    if isinstance(raw_value, list):
        values = raw_value
    else:
        values = str(raw_value).split(",")
    normalized = [value.strip() for value in values if value.strip()]
    return normalized or fallback


def _has_candidate_input(raw_value):
    if raw_value is None:
        return False
    if isinstance(raw_value, list):
        return any(str(value).strip() for value in raw_value)
    return bool(str(raw_value).strip())


def _text_bias(*parts):
    return sum(ord(char) for part in parts for char in str(part)) % 3


def _decorate_segments(segments, home_label, office_label, station_name, offset):
    decorated = []
    total_segments = len(segments)
    for index, segment in enumerate(segments):
        duration = max(1, segment["duration_min"] + offset)
        if total_segments == 1:
            from_name = home_label
            to_name = office_label
        elif index == 0:
            from_name = home_label
            to_name = station_name
        elif index == total_segments - 1:
            from_name = station_name
            to_name = office_label
        else:
            from_name = station_name
            to_name = station_name
        decorated.append(
            {
                "mode": segment["mode"],
                "duration_min": duration,
                "from_name": from_name,
                "to_name": to_name,
            }
        )
    return decorated


def _normalize_station_name(name):
    if not isinstance(name, str):
        return None
    normalized = name.strip()
    if not normalized:
        return None
    if normalized.endswith("站"):
        return normalized
    if any("\u4e00" <= char <= "\u9fff" for char in normalized):
        return f"{normalized}站"
    return normalized


def _station_name_key(name):
    normalized = _normalize_station_name(name)
    if not normalized:
        return ""
    return normalized[:-1] if normalized.endswith("站") else normalized


def _station_matches_name(point, expected_name):
    point_key = _station_name_key(point.get("label", ""))
    expected_key = _station_name_key(expected_name)
    if not point_key or not expected_key:
        return False
    return point_key == expected_key or point_key in expected_key or expected_key in point_key


def _coerce_stop_name(value):
    if isinstance(value, str):
        return _normalize_station_name(value)
    if isinstance(value, dict):
        for key in ("name", "title", "station_name"):
            candidate = _normalize_station_name(value.get(key))
            if candidate:
                return candidate
    return None


def _normalize_transit_line_name(value):
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    if not normalized:
        return None
    normalized = normalized.replace("地铁", "")
    normalized = re.sub(r"\(.*?\)", "", normalized).strip()
    match = re.search(r"(\d+号线)", normalized)
    if match:
        return match.group(1)
    if re.fullmatch(r"[sS]\d+线", normalized):
        return normalized.upper()
    if normalized.endswith("机场线"):
        return normalized
    return None


def _looks_like_subway_station_name(name):
    normalized = str(name).strip()
    if not normalized:
        return False
    return normalized.endswith("站") or "地铁站" in normalized or "号线" in normalized


def _collect_station_pairs(node):
    pairs = []
    if isinstance(node, dict):
        for start_key, end_key in (
            ("departure_stop", "arrival_stop"),
            ("on_station", "off_station"),
            ("geton", "getoff"),
            ("origin_stop", "terminal_stop"),
            ("start_stop", "end_stop"),
            ("start_station", "end_station"),
        ):
            start_name = _coerce_stop_name(node.get(start_key))
            end_name = _coerce_stop_name(node.get(end_key))
            if start_name and end_name:
                pairs.append((start_name, end_name))
        for value in node.values():
            pairs.extend(_collect_station_pairs(value))
    elif isinstance(node, list):
        for item in node:
            pairs.extend(_collect_station_pairs(item))
    return pairs


def _pick_station_pair(pairs):
    if not pairs:
        return None, None
    return pairs[0][0], pairs[-1][1]


def _amap_transit_station_pair(route):
    segments = route.get("segments", [])
    if isinstance(segments, dict):
        segments = [segments]
    elif not isinstance(segments, list):
        segments = []
    pairs = []
    line_names = []
    for segment in segments:
        if not isinstance(segment, dict):
            continue
        bus = segment.get("bus", {})
        if not isinstance(bus, dict):
            continue
        buslines = bus.get("buslines", []) or []
        if isinstance(buslines, dict):
            buslines = [buslines]
        for busline in buslines:
            if not isinstance(busline, dict):
                continue
            line_name = _normalize_transit_line_name(busline.get("name"))
            if not line_name:
                continue
            if line_name and line_name not in line_names:
                line_names.append(line_name)
            departure = _coerce_stop_name(busline.get("departure_stop"))
            arrival = _coerce_stop_name(busline.get("arrival_stop"))
            if departure and arrival:
                pairs.append((departure, arrival))
    if pairs:
        entry_name, exit_name = pairs[0][0], pairs[-1][1]
        return entry_name, exit_name, " / ".join(line_names) if line_names else None
    return None, None, None


def _amap_transit_leg_breakdown(route):
    total_seconds = _route_seconds(route)
    segments = route.get("segments", [])
    if isinstance(segments, dict):
        segments = [segments]
    elif not isinstance(segments, list):
        segments = []

    access_seconds = 0
    egress_seconds = 0
    first_walking = None
    last_walking = None

    for segment in segments:
        if not isinstance(segment, dict):
            continue
        walking = segment.get("walking")
        if isinstance(walking, dict) and first_walking is None:
            first_walking = walking
        if isinstance(walking, dict):
            last_walking = walking

    if isinstance(first_walking, dict):
        access_seconds = _duration_seconds(first_walking.get("duration"))
    if isinstance(last_walking, dict):
        egress_seconds = _duration_seconds(last_walking.get("duration"))

    transit_seconds = max(0, total_seconds - access_seconds - egress_seconds)
    return {
        "access_duration_min": _pick_duration_minutes(access_seconds) if access_seconds else 0,
        "egress_duration_min": _pick_duration_minutes(egress_seconds) if egress_seconds else 0,
        "transit_only_duration_min": _pick_duration_minutes(transit_seconds) if transit_seconds else 0,
        "total_duration_min": _pick_duration_minutes(total_seconds),
    }


def _amap_error_detail(payload, default_message):
    if not isinstance(payload, dict):
        return default_message
    fields = []
    for key in ("errmsg", "errdetail", "info", "infocode", "errcode", "status"):
        value = payload.get(key)
        if value in (None, "", []):
            continue
        fields.append(f"{key}={value}")
    if not fields:
        return default_message
    return f"{default_message}: {'; '.join(fields)}"


def _baidu_transit_station_pair(route):
    return _pick_station_pair(_collect_station_pairs(route.get("steps", route)))


def _qq_transit_station_pair(route):
    return _pick_station_pair(_collect_station_pairs(route.get("steps", route)))


def _mock_routes(payload):
    office = payload.get("office", "字节跳动深圳湾工区")
    home = payload.get("home", "南山区示例花园")
    office_aliases = _split_candidates(payload.get("office_aliases"), [office])
    home_gates = _split_candidates(payload.get("home_gates"), [home])
    stations_input = payload.get("stations")
    stations_user_supplied = _has_candidate_input(stations_input)
    stations = _split_candidates(stations_input, ["后海站", "科苑站", "高新园站"])

    office_label = office_aliases[_text_bias(office, "office") % len(office_aliases)]
    home_label = home_gates[_text_bias(home, "home") % len(home_gates)]

    options = []
    for provider, profile in PROVIDER_PROFILES.items():
        for template, segments in TEMPLATE_LIBRARY.items():
            station_name = stations[_text_bias(provider, template, office, home) % len(stations)]
            station_display_name = station_name if stations_user_supplied else "系统自动匹配地铁站"
            offset = profile["offset"] + _text_bias(office_label, home_label, template) - 1
            route_segments = _decorate_segments(
                segments,
                home_label=home_label,
                office_label=office_label,
                station_name=station_display_name,
                offset=offset,
            )
            options.append(
                {
                    "provider": provider,
                    "template": template,
                    "segments": route_segments,
                    "screenshot_hint": f"{profile['hint']}，优先检查 {station_name} 这一段。",
                }
            )
    return options


def _provider_error_message(provider, error):
    provider_label = PROVIDER_LABELS.get(provider, provider)
    error_text = str(error).strip() or error.__class__.__name__
    return f"{provider_label}: {error_text}"


def _append_unique_error(errors, provider, message):
    normalized = str(message).strip()
    if not normalized:
        return
    candidate = {"provider": provider, "message": normalized}
    if candidate not in errors:
        errors.append(candidate)


def _is_amap_soft_timeout_error(error):
    return isinstance(error, _AmapSoftTimeoutError)


def _point_from_location(location, label, citycode="", address="", poi_id=""):
    if not isinstance(location, str) or "," not in location:
        raise ValueError(f"invalid location for {label}")
    lng, lat = [float(item) for item in location.split(",", 1)]
    return {
        "lat": lat,
        "lng": lng,
        "citycode": citycode or "",
        "label": label,
        "address": address,
        "poi_id": str(poi_id or "").strip(),
    }


def _point_from_selection(selection, fallback_label):
    if not isinstance(selection, dict):
        return None
    location = selection.get("location")
    if not location:
        return None
    label = selection.get("name") or fallback_label
    address = selection.get("address", "")
    citycode = selection.get("citycode") or selection.get("adcode") or ""
    poi_id = selection.get("id") or selection.get("poi_id") or ""
    return _point_from_location(location, label, citycode=citycode, address=address, poi_id=poi_id)


def _fetch_json(url):
    global _NEXT_AMAP_FETCH_AT
    started_at = time.monotonic()
    if "restapi.amap.com" in url:
        with _FETCH_LOCK:
            now = time.monotonic()
            wait_sec = max(0.0, _NEXT_AMAP_FETCH_AT - now)
            if wait_sec > 0:
                time.sleep(wait_sec)
            _NEXT_AMAP_FETCH_AT = time.monotonic() + AMAP_MIN_REQUEST_INTERVAL_SEC
    parsed = urlparse(url)
    route_name = parsed.path.rsplit("/", 1)[-1] or parsed.path
    try:
        with urlopen(url, timeout=10) as response:
            payload = json.loads(response.read().decode("utf-8"))
        elapsed_ms = int((time.monotonic() - started_at) * 1000)
        _debug_log(f"amap request ok type={route_name} cost_ms={elapsed_ms}")
        return payload
    except Exception as error:
        elapsed_ms = int((time.monotonic() - started_at) * 1000)
        _debug_log(f"amap request failed type={route_name} cost_ms={elapsed_ms} error={error}")
        raise


def _request_type_from_url(url):
    parsed = urlparse(url)
    return parsed.path.rsplit("/", 1)[-1] or parsed.path


def _coord_from_text(raw_value):
    if not isinstance(raw_value, str) or "," not in raw_value:
        return None
    left, right = [item.strip() for item in raw_value.split(",", 1)]
    try:
        first = float(left)
        second = float(right)
    except ValueError:
        return None
    return {
        "lat": second,
        "lng": first,
        "citycode": "",
        "label": raw_value,
    }


def _build_live_payload_context(payload):
    office = str(payload.get("office", "")).strip()
    home = str(payload.get("home", "")).strip()
    return {
        "office": office,
        "home": home,
        "office_selection": payload.get("office_selection"),
        "home_selection": payload.get("home_selection"),
    }


def _pick_duration_minutes(raw_seconds):
    if raw_seconds is None:
        raise ValueError("missing duration")
    seconds = float(raw_seconds)
    minutes = max(1, round(seconds / 60))
    return int(minutes)


def _duration_seconds(raw_seconds):
    if raw_seconds in (None, "", []):
        return 0
    return max(0, int(round(float(raw_seconds))))


def _route_seconds(raw_route):
    if not isinstance(raw_route, dict):
        return 0
    cost = raw_route.get("cost")
    if isinstance(cost, dict):
        value = cost.get("duration")
        if value not in (None, "", []):
            return _duration_seconds(value)
    value = raw_route.get("duration")
    if value not in (None, "", []):
        return _duration_seconds(value)
    return 0


def _pick_best_route_candidate(candidates):
    normalized_candidates = []
    for candidate in candidates or []:
        if not isinstance(candidate, dict):
            continue
        seconds = _route_seconds(candidate)
        if seconds <= 0:
            continue
        normalized_candidates.append((seconds, candidate))
    if not normalized_candidates:
        return None
    normalized_candidates.sort(key=lambda item: item[0])
    return normalized_candidates[0][1]


def _station_pairs(stations):
    if not stations:
        return []
    pairs = []
    for start in stations:
        for end in stations:
            pairs.append((start, end))
    return pairs


def _best_option(candidates):
    if not candidates:
        return None
    return min(candidates, key=lambda item: sum(segment["duration_min"] for segment in item["segments"]))


def _default_transit_time_profiles(today=None):
    today = today or date.today()

    weekday_date = today
    while weekday_date.weekday() >= 5:
        weekday_date += timedelta(days=1)

    weekend_date = today
    while weekend_date.weekday() != 5:
        weekend_date += timedelta(days=1)

    weekday_iso = weekday_date.isoformat()
    weekend_iso = weekend_date.isoformat()
    return [
        {"id": "weekday_morning", "label": "工作日早高峰", "date": weekday_iso, "time": "08:30"},
        {"id": "weekday_midday", "label": "工作日平峰", "date": weekday_iso, "time": "11:00"},
        {"id": "weekend_daytime", "label": "周末白天", "date": weekend_iso, "time": "10:00"},
    ]


def _route_options_key(route_options):
    if not route_options:
        return ()
    items = []
    for key, value in sorted(route_options.items()):
        if isinstance(value, dict):
            items.append((key, tuple(sorted(value.items()))))
        else:
            items.append((key, value))
    return tuple(items)


def _point_identity(point):
    return (
        round(float(point.get("lng", 0)), 6),
        round(float(point.get("lat", 0)), 6),
        str(point.get("label", "")).strip(),
        str(point.get("poi_id", "")).strip(),
    )


def _unique_points(points):
    seen = set()
    unique = []
    for point in points:
        if not isinstance(point, dict):
            continue
        identity = _point_identity(point)
        if identity in seen:
            continue
        seen.add(identity)
        unique.append(point)
    return unique


def _build_static_time_comparisons(duration_min, transit_profiles, note, transit_duration_min=0):
    rows = [
        {
            "id": profile["id"],
            "label": profile["label"],
            "date": profile["date"],
            "time": profile["time"],
            "transit_duration_min": transit_duration_min,
            "total_duration_min": duration_min,
            "note": note,
        }
        for profile in transit_profiles
    ]
    return rows, (rows[0] if rows else None)


def _route_template_from_segments(segments):
    if not segments:
        return "walk"
    return "->".join(segment["mode"] for segment in segments)


# 中文注释：统一读取当前搜索所用的房补规则，provider 在决定是否触发别名补救时也要用到同一套阈值。
def _provider_rules(payload):
    raw_rules = payload.get("rules") if isinstance(payload, dict) else None
    return normalize_rules(raw_rules)


# 中文注释：把候选方案按规则做一次轻量评估，用于判断“精确起终点是否已经合规”。
def _candidate_evaluation(candidate, rules):
    total_duration = sum(segment["duration_min"] for segment in candidate["segments"])
    return evaluate_plan(
        {
            "template": candidate.get("template_override") or _route_template_from_segments(candidate["segments"]),
            "segments": candidate["segments"],
            "total_duration_min": total_duration,
        },
        rules,
    )


def _candidate_is_compliant(candidate, rules):
    return _candidate_evaluation(candidate, rules)["is_compliant"]


def _candidate_needs_expansion(candidate, rules):
    if not candidate:
        return True
    evaluation = _candidate_evaluation(candidate, rules)
    return (
        not evaluation["is_compliant"]
        or evaluation["margin_min"] <= ALIAS_EXPANSION_MARGIN_MIN
    )


def _route_source_priority(candidate):
    source = str((candidate or {}).get("route_source", "direct"))
    if source == "integrated":
        return 0
    if source == "direct":
        return 1
    if source == "stitched_station_combo":
        return 2
    return 3


# 中文注释：同名门口/楼栋别名也是产品要比较的正式候选，不能因为精确点已合规就提前停止。
def _pick_template_candidate(exact_candidate, fallback_candidates, rules):
    pool = [candidate for candidate in [exact_candidate, *(fallback_candidates or [])] if candidate]
    if not pool:
        return None
    return min(
        pool,
        key=lambda candidate: (
            not _candidate_is_compliant(candidate, rules),
            sum(segment["duration_min"] for segment in candidate["segments"]),
            candidate.get("used_alias_fallback", False),
            _route_source_priority(candidate),
        ),
    )


def _point_display_label(point):
    return point.get("display_label") or point["label"]


# 中文注释：保留地图真实解析到的 POI 名称，同时单独保存页面展示名，避免页面直接露出无关附近点。
def _with_display_label(point, display_label, *, requested_label=None, used_alias_fallback=False):
    normalized = {**point}
    normalized["resolved_label"] = point.get("resolved_label") or point.get("label") or display_label
    normalized["display_label"] = display_label
    normalized["requested_label"] = requested_label or display_label
    normalized["used_alias_fallback"] = used_alias_fallback
    return normalized


def _normalize_name_for_match(value):
    return "".join(
        char.lower()
        for char in str(value).strip()
        if char.isalnum() or ("\u4e00" <= char <= "\u9fff")
    )


def _looks_like_same_place(query, candidate_name):
    normalized_query = _normalize_name_for_match(query)
    normalized_candidate = _normalize_name_for_match(candidate_name)
    if not normalized_query or not normalized_candidate:
        return False
    return normalized_query in normalized_candidate or normalized_candidate in normalized_query


# 中文注释：别名只允许从原始名称派生，首版不再去附近任意 POI 里“猜门口”。
def _derive_alias_queries(query, place_role):
    normalized = str(query).strip()
    if not normalized:
        return []
    if any(suffix in normalized for suffix in KNOWN_ALIAS_SUFFIXES):
        return []

    suffixes = HOME_ALIAS_SUFFIXES if place_role == "home" else OFFICE_ALIAS_SUFFIXES
    return [f"{normalized}{suffix}" for suffix in suffixes]


def _is_qps_error(error):
    message = str(error)
    return "10021" in message or "CUQPS_HAS_EXCEEDED_THE_LIMIT" in message


def _append_if_best(results, provider, template, best_candidate):
    if not best_candidate:
        return
    normalized = {
        "provider": provider,
        "template": template,
        "origin_name": best_candidate.get("origin_name"),
        "destination_name": best_candidate.get("destination_name"),
        "used_alias_fallback": best_candidate.get("used_alias_fallback", False),
        "search_strategy": best_candidate.get("search_strategy", "exact"),
        "route_source": best_candidate.get("route_source", "direct"),
        "segments": best_candidate["segments"],
        "screenshot_hint": best_candidate["screenshot_hint"],
    }
    for key in (
        "time_comparisons",
        "timing_recommendation",
        "alias_type",
        "exact_total_duration_min",
        "alias_total_duration_min",
        "transit_strategy_label",
        "transit_strategy_value",
        "station_source",
    ):
        if key in best_candidate:
            normalized[key] = best_candidate[key]
    results.append(normalized)


def _amap_geocode(address, key, fetch_json):
    direct = _coord_from_text(address)
    if direct:
        return direct
    query = urlencode({"address": address, "key": key, "output": "json"})
    payload = fetch_json(f"https://restapi.amap.com/v3/geocode/geo?{query}")
    if payload.get("status") != "1" or not payload.get("geocodes"):
        raise ValueError(_amap_error_detail(payload, f"amap geocode failed for {address}"))
    result = payload["geocodes"][0]
    lng, lat = [float(item) for item in result["location"].split(",")]
    return {
        "lat": lat,
        "lng": lng,
        "citycode": result.get("citycode", ""),
        "label": address,
    }


def _amap_input_tips(query, key, fetch_json):
    normalized = str(query).strip()
    if not normalized:
        return []
    params = {
        "keywords": normalized,
        "key": key,
        "datatype": "all",
    }
    payload = fetch_json(f"https://restapi.amap.com/v3/assistant/inputtips?{urlencode(params)}")
    if payload.get("status") != "1":
        raise ValueError(_amap_error_detail(payload, f"amap input tips failed for {normalized}"))

    suggestions = []
    for tip in payload.get("tips", []):
        location = tip.get("location")
        name = str(tip.get("name", "")).strip()
        if not name or not location or "," not in location:
            continue
        suggestions.append(
            {
                "id": tip.get("id", ""),
                "name": name,
                "district": str(tip.get("district", "")).strip(),
                "address": str(tip.get("address", "")).strip(),
                "location": location,
                "adcode": tip.get("adcode", ""),
            }
        )
        if len(suggestions) >= AMAP_SUGGEST_LIMIT:
            break
    return suggestions


def _amap_text_search(query, key, fetch_json):
    normalized = str(query).strip()
    if not normalized:
        return []
    params = {
        "keywords": normalized,
        "key": key,
        "page_size": AMAP_SUGGEST_LIMIT,
    }
    payload = fetch_json(f"https://restapi.amap.com/v5/place/text?{urlencode(params)}")
    if payload.get("status") != "1":
        raise ValueError(_amap_error_detail(payload, f"amap poi search failed for {normalized}"))

    suggestions = []
    for poi in payload.get("pois", []):
        location = poi.get("location")
        name = str(poi.get("name", "")).strip()
        if not name or not location or "," not in location:
            continue
        suggestions.append(
            {
                "id": poi.get("id", ""),
                "name": name,
                "district": str(poi.get("cityname", "") or poi.get("pname", "")).strip(),
                "address": str(poi.get("address", "")).strip(),
                "location": location,
                "adcode": poi.get("adcode", ""),
            }
        )
        if len(suggestions) >= AMAP_SUGGEST_LIMIT:
            break
    return suggestions


def _amap_candidate_to_point(candidate, fallback_label):
    label = str(candidate.get("name", "")).strip() or fallback_label
    address = str(candidate.get("address", "")).strip()
    citycode = candidate.get("adcode", "")
    poi_id = candidate.get("id", "")
    return _point_from_location(candidate["location"], label, citycode=citycode, address=address, poi_id=poi_id)


def _amap_resolve_place(query, key, fetch_json, selection=None):
    direct = _coord_from_text(query)
    if direct:
        return direct

    selected_point = _point_from_selection(selection, query)
    if selected_point:
        return selected_point

    suggestions = _amap_input_tips(query, key, fetch_json)
    if suggestions:
        return _amap_candidate_to_point(suggestions[0], query)

    pois = _amap_text_search(query, key, fetch_json)
    if pois:
        return _amap_candidate_to_point(pois[0], query)

    return _amap_geocode(query, key, fetch_json)


def _amap_search_candidates(query, key, fetch_json):
    suggestions = _amap_input_tips(query, key, fetch_json)
    if suggestions:
        return suggestions
    return _amap_text_search(query, key, fetch_json)


# 中文注释：别名补救只接受“名称上仍然像同一个地方”的搜索结果，避免把附近无关 POI 当成门口。
def _amap_resolve_name_derived_points(query, key, fetch_json, place_role):
    points = []
    for alias_query in _derive_alias_queries(query, place_role):
        for candidate in _amap_search_candidates(alias_query, key, fetch_json):
            if not _looks_like_same_place(alias_query, candidate.get("name", "")):
                continue
            points.append(
                _with_display_label(
                    _amap_candidate_to_point(candidate, alias_query),
                    alias_query,
                    requested_label=query,
                    used_alias_fallback=True,
                )
            )
            break
    return _unique_points(points)


def _amap_expand_place_candidates(query, key, fetch_json, selection=None):
    direct = _coord_from_text(query)
    if direct:
        return [direct]

    selected_point = _point_from_selection(selection, query)
    if selected_point:
        return [selected_point]

    candidates = []
    suggestions = _amap_input_tips(query, key, fetch_json)
    source_candidates = suggestions[:3] if suggestions else _amap_text_search(query, key, fetch_json)[:3]
    for candidate in source_candidates:
        candidates.append(_amap_candidate_to_point(candidate, query))
    if not candidates:
        candidates.append(_amap_geocode(query, key, fetch_json))
    return _unique_points(candidates)


def _amap_resolve_same_query_points(query, key, fetch_json, selection=None):
    if selection:
        return []

    normalized_query = _normalize_name_for_match(query)
    points = []
    for candidate in _amap_search_candidates(query, key, fetch_json):
        candidate_name = str(candidate.get("name", "")).strip()
        if not _looks_like_same_place(query, candidate_name):
            continue
        normalized_candidate = _normalize_name_for_match(candidate_name)
        points.append(
            _with_display_label(
                _amap_candidate_to_point(candidate, query),
                candidate_name or query,
                requested_label=query,
                used_alias_fallback=normalized_candidate != normalized_query,
            )
        )
    return _unique_points(points)


def _amap_resolve_station_points(station_name, key, fetch_json):
    normalized_station_name = _normalize_station_name(station_name)
    if not normalized_station_name:
        return []

    points = []
    for candidate in _amap_search_candidates(normalized_station_name, key, fetch_json):
        candidate_name = str(candidate.get("name", "")).strip()
        if not candidate_name:
            continue
        if not _station_matches_name({"label": candidate_name}, normalized_station_name):
            continue
        points.append(_amap_candidate_to_point(candidate, normalized_station_name))
    return _unique_points(points)


def _amap_nearby_gate_candidates(point, key, fetch_json):
    params = {
        "location": _amap_format(point),
        "keywords": "门",
        "key": key,
        "page_size": 4,
        "sortrule": "distance",
    }
    payload = fetch_json(f"https://restapi.amap.com/v5/place/around?{urlencode(params)}")
    if payload.get("status") != "1":
        raise ValueError(_amap_error_detail(payload, f"amap nearby gate failed for {point['label']}"))

    gates = []
    for poi in payload.get("pois", []):
        name = str(poi.get("name", "")).strip()
        location = poi.get("location")
        if not name or not location or "," not in location:
            continue
        gates.append(_point_from_location(location, name, citycode=poi.get("adcode", "")))
    return _unique_points(gates)


def _amap_pick_access_point(point, key, fetch_json):
    gates = _amap_nearby_gate_candidates(point, key, fetch_json)
    return gates[0] if gates else point


def _amap_nearby_subway_stations(point, key, fetch_json):
    params = {
        "location": _amap_format(point),
        "keywords": "地铁站出入口",
        "key": key,
        "page_size": AMAP_NEARBY_STATION_LIMIT,
        "sortrule": "distance",
    }
    payload = fetch_json(f"https://restapi.amap.com/v5/place/around?{urlencode(params)}")
    if payload.get("status") != "1":
        raise ValueError(_amap_error_detail(payload, f"amap nearby subway failed for {point['label']}"))

    stations = []
    seen = set()
    for poi in payload.get("pois", []):
        name = str(poi.get("name", "")).strip()
        location = poi.get("location")
        if (
            not name
            or not location
            or name in seen
            or "," not in location
            or not _looks_like_subway_station_name(name)
        ):
            continue
        seen.add(name)
        station = _point_from_location(location, name, citycode=poi.get("adcode", ""))
        station["distance_m"] = int(float(poi.get("distance", 0) or 0))
        stations.append(station)
        if len(stations) >= AMAP_NEARBY_STATION_LIMIT:
            break
    return stations


def _amap_format(point):
    return f"{point['lng']:.6f},{point['lat']:.6f}"


def _amap_route(mode, origin, destination, key, fetch_json, route_options=None):
    route_options = route_options or {}
    transit_profile = route_options.get("transit_profile")
    transit_strategy = str(route_options.get("transit_strategy", "0")).strip() or "0"
    endpoints = {
        "walk": "https://restapi.amap.com/v5/direction/walking",
        "bike": "https://restapi.amap.com/v5/direction/bicycling",
        "subway": "https://restapi.amap.com/v5/direction/transit/integrated"
        if not transit_profile
        else "https://restapi.amap.com/v3/direction/transit/integrated",
    }
    params = {
        "origin": _amap_format(origin),
        "destination": _amap_format(destination),
        "key": key,
    }
    if mode == "subway":
        origin_poi = str(origin.get("poi_id", "")).strip()
        destination_poi = str(destination.get("poi_id", "")).strip()
        if origin_poi:
            params["originpoi"] = origin_poi
        if destination_poi:
            params["destinationpoi"] = destination_poi
    if mode in {"bike", "subway"}:
        params["show_fields"] = "cost"
    if mode == "bike":
        params["alternative_route"] = "3"
    if mode == "subway":
        city = origin.get("citycode") or destination.get("citycode")
        destination_city = destination.get("citycode") or city
        params["AlternativeRoute"] = "5"
        params["strategy"] = transit_strategy
        if transit_profile:
            params.pop("show_fields", None)
            if city:
                params["city"] = city
                params["cityd"] = destination_city
            params["extensions"] = "all"
            params["date"] = transit_profile["date"]
            params["time"] = transit_profile["time"]
        elif city:
            params["city1"] = city
            params["city2"] = destination_city
    payload = fetch_json(f"{endpoints[mode]}?{urlencode(params)}")
    if mode == "bike":
        v5_paths = payload.get("route", {}).get("paths", [])
        legacy_paths = payload.get("data", {}).get("paths", [])
        if payload.get("status") in {"1", 1} and v5_paths:
            route = _pick_best_route_candidate(v5_paths)
        elif payload.get("errcode") in {0, "0", None} and legacy_paths:
            route = _pick_best_route_candidate(legacy_paths)
        else:
            raise ValueError(_amap_error_detail(payload, "amap bicycling failed"))
        if not route:
            raise ValueError(_amap_error_detail(payload, "amap bicycling returned no valid path"))
        return {
            "duration_min": _pick_duration_minutes(
                route.get("cost", {}).get("duration") if isinstance(route.get("cost"), dict) else route.get("duration")
            ),
            "distance_m": int(float(route.get("distance", 0))),
        }
    if payload.get("status") not in {"1", 1, None} and payload.get("route") is None:
        raise ValueError(_amap_error_detail(payload, f"amap {mode} failed"))
    if mode == "subway":
        transits = payload.get("route", {}).get("transits", [])
        if not transits:
            raise ValueError(_amap_error_detail(payload, "amap transit returned no plans"))
        subway_transits = [
            transit
            for transit in transits
            if _amap_transit_station_pair(transit)[0] and _amap_transit_station_pair(transit)[1]
        ]
        if not subway_transits:
            raise ValueError(_amap_error_detail(payload, "amap transit returned no subway plans"))
        route = _pick_best_route_candidate(subway_transits)
        if not route:
            raise ValueError(_amap_error_detail(payload, "amap transit returned no valid subway plan"))
        duration = route.get("cost", {}).get("duration") if isinstance(route.get("cost"), dict) else route.get("duration")
        entry_name, exit_name, line_name = _amap_transit_station_pair(route)
        leg_breakdown = _amap_transit_leg_breakdown(route)
    else:
        paths = payload.get("route", {}).get("paths", [])
        if not paths:
            raise ValueError(_amap_error_detail(payload, f"amap {mode} returned no paths"))
        route = _pick_best_route_candidate(paths)
        if not route:
            raise ValueError(_amap_error_detail(payload, f"amap {mode} returned no valid path"))
        duration = route.get("cost", {}).get("duration") if isinstance(route.get("cost"), dict) else route.get("duration")
        entry_name, exit_name, line_name = None, None, None
        leg_breakdown = {}
    result = {
        "duration_min": _pick_duration_minutes(duration),
        "distance_m": int(float(route.get("distance", 0))),
    }
    result.update(leg_breakdown)
    if entry_name and exit_name:
        result["transit_entry_name"] = entry_name
        result["transit_exit_name"] = exit_name
    if line_name:
        result["transit_line_name"] = line_name
    if mode == "subway":
        result["transit_strategy"] = transit_strategy
    return result


def _baidu_geocode(address, key, fetch_json):
    direct = _coord_from_text(address)
    if direct:
        return direct
    query = urlencode({"address": address, "output": "json", "ak": key})
    payload = fetch_json(f"https://api.map.baidu.com/geocoding/v3/?{query}")
    if payload.get("status") != 0 or "result" not in payload:
        raise ValueError(f"baidu geocode failed for {address}")
    location = payload["result"]["location"]
    return {
        "lat": float(location["lat"]),
        "lng": float(location["lng"]),
        "citycode": "",
        "label": address,
    }


def _baidu_format(point):
    return f"{point['lat']:.6f},{point['lng']:.6f}"


def _baidu_duration(value):
    if isinstance(value, dict):
        value = value.get("value")
    return _pick_duration_minutes(value)


def _baidu_route(mode, origin, destination, key, fetch_json):
    endpoints = {
        "walk": "https://api.map.baidu.com/directionlite/v1/walking",
        "bike": "https://api.map.baidu.com/directionlite/v1/riding",
        "subway": "https://api.map.baidu.com/directionlite/v1/transit",
    }
    params = {
        "origin": _baidu_format(origin),
        "destination": _baidu_format(destination),
        "ak": key,
    }
    payload = fetch_json(f"{endpoints[mode]}?{urlencode(params)}")
    if payload.get("status") != 0 or not payload.get("result", {}).get("routes"):
        raise ValueError(f"baidu {mode} failed")
    route = payload["result"]["routes"][0]
    result = {
        "duration_min": _baidu_duration(route.get("duration")),
        "distance_m": int(float(route.get("distance", 0))),
    }
    if mode == "subway":
        entry_name, exit_name = _baidu_transit_station_pair(route)
        if entry_name and exit_name:
            result["transit_entry_name"] = entry_name
            result["transit_exit_name"] = exit_name
    return result


def _qq_geocode(address, key, fetch_json):
    direct = _coord_from_text(address)
    if direct:
        return direct
    query = urlencode({"address": address, "key": key})
    payload = fetch_json(f"https://apis.map.qq.com/ws/geocoder/v1/?{query}")
    if payload.get("status") != 0 or "result" not in payload:
        raise ValueError(f"qq geocode failed for {address}")
    location = payload["result"]["location"]
    return {
        "lat": float(location["lat"]),
        "lng": float(location["lng"]),
        "citycode": "",
        "label": address,
    }


def _qq_format(point):
    return f"{point['lat']:.6f},{point['lng']:.6f}"


def _qq_route(mode, origin, destination, key, fetch_json):
    endpoints = {
        "walk": "https://apis.map.qq.com/ws/direction/v1/walking",
        "bike": "https://apis.map.qq.com/ws/direction/v1/bicycling",
        "subway": "https://apis.map.qq.com/ws/direction/v1/transit",
    }
    params = {
        "from": _qq_format(origin),
        "to": _qq_format(destination),
        "key": key,
    }
    payload = fetch_json(f"{endpoints[mode]}?{urlencode(params)}")
    if payload.get("status") != 0 or not payload.get("result", {}).get("routes"):
        raise ValueError(f"qq {mode} failed")
    route = payload["result"]["routes"][0]
    result = {
        "duration_min": _pick_duration_minutes(route.get("duration")),
        "distance_m": int(float(route.get("distance", 0))),
    }
    if mode == "subway":
        entry_name, exit_name = _qq_transit_station_pair(route)
        if entry_name and exit_name:
            result["transit_entry_name"] = entry_name
            result["transit_exit_name"] = exit_name
    return result


def _resolve_points(labels, geocode_fn, key, fetch_json):
    resolved = []
    cache = {}
    for label in labels:
        if label in cache:
            resolved.append(cache[label])
            continue
        point = geocode_fn(label, key, fetch_json)
        point["label"] = label
        cache[label] = point
        resolved.append(point)
    return resolved


def _build_provider_results(provider, key, payload_context, geocode_fn, route_fn, fetch_json):
    home_points = _resolve_points(payload_context["home_gates"], geocode_fn, key, fetch_json)
    office_points = _resolve_points(payload_context["office_aliases"], geocode_fn, key, fetch_json)
    route_cache = {}

    results = []
    deferred_errors = []

    def route_for(mode, origin, destination):
        cache_key = (
            mode,
            origin["label"],
            destination["label"],
        )
        if cache_key not in route_cache:
            route_cache[cache_key] = route_fn(mode, origin, destination, key, fetch_json)
        return route_cache[cache_key]

    for template in ("walk", "bike", "subway"):
        if template not in LIVE_TEMPLATES:
            continue
        candidates = []
        for home_point in home_points:
            for office_point in office_points:
                route = route_for(template, home_point, office_point)
                candidates.append(
                    {
                        "origin_name": home_point["label"],
                        "destination_name": office_point["label"],
                        "segments": [
                            {
                                "mode": template if template != "subway" else "subway",
                                "duration_min": route["duration_min"],
                                "from_name": home_point["label"],
                                "to_name": office_point["label"],
                                "transit_entry_name": route.get("transit_entry_name"),
                                "transit_exit_name": route.get("transit_exit_name"),
                                "transit_line_name": route.get("transit_line_name"),
                            }
                        ],
                        "screenshot_hint": f"{provider} 真实算路结果，直接复核 {home_point['label']} -> {office_point['label']}。",
                    }
                )
        _append_if_best(results, provider, template, _best_option(candidates))

    station_points = []
    if payload_context["stations"]:
        try:
            station_points = _resolve_points(payload_context["stations"], geocode_fn, key, fetch_json)
            for point in station_points:
                point["display_label"] = point["label"]
        except Exception as error:
            deferred_errors.append(
                {
                    "provider": provider,
                    "message": f"候选地铁站解析失败: {error}",
                }
            )

    for access_mode, template in (("walk", "walk->subway"), ("bike", "bike->subway")):
        if template not in LIVE_TEMPLATES:
            continue
        if not station_points:
            continue
        candidates = []
        for home_point in home_points:
            for station_point in station_points:
                for office_point in office_points:
                    access = route_for(access_mode, home_point, station_point)
                    transit = route_for("subway", station_point, office_point)
                    station_display_name = (
                        transit.get("transit_entry_name")
                        or station_point.get("display_label")
                        or station_point["label"]
                    )
                    candidates.append(
                        {
                            "origin_name": home_point["label"],
                            "destination_name": office_point["label"],
                            "segments": [
                                {
                                    "mode": access_mode,
                                    "duration_min": access["duration_min"],
                                    "from_name": home_point["label"],
                                    "to_name": station_display_name,
                                },
                                {
                                    "mode": "subway",
                                    "duration_min": transit["duration_min"],
                                    "from_name": station_display_name,
                                    "to_name": office_point["label"],
                                    "transit_entry_name": transit.get("transit_entry_name"),
                                    "transit_exit_name": transit.get("transit_exit_name"),
                                    "transit_line_name": transit.get("transit_line_name"),
                                },
                            ],
                            "screenshot_hint": f"{provider} 真实算路结果，先截 {station_display_name} 接驳，再截去公司段。",
                        }
                    )
        _append_if_best(results, provider, template, _best_option(candidates))

    return {
        "results": results,
        "errors": deferred_errors,
    }


def build_live_provider_options(payload, config, fetch_json=_fetch_json, transit_profiles=None):
    return _build_live_provider_payload(
        payload,
        config,
        fetch_json,
        transit_profiles=transit_profiles,
    )["options"]


def load_place_suggestions(query, config=None, fetch_json=_fetch_json):
    config = config or load_config()
    if not config.amap_key:
        return {"provider": "amap", "suggestions": [], "warning": LIVE_KEY_WARNING}
    normalized = str(query).strip()
    if not normalized:
        return {"provider": "amap", "suggestions": [], "warning": ""}
    suggestions = _amap_input_tips(normalized, config.amap_key, fetch_json)
    if not suggestions:
        suggestions = _amap_text_search(normalized, config.amap_key, fetch_json)
    return {"provider": "amap", "suggestions": suggestions, "warning": ""}


def _build_live_provider_payload(payload, config, fetch_json=_fetch_json, transit_profiles=None):
    payload_context = _build_live_payload_context(payload)
    results = []
    provider_errors = []
    if not config.amap_key:
        return {"options": [], "provider_errors": provider_errors, "soft_timeout": False}
    transit_profiles = transit_profiles or _default_transit_time_profiles()
    rules = _provider_rules(payload)
    fetch_cache = {}
    request_counts = {}
    started_at = time.monotonic()
    soft_timeout_triggered = False

    # 中文注释：同一次搜索里，相同 URL 的高德请求直接复用，避免把 QPS 浪费在重复查询上。
    def cached_fetch_json(url):
        nonlocal soft_timeout_triggered
        if url not in fetch_cache:
            if "restapi.amap.com" in url and (time.monotonic() - started_at) >= AMAP_SOFT_TIMEOUT_SEC:
                soft_timeout_triggered = True
                raise _AmapSoftTimeoutError(f"amap soft timeout after {int(AMAP_SOFT_TIMEOUT_SEC * 1000)}ms")
            request_type = _request_type_from_url(url)
            request_counts[request_type] = request_counts.get(request_type, 0) + 1
            fetch_cache[url] = fetch_json(url)
            if "restapi.amap.com" in url and (time.monotonic() - started_at) >= AMAP_SOFT_TIMEOUT_SEC:
                soft_timeout_triggered = True
        return fetch_cache[url]

    try:
        office_query = payload_context["office"]
        home_query = payload_context["home"]
        if not office_query or not home_query:
            raise ValueError("company and home are required")

        exact_home_point = _with_display_label(
            _amap_resolve_place(
                home_query,
                config.amap_key,
                cached_fetch_json,
                selection=payload_context.get("home_selection"),
            ),
            home_query,
            requested_label=home_query,
            used_alias_fallback=False,
        )
        exact_office_point = _with_display_label(
            _amap_resolve_place(
                office_query,
                config.amap_key,
                cached_fetch_json,
                selection=payload_context.get("office_selection"),
            ),
            office_query,
            requested_label=office_query,
            used_alias_fallback=False,
        )

        route_cache = {}
        route_errors = {}
        station_cache = {}
        rate_limit_error = None
        alias_points_cache = {"home": None, "office": None}
        same_query_points_cache = {"home": None, "office": None}
        fallback_pairs_cache = None

        def route_for(mode, origin, destination, route_options=None):
            cache_key = (mode, _point_identity(origin), _point_identity(destination), _route_options_key(route_options))
            if cache_key not in route_cache:
                route_cache[cache_key] = _amap_route(
                    mode,
                    origin,
                    destination,
                    config.amap_key,
                    cached_fetch_json,
                    route_options=route_options,
                )
            return route_cache[cache_key]

        def safe_route_for(mode, origin, destination, route_options=None):
            nonlocal rate_limit_error
            if rate_limit_error is not None:
                raise rate_limit_error
            cache_key = (mode, _point_identity(origin), _point_identity(destination), _route_options_key(route_options))
            if cache_key in route_errors:
                raise route_errors[cache_key]
            try:
                return route_for(mode, origin, destination, route_options=route_options)
            except Exception as error:
                route_errors[cache_key] = error
                if _is_qps_error(error):
                    rate_limit_error = error
                raise

        def record_mode_error(mode, error):
            _append_unique_error(provider_errors, "amap", f"{mode} route failed: {error}")

        def alias_points_for(place_role):
            cached = alias_points_cache[place_role]
            if cached is not None:
                return cached
            try:
                alias_points_cache[place_role] = _amap_resolve_name_derived_points(
                    home_query if place_role == "home" else office_query,
                    config.amap_key,
                    cached_fetch_json,
                    place_role,
                )
            except Exception as error:
                alias_points_cache[place_role] = []
                role_label = "房源" if place_role == "home" else "公司"
                _append_unique_error(provider_errors, "amap", f"{role_label}别名补救失败: {error}")
            return alias_points_cache[place_role]

        # 中文注释：把原始输入提示里的“同名门口/楼栋”也纳入正式候选，而不是只拿第一个 POI。
        def same_query_points_for(place_role):
            cached = same_query_points_cache[place_role]
            if cached is not None:
                return cached
            try:
                same_query_points_cache[place_role] = _amap_resolve_same_query_points(
                    home_query if place_role == "home" else office_query,
                    config.amap_key,
                    cached_fetch_json,
                    selection=payload_context.get("home_selection")
                    if place_role == "home"
                    else payload_context.get("office_selection"),
                )
            except Exception as error:
                same_query_points_cache[place_role] = []
                role_label = "房源" if place_role == "home" else "公司"
                _append_unique_error(provider_errors, "amap", f"{role_label}候选扩展失败: {error}")
            return same_query_points_cache[place_role]

        def fallback_point_pairs():
            nonlocal fallback_pairs_cache
            if fallback_pairs_cache is not None:
                return fallback_pairs_cache

            seen = set()
            pairs = []
            home_points = [exact_home_point, *alias_points_for("home")]
            office_points = [exact_office_point, *alias_points_for("office")]
            for home_point in home_points:
                for office_point in office_points:
                    if not (home_point.get("used_alias_fallback") or office_point.get("used_alias_fallback")):
                        continue
                    identity = (_point_identity(home_point), _point_identity(office_point))
                    if identity in seen:
                        continue
                    seen.add(identity)
                    pairs.append((home_point, office_point))
            fallback_pairs_cache = pairs
            return fallback_pairs_cache

        def candidate_alias_type(origin_point, destination_point):
            if origin_point.get("used_alias_fallback"):
                return "gate"
            if destination_point.get("used_alias_fallback"):
                return "office"
            return None

        def attach_alias_comparison(best_candidate, exact_candidate):
            if not best_candidate or not best_candidate.get("used_alias_fallback") or not exact_candidate:
                return best_candidate
            decorated = dict(best_candidate)
            decorated["alias_type"] = decorated.get("alias_type") or exact_candidate.get("alias_type") or "gate"
            decorated["exact_total_duration_min"] = sum(
                segment["duration_min"] for segment in exact_candidate.get("segments", [])
            )
            decorated["alias_total_duration_min"] = sum(
                segment["duration_min"] for segment in decorated.get("segments", [])
            )
            return decorated

        # 中文注释：单段直达路线只展示当前参与算路的起终点名称；精确路线合规时，不再继续枚举别名补救。
        def build_direct_candidate(mode, origin_point, destination_point):
            try:
                route = safe_route_for(mode, origin_point, destination_point)
            except Exception as error:
                record_mode_error(mode, error)
                return None
            mode_label = "步行" if mode == "walk" else "骑行"
            time_comparisons, timing_recommendation = _build_static_time_comparisons(
                route["duration_min"],
                transit_profiles,
                f"{mode_label}当前接口以实时结果为准，暂不支持按出发时间精确枚举。",
            )
            return {
                "origin_name": home_query,
                "destination_name": office_query,
                "used_alias_fallback": bool(
                    origin_point.get("used_alias_fallback") or destination_point.get("used_alias_fallback")
                ),
                "search_strategy": (
                    "alias_fallback"
                    if origin_point.get("used_alias_fallback") or destination_point.get("used_alias_fallback")
                    else "exact"
                ),
                "alias_type": candidate_alias_type(origin_point, destination_point),
                "segments": [
                    {
                        "mode": mode,
                        "duration_min": route["duration_min"],
                        "from_name": _point_display_label(origin_point),
                        "to_name": _point_display_label(destination_point),
                        "transit_entry_name": route.get("transit_entry_name"),
                        "transit_exit_name": route.get("transit_exit_name"),
                        "transit_line_name": route.get("transit_line_name"),
                    }
                ],
                "time_comparisons": time_comparisons,
                "timing_recommendation": timing_recommendation,
                "screenshot_hint": f"高德真实算路结果，直接复核 {_point_display_label(origin_point)} → {_point_display_label(destination_point)}。",
            }

        def stations_for(point):
            cache_key = _point_identity(point)
            if cache_key not in station_cache:
                station_cache[cache_key] = _amap_nearby_subway_stations(point, config.amap_key, cached_fetch_json)
            return station_cache[cache_key]

        def build_integrated_transit_candidate(origin_point, destination_point, include_profile_queries=True):
            selected_strategy = TRANSIT_STRATEGIES[0]
            try:
                baseline_transit = safe_route_for(
                    "subway",
                    origin_point,
                    destination_point,
                    route_options={"transit_strategy": selected_strategy["value"]},
                )
            except Exception as error:
                record_mode_error("subway", error)
                return None

            time_comparisons, selected_comparison = _build_static_time_comparisons(
                baseline_transit["duration_min"],
                transit_profiles,
                (
                    f"当前先按高德综合公交实时路线快照展示，默认使用{selected_strategy['label']}，不再为每个时段重复请求接口。"
                ),
                transit_duration_min=max(
                    1,
                    int(baseline_transit.get("transit_only_duration_min", 0) or baseline_transit["duration_min"]),
                ),
            )

            access_duration = int(baseline_transit.get("access_duration_min", 0) or 0)
            egress_duration = int(baseline_transit.get("egress_duration_min", 0) or 0)
            transit_only = int(baseline_transit.get("transit_only_duration_min", 0) or 0)
            entry_name = baseline_transit.get("transit_entry_name") or "起始地铁站"
            exit_name = baseline_transit.get("transit_exit_name") or "终点地铁站"
            if access_duration <= 0:
                access_duration = 1
            if egress_duration <= 0:
                egress_duration = 1
            if transit_only <= 0:
                transit_only = max(1, baseline_transit["duration_min"] - access_duration - egress_duration)

            target_total_duration = int(
                (selected_comparison or {}).get("total_duration_min", baseline_transit["duration_min"])
            )
            target_transit_only = max(1, target_total_duration - access_duration - egress_duration)
            segments = [
                {
                    "mode": "walk",
                    "duration_min": access_duration,
                    "from_name": _point_display_label(origin_point),
                    "to_name": entry_name,
                },
                {
                    "mode": "subway",
                    "duration_min": target_transit_only,
                    "from_name": entry_name,
                    "to_name": exit_name,
                    "transit_entry_name": entry_name,
                    "transit_exit_name": exit_name,
                    "transit_line_name": baseline_transit.get("transit_line_name"),
                },
                {
                    "mode": "walk",
                    "duration_min": egress_duration,
                    "from_name": exit_name,
                    "to_name": _point_display_label(destination_point),
                },
            ]
            if not selected_comparison:
                segments[1]["duration_min"] = transit_only
            _debug_log(
                "integrated candidate "
                f"from={_point_display_label(origin_point)} to={_point_display_label(destination_point)} "
                f"entry={entry_name} exit={exit_name} realtime={baseline_transit['duration_min']} "
                f"selected={segments[0]['duration_min'] + segments[1]['duration_min'] + segments[2]['duration_min']}"
            )
            return {
                "template_override": "subway",
                "origin_name": home_query,
                "destination_name": office_query,
                "used_alias_fallback": bool(
                    origin_point.get("used_alias_fallback") or destination_point.get("used_alias_fallback")
                ),
                "search_strategy": (
                    "alias_fallback"
                    if origin_point.get("used_alias_fallback") or destination_point.get("used_alias_fallback")
                    else "exact"
                ),
                "alias_type": candidate_alias_type(origin_point, destination_point),
                "segments": segments,
                "time_comparisons": time_comparisons,
                "timing_recommendation": selected_comparison,
                "route_source": "integrated",
                "transit_strategy_label": selected_strategy["label"],
                "transit_strategy_value": selected_strategy["value"],
                "integrated_subway_duration_min": target_transit_only,
                "screenshot_hint": (
                    f"高德综合公交规划结果，优先复核 {_point_display_label(origin_point)} → {entry_name}、"
                    f"{entry_name} → {exit_name}、{exit_name} → {_point_display_label(destination_point)}。"
                ),
            }

        # 中文注释：只有在直骑和综合公交都不合规时，才退回到站点组合穷举，尝试通过门口/站点优化压缩时间。
        def build_station_combination_candidate_pool(
            point_pairs,
            preferred_station_pair=None,
            mode_pairs=None,
            transit_strategy=None,
            explicit_station_pairs=None,
            integrated_transit_snapshot=None,
            include_profile_queries=True,
        ):
            mode_pairs = mode_pairs or (("bike", "bike"),)
            candidates = []
            for origin_point, destination_point in point_pairs:
                station_pairs = list(explicit_station_pairs or [])
                if not station_pairs:
                    try:
                        home_stations = stations_for(origin_point)
                    except Exception as error:
                        _append_unique_error(provider_errors, "amap", f"附近地铁站识别失败: {error}")
                        home_stations = []
                    try:
                        office_stations = stations_for(destination_point)
                    except Exception as error:
                        _append_unique_error(provider_errors, "amap", f"附近地铁站识别失败: {error}")
                        office_stations = []
                    station_pairs = [(home_station, office_station) for home_station in home_stations for office_station in office_stations]
                if preferred_station_pair and station_pairs:
                    preferred_entry_name, preferred_exit_name = preferred_station_pair
                    preferred_pairs = [
                        (home_station, office_station)
                        for home_station, office_station in station_pairs
                        if _station_matches_name(home_station, preferred_entry_name)
                        and _station_matches_name(office_station, preferred_exit_name)
                    ]
                    if preferred_pairs:
                        station_pairs = preferred_pairs
                    else:
                        continue

                for home_station, office_station in station_pairs:
                        if integrated_transit_snapshot and preferred_station_pair:
                            selected_transit = {
                                "duration_min": int(
                                    integrated_transit_snapshot.get("integrated_subway_duration_min")
                                    or integrated_transit_snapshot["segments"][1]["duration_min"]
                                ),
                                "transit_entry_name": preferred_station_pair[0],
                                "transit_exit_name": preferred_station_pair[1],
                                "transit_line_name": integrated_transit_snapshot["segments"][1].get("transit_line_name"),
                            }
                        else:
                            try:
                                selected_transit = safe_route_for(
                                    "subway",
                                    home_station,
                                    office_station,
                                    route_options=(
                                        {"transit_strategy": transit_strategy}
                                        if transit_strategy
                                        else None
                                    ),
                                )
                            except Exception as error:
                                record_mode_error("subway", error)
                                continue
                        time_comparisons, selected_comparison = _build_static_time_comparisons(
                            selected_transit["duration_min"],
                            transit_profiles,
                            "当前分段地铁段使用实时路线快照，不再为每个时段重复请求接口。",
                            transit_duration_min=selected_transit["duration_min"],
                        )

                        transit_entry_name = selected_transit.get("transit_entry_name") or home_station["label"]
                        transit_exit_name = selected_transit.get("transit_exit_name") or office_station["label"]

                        for access_mode, egress_mode in mode_pairs:
                            try:
                                access = safe_route_for(access_mode, origin_point, home_station)
                            except Exception as error:
                                record_mode_error(access_mode, error)
                                continue
                            try:
                                egress = safe_route_for(egress_mode, office_station, destination_point)
                            except Exception as error:
                                record_mode_error(egress_mode, error)
                                continue

                            detailed_comparisons = []
                            for comparison in time_comparisons:
                                detailed_comparisons.append(
                                    {
                                        **comparison,
                                        "total_duration_min": (
                                            access["duration_min"]
                                            + comparison["transit_duration_min"]
                                            + egress["duration_min"]
                                        ),
                                    }
                                )
                            best_comparison = (
                                min(
                                    detailed_comparisons,
                                    key=lambda item: (item["total_duration_min"], item["transit_duration_min"]),
                                )
                                if detailed_comparisons
                                else None
                            )
                            selected_total_duration = int(
                                (best_comparison or {}).get(
                                    "total_duration_min",
                                    access["duration_min"] + selected_transit["duration_min"] + egress["duration_min"],
                                )
                            )
                            transit_duration = max(
                                1,
                                selected_total_duration - access["duration_min"] - egress["duration_min"],
                            )
                            template = f"{access_mode}->subway->{egress_mode}"
                            candidates.append(
                                {
                                    "origin_name": home_query,
                                    "destination_name": office_query,
                                    "used_alias_fallback": bool(
                                        origin_point.get("used_alias_fallback")
                                        or destination_point.get("used_alias_fallback")
                                    ),
                                    "search_strategy": (
                                        "alias_fallback"
                                        if origin_point.get("used_alias_fallback")
                                        or destination_point.get("used_alias_fallback")
                                        else "exact"
                                    ),
                                    "alias_type": candidate_alias_type(origin_point, destination_point),
                                    "segments": [
                                        {
                                            "mode": access_mode,
                                            "duration_min": access["duration_min"],
                                            "from_name": _point_display_label(origin_point),
                                            "to_name": transit_entry_name,
                                        },
                                        {
                                            "mode": "subway",
                                            "duration_min": transit_duration,
                                            "from_name": transit_entry_name,
                                            "to_name": transit_exit_name,
                                            "transit_entry_name": transit_entry_name,
                                            "transit_exit_name": transit_exit_name,
                                            "transit_line_name": selected_transit.get("transit_line_name"),
                                        },
                                        {
                                            "mode": egress_mode,
                                            "duration_min": egress["duration_min"],
                                            "from_name": transit_exit_name,
                                            "to_name": _point_display_label(destination_point),
                                        },
                                    ],
                                    "time_comparisons": detailed_comparisons,
                                    "timing_recommendation": best_comparison,
                                    "route_source": "stitched_station_combo",
                                    "station_source": "integrated_station_match" if explicit_station_pairs else "nearby_station_search",
                                    "template_override": template,
                                    "screenshot_hint": (
                                        f"高德真实算路结果，依次截图 {_point_display_label(origin_point)} → {transit_entry_name}、"
                                        f"{transit_entry_name} → {transit_exit_name}、{transit_exit_name} → {_point_display_label(destination_point)}。"
                                    ),
                                }
                            )
            return candidates

        exact_bike_candidate = build_direct_candidate("bike", exact_home_point, exact_office_point)
        exact_walk_candidate = None
        fallback_bike_candidates = []
        fallback_integrated_candidates = []
        fallback_station_candidates = []
        _debug_log(
            f"exact direct bike={sum(segment['duration_min'] for segment in exact_bike_candidate['segments']) if exact_bike_candidate else 'NA'}"
        )

        exact_integrated_candidate = None
        exact_station_candidates = []

        def build_station_candidates_for_pair(origin_point, destination_point, integrated_candidate):
            preferred_station_pair = None
            explicit_station_pairs = None
            if integrated_candidate:
                subway_segment = next(
                    (segment for segment in integrated_candidate["segments"] if segment["mode"] == "subway"),
                    None,
                )
                if subway_segment:
                    preferred_station_pair = (
                        subway_segment.get("transit_entry_name"),
                        subway_segment.get("transit_exit_name"),
                    )
                    entry_points = _amap_resolve_station_points(
                        preferred_station_pair[0],
                        config.amap_key,
                        cached_fetch_json,
                    )
                    exit_points = _amap_resolve_station_points(
                        preferred_station_pair[1],
                        config.amap_key,
                        cached_fetch_json,
                    )
                    if entry_points and exit_points:
                        explicit_station_pairs = [
                            (entry_point, exit_point)
                            for entry_point in entry_points
                            for exit_point in exit_points
                        ]
            station_candidates = build_station_combination_candidate_pool(
                [(origin_point, destination_point)],
                preferred_station_pair=preferred_station_pair,
                mode_pairs=(("bike", "bike"),),
                transit_strategy=integrated_candidate.get("transit_strategy_value")
                if integrated_candidate
                else None,
                explicit_station_pairs=explicit_station_pairs,
                integrated_transit_snapshot=integrated_candidate,
            )
            return station_candidates, explicit_station_pairs

        has_exact_compliant = bool(exact_bike_candidate and _candidate_is_compliant(exact_bike_candidate, rules))
        if not has_exact_compliant:
            exact_integrated_candidate = build_integrated_transit_candidate(exact_home_point, exact_office_point)
            _debug_log(
                "exact bike over limit, checking integrated transit "
                f"result={'missing' if not exact_integrated_candidate else sum(segment['duration_min'] for segment in exact_integrated_candidate['segments'])}"
            )
            exact_station_candidates, exact_explicit_station_pairs = build_station_candidates_for_pair(
                exact_home_point,
                exact_office_point,
                exact_integrated_candidate,
            )
            _debug_log(
                f"exact mixed station candidates={len(exact_station_candidates)} "
                f"station_source={'integrated_station_match' if exact_explicit_station_pairs else 'nearby_station_search'}"
            )
            has_exact_compliant = bool(
                (exact_integrated_candidate and _candidate_is_compliant(exact_integrated_candidate, rules))
                or any(_candidate_is_compliant(candidate, rules) for candidate in exact_station_candidates)
            )
            if not has_exact_compliant:
                alias_pairs = fallback_point_pairs()
                _debug_log(
                    f"exact bike / integrated / bike->subway->bike all over limit, checking alias fallback pairs={len(alias_pairs)}"
                )
                for origin_point, destination_point in alias_pairs:
                    fallback_bike_candidate = build_direct_candidate("bike", origin_point, destination_point)
                    if fallback_bike_candidate:
                        fallback_bike_candidates.append(fallback_bike_candidate)
                        if _candidate_is_compliant(fallback_bike_candidate, rules):
                            continue
                    fallback_integrated_candidate = build_integrated_transit_candidate(origin_point, destination_point)
                    if fallback_integrated_candidate:
                        fallback_integrated_candidates.append(fallback_integrated_candidate)
                    station_candidates, _ = build_station_candidates_for_pair(
                        origin_point,
                        destination_point,
                        fallback_integrated_candidate,
                    )
                    fallback_station_candidates.extend(station_candidates)
        else:
            _debug_log("exact direct bike compliant, stopping before integrated / walk fallback")

        if not has_exact_compliant and exact_walk_candidate is None:
            exact_walk_candidate = build_direct_candidate("walk", exact_home_point, exact_office_point)

        selected_walk_candidate = attach_alias_comparison(
            _pick_template_candidate(exact_walk_candidate, None, rules),
            exact_walk_candidate,
        )
        selected_bike_candidate = attach_alias_comparison(
            _pick_template_candidate(exact_bike_candidate, fallback_bike_candidates, rules),
            exact_bike_candidate,
        )

        _append_if_best(results, "amap", "walk", selected_walk_candidate)
        _append_if_best(results, "amap", "bike", selected_bike_candidate)

        selected_integrated_candidate = attach_alias_comparison(
            _pick_template_candidate(exact_integrated_candidate, fallback_integrated_candidates, rules),
            exact_integrated_candidate,
        )
        if selected_integrated_candidate:
            selected_integrated_candidate["template_override"] = "subway"
            _append_if_best(
                results,
                "amap",
                selected_integrated_candidate.pop("template_override"),
                selected_integrated_candidate,
            )

        station_candidate_pool = [*exact_station_candidates, *fallback_station_candidates]
        for template in ("bike->subway->bike",):
            station_candidates = [item for item in station_candidate_pool if item.get("template_override") == template]
            if not station_candidates:
                continue
            _append_if_best(
                results,
                "amap",
                template,
                attach_alias_comparison(_pick_template_candidate(None, station_candidates, rules), exact_integrated_candidate),
            )
    except Exception as error:
        _append_unique_error(provider_errors, "amap", str(error).strip() or error.__class__.__name__)
        if _is_amap_soft_timeout_error(error):
            soft_timeout_triggered = True

    if request_counts:
        request_summary = ", ".join(f"{key}={value}" for key, value in sorted(request_counts.items()))
        _debug_log(
            f"amap request summary total={sum(request_counts.values())} {request_summary}"
        )

    return {
        "options": results,
        "provider_errors": provider_errors,
        "soft_timeout": soft_timeout_triggered,
    }


def _fallback_provider_payload_context(payload):
    office = str(payload.get("office", "")).strip()
    home = str(payload.get("home", "")).strip()
    return {
        "office_aliases": [office] if office else [],
        "home_gates": [home] if home else [],
        "stations": [],
    }


def _build_fallback_provider_payload(payload, config, fetch_json=_fetch_json):
    payload_context = _fallback_provider_payload_context(payload)
    results = []
    provider_errors = []
    provider_specs = (
        ("baidu", config.baidu_key, _baidu_geocode, _baidu_route),
        ("qq", config.qq_key, _qq_geocode, _qq_route),
    )

    for provider, key, geocode_fn, route_fn in provider_specs:
        if not key:
            continue
        try:
            provider_payload = _build_provider_results(
                provider,
                key,
                payload_context,
                geocode_fn,
                route_fn,
                fetch_json,
            )
        except Exception as error:
            _append_unique_error(provider_errors, provider, str(error).strip() or error.__class__.__name__)
            continue
        results.extend(provider_payload["results"])
        for item in provider_payload["errors"]:
            _append_unique_error(provider_errors, item["provider"], item["message"])

    return {
        "options": results,
        "provider_errors": provider_errors,
    }


def load_provider_payload(payload, config=None, fetch_json=_fetch_json):
    config = config or load_config()
    provider_mode = config.mode
    provider_request_count = 0

    def counted_fetch_json(url):
        nonlocal provider_request_count
        provider_request_count += 1
        return fetch_json(url)

    if provider_mode == "live":
        if not config.amap_key:
            return {
                "options": [],
                "data_source": "live",
                "provider_mode": provider_mode,
                "live_failed": True,
                "warnings": [LIVE_KEY_WARNING],
                "provider_errors": [],
                "provider_request_count": 0,
            }

        live_payload = _build_live_provider_payload(payload, config, counted_fetch_json)
        live_results = list(live_payload["options"])
        provider_errors = list(live_payload["provider_errors"])
        if live_payload.get("soft_timeout"):
            fallback_payload = _build_fallback_provider_payload(payload, config, counted_fetch_json)
            live_results.extend(fallback_payload["options"])
            for item in fallback_payload["provider_errors"]:
                _append_unique_error(provider_errors, item["provider"], item["message"])
        if live_results:
            warnings = []
            if provider_errors:
                warnings.append(
                    "部分地图请求失败：" + "；".join(
                        _provider_error_message(item["provider"], item["message"])
                        for item in provider_errors
                    )
                )
            return {
                "options": live_results,
                "data_source": "live",
                "provider_mode": provider_mode,
                "live_failed": False,
                "warnings": warnings,
                "provider_errors": provider_errors,
                "provider_request_count": provider_request_count,
            }

        warnings = [LIVE_EMPTY_WARNING]
        if provider_errors:
            warnings.append(
                "具体失败原因：" + "；".join(
                    _provider_error_message(item["provider"], item["message"])
                    for item in provider_errors
                )
            )
        return {
            "options": [],
            "data_source": "live",
            "provider_mode": provider_mode,
            "live_failed": True,
            "warnings": warnings,
            "provider_errors": provider_errors,
            "provider_request_count": provider_request_count,
        }

    return {
        "options": _mock_routes(payload),
        "data_source": "mock",
        "provider_mode": provider_mode,
        "live_failed": False,
        "warnings": [DEMO_WARNING],
        "provider_errors": [],
        "provider_request_count": 0,
    }


def load_provider_options(payload):
    return load_provider_payload(payload)["options"]
