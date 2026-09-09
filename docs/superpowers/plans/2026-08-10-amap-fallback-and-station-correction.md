# AMap Fallback And Station Correction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add AMap soft-timeout fallback to Baidu and Tencent, correct the station choice around Lijin Zhidi West Tower, and keep the UI limited to compliant shortest results.

**Architecture:** Keep AMap as the primary live provider, but stop AMap expansion once a soft time budget is exhausted and then try Baidu and Tencent as direct-provider fallbacks. Preserve backend ranking in `backend/engine.py`, correct station-pair preference inside the AMap provider flow, and tighten frontend visibility rules in `app/presentation.js`.

**Tech Stack:** Python 3 `unittest`, standard-library HTTP client wrappers, vanilla JavaScript module tests with `node --test`

---

### Task 1: Provider Fallback Policy

**Files:**
- Modify: `/Users/dengzhilei/Documents/Codex/2026-08-01/ai/backend/providers.py`
- Test: `/Users/dengzhilei/Documents/Codex/2026-08-01/ai/backend/tests/test_providers.py`

- [ ] Write a failing backend regression test for AMap soft-timeout and provider fallback.
- [ ] Run the targeted provider test to confirm the fallback behavior is missing.
- [ ] Add the minimal AMap soft-timeout tracking and Baidu/QQ fallback wiring.
- [ ] Re-run the targeted provider test until it passes.

### Task 2: Station Pair Correction

**Files:**
- Modify: `/Users/dengzhilei/Documents/Codex/2026-08-01/ai/backend/providers.py`
- Test: `/Users/dengzhilei/Documents/Codex/2026-08-01/ai/backend/tests/test_providers.py`

- [ ] Write a failing backend regression test for the Lijin Zhidi West Tower station choice preferring `魏公村站` over `苏州桥站`.
- [ ] Run the targeted provider test to confirm the current station preference can regress.
- [ ] Add the minimal candidate-selection bias toward the integrated station pair.
- [ ] Re-run the targeted provider test until it passes.

### Task 3: Compliant-Only Visible Results

**Files:**
- Modify: `/Users/dengzhilei/Documents/Codex/2026-08-01/ai/app/presentation.js`
- Test: `/Users/dengzhilei/Documents/Codex/2026-08-01/ai/app/presentation.test.js`

- [ ] Write a failing frontend regression test that hides over-limit alternatives when compliant options exist.
- [ ] Run the targeted frontend test to confirm the current near-miss display still leaks non-compliant results.
- [ ] Update `buildVisibleResults` to keep only compliant results, ordered by the shortest valid plan first.
- [ ] Re-run the targeted frontend test until it passes.
