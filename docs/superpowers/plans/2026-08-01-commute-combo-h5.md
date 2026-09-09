# Commute Combo H5 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a runnable H5 demo that searches multi-segment commute options across mock/live provider adapters and returns the shortest compliant plan under configurable housing rules.

**Architecture:** Serve a static H5 frontend plus a small Python standard-library API server. Put the core commute search and rule evaluation in isolated Python modules with unit tests first. Support `mock` mode by default and `live` provider mode when API keys are present, so the demo works locally without setup but can be upgraded to real map calls later.

**Tech Stack:** HTML, CSS, vanilla JavaScript modules, Python 3 standard library (`http.server`, `urllib`, `unittest`)

---

## File Structure

- Create: `app/index.html`
- Create: `app/styles.css`
- Create: `app/app.js`
- Create: `app/demo-data.js`
- Create: `backend/config.py`
- Create: `backend/models.py`
- Create: `backend/rules.py`
- Create: `backend/engine.py`
- Create: `backend/providers.py`
- Create: `backend/server.py`
- Create: `backend/tests/test_rules.py`
- Create: `backend/tests/test_engine.py`
- Create: `backend/tests/test_server.py`
- Create: `README.md`

## Task 1: Define Rule Evaluation Core

**Files:**
- Create: `backend/models.py`
- Create: `backend/rules.py`
- Test: `backend/tests/test_rules.py`

- [ ] **Step 1: Write the failing rule tests**

```python
import unittest

from backend.rules import evaluate_plan


class EvaluatePlanTests(unittest.TestCase):
    def test_walk_only_is_valid_under_walk_limit(self):
        plan = {
            "segments": [{"mode": "walk", "duration_min": 28}],
            "total_duration_min": 28,
        }
        rules = {
            "walk_max_min": 30,
            "bike_or_subway_max_min": 20,
            "mixed_max_min": 20,
        }

        result = evaluate_plan(plan, rules)

        self.assertTrue(result["is_compliant"])
        self.assertEqual(result["reason"], "walk_within_limit")

    def test_bike_plus_subway_uses_mixed_limit(self):
        plan = {
            "segments": [
                {"mode": "bike", "duration_min": 6},
                {"mode": "subway", "duration_min": 11},
            ],
            "total_duration_min": 17,
        }
        rules = {
            "walk_max_min": 30,
            "bike_or_subway_max_min": 20,
            "mixed_max_min": 20,
        }

        result = evaluate_plan(plan, rules)

        self.assertTrue(result["is_compliant"])
        self.assertEqual(result["reason"], "mixed_within_limit")

    def test_non_compliant_plan_reports_margin(self):
        plan = {
            "segments": [{"mode": "subway", "duration_min": 24}],
            "total_duration_min": 24,
        }
        rules = {
            "walk_max_min": 30,
            "bike_or_subway_max_min": 20,
            "mixed_max_min": 20,
        }

        result = evaluate_plan(plan, rules)

        self.assertFalse(result["is_compliant"])
        self.assertEqual(result["over_limit_min"], 4)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
/Users/dengzhilei/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m unittest backend.tests.test_rules -v
```

Expected: `ImportError` or `ModuleNotFoundError` because `backend.rules` does not exist yet.

- [ ] **Step 3: Write minimal rule implementation**

```python
def evaluate_plan(plan, rules):
    modes = [segment["mode"] for segment in plan["segments"]]
    total = plan["total_duration_min"]

    if set(modes) == {"walk"}:
        limit = rules["walk_max_min"]
        reason = "walk_within_limit"
    elif len(set(modes)) == 1 and modes[0] in {"bike", "subway"}:
        limit = rules["bike_or_subway_max_min"]
        reason = f"{modes[0]}_within_limit"
    else:
        limit = rules["mixed_max_min"]
        reason = "mixed_within_limit"

    is_compliant = total <= limit
    return {
        "is_compliant": is_compliant,
        "reason": reason if is_compliant else "over_limit",
        "limit_min": limit,
        "over_limit_min": max(total - limit, 0),
        "margin_min": limit - total,
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run:

```bash
/Users/dengzhilei/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m unittest backend.tests.test_rules -v
```

Expected: `OK`

## Task 2: Implement Commute Combination Search

**Files:**
- Create: `backend/engine.py`
- Modify: `backend/models.py`
- Test: `backend/tests/test_engine.py`

- [ ] **Step 1: Write the failing engine tests**

```python
import unittest

