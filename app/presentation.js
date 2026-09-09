const providerLabels = {
  amap: "高德地图",
  baidu: "百度地图",
  qq: "腾讯地图",
};

const modeLabels = {
  walk: "步行",
  bike: "骑行",
  subway: "地铁",
};

const dataSourceLabels = {
  live: "实时地图结果",
  mock: "演示数据",
};

const routeSourceLabels = {
  direct: "直达结果",
  integrated: "高德综合公交",
  stitched_station_combo: "分段接驳兜底",
};

const stationSourceLabels = {
  integrated_station_match: "高德站名直解",
  nearby_station_search: "附近站枚举",
};

export function formatProviderLabel(provider) {
  return providerLabels[provider] ?? provider;
}

export function formatModeLabel(mode) {
  return modeLabels[mode] ?? mode;
}

export function formatTemplateLabel(template) {
  return template
    .split("->")
    .map((part) => formatModeLabel(part))
    .join(" → ");
}

function formatTransitLineName(segment) {
  return segment.transit_line_name ? `${segment.transit_line_name} · ` : "";
}

function formatTransitStationPair(segment) {
  if (!segment.transit_entry_name || !segment.transit_exit_name) {
    return "";
  }
  return `，${formatTransitLineName(segment)}${segment.transit_entry_name} → ${segment.transit_exit_name}`;
}

export function buildResultHeadline(result) {
  const segments = result.segments ?? [];
  const firstSegment = segments[0];
  const lastSegment = segments[segments.length - 1];
  const originName = result.origin_name ?? firstSegment?.from_name ?? "";
  const destinationName = result.destination_name ?? lastSegment?.to_name ?? "";
  const totalDurationMin = result.total_duration_min ?? segments.reduce((sum, segment) => sum + segment.duration_min, 0);
  const templateLabel = segments.length === 1
    ? formatModeLabel(segments[0].mode)
    : formatTemplateLabel(result.template);
  return `${templateLabel} ${totalDurationMin} 分钟 · ${originName} → ${destinationName}`;
}

export function buildVisibleResults(results) {
  const normalized = (results ?? []).filter((result) => result?.evaluation?.template_allowed !== false).slice();
  const deduped = normalized
    .filter((result, index, items) => items.indexOf(result) === index)
    .sort((left, right) => {
      const leftEvaluation = left?.evaluation ?? {};
      const rightEvaluation = right?.evaluation ?? {};
      const leftCompliant = Boolean(leftEvaluation.is_compliant);
      const rightCompliant = Boolean(rightEvaluation.is_compliant);
      if (leftCompliant !== rightCompliant) {
        return leftCompliant ? -1 : 1;
      }
      const leftDuration = Number(left.total_duration_min ?? 0);
      const rightDuration = Number(right.total_duration_min ?? 0);
      if (leftDuration !== rightDuration) {
        return leftDuration - rightDuration;
      }
      const leftSegments = left.segments?.length ?? 0;
      const rightSegments = right.segments?.length ?? 0;
      if (leftSegments !== rightSegments) {
        return leftSegments - rightSegments;
      }
      return 0;
    });
  const compliant = deduped.filter((result) => Boolean(result?.evaluation?.is_compliant));
  if (compliant.length) {
    return compliant;
  }
  if (!deduped.length) {
    return [];
  }
  return deduped
    .filter((result) => result?.evaluation?.reason !== "route_template_not_allowed")
    .slice()
    .sort((left, right) => {
      const leftEvaluation = left?.evaluation ?? {};
      const rightEvaluation = right?.evaluation ?? {};
      const leftOverLimit = Number(leftEvaluation.over_limit_min ?? Number.POSITIVE_INFINITY);
      const rightOverLimit = Number(rightEvaluation.over_limit_min ?? Number.POSITIVE_INFINITY);
      if (leftOverLimit !== rightOverLimit) {
        return leftOverLimit - rightOverLimit;
      }
      const leftDuration = Number(left.total_duration_min ?? 0);
      const rightDuration = Number(right.total_duration_min ?? 0);
      if (leftDuration !== rightDuration) {
        return leftDuration - rightDuration;
      }
      const leftSegments = left.segments?.length ?? 0;
      const rightSegments = right.segments?.length ?? 0;
      return leftSegments - rightSegments;
    })
    .slice(0, 1);
}

export function buildAlternativeResults(results) {
  return (results ?? []).slice(1);
}

export function formatSegmentDetail(segment, provider) {
  if (
    segment.mode === "subway" &&
    segment.transit_entry_name &&
    segment.transit_exit_name &&
    segment.from_name === segment.transit_entry_name &&
    segment.to_name === segment.transit_exit_name
  ) {
    return `该段预计 ${segment.duration_min} 分钟，来自 ${formatProviderLabel(provider)}。测距页面：${formatTransitLineName(segment)}${segment.transit_entry_name} → ${segment.transit_exit_name}。建议把这一段单独截图，再和其他段累加。`;
  }
  return `该段预计 ${segment.duration_min} 分钟，来自 ${formatProviderLabel(provider)}。测距页面：${segment.from_name} → ${segment.to_name}${formatTransitStationPair(segment)}。建议把这一段单独截图，再和其他段累加。`;
}

