import test from "node:test";
import assert from "node:assert/strict";

import { buildMetricCards, buildTemplateRows, formatPercent } from "./metrics.js";

test("formats percentage with one decimal place", () => {
  assert.equal(formatPercent(2, 5), "40.0%");
  assert.equal(formatPercent(0, 0), "0.0%");
});

test("builds overview metric cards from metrics payload", () => {
  const cards = buildMetricCards({
    total_searches: 10,
    successful_searches: 7,
    empty_searches: 3,
    compliant_searches: 4,
    alias_searches: 2,
    live_failed_searches: 1,
  });

  assert.equal(cards.length, 6)
  assert.equal(cards[0].title, "总搜索次数");
  assert.equal(cards[0].value, "10");
  assert.match(cards[1].note, /70.0%/);
  assert.match(cards[3].note, /40.0%/);
});

test("builds template rows sorted by count descending", () => {
  const rows = buildTemplateRows({
    template_breakdown: {
      bike: 6,
      "bike->subway->walk": 2,
      walk: 3,
    },
  });

  assert.deepEqual(
    rows.map((item) => item.template),
    ["bike", "walk", "bike->subway->walk"],
  );
  assert.equal(rows[0].count, 6);
});
