import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";

import {
  buildAlternativeResults,
  buildCandidateComparison,
  buildScreenshotChecklist,
  buildResultHeadline,
  buildVisibleResults,
  describeNearMissHint,
  describeDiagnostics,
  describeComplianceStatus,
  describePlan,
  describeMixedRouteAccuracyNote,
  describeStrategyNote,
  describeTimingRecommendation,
  formatDataSourceLabel,
  formatModeLabel,
  formatProviderLabel,
  formatSegmentDetail,
  formatTemplateLabel,
} from "./presentation.js";

test("formats provider, mode, and template labels in Chinese", () => {
  assert.equal(formatProviderLabel("amap"), "高德地图");
  assert.equal(formatProviderLabel("baidu"), "百度地图");
  assert.equal(formatProviderLabel("qq"), "腾讯地图");
  assert.equal(formatModeLabel("walk"), "步行");
  assert.equal(formatModeLabel("bike"), "骑行");
  assert.equal(formatModeLabel("subway"), "地铁");
  assert.equal(formatTemplateLabel("bike->subway->walk"), "骑行 → 地铁 → 步行");
});

test("describes route with concrete station transfers and map source", () => {
  const result = {
    provider: "amap",
    template: "bike->subway->walk",
    segments: [
      {
        mode: "bike",
        duration_min: 5,
        from_name: "南山区示例花园东门",
        to_name: "后海站",
      },
      {
        mode: "subway",
        duration_min: 12,
        from_name: "后海站",
        to_name: "字节跳动深圳湾工区",
        transit_entry_name: "后海站",
        transit_exit_name: "科苑站",
        transit_line_name: "11号线",
      },
      {
        mode: "walk",
        duration_min: 4,
        from_name: "科苑站",
        to_name: "字节跳动深圳湾工区",
      },
    ],
  };

  const description = describePlan(result);

  assert.match(description.title, /高德地图/);
  assert.match(description.title, /骑行/);
  assert.match(description.primaryLine, /南山区示例花园东门/);
  assert.match(description.primaryLine, /字节跳动深圳湾工区/);
  assert.match(description.transferLine, /后海站/);
  assert.match(description.transferLine, /科苑站/);
  assert.match(description.transferLine, /11号线/);
  assert.match(description.segmentLines[1], /11号线/);
});

test("collapses generic auto-matched station labels in transfer summary", () => {
  const result = {
    provider: "baidu",
    template: "bike->subway->walk",
    segments: [
      {
        mode: "bike",
        duration_min: 2,
        from_name: "海淀区北洼路中海雅园东门",
        to_name: "系统自动匹配地铁站",
      },
      {
        mode: "subway",
        duration_min: 7,
        from_name: "系统自动匹配地铁站",
        to_name: "系统自动匹配地铁站",
      },
      {
        mode: "walk",
        duration_min: 1,
        from_name: "系统自动匹配地铁站",
        to_name: "丽金智地西塔",
      },
    ],
  };

  const description = describePlan(result);

  assert.equal(description.transferLine, "换乘信息：系统自动匹配地铁站");
});

test("shows direct-arrival text for single subway plan", () => {
  const result = {
    provider: "baidu",
    template: "subway",
    segments: [
      {
        mode: "subway",
        duration_min: 19,
        from_name: "海淀区北洼西里中海雅园",
        to_name: "丽金智地西塔",
      },
    ],
  };

  const description = describePlan(result);

  assert.equal(description.transferLine, "无中转，直接到达公司");
});

test("formats transit segment detail with real station pair", () => {
  const detail = formatSegmentDetail(
    {
      mode: "subway",
      duration_min: 14,
      from_name: "后海站",
      to_name: "深圳湾创新科技中心T2栋",
      transit_entry_name: "后海站",
      transit_exit_name: "科苑站",
      transit_line_name: "11号线",
    },
    "amap"
  );

  assert.match(detail, /高德地图/);
  assert.match(detail, /后海站/);
  assert.match(detail, /科苑站/);
  assert.match(detail, /11号线/);
});

test("builds a large summary headline from total duration and origin destination", () => {
  const headline = buildResultHeadline({
    template: "bike",
    total_duration_min: 22,
    origin_name: "中海雅园",
    destination_name: "丽金智地中心西塔",
    segments: [
      {
        mode: "bike",
        duration_min: 22,
        from_name: "中海雅园",
        to_name: "丽金智地中心西塔",
      },
    ],
  });

  assert.equal(headline, "骑行 22 分钟 · 中海雅园 → 丽金智地中心西塔");
});