export function formatSegmentLine(segment) {
  if (segment.mode === "subway" && segment.transit_entry_name && segment.transit_exit_name) {
    return `${formatModeLabel(segment.mode)} ${segment.duration_min} 分钟 · ${formatTransitLineName(segment)}${segment.transit_entry_name} → ${segment.transit_exit_name}`;
  }
  return `${formatModeLabel(segment.mode)} ${segment.duration_min} 分钟 · ${segment.from_name} → ${segment.to_name}${formatTransitStationPair(segment)}`;
}

export function formatDataSourceLabel(meta) {
  return dataSourceLabels[meta?.data_source] ?? "结果来源未知";
}

export function describeDiagnostics(result) {
  const items = [];
  const routeSource = routeSourceLabels[result?.route_source] ?? "";
  const stationSource = stationSourceLabels[result?.station_source] ?? "";
  const transitStrategy = result?.transit_strategy_label ?? "";

  if (routeSource) {
    items.push(`结果来源：${routeSource}`);
  }
  if (transitStrategy) {
    items.push(`公交策略：${transitStrategy}`);
  }
  if (stationSource) {
    items.push(`站点来源：${stationSource}`);
  }
  return items;
}

export function describeTimingRecommendation(result, limitMin) {
  const recommendation = result.timing_recommendation;
  const comparisons = result.time_comparisons ?? [];
  const hasSubway = (result.segments ?? []).some((segment) => segment.mode === "subway");
  if (!hasSubway || !recommendation || !comparisons.length) {
    return null;
  }

  const rows = comparisons.map((item) => ({
    label: `${item.label} · ${item.date} ${item.time}`,
    totalDurationMin: item.total_duration_min,
    transitDurationMin: item.transit_duration_min,
    isCompliant: Number.isFinite(limitMin) ? item.total_duration_min <= limitMin : null,
    strategyLabel: item.strategy_label ?? result.transit_strategy_label ?? "",
    note: item.note ?? "",
  }));

  const strategyLine = recommendation.strategy_label ?? result.transit_strategy_label ?? "";

  return {
    headline: `推荐测距时段：${recommendation.label} · ${recommendation.date} ${recommendation.time}${strategyLine ? ` · ${strategyLine}` : ""}`,
    summary: recommendation.note
      ? `该时段预计总时长 ${recommendation.total_duration_min} 分钟。${strategyLine ? `当前采用${strategyLine}。` : ""}${recommendation.note}`
      : `该时段预计总时长 ${recommendation.total_duration_min} 分钟，地铁段 ${recommendation.transit_duration_min} 分钟。${strategyLine ? `当前采用${strategyLine}。` : ""}`,
    rows,
  };
}

export function describeMixedRouteAccuracyNote(result) {
  const template = String(result?.template || "");
  if (!["bike->subway->bike"].includes(template)) {
    return null;
  }
  if (result?.route_source === "integrated") {
    return "当前方案来自高德综合公交规划，站点与总时长更接近 App 端到端结果。建议最终仍在 App 内复验并截图。";
  }
  return "当前方案由门口 / 站点兜底拼装得出，分段时间可能与高德 App 端到端算路存在少量偏差。建议以 App 实际复验结果为准。";
}

export function describeNearMissHint(result) {
  const evaluation = result?.evaluation ?? {};
  const overLimitMin = Number(evaluation.over_limit_min ?? 0);
  if (evaluation.is_compliant || overLimitMin < 1 || overLimitMin > 3) {
    return null;
  }
  return `当前只超出规则 ${overLimitMin} 分钟，属于临界未合规方案；可回到地图 App 换个时间段复核，但复核前不能计为房补成功。`;
}


// 中文注释：当结果来自同名门口/楼栋别名比较时，给用户一个明确解释，说明为什么推荐这个起终点。
export function describeStrategyNote(result) {
  if (!result?.used_alias_fallback || !result?.segments?.length) {
    return null;
  }
  const firstSegment = result.segments[0];
  const lastSegment = result.segments[result.segments.length - 1];
  const exact = Number(result.exact_total_duration_min);
  const alias = Number(result.alias_total_duration_min ?? result.total_duration_min);
  const saved = Number.isFinite(exact) && Number.isFinite(alias) ? Math.max(0, exact - alias) : null;
  return `已比较同名门口 / 楼栋别名和原始地点，当前推荐：${firstSegment.from_name} → ${lastSegment.to_name}${saved != null ? `，比原始点节省 ${saved} 分钟` : ""}。`;
}