from backend.engine import search_best_plans


class SearchBestPlansTests(unittest.TestCase):
    def test_returns_fastest_compliant_plan_first(self):
        provider_options = [
            {
                "provider": "amap",
                "template": "bike->subway",
                "segments": [
                    {"mode": "bike", "duration_min": 7},
                    {"mode": "subway", "duration_min": 12},
                ],
            },
            {
                "provider": "qq",
                "template": "bike->subway",
                "segments": [
                    {"mode": "bike", "duration_min": 6},
                    {"mode": "subway", "duration_min": 11},
                ],
            },
            {
                "provider": "baidu",
                "template": "walk",
                "segments": [{"mode": "walk", "duration_min": 33}],
            },
        ]
        rules = {
            "walk_max_min": 30,
            "bike_or_subway_max_min": 20,
            "mixed_max_min": 20,
        }

        results = search_best_plans(provider_options, rules)

        self.assertEqual(results[0]["provider"], "qq")
        self.assertTrue(results[0]["evaluation"]["is_compliant"])
        self.assertEqual(results[0]["total_duration_min"], 17)

    def test_keeps_non_compliant_plans_after_compliant_ones(self):
        provider_options = [
            {
                "provider": "amap",
                "template": "subway",
                "segments": [{"mode": "subway", "duration_min": 22}],
            },
            {
                "provider": "qq",
                "template": "bike",
                "segments": [{"mode": "bike", "duration_min": 19}],
            },
        ]
        rules = {
            "walk_max_min": 30,
            "bike_or_subway_max_min": 20,
            "mixed_max_min": 20,
        }

        results = search_best_plans(provider_options, rules)

        self.assertEqual(results[0]["provider"], "qq")
        self.assertFalse(results[1]["evaluation"]["is_compliant"])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
/Users/dengzhilei/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m unittest backend.tests.test_engine -v
```

Expected: `ImportError` because `search_best_plans` does not exist yet.

- [ ] **Step 3: Write minimal search implementation**

```python
from backend.rules import evaluate_plan


def search_best_plans(provider_options, rules):
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
            item["total_duration_min"],
            item["provider"],
        )
    )
    return normalized
```

- [ ] **Step 4: Run tests to verify they pass**

Run:

```bash
/Users/dengzhilei/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m unittest backend.tests.test_engine -v
```

Expected: `OK`

## Task 3: Add Provider Adapters And API Endpoint

**Files:**
- Create: `backend/config.py`
- Create: `backend/providers.py`
- Create: `backend/server.py`
- Test: `backend/tests/test_server.py`

- [ ] **Step 1: Write the failing server test**

```python
import json
import unittest

from backend.server import create_app


class ServerApiTests(unittest.TestCase):
    def test_search_endpoint_returns_ranked_results(self):
        app = create_app()
        client = app.test_client()

        response = client.post(
            "/api/search",
            data=json.dumps(
                {
                    "office": "ByteDance Shenzhen Bay",
                    "home": "Nanshan Example Garden",
                    "rules": {
                        "walk_max_min": 30,
                        "bike_or_subway_max_min": 20,
                        "mixed_max_min": 20,
                    },
                }
            ),
            headers={"Content-Type": "application/json"},
        )

        payload = json.loads(response.data.decode("utf-8"))

        self.assertEqual(response.status_code, 200)
        self.assertIn("results", payload)
        self.assertGreater(len(payload["results"]), 0)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Replace the failing test with a standard-library HTTP test before implementation**