test("shows only compliant results when at least one valid plan exists", () => {
  const visible = buildVisibleResults([
    {
      provider: "amap",
      template: "bike",
      total_duration_min: 20,
      segments: [{ mode: "bike", duration_min: 20, from_name: "中海雅园", to_name: "公司" }],
      evaluation: { is_compliant: true, limit_min: 20, over_limit_min: 0, margin_min: 0 },
    },
    {
      provider: "amap",
      template: "walk",
      total_duration_min: 33,
      segments: [{ mode: "walk", duration_min: 33, from_name: "中海雅园", to_name: "公司" }],
      evaluation: { is_compliant: false, limit_min: 30, over_limit_min: 3, margin_min: -3 },
    },
    {
      provider: "amap",
      template: "bike->subway->walk",
      total_duration_min: 26,
      segments: [
        { mode: "bike", duration_min: 5, from_name: "中海雅园", to_name: "慈寿寺站" },
        { mode: "subway", duration_min: 17, from_name: "慈寿寺站", to_name: "魏公村站" },
        { mode: "walk", duration_min: 4, from_name: "魏公村站", to_name: "公司" },
      ],
      evaluation: { is_compliant: false, limit_min: 20, over_limit_min: 6, margin_min: -6 },
    },
  ]);

  assert.equal(visible.length, 1);
  assert.equal(visible[0].template, "bike");
});

test("shows the closest near-miss result when no compliant plan exists", () => {
  const visible = buildVisibleResults([
    {
      provider: "amap",
      template: "walk",
      total_duration_min: 33,
      segments: [{ mode: "walk", duration_min: 33, from_name: "中海雅园", to_name: "公司" }],
      evaluation: { is_compliant: false, limit_min: 30, over_limit_min: 3, margin_min: -3 },
    },
    {
      provider: "baidu",
      template: "bike",
      total_duration_min: 22,
      segments: [{ mode: "bike", duration_min: 22, from_name: "中海雅园", to_name: "公司" }],
      evaluation: { is_compliant: false, limit_min: 20, over_limit_min: 2, margin_min: -2 },
    },
    {
      provider: "qq",
      template: "subway",
      total_duration_min: 27,
      segments: [{ mode: "subway", duration_min: 27, from_name: "中海雅园", to_name: "公司" }],
      evaluation: { is_compliant: false, limit_min: 20, over_limit_min: 7, margin_min: -7 },
    },
  ]);

  assert.equal(visible.length, 1);
  assert.equal(visible[0].provider, "baidu");
  assert.equal(visible[0].template, "bike");
});

test("omits the shortest summary plan from the alternatives list", () => {
  const alternatives = buildAlternativeResults([
    { template: "bike", total_duration_min: 20 },
    { template: "walk", total_duration_min: 33 },
    { template: "bike->subway->walk", total_duration_min: 26 },
  ]);

  assert.deepEqual(
    alternatives.map((item) => item.template),
    ["walk", "bike->subway->walk"]
  );
});

test("shows a retry hint when a result is only slightly over the limit", () => {
  const hint = describeNearMissHint({
    evaluation: {
      is_compliant: false,
      over_limit_min: 2,
      limit_min: 20,
    },
  });

  assert.match(hint, /地图 App/);
  assert.match(hint, /换个时间段/);
});

test("formats data source labels in Chinese", () => {
  assert.equal(formatDataSourceLabel({ data_source: "live" }), "实时地图结果");
  assert.equal(formatDataSourceLabel({ data_source: "mock" }), "演示数据");
});

test("builds screenshot checklist with per-segment instructions and total summary", () => {
  const checklist = buildScreenshotChecklist({
    provider: "amap",
    total_duration_min: 19,
    segments: [
      {
        mode: "bike",
        duration_min: 5,
        from_name: "中海雅园",
        to_name: "后海站",
      },
      {
        mode: "subway",
        duration_min: 10,
        from_name: "后海站",
        to_name: "科苑站",
        transit_entry_name: "后海站",
        transit_exit_name: "科苑站",
      },
      {
        mode: "walk",
        duration_min: 4,
        from_name: "科苑站",
        to_name: "字节跳动深圳湾工区",
      },
    ],
  });

  assert.equal(checklist.steps.length, 3);
  assert.equal(checklist.steps[0].mapApp, "高德地图");
  assert.equal(checklist.steps[1].mode, "公交 / 地铁");
  assert.match(checklist.steps[1].note, /后海站/);
  assert.match(checklist.steps[1].note, /科苑站/);
  assert.equal(checklist.totalLine, "5 分钟 + 10 分钟 + 4 分钟");
  assert.match(checklist.submissionNote, /19 分钟/);
});

