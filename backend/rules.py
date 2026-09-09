APP_VERSION = "0.4.0"
RULE_VERSION = "commute-r1.0"
LEGAL_ROUTE_TEMPLATES = (
    "walk",
    "bike",
    "subway",
    "bike->subway->bike",
)
DEFAULT_RULES = {
    "rule_version": RULE_VERSION,
    "walk_max_min": 30,
    "bike_or_subway_max_min": 20,
    "mixed_max_min": 20,
}
BOUNDARY_MARGIN_MIN = 2


def normalize_rules(raw_rules=None):
    rules = dict(DEFAULT_RULES)
    if isinstance(raw_rules, dict):
        for key in ("walk_max_min", "bike_or_subway_max_min", "mixed_max_min"):
            if raw_rules.get(key) is not None:
                rules[key] = int(raw_rules[key])
        requested_version = str(raw_rules.get("rule_version") or RULE_VERSION).strip()
        if requested_version != RULE_VERSION:
            raise ValueError(f"unsupported rule_version: {requested_version}")
    return rules


def route_template(plan):
    explicit = str(plan.get("template") or "").strip()
    if explicit:
        return explicit
    return "->".join(segment["mode"] for segment in plan.get("segments", []))


def evaluate_plan(plan, rules=None):
    normalized_rules = normalize_rules(rules)
    template = route_template(plan)
    total = int(plan["total_duration_min"])

    if template == "walk":
        limit = normalized_rules["walk_max_min"]
        success_reason = "walk_within_limit"
    elif template in {"bike", "subway"}:
        limit = normalized_rules["bike_or_subway_max_min"]
        success_reason = f"{template}_within_limit"
    else:
        limit = normalized_rules["mixed_max_min"]
        success_reason = "mixed_within_limit"

    template_allowed = template in LEGAL_ROUTE_TEMPLATES
    within_limit = total <= limit
    is_compliant = template_allowed and within_limit
    margin_min = limit - total
    if not template_allowed:
        reason = "route_template_not_allowed"
        compliance_level = "excluded"
    elif not within_limit:
        reason = "over_limit"
        compliance_level = "over_limit"
    elif margin_min <= BOUNDARY_MARGIN_MIN:
        reason = success_reason
        compliance_level = "boundary"
    else:
        reason = success_reason
        compliance_level = "clear"

    return {
        "route_found": True,
        "template_allowed": template_allowed,
        "is_compliant": is_compliant,
        "compliance_level": compliance_level,
        "reason": reason,
        "rule_version": normalized_rules["rule_version"],
        "limit_min": limit,
        "over_limit_min": max(total - limit, 0),
        "margin_min": margin_min,
    }