```python
import json
import threading
import time
import unittest
import urllib.request

from backend.server import build_handler, ThreadingHTTPServer


class ServerApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), build_handler())
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        time.sleep(0.1)

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.thread.join(timeout=2)

    def test_search_endpoint_returns_ranked_results(self):
        request = urllib.request.Request(
            f"http://127.0.0.1:{self.port}/api/search",
            data=json.dumps(
                {
                    "office": "ByteDance Shenzhen Bay",
                    "home": "Nanshan Example Garden",
                    "rules": {
                        "walk_max_min": 30,
                        "bike_or_subway_max_min": 20,
                        "mixed_max_min": 20,
                    },
                }
            ).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        with urllib.request.urlopen(request) as response:
            payload = json.loads(response.read().decode("utf-8"))

        self.assertIn("results", payload)
        self.assertGreater(len(payload["results"]), 0)
```

- [ ] **Step 3: Run tests to verify they fail**

Run:

```bash
/Users/dengzhilei/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m unittest backend.tests.test_server -v
```

Expected: `ImportError` because the server modules do not exist yet.

- [ ] **Step 4: Write minimal provider and server implementation**

```python
def load_provider_options(payload):
    return [
        {
            "provider": "qq",
            "template": "bike->subway",
            "segments": [
                {"mode": "bike", "duration_min": 6},
                {"mode": "subway", "duration_min": 11},
            ],
        },
        {
            "provider": "amap",
            "template": "walk->subway",
            "segments": [
                {"mode": "walk", "duration_min": 5},
                {"mode": "subway", "duration_min": 13},
            ],
        },
    ]
```

```python
class CommuteHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        if self.path != "/api/search":
            self.send_error(404)
            return
```

- [ ] **Step 5: Run tests to verify they pass**

Run:

```bash
/Users/dengzhilei/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m unittest backend.tests.test_server -v
```

Expected: `OK`

## Task 4: Build H5 Search And Results Interface

**Files:**
- Create: `app/index.html`
- Create: `app/styles.css`
- Create: `app/app.js`
- Create: `app/demo-data.js`
- Modify: `backend/server.py`

- [ ] **Step 1: Write the UI contract down in code comments before markup**

```html
<!-- Search form: office, home, aliases, gates, rules -->
<!-- Summary card: best plan, total time, compliance -->
<!-- Ranked plan list: provider, template, segments, margin -->
<!-- Detail panel: segment breakdown and screenshot hint -->
```

- [ ] **Step 2: Create the minimal markup and seeded state**

```html
<main class="app-shell">
  <section class="query-panel"></section>
  <section class="result-panel"></section>
</main>
```

```js
const initialState = {
  office: "字节跳动深圳湾工区",
  home: "南山区示例花园",
  rules: {
    walk_max_min: 30,
    bike_or_subway_max_min: 20,
    mixed_max_min: 20,
  },
  results: [],
};
```

- [ ] **Step 3: Add result rendering and submit flow**

```js
async function searchPlans(payload) {
  const response = await fetch("/api/search", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  return response.json();
}
```

```js
function renderSummary(result) {
  return `
    <article class="hero-card">
      <p class="eyebrow">Best compliant route</p>
      <h2>${result.provider} · ${result.total_duration_min} min</h2>
      <p>${result.template}</p>
    </article>
  `;
}
```

- [ ] **Step 4: Add responsive styles and visual hierarchy**

```css
:root {
  --bg: #f3efe6;
  --panel: rgba(255, 255, 255, 0.86);
  --ink: #182126;
  --muted: #5d6a73;
  --accent: #1b7768;
  --warm: #ef9f63;
}
```

- [ ] **Step 5: Update server to serve static files**

```python
if self.path == "/" or self.path == "/index.html":
    return self._serve_file(APP_DIR / "index.html", "text/html; charset=utf-8")
```

## Task 5: Verify The Local Demo

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Run the full backend test suite**

Run:

```bash
/Users/dengzhilei/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m unittest discover backend/tests -v
```

Expected: `OK`

- [ ] **Step 2: Start the local server**

Run:

```bash
/Users/dengzhilei/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 backend/server.py
```

Expected: `Serving Commute Combo on http://127.0.0.1:8000`

- [ ] **Step 3: Check the rendered UI**

Open:

```text
http://127.0.0.1:8000
```

Expected:

- Search form is visible
- Clicking search returns at least one ranked result
- Summary card and detail drawer update

- [ ] **Step 4: Document setup and live-mode expectations**

Document:

- `mock` mode is the default
- real API calls require user-provided map keys
- live provider integration path is implemented behind environment variables