test("describes recommended transit measurement time window", () => {
  const timing = describeTimingRecommendation(
    {
      segments: [
        { mode: "bike", duration_min: 5, from_name: "中海雅园", to_name: "后海站" },
        { mode: "subway", duration_min: 10, from_name: "后海站", to_name: "科苑站" },
        { mode: "walk", duration_min: 4, from_name: "科苑站", to_name: "字节跳动深圳湾工区" },
      ],
      timing_recommendation: {
        label: "周末白天",
        date: "2026-08-08",
        time: "10:00",
        total_duration_min: 19,
        transit_duration_min: 10,
        strategy_label: "时间短模式",
      },
      time_comparisons: [
        {
          label: "工作日早高峰",
          date: "2026-08-03",
          time: "08:30",
          total_duration_min: 24,
          transit_duration_min: 15,
          strategy_label: "时间短模式",
        },
        {
          label: "周末白天",
          date: "2026-08-08",
          time: "10:00",
          total_duration_min: 19,
          transit_duration_min: 10,
          strategy_label: "时间短模式",
        },
      ],
    },
    20
  );

  assert.match(timing.headline, /2026-08-08 10:00/);
  assert.match(timing.headline, /时间短模式/);
  assert.match(timing.summary, /19 分钟/);
  assert.match(timing.summary, /时间短模式/);
  assert.equal(timing.rows[0].isCompliant, false);
  assert.equal(timing.rows[1].isCompliant, true);
});

test("does not show timing comparison for direct non-subway plans", () => {
  const timing = describeTimingRecommendation(
    {
      template: "bike",
      segments: [{ mode: "bike", duration_min: 25, from_name: "中海雅园", to_name: "丽金智地中心西塔" }],
      timing_recommendation: {
        label: "工作日早高峰",
        date: "2026-08-03",
        time: "08:30",
        total_duration_min: 25,
        transit_duration_min: 0,
        note: "骑行当前接口以实时结果为准，暂不支持按出发时间精确枚举。",
      },
      time_comparisons: [
        {
          label: "工作日早高峰",
          date: "2026-08-03",
          time: "08:30",
          total_duration_min: 25,
          transit_duration_min: 0,
          note: "骑行当前接口以实时结果为准，暂不支持按出发时间精确枚举。",
        },
      ],
    },
    20
  );

  assert.equal(timing, null);
});

test("explains when a faster name-derived alias route is recommended", () => {
  const note = describeStrategyNote({
    used_alias_fallback: true,
    exact_total_duration_min: 23,
    alias_total_duration_min: 19,
    segments: [
      {
        mode: "bike",
        duration_min: 19,
        from_name: "中海雅园北门",
        to_name: "丽金智地中心西塔",
      },
    ],
  });

  assert.match(note, /已比较同名门口/);
  assert.match(note, /中海雅园北门/);
  assert.match(note, /丽金智地中心西塔/);
  assert.match(note, /节省 4 分钟/);
});

test("separates boundary compliance from clear compliance", () => {
  assert.equal(describeComplianceStatus({ evaluation: { is_compliant: true, compliance_level: "boundary" } }).label, "临界合规·待复核");
  assert.equal(describeComplianceStatus({ evaluation: { is_compliant: true, compliance_level: "clear" } }).label, "明确合规·待复核");
});

test("builds original versus alias candidate comparison", () => {
  const rows = buildCandidateComparison({ used_alias_fallback: true, exact_total_duration_min: 24, alias_total_duration_min: 19 });
  assert.deepEqual(rows.map((item) => item.duration), [24, 19]);
  assert.equal(rows[1].recommended, true);
});

test("describes diagnostic info for live mixed route results", () => {
  const diagnostics = describeDiagnostics({
    route_source: "integrated",
    transit_strategy_label: "时间短模式",
    station_source: "integrated_station_match",
  });

  assert.deepEqual(diagnostics, [
    "结果来源：高德综合公交",
    "公交策略：时间短模式",
    "站点来源：高德站名直解",
  ]);
});

test("shows a timing-bias note for split subway routes", () => {
  const note = describeMixedRouteAccuracyNote({
    template: "bike->subway->bike",
    route_source: "stitched_station_combo",
    segments: [
      { mode: "bike", duration_min: 4, from_name: "中海雅园北门", to_name: "慈寿寺站A口" },
      { mode: "subway", duration_min: 11, from_name: "慈寿寺站", to_name: "魏公村站" },
      { mode: "bike", duration_min: 3, from_name: "魏公村站B口", to_name: "飞诺门阵" },
    ],
  });

  assert.match(note, /门口 \/ 站点兜底拼装/);
  assert.match(note, /高德 App/);
});

test("does not show a timing-bias note for direct routes", () => {
  const note = describeMixedRouteAccuracyNote({
    template: "bike",
    segments: [{ mode: "bike", duration_min: 18, from_name: "中海雅园", to_name: "飞诺门阵" }],
  });

  assert.equal(note, null);
});

test("index page shows privacy and analytics notice", () => {
  const html = fs.readFileSync(new URL("./index.html", import.meta.url), "utf8");

  assert.match(html, /隐私与数据说明/);
  assert.match(html, /不会存储完整地址原文/);
  assert.match(html, /脱敏后的搜索统计/);
  assert.match(html, /这组结果对你有帮助吗/);
  assert.match(html, /v0\.4\.0 · 实验版 · 非正式生产工具/);
  assert.match(html, /地图 App 复核/);
  assert.match(html, /CASE-001/);
});
