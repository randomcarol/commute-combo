import {
  buildAlternativeResults,
  buildCandidateComparison,
  buildScreenshotChecklist,
  buildResultHeadline,
  buildVisibleResults,
  describeDiagnostics,
  describeComplianceStatus,
  describeMixedRouteAccuracyNote,
  describeNearMissHint,
  describePlan,
  describeRecommendation,
  describeRuleExclusions,
  describeStrategyNote,
  describeTimingRecommendation,
  formatDataSourceLabel,
  formatModeLabel,
  formatProviderLabel,
  formatSegmentDetail,
  formatTemplateLabel,
} from "./presentation.js";
import { scheduleSearchProgress } from "./search-timing.js";

const APP_VERSION = "0.4.0";
const RULE_VERSION = "commute-r1.0";
const VALID_ENVIRONMENTS = new Set(["dev", "test", "demo", "self_test", "prod"]);

function createId() {
  return globalThis.crypto?.randomUUID?.() ?? `local-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function getAnonymousSessionId() {
  try {
    const key = "commute_anonymous_session_id";
    const current = localStorage.getItem(key);
    if (current) return current;
    const created = createId();
    localStorage.setItem(key, created);
    return created;
  } catch (error) {
    return createId();
  }
}

const ANONYMOUS_SESSION_ID = getAnonymousSessionId();

const state = {
  mode: "checking",
  results: [],
  selectedIndex: 0,
  lastPayload: null,
  meta: null,
  banner: null,
  isSearching: false,
  slowSearchTimer: null,
  activeSearchController: null,
  searchAbortReason: "",
  selectedPlaces: {
    office: null,
    home: null,
  },
  suggestions: {
    office: [],
    home: [],
  },
  feedback: {
    helpful: null,
    submitted: false,
    loading: false,
    error: "",
  },
  review: { submitted: false, loading: false, error: "" },
  experiment: { submitted: false, loading: false, error: "" },
};

const elements = {
  form: document.querySelector("#search-form"),
  office: document.querySelector("#office"),
  home: document.querySelector("#home"),
  officeSuggestions: document.querySelector("#office-suggestions"),
  homeSuggestions: document.querySelector("#home-suggestions"),
  walkLimit: document.querySelector("#walk-limit"),
  bikeSubwayLimit: document.querySelector("#bike-subway-limit"),
  mixedLimit: document.querySelector("#mixed-limit"),
  environment: document.querySelector("#environment"),
  searchSubmit: document.querySelector("#search-submit"),
  searchCancel: document.querySelector("#search-cancel"),
  sourceBanner: document.querySelector("#source-banner"),
  summaryCard: document.querySelector("#summary-card"),
  resultList: document.querySelector("#result-list"),
  detailView: document.querySelector("#detail-view"),
  feedbackPanel: document.querySelector("#feedback-panel"),
  feedbackHelpful: document.querySelector("#feedback-helpful"),
  feedbackUnhelpful: document.querySelector("#feedback-unhelpful"),
  feedbackExtra: document.querySelector("#feedback-extra"),
  feedbackNote: document.querySelector("#feedback-note"),
  feedbackSubmit: document.querySelector("#feedback-submit"),
  feedbackStatus: document.querySelector("#feedback-status"),
  reviewPanel: document.querySelector("#review-panel"),
  reviewOutcomes: document.querySelector("#review-outcomes"),
  reviewMinutes: document.querySelector("#review-minutes"),
  reviewIssue: document.querySelector("#review-issue"),
  reviewNote: document.querySelector("#review-note"),
  reviewSubmit: document.querySelector("#review-submit"),
  reviewStatus: document.querySelector("#review-status"),
  experimentForm: document.querySelector("#experiment-form"),
  experimentStatus: document.querySelector("#experiment-status"),
};

const suggestionTimers = new Map();

function getInputElement(field) {
  return field === "office" ? elements.office : elements.home;
}

function getSuggestionElement(field) {
  return field === "office" ? elements.officeSuggestions : elements.homeSuggestions;
}

function collectPayload() {
  const requestedEnvironment = elements.environment?.value || "dev";
  return {
    request_id: createId(),
    anonymous_session_id: ANONYMOUS_SESSION_ID,
    environment: VALID_ENVIRONMENTS.has(requestedEnvironment) ? requestedEnvironment : "dev",
    app_version: APP_VERSION,
    rule_version: RULE_VERSION,
    office: elements.office.value.trim(),
    home: elements.home.value.trim(),
    office_selection: state.selectedPlaces.office,
    home_selection: state.selectedPlaces.home,
    rules: {
      rule_version: RULE_VERSION,
      walk_max_min: Number(elements.walkLimit.value),
      bike_or_subway_max_min: Number(elements.bikeSubwayLimit.value),
      mixed_max_min: Number(elements.mixedLimit.value),
    },
  };
}

function resetBanner() {
  state.banner = null;
}

function setBanner(kind, title, text) {
  state.banner = { kind, title, text };
  renderSourceBanner();
}

async function requestSearch(payload, signal) {
  const response = await fetch("/api/search", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
    signal,
  });

  let responsePayload = null;
  try {
    responsePayload = await response.json();
  } catch (error) {
    responsePayload = null;
  }

  if (!response.ok) {
    const detail =
      responsePayload?.detail ||
      responsePayload?.error ||
      `search failed: ${response.status}`;
    const requestError = new Error(detail);
    requestError.status = response.status;
    throw requestError;
  }

  state.mode = "service";
  return responsePayload;
}

function describeSearchFailure(error) {
  if (error?.name === "AbortError") {
    if (state.searchAbortReason === "manual") {
      return "已停止本次搜索。";
    }
    return "本次搜索已取消。";
  }
  const message = String(error?.message || "").trim();
  if (!message) {
    return "请求失败，请检查本地服务或实时地图配置。";
  }
  if (message.includes("Failed to fetch")) {
    return "未连接到本地后端。请确认 http://127.0.0.1:8000 已启动，再刷新页面重试。";
  }
  if (message.includes("search failed:")) {
    return "搜索接口返回异常，请查看启动服务的终端日志。";
  }
  return message;
}

async function requestSuggestions(query) {
  try {
    const response = await fetch("/api/suggest", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ query }),
    });
    if (!response.ok) {
      throw new Error(`suggest failed: ${response.status}`);
    }
    return await response.json();
  } catch (error) {
    return { provider: "amap", suggestions: [], warning: "" };
  }
}

async function requestEvent(payload) {
  try {
    await fetch("/api/event", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
  } catch (error) {
    return null;
  }
  return true;
}

async function requestFeedback(payload) {
  const response = await fetch("/api/feedback", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!response.ok) {
    throw new Error(`feedback failed: ${response.status}`);
  }
  return await response.json();
}

async function postJson(path, payload) {
  const response = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(body.error || `${path} failed: ${response.status}`);
  return body;
}

function linkedContext() {
  return {
    request_id: state.meta?.request_id || state.lastPayload?.request_id,
    anonymous_session_id: ANONYMOUS_SESSION_ID,
    environment: state.meta?.environment || state.lastPayload?.environment || "dev",
    app_version: APP_VERSION,
    rule_version: RULE_VERSION,
  };
}

function buildEmptyMessage() {
  if (state.banner?.text) {
    return state.banner.text;
  }
  if (state.meta?.live_failed) {
    return state.meta.warnings[0] ?? "当前没有拿到真实地图结果。";
  }
  if (state.lastPayload && state.meta?.data_source === "live") {
    return "当前没有命中合规方案。可以换个时间段复测，或在地图 App 里复核门口 / 楼栋与地铁站组合。";
  }
  if (state.meta?.data_source === "mock") {
    return "当前是演示数据，可正常预览页面，但不能作为真实通勤依据。";
  }
  return "输入公司地点和租房小区后，点击搜索查看合规通勤方案。";
}

function renderSourceBanner() {
  if (!elements.sourceBanner) {
    return;
  }

  if (state.isSearching) {
    elements.sourceBanner.className = "source-banner";
    elements.sourceBanner.innerHTML = `
      <strong>正在请求高德实时路线</strong>
      <span>${state.banner?.text || "正在按“直骑优先，超时再综合公交规划”的顺序计算，请稍候；如果计算较慢，结果回来后仍会继续展示。"}</span>
    `;
    return;
  }

  if (state.banner) {
    elements.sourceBanner.className = `source-banner ${state.banner.kind}`;
    elements.sourceBanner.innerHTML = `
      <strong>${state.banner.title}</strong>
      <span>${state.banner.text}</span>
    `;
    return;
  }

  if (!state.meta) {
    elements.sourceBanner.className = "source-banner hidden";
    elements.sourceBanner.innerHTML = "";
    return;
  }

  const warningText = (state.meta.warnings ?? []).join(" ");
  const statusText = formatDataSourceLabel(state.meta);
  const bannerClass = [
    "source-banner",
    state.meta.data_source === "mock" ? "demo" : "",
    state.meta.live_failed ? "warning" : "",
  ]
    .filter(Boolean)
    .join(" ");

  elements.sourceBanner.className = bannerClass;
  elements.sourceBanner.innerHTML = `
    <strong>当前来源：${statusText}</strong>
    <span>${warningText || "已按当前输入完成高德主算路搜索。"}</span>
  `;
}

function compliancePill(evaluation) {
  if (evaluation.is_compliant) {
    return `<span class="pill">合规 · 余量 ${evaluation.margin_min} 分钟</span>`;
  }
  return `<span class="pill bad">超时 ${evaluation.over_limit_min} 分钟</span>`;
}

function renderSummary() {
  const best = state.results[0];
  if (!best) {
    elements.summaryCard.className = "summary-card empty";
    elements.summaryCard.innerHTML = buildEmptyMessage();
    return;
  }

  const plan = describePlan(best);
  const strategyNote = describeStrategyNote(best);
  const timing = describeTimingRecommendation(best, best.evaluation?.limit_min);
  const accuracyNote = describeMixedRouteAccuracyNote(best);
  const nearMissHint = describeNearMissHint(best);
  const complianceStatus = describeComplianceStatus(best);
  const recommendation = describeRecommendation(best);
  const candidateRows = buildCandidateComparison(best);
  const exclusions = describeRuleExclusions(state.meta);
  elements.summaryCard.className = `summary-card ${best.evaluation.is_compliant ? "compliant" : "overtime"}`;
  elements.summaryCard.innerHTML = `
    <div class="summary-grid">
      <div class="summary-lead">
        <p>${best.evaluation.is_compliant ? "最优合规方案" : "当前最短方案"}</p>
        <h3 class="summary-headline">${buildResultHeadline(best)}</h3>
        <p class="summary-title">${plan.title}</p>
      </div>
      <div>
        <p>路线方式</p>
        <strong>${formatTemplateLabel(best.template)}</strong>
      </div>
      <div>
        <p>状态</p>
        <strong class="${complianceStatus.className}">${complianceStatus.label}</strong>
      </div>
      <div>
        <p>中转信息</p>
        <strong>${plan.transferLine}</strong>
      </div>
      ${strategyNote ? `<div class="summary-strategy-note">${strategyNote}</div>` : ""}
      <div class="summary-strategy-note"><strong>推荐理由：</strong>${recommendation}</div>
      <div class="candidate-compare">
        <strong>候选点对比</strong>
        ${candidateRows.map((row) => `<span>${row.candidate}：${row.duration} 分钟${row.recommended ? " · 当前采用" : ""}</span>`).join("")}
      </div>
      ${exclusions.length ? `<div class="rule-exclusions"><strong>规则排除</strong>${exclusions.map((item) => `<span>${item.template} ${item.duration ?? "-"} 分钟：${item.reason}</span>`).join("")}</div>` : ""}
      <div class="summary-segments">
        ${plan.segmentLines
          .map((line) => `<p class="summary-segment-line">${line}</p>`)
          .join("")}
      </div>
      ${
        timing
          ? `
            <div class="timing-banner">
              <strong>${timing.headline}</strong>
              <p>${timing.summary}</p>
            </div>
          `
          : ""
      }
      ${nearMissHint ? `<div class="near-miss-note">${nearMissHint}</div>` : ""}
      ${accuracyNote ? `<div class="accuracy-note">${accuracyNote}</div>` : ""}
    </div>
  `;
}

function renderResultList() {
  const alternativeResults = buildAlternativeResults(state.results);
  if (!alternativeResults.length) {
    elements.resultList.className = "result-list empty";
    elements.resultList.innerHTML = state.results.length ? "当前没有其他备选方案。" : buildEmptyMessage();
    return;
  }

  elements.resultList.className = "result-list";
  elements.resultList.innerHTML = alternativeResults
    .map((result, index) => {
      const originalIndex = index + 1;
      const activeClass = originalIndex === state.selectedIndex ? "active" : "";
      const plan = describePlan(result);
      const cardClass = result.evaluation.is_compliant ? "compliant" : "overtime";
      const nearMissHint = describeNearMissHint(result);
      return `
        <article class="plan-card ${activeClass} ${cardClass}" data-index="${originalIndex}">
          <div class="plan-head">
            <div>
              <div class="plan-provider">${formatProviderLabel(result.provider)}</div>
              <div class="plan-template">${formatTemplateLabel(result.template)}</div>
            </div>
            ${compliancePill(result.evaluation)}
          </div>
          <p class="plan-headline">${buildResultHeadline(result)}</p>
          <div class="plan-metrics">
            <span>总时长 ${result.total_duration_min} 分钟</span>
            <span>阈值 ${result.evaluation.limit_min} 分钟</span>
          </div>
          <p class="plan-route">${plan.primaryLine}</p>
          <p class="plan-transfer">${plan.transferLine}</p>
          ${nearMissHint ? `<p class="plan-near-miss">${nearMissHint}</p>` : ""}
          <div class="segment-ribbon">
            ${result.segments
              .map(
                (segment) =>
                  `<span class="segment-chip ${segment.mode}">${formatModeLabel(segment.mode)} ${segment.duration_min}分钟</span>`
              )
              .join("")}
          </div>
        </article>
      `;
    })
    .join("");

  elements.resultList.querySelectorAll(".plan-card").forEach((card) => {
    card.addEventListener("click", () => {
      state.selectedIndex = Number(card.dataset.index);
      renderResultList();
      renderDetail();
    });
  });
}

function renderDetail() {
  const active = state.results[state.selectedIndex];
  if (!active) {
    elements.detailView.className = "detail-view empty";
    elements.detailView.innerHTML = state.meta?.live_failed
      ? "当前没有真实方案可展示。请调整地点关键词，或先从候选下拉中选择更准确的 POI。"
      : "选中一条结果后，这里会展示分段细节。";
    return;
  }

  const plan = describePlan(active);
  const strategyNote = describeStrategyNote(active);
  const checklist = buildScreenshotChecklist(active);
  const timing = describeTimingRecommendation(active, active.evaluation?.limit_min);
  const accuracyNote = describeMixedRouteAccuracyNote(active);
  const nearMissHint = describeNearMissHint(active);
  const diagnostics = describeDiagnostics(active);
  const complianceStatus = describeComplianceStatus(active);
  elements.detailView.className = "detail-view";
  elements.detailView.innerHTML = `
    <section class="detail-hero">
      <div class="detail-head">
        <span class="plan-provider">${formatProviderLabel(active.provider)}</span>
        <h3>${buildResultHeadline(active)}</h3>
        <p class="detail-template">${plan.title}</p>
        ${compliancePill(active.evaluation)}
        <p class="compliance-copy">${complianceStatus.copy}</p>
      </div>
      <div class="detail-metrics">
        <span>总时长 ${active.total_duration_min} 分钟</span>
        <span>${plan.primaryLine}</span>
        <span>${plan.transferLine}</span>
      </div>
      ${strategyNote ? `<p class="detail-strategy-note">${strategyNote}</p>` : ""}
      ${nearMissHint ? `<p class="detail-strategy-note near-miss-inline">${nearMissHint}</p>` : ""}
    </section>
    ${
      diagnostics.length
        ? `
          <section class="hint-box diagnostic-box">
            <strong>诊断信息：</strong>
            <div>${diagnostics.map((item) => `<p>${item}</p>`).join("")}</div>
          </section>
        `
        : ""
    }
    ${
      timing
        ? `
          <section class="timing-panel">
            <div class="panel-heading compact">
              <h3>推荐测距时段</h3>
              <p>${timing.summary}</p>
            </div>
            <div class="timing-highlight">${timing.headline}</div>
            <div class="timing-grid">
              ${timing.rows
                .map(
                  (row) => `
                    <article class="timing-card ${row.isCompliant === false ? "late" : ""}">
                      <strong>${row.label}</strong>
                      <p>总时长 ${row.totalDurationMin} 分钟</p>
                      <p>${row.note || `地铁段 ${row.transitDurationMin} 分钟`}</p>
                      <p>${row.isCompliant === null ? "未校验房补阈值" : row.isCompliant ? "该时段进入规则范围，仍需地图复核" : "该时段超出房补范围"}</p>
                    </article>
                  `
                )
                .join("")}
            </div>
          </section>
        `
        : ""
    }
    ${accuracyNote ? `<aside class="accuracy-note detail">${accuracyNote}</aside>` : ""}
    <section class="detail-steps">
      ${active.segments
        .map(
          (segment) => `
            <article class="detail-step">
              <div class="step-mode segment-chip ${segment.mode}">${formatModeLabel(segment.mode)}</div>
              <div class="step-copy">
                <strong>${segment.from_name} → ${segment.to_name}</strong>
                <p>${formatSegmentDetail(segment, active.provider)}</p>
              </div>
            </article>
          `
        )
        .join("")}
    </section>
    <section class="checklist-panel">
      <div class="panel-heading compact">
        <h3>截图清单</h3>
        <p>按下面顺序逐段截图，最后把总时长相加即可。</p>
      </div>
      <div class="checklist-steps">
        ${checklist.steps
          .map(
            (step) => `
              <article class="checklist-step">
                <div class="checklist-index">${step.index}</div>
                <div class="checklist-copy">
                  <strong>${step.title} · ${step.mapApp} · ${step.mode}</strong>
                  <p>起点：${step.fromName}</p>
                  <p>终点：${step.toName}</p>
                  <p>该段时长：${step.durationLine}</p>
                  <p>${step.note}</p>
                </div>
              </article>
            `
          )
          .join("")}
      </div>
      <div class="checklist-summary">
        <strong>汇总说明</strong>
        <p>${checklist.submissionNote}</p>
      </div>
    </section>
    <aside class="hint-box">
      <strong>截图建议：</strong>${active.screenshot_hint}
    </aside>
  `;
}

function resetFeedbackState() {
  state.feedback.helpful = null;
  state.feedback.submitted = false;
  state.feedback.loading = false;
  state.feedback.error = "";
  if (elements.feedbackNote) {
    elements.feedbackNote.value = "";
  }
  state.review = { submitted: false, loading: false, error: "" };
  if (elements.reviewOutcomes) {
    elements.reviewOutcomes.querySelectorAll("input[type=checkbox]").forEach((input) => { input.checked = false; });
  }
  if (elements.reviewMinutes) elements.reviewMinutes.value = "";
  if (elements.reviewNote) elements.reviewNote.value = "";
}

function renderFeedbackPanel() {
  if (!elements.feedbackPanel) {
    return;
  }
  const hasResults = state.results.length > 0;
  elements.feedbackPanel.classList.toggle("disabled", !hasResults);
  elements.feedbackHelpful.classList.toggle("active", state.feedback.helpful === true);
  elements.feedbackUnhelpful.classList.toggle("active", state.feedback.helpful === false);
  elements.feedbackExtra.classList.toggle("hidden", state.feedback.helpful !== false);
  elements.feedbackSubmit.disabled = !hasResults || state.feedback.helpful === null || state.feedback.loading;

  if (!hasResults) {
    elements.feedbackStatus.textContent = "搜索完成后可以直接反馈，帮助后续优化。";
    return;
  }
  if (state.feedback.loading) {
    elements.feedbackStatus.textContent = "正在提交反馈...";
    return;
  }
  if (state.feedback.submitted) {
    elements.feedbackStatus.textContent = "反馈已记录，后续会结合搜索成功率和失败原因一起优化。";
    return;
  }
  if (state.feedback.error) {
    elements.feedbackStatus.textContent = state.feedback.error;
    return;
  }
  elements.feedbackStatus.textContent =
    state.feedback.helpful === false ? "可以补充一句还差什么，帮助定位门口、楼栋或站点问题。" : "选择后即可提交反馈。";
}

function renderReviewPanel() {
  if (!elements.reviewPanel) return;
  const hasSearch = Boolean(state.meta?.request_id);
  elements.reviewPanel.classList.toggle("disabled", !hasSearch);
  if (elements.reviewSubmit) elements.reviewSubmit.disabled = !hasSearch || state.review.loading;
  if (!elements.reviewStatus) return;
  if (!hasSearch) elements.reviewStatus.textContent = "完成一次搜索后即可记录地图 App 复核。";
  else if (state.review.loading) elements.reviewStatus.textContent = "正在保存复核记录...";
  else if (state.review.submitted) elements.reviewStatus.textContent = `已关联请求 ${state.meta.request_id.slice(0, 8)}…`;
  else if (state.review.error) elements.reviewStatus.textContent = state.review.error;
  else elements.reviewStatus.textContent = "可多选结论；备注不要填写完整地址。";
}

function fillExperimentDefaults() {
  if (!elements.experimentForm || !state.meta) return;
  const best = state.results[0];
  const setValue = (name, value) => {
    const input = elements.experimentForm.elements.namedItem(name);
    if (input && value != null) input.value = value;
  };
  setValue("request_id", state.meta.request_id || "");
  setValue("environment", state.meta.environment || state.lastPayload?.environment || "dev");
  setValue("data_source", state.meta.data_source || "");
  setValue("rule_version", RULE_VERSION);
  setValue("tool_search_seconds", state.meta.latency_ms != null ? (Number(state.meta.latency_ms) / 1000).toFixed(2) : "");
  setValue("tool_best_minutes", best?.total_duration_min ?? "");
  const success = elements.experimentForm.elements.namedItem("tool_search_success");
  const compliant = elements.experimentForm.elements.namedItem("found_compliant_plan");
  if (success) success.checked = state.meta.data_source === "live" && Boolean(state.meta.route_found);
  if (compliant) compliant.checked = Boolean(state.meta.compliant_route_found);
}

function renderSearchButton() {
  if (!elements.searchSubmit || !elements.searchCancel) {
    return;
  }
  elements.searchSubmit.disabled = state.isSearching;
  elements.searchSubmit.textContent = state.isSearching ? "正在搜索..." : "开始搜索最优通勤组合";
  elements.searchCancel.disabled = !state.isSearching;
  elements.searchCancel.textContent = state.isSearching ? "停止搜索" : "停止搜索";
}

function cancelActiveSearch(reason) {
  state.searchAbortReason = reason;
  if (state.activeSearchController) {
    state.activeSearchController.abort();
    state.activeSearchController = null;
  }
}

function closeSuggestions(field) {
  state.suggestions[field] = [];
  const container = getSuggestionElement(field);
  if (container) {
    container.classList.remove("visible");
    container.innerHTML = "";
  }
}

function renderSuggestions(field) {
  const container = getSuggestionElement(field);
  const suggestions = state.suggestions[field];
  if (!container) {
    return;
  }
  if (!suggestions.length) {
    closeSuggestions(field);
    return;
  }

  container.className = "suggestion-list visible";
  container.innerHTML = suggestions
    .map(
      (item, index) => `
        <button type="button" class="suggestion-item" data-field="${field}" data-index="${index}">
          <strong>${item.name}</strong>
          <span>${[item.district, item.address].filter(Boolean).join(" ") || "高德候选地点"}</span>
        </button>
      `
    )
    .join("");

  container.querySelectorAll(".suggestion-item").forEach((item) => {
    item.addEventListener("click", () => {
      const picked = suggestions[Number(item.dataset.index)];
      state.selectedPlaces[field] = picked;
      getInputElement(field).value = picked.name;
      closeSuggestions(field);
    });
  });
}

async function loadSuggestions(field, query) {
  const response = await requestSuggestions(query);
  state.suggestions[field] = response.suggestions ?? [];
  renderSuggestions(field);
}

function scheduleSuggestions(field) {
  const input = getInputElement(field);
  const query = input.value.trim();

  if (state.selectedPlaces[field] && state.selectedPlaces[field].name !== query) {
    state.selectedPlaces[field] = null;
  }

  if (!query || query.length < 2) {
    closeSuggestions(field);
    return;
  }

  const previousTimer = suggestionTimers.get(field);
  if (previousTimer) {
    clearTimeout(previousTimer);
  }

  suggestionTimers.set(
    field,
    setTimeout(() => {
      loadSuggestions(field, query);
    }, 220)
  );
}

async function runSearch(payload) {
  state.lastPayload = payload;
  resetBanner();
  resetFeedbackState();
  state.searchAbortReason = "";
  state.isSearching = true;
  state.activeSearchController = new AbortController();
  state.slowSearchTimer = scheduleSearchProgress({
    onSlow() {
      setBanner("warning", "路线计算较慢", "正在按“直骑 → 综合公交 → 骑行接驳地铁”的顺序搜索。你可以继续等待，结果回来后仍会显示，也可以直接停止本次搜索。");
    },
  });
  renderSourceBanner();
  renderSearchButton();
  try {
    const response = await requestSearch(payload, state.activeSearchController.signal);
    state.results = buildVisibleResults(response.results ?? []);
    state.selectedIndex = 0;
    state.meta = response.meta ?? null;
    fillExperimentDefaults();
    renderSourceBanner();
    renderSummary();
    renderResultList();
    renderDetail();
    renderFeedbackPanel();
    renderReviewPanel();
    if (state.results[0]) {
      requestEvent({
        ...linkedContext(),
        event_type: "result_shown",
        provider: state.results[0].provider,
        template: state.results[0].template,
        total_duration_min: state.results[0].total_duration_min,
        is_compliant: Boolean(state.results[0].evaluation?.is_compliant),
        evaluation: state.results[0].evaluation,
        alias_used: Boolean(state.results[0].used_alias_fallback),
        result_type: state.meta?.result_type,
        data_source: state.meta?.data_source,
      });
    }
  } catch (error) {
    state.results = [];
    state.selectedIndex = 0;
    state.meta = null;
    setBanner("warning", "搜索失败", describeSearchFailure(error));
    renderSummary();
    renderResultList();
    renderDetail();
    renderFeedbackPanel();
    renderReviewPanel();
  } finally {
    state.isSearching = false;
    state.activeSearchController = null;
    if (state.slowSearchTimer) {
      state.slowSearchTimer.cancel();
      state.slowSearchTimer = null;
    }
    renderSearchButton();
    renderSourceBanner();
  }
}

function validatePayload(payload) {
  if (!payload.office || !payload.home) {
    setBanner("warning", "请先完善输入", "公司地点和租房小区都不能为空。");
    state.results = [];
    renderSummary();
    renderResultList();
    renderDetail();
    return false;
  }
  return true;
}

["office", "home"].forEach((field) => {
  const input = getInputElement(field);
  input.addEventListener("input", () => {
    resetBanner();
    renderSourceBanner();
    scheduleSuggestions(field);
  });
  input.addEventListener("focus", () => {
    if (state.suggestions[field].length) {
      renderSuggestions(field);
    }
  });
  input.addEventListener("blur", () => {
    setTimeout(() => closeSuggestions(field), 120);
  });
});

document.addEventListener("click", (event) => {
  if (!event.target.closest(".search-field")) {
    closeSuggestions("office");
    closeSuggestions("home");
  }
});

elements.form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const payload = collectPayload();
  if (!validatePayload(payload)) {
    return;
  }
  await runSearch(payload);
});

elements.searchCancel?.addEventListener("click", () => {
  if (!state.isSearching) {
    return;
  }
  cancelActiveSearch("manual");
});

elements.feedbackHelpful?.addEventListener("click", () => {
  state.feedback.helpful = true;
  state.feedback.submitted = false;
  state.feedback.error = "";
  renderFeedbackPanel();
});

elements.feedbackUnhelpful?.addEventListener("click", () => {
  state.feedback.helpful = false;
  state.feedback.submitted = false;
  state.feedback.error = "";
  renderFeedbackPanel();
});

elements.feedbackSubmit?.addEventListener("click", async () => {
  if (!state.results.length || state.feedback.helpful === null || state.feedback.loading) {
    return;
  }
  state.feedback.loading = true;
  state.feedback.error = "";
  renderFeedbackPanel();
  try {
    await requestFeedback({
      ...linkedContext(),
      helpful: state.feedback.helpful,
      note: elements.feedbackNote?.value.trim() || "",
    });
    state.feedback.submitted = true;
  } catch (error) {
    state.feedback.error = "反馈提交失败，请稍后重试。";
  } finally {
    state.feedback.loading = false;
    renderFeedbackPanel();
  }
});

elements.reviewSubmit?.addEventListener("click", async () => {
  const outcomes = Array.from(elements.reviewOutcomes?.querySelectorAll("input[type=checkbox]:checked") || []).map((input) => input.value);
  if (!outcomes.length) {
    state.review.error = "请至少选择一项复核结论。";
    renderReviewPanel();
    return;
  }
  state.review.loading = true;
  state.review.error = "";
  renderReviewPanel();
  try {
    await postJson("/api/review", {
      ...linkedContext(), outcomes,
      actual_minutes: elements.reviewMinutes?.value || null,
      issue_category: elements.reviewIssue?.value || "none",
      note: elements.reviewNote?.value.trim() || "",
    });
    state.review.submitted = true;
  } catch (error) {
    state.review.error = "复核记录保存失败，请稍后重试。";
  } finally {
    state.review.loading = false;
    renderReviewPanel();
  }
});

elements.experimentForm?.addEventListener("submit", async (event) => {
  event.preventDefault();
  state.experiment.loading = true;
  if (elements.experimentStatus) elements.experimentStatus.textContent = "正在保存脱敏实验记录...";
  const form = new FormData(elements.experimentForm);
  const payload = Object.fromEntries(form.entries());
  ["manual_search_seconds", "manual_attempt_count", "manual_best_minutes", "tool_search_seconds", "tool_best_minutes"].forEach((name) => {
    payload[name] = payload[name] === "" ? null : Number(payload[name]);
  });
  ["tool_search_success", "found_compliant_plan", "matches_manual", "top1_valid", "alias_improved", "false_compliance"].forEach((name) => {
    payload[name] = form.has(name);
  });
  try {
    const response = await postJson("/api/experiment", payload);
    state.experiment.submitted = true;
    if (elements.experimentStatus) elements.experimentStatus.textContent = `${response.case_id} 已保存；当前独立案例 ${response.summary.case_count} 个。`;
  } catch (error) {
    state.experiment.error = String(error.message || error);
    if (elements.experimentStatus) elements.experimentStatus.textContent = `保存失败：${state.experiment.error}`;
  } finally {
    state.experiment.loading = false;
  }
});

renderSourceBanner();
renderSummary();
renderResultList();
renderDetail();
renderFeedbackPanel();
renderReviewPanel();
renderSearchButton();