export function describeComplianceStatus(result) {
  const evaluation = result?.evaluation ?? {};
  if (!evaluation.is_compliant) {
    return { label: "未满足规则", className: "status-bad", copy: "系统找到了路线，但它没有通过当前房补规则。" };
  }
  if (evaluation.compliance_level === "boundary") {
    return { label: "临界合规·待复核", className: "status-boundary", copy: "时长已进入规则范围，但余量较小，必须回到地图 App 复核。" };
  }
  return { label: "明确合规·待复核", className: "status-good", copy: "路线已通过系统规则，仍需在地图 App 核对站点、出入口和截图。" };
}

export function buildCandidateComparison(result) {
  const exact = result?.exact_total_duration_min;
  const alias = result?.alias_total_duration_min ?? (result?.used_alias_fallback ? result?.total_duration_min : null);
  const rows = [];
  if (exact != null) rows.push({ candidate: "原始地点", duration: Number(exact), recommended: !result?.used_alias_fallback });
  if (alias != null) rows.push({ candidate: "门口 / 楼栋别名", duration: Number(alias), recommended: Boolean(result?.used_alias_fallback) });
  if (!rows.length && result?.total_duration_min != null) rows.push({ candidate: "原始地点", duration: Number(result.total_duration_min), recommended: true });
  return rows;
}

export function describeRecommendation(result) {
  const status = describeComplianceStatus(result);
  const aliasNote = describeStrategyNote(result);
  return `${status.copy}${aliasNote ? ` ${aliasNote}` : " 当前方案在合法模板中按合规状态、段数和总时长排序靠前。"}`;
}

export function describeRuleExclusions(meta) {
  return (meta?.excluded_routes ?? []).map((item) => ({
    template: formatTemplateLabel(item.template || "-"),
    duration: item.total_duration_min,
    reason: item.reason === "route_template_not_allowed"
      ? "路线组合不在当前规则白名单"
      : `超出对应阈值 ${item.over_limit_min ?? 0} 分钟`,
  }));
}

function formatScreenshotMode(segment) {
  if (segment.mode === "subway") {
    return "公交 / 地铁";
  }
  return formatModeLabel(segment.mode);
}

export function buildScreenshotChecklist(result) {
  const providerLabel = formatProviderLabel(result.provider);
  const total = result.total_duration_min ?? result.segments.reduce((sum, segment) => sum + segment.duration_min, 0);
  const steps = result.segments.map((segment, index) => ({
    index: index + 1,
    title: `截图 ${index + 1}`,
    mapApp: providerLabel,
    mode: formatScreenshotMode(segment),
    fromName: segment.from_name,
    toName: segment.to_name,
    durationLine: `${segment.duration_min} 分钟`,
    note:
      segment.mode === "subway" && segment.transit_entry_name && segment.transit_exit_name
        ? `地铁区间按 ${formatTransitLineName(segment)}${segment.transit_entry_name} → ${segment.transit_exit_name} 截图保存。`
        : "保留当前路线页的总时长和起终点信息。",
  }));
  const totalLine = steps.map((step) => step.durationLine).join(" + ");
  const submissionNote = result?.evaluation?.is_compliant
    ? `测距汇总：${totalLine} = ${total} 分钟。请回到地图 App 复核后，再判断能否作为房补材料。`
    : `测距汇总：${totalLine} = ${total} 分钟。当前未满足规则，仅用于定位差距，不应作为合规结论。`;

  return {
    steps,
    total,
    totalLine,
    submissionNote,
  };
}

export function describePlan(result) {
  const firstSegment = result.segments[0];
  const lastSegment = result.segments[result.segments.length - 1];
  const originName = result.origin_name ?? firstSegment.from_name;
  const destinationName = result.destination_name ?? lastSegment.to_name;
  if (result.segments.length <= 1) {
    return {
      title: `${formatProviderLabel(result.provider)} · ${formatTemplateLabel(result.template)}`,
      headline: buildResultHeadline(result),
      primaryLine: `${originName} → ${destinationName}`,
      transferLine: "无中转，直接到达公司",
      segmentLines: result.segments.map((segment) => formatSegmentLine(segment)),
    };
  }

  const transferStops = result.segments
    .filter((segment) => segment.mode === "subway")
    .map((segment) => {
      if (segment.transit_entry_name && segment.transit_exit_name) {
        const lineLabel = segment.transit_line_name ? `${segment.transit_line_name} · ` : "";
        return `${lineLabel}${segment.transit_entry_name} → ${segment.transit_exit_name}`;
      }
      if (segment.from_name === segment.to_name) {
        return segment.from_name;
      }
      return `${segment.from_name} → ${segment.to_name}`;
    });

  return {
    title: `${formatProviderLabel(result.provider)} · ${formatTemplateLabel(result.template)}`,
    headline: buildResultHeadline(result),
    primaryLine: `${originName} → ${destinationName}`,
    transferLine:
      transferStops.length > 0 ? `换乘信息：${transferStops.join("；")}` : "无中转，直接到达公司",
    segmentLines: result.segments.map((segment) => formatSegmentLine(segment)),
  };
}
