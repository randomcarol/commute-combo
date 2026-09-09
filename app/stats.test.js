import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";

import {
  buildExperimentCards,
  buildFeedbackThemeRows,
  buildProviderRows,
  buildRecentRows,
  buildRecommendationCards,
  buildRouteRows,
  buildStatCards,
} from "./stats.js";

test("builds summary cards for stats page", () => {
  const cards = buildStatCards({
    total_searches: 10,
    successful_searches: 7,
    compliant_searches: 4,
    result_without_compliant_searches: 2,
    warning_searches: 1,
    feedback_total: 5,
    feedback_helpful_count: 4,
  });

  assert.equal(cards.length, 6);
  assert.equal(cards[0].title, "有效测距完成率");
  assert.match(cards[1].note, /70\.0%/);
  assert.equal(cards[3].title, "错误合规");
});

test("builds honest small-sample experiment cards", () => {
  const cards = buildExperimentCards({ experiment_summary: { case_count: 3, sample_note: "样本量较小，仅用于探索性验证", live_search_success_rate: 2 / 3 } });
  assert.equal(cards[0].value, "3");
  assert.match(cards[0].note, /样本量较小/);
  assert.equal(cards[1].value, "66.7%");
});

test("builds route rows and recent search rows", () => {
  const routeRows = buildRouteRows({
    route_type_distribution: {
      bike: { matched_count: 3, shown_count: 5, average_duration_min: 18.3 },
    },
  });
  const recentRows = buildRecentRows({
    recent_searches: [
      {
        request_id: "request-123456",
        environment: "self_test",
        template: "bike",
        total_duration_min: 18,
        is_compliant: true,
      },
    ],
  });

  assert.equal(routeRows[0].template, "bike");
  assert.equal(routeRows[0].matchRate, "60.0%");
  assert.equal(recentRows[0].duration, "18 分钟");
  assert.equal(recentRows[0].compliance, "系统合规·待复核");
});

test("builds provider rows, feedback theme rows, and recommendation cards", () => {
  const providerRows = buildProviderRows({
    total_searches: 10,
    provider_breakdown: {
      amap: 5,
      baidu: 3,
      qq: 2,
    },
  });
  const feedbackRows = buildFeedbackThemeRows({
    feedback_theme_breakdown: {
      station_accuracy: 2,
      alias_coverage: 1,
    },
  });
  const recommendations = buildRecommendationCards({
    total_searches: 10,
    empty_searches: 3,
    result_without_compliant_searches: 4,
    warning_searches: 2,
    alias_uplift: { count: 2, average_saved_min: 4.5 },
    feedback_theme_breakdown: {
      station_accuracy: 3,
      speed_or_latency: 2,
      alias_coverage: 1,
    },
  });

  assert.equal(providerRows[0].provider, "amap");
  assert.equal(providerRows[0].share, "50.0%");
  assert.equal(feedbackRows[0].theme, "station_accuracy");
  assert.match(recommendations[0].title, /地铁站|接驳/);
  assert.equal(recommendations.length, 4);
});

test("stats page includes a table and next-iteration tip", () => {
  const html = fs.readFileSync(new URL("./stats.html", import.meta.url), "utf8");

  assert.match(html, /最近 10 次关联搜索/);
  assert.match(html, /产品下一步建议/);
  assert.match(html, /反馈主题/);
  assert.match(html, /provider-breakdown-body/);
  assert.match(html, /route-distribution-body/);
  assert.match(html, /stats-environment/);
  assert.match(html, /样本量较小/);
});
