from backend.rules import evaluate_plan, normalize_rules


def _route_source_priority(plan):
    source = str(plan.get("route_source", "direct"))
    if source == "integrated":
        return 0
    if source == "direct":
        return 1
    if source == "stitched_station_combo":
        return 2
    return 3


def _bike_segment_priority(plan):
    segments = plan.get("segments", [])
    bike_count = sum(1 for segment in segments if segment.get("mode") == "bike")
    return -bike_count


def search_best_plans(provider_options, rules):
    rules = normalize_rules(rules)
    normalized = []
    for option in provider_options:
        total = sum(segment["duration_min"] for segment in option["segments"])
        plan = {
            **option,
            "total_duration_min": total,
        }
        plan["evaluation"] = evaluate_plan(plan, rules)
        normalized.append(plan)

    normalized.sort(
        key=lambda item: (
            not item["evaluation"]["is_compliant"],
            len(item["segments"]),
            item["total_duration_min"],
            _bike_segment_priority(item),
            item.get("used_alias_fallback", False),
            _route_source_priority(item),
            item["provider"],
        )
    )
    return normalized
