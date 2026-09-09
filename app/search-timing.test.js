import test from "node:test";
import assert from "node:assert/strict";

import { scheduleSearchProgress } from "./search-timing.js";

test("search progress only schedules a slow-search hint and does not auto-abort", () => {
  const scheduled = [];
  const cleared = [];
  let slowTriggered = 0;

  const handle = scheduleSearchProgress({
    onSlow() {
      slowTriggered += 1;
    },
    setTimeoutFn(callback, delay) {
      scheduled.push({ callback, delay });
      return scheduled.length;
    },
    clearTimeoutFn(timerId) {
      cleared.push(timerId);
    },
  });

  assert.equal(scheduled.length, 1);
  assert.equal(scheduled[0].delay, 5000);

  scheduled[0].callback();
  assert.equal(slowTriggered, 1);

  handle.cancel();
  assert.deepEqual(cleared, [1]);
});
