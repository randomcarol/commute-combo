const providerProfiles = {
  amap: { offset: 0, hint: "高德主算路会自动识别地点和附近地铁站" },
};

const templateLibrary = {
  walk: [{ mode: "walk", duration_min: 29 }],
  bike: [{ mode: "bike", duration_min: 19 }],
  subway: [
    { mode: "subway", duration_min: 10 },
  ],
  "bike->subway->bike": [
    { mode: "bike", duration_min: 5 },
    { mode: "subway", duration_min: 10 },
    { mode: "bike", duration_min: 4 },
  ],
};

function splitCandidates(rawValue, fallback) {
  if (!rawValue) return fallback;
  const values = Array.isArray(rawValue) ? rawValue : String(rawValue).split(",");
  const normalized = values.map((value) => value.trim()).filter(Boolean);
  return normalized.length ? normalized : fallback;
}

function textBias(...parts) {
  return (
    parts
      .flatMap((part) => Array.from(String(part)))
      .reduce((sum, char) => sum + char.charCodeAt(0), 0) % 3
  );
}

function decorateSegments(segments, homeLabel, officeLabel, stationName, offset) {
  return segments.map((segment, index) => {
    const duration = Math.max(1, segment.duration_min + offset);
    const totalSegments = segments.length;
    let fromName = homeLabel;
    let toName = officeLabel;

    if (totalSegments > 1 && index === 0) {
      toName = stationName;
    } else if (totalSegments > 1 && index === totalSegments - 1) {
      fromName = stationName;
    } else if (totalSegments > 2) {
      fromName = stationName;
      toName = stationName;
    }

    return { ...segment, duration_min: duration, from_name: fromName, to_name: toName };
  });
}

function evaluatePlan(plan, rules) {
  const modes = plan.segments.map((segment) => segment.mode);
  const uniqueModes = new Set(modes);
  const total = plan.total_duration_min;

  let limit = rules.mixed_max_min;
  let reason = "mixed_within_limit";

  if (uniqueModes.size === 1 && uniqueModes.has("walk")) {
    limit = rules.walk_max_min;
    reason = "walk_within_limit";
  } else if (uniqueModes.size === 1 && (uniqueModes.has("bike") || uniqueModes.has("subway"))) {
    limit = rules.bike_or_subway_max_min;
    reason = `${modes[0]}_within_limit`;
  }

  const templateAllowed = ["walk", "bike", "subway", "bike->subway->bike"].includes(plan.template);
  const isCompliant = templateAllowed && total <= limit;
  return {
    is_compliant: isCompliant,
    template_allowed: templateAllowed,
    rule_version: "commute-r1.0",
    compliance_level: isCompliant ? (limit - total <= 2 ? "boundary" : "clear") : (templateAllowed ? "over_limit" : "excluded"),
    reason: isCompliant ? reason : (templateAllowed ? "over_limit" : "route_template_not_allowed"),
    limit_min: limit,
    over_limit_min: Math.max(total - limit, 0),
    margin_min: limit - total,
  };
}

export function buildDemoResponse(payload) {
  const office = payload.office || "示例公司园区";
  const home = payload.home || "示例租房小区";
  const officeLabel = office;
  const homeLabel = home;
  const stations = ["系统识别起始站", "系统识别到达站"];

  const options = Object.entries(providerProfiles).flatMap(([provider, profile]) =>
    Object.entries(templateLibrary).map(([template, segments]) => {
      const stationName = stations[textBias(provider, template, office, home) % stations.length];
      const offset = profile.offset + textBias(officeLabel, homeLabel, template) - 1;
      const routeSegments = decorateSegments(segments, homeLabel, officeLabel, stationName, offset);
      const total = routeSegments.reduce((sum, segment) => sum + segment.duration_min, 0);
      const plan = {
        provider,
        template,
        segments: routeSegments,
        total_duration_min: total,
      };
      return {
        ...plan,
        evaluation: evaluatePlan(plan, payload.rules),
        screenshot_hint: `${profile.hint}，优先检查 ${stationName} 这一段。`,
      };
    })
  );

  options.sort(
    (left, right) =>
      Number(left.evaluation.is_compliant) * -1 +
      Number(right.evaluation.is_compliant) -
      right.total_duration_min +
      left.total_duration_min
  );
  options.sort((left, right) => {
    if (left.evaluation.is_compliant !== right.evaluation.is_compliant) {
      return left.evaluation.is_compliant ? -1 : 1;
    }
    if (left.segments.length !== right.segments.length) {
      return left.segments.length - right.segments.length;
    }
    if (left.total_duration_min !== right.total_duration_min) {
      return left.total_duration_min - right.total_duration_min;
    }
    return left.provider.localeCompare(right.provider);
  });

  return {
    query: payload,
    results: options,
    meta: {
      app_version: "0.4.0",
      rule_version: "commute-r1.0",
      environment: "demo",
      provider_request_count: 0,
      data_source: "mock",
      provider_mode: "mock",
      live_failed: false,
      warnings: ["当前展示的是演示数据，不代表真实地图时间。"],
    },
  };
}
