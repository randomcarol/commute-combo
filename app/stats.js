export function formatPercent(numerator, denominator) {
  return denominator ? `${((Number(numerator || 0) / Number(denominator)) * 100).toFixed(1)}%` : "0.0%";
}

const providerLabels = { amap: "高德", baidu: "百度", qq: "腾讯" };
const feedbackThemeLabels = {
  station_accuracy: "地铁站 / 接驳", speed_or_latency: "速度 / 超时", alias_coverage: "门口 / 楼栋别名",
  empty_or_compliance: "无结果 / 合规", explanation_or_screenshot: "解释 / 截图", other: "其他",
};

export function buildStatCards(summary) {
  const total = Number(summary?.total_searches || 0);
  const routeFound = Number(summary?.successful_searches || 0);
  const compliant = Number(summary?.compliant_searches || 0);
  const completed = Number(summary?.effective_measurement_completed || 0);
  const falseCompliance = Number(summary?.false_compliance_count || 0);
  return [
    { title: "有效测距完成率", value: formatPercent(completed, total), note: `${completed}/${total} 次：系统合规 + 地图一致 + 截图可用` },
    { title: "系统找到路线", value: String(routeFound), note: `路线返回率 ${formatPercent(routeFound, total)}，不等同于房补成功` },
    { title: "规则合规搜索", value: String(compliant), note: `系统合规率 ${formatPercent(compliant, total)}，仍需地图复核` },
    { title: "错误合规", value: String(falseCompliance), note: `护栏指标 ${formatPercent(falseCompliance, compliant)}` },
    { title: "P50 搜索延迟", value: summary?.latency_p50_ms == null ? "-" : `${summary.latency_p50_ms} ms`, note: `P95 ${summary?.latency_p95_ms ?? "-"} ms` },
    { title: "地图请求次数", value: String(summary?.provider_request_count_total || 0), note: `当前筛选环境累计；搜索数 ${total}` },
  ];
}

export function buildExperimentCards(summary) {
  const item = summary?.experiment_summary || {};
  const difference = item.average_abs_best_difference_min == null ? "-" : `${item.average_abs_best_difference_min} 分钟`;
  const median = item.median_abs_best_difference_min == null ? "-" : `${item.median_abs_best_difference_min} 分钟`;
  const timeChange = item.average_task_time_change_seconds == null ? "-" : `${item.average_task_time_change_seconds} 秒`;
  return [
    { title: "独立案例", value: String(item.case_count || 0), note: item.sample_note || "样本量较小，仅用于探索性验证" },
    { title: "实时搜索成功率", value: formatPercent(Number(item.live_search_success_rate || 0) * 100, 100), note: "仅来自匿名 CASE 自测记录" },
    { title: "与人工一致率", value: formatPercent(Number(item.manual_match_rate || 0) * 100, 100), note: "同一批地址配对比较" },
    { title: "Top-1 有效命中率", value: formatPercent(Number(item.top1_valid_rate || 0) * 100, 100), note: "Top-1 经地图复核可用" },
    { title: "最优结果分钟差", value: difference, note: `绝对差中位数 ${median}` },
    { title: "单次任务耗时变化", value: timeChange, note: "正数表示工具相对人工节省时间" },
    { title: "别名策略有效案例", value: String(item.alias_effective_case_count || 0), note: "门口 / 楼栋 / 出入口带来改善" },
    { title: "错误合规案例", value: String(item.false_compliance_case_count || 0), note: "实验护栏，必须逐例复盘" },
  ];
}

export function buildProviderRows(summary) {
  return Object.entries(summary?.provider_breakdown || {}).sort((a, b) => Number(b[1]) - Number(a[1]) || a[0].localeCompare(b[0])).map(([provider, count]) => ({
    provider, label: providerLabels[provider] ?? provider, count: Number(count || 0), share: formatPercent(count, Number(summary?.total_searches || 0)),
  }));
}

export function buildRouteRows(summary) {
  return Object.entries(summary?.route_type_distribution || {}).sort((a, b) => a[0].localeCompare(b[0])).map(([template, item]) => ({
    template, matchedCount: Number(item?.matched_count || 0), shownCount: Number(item?.shown_count || 0),
    matchRate: formatPercent(item?.matched_count || 0, item?.shown_count || 0),
    averageDuration: item?.average_duration_min == null ? "-" : `${item.average_duration_min} 分钟`,
  }));
}

export function buildFeedbackThemeRows(summary) {
  return Object.entries(summary?.feedback_theme_breakdown || {}).sort((a, b) => Number(b[1]) - Number(a[1]) || a[0].localeCompare(b[0])).map(([theme, count]) => ({
    theme, label: feedbackThemeLabels[theme] ?? theme, count: Number(count || 0),
  }));
}

export function buildRecommendationCards(summary) {
  const cards = [];
  const feedback = summary?.feedback_theme_breakdown || {};
  if (Number(summary?.false_compliance_count || 0) > 0) cards.push({ title: "先复盘错误合规", note: `${summary.false_compliance_count} 次系统合规在地图复核后失效。`, detail: "逐例核对模板、站点、出入口和阈值。" });
  if (Number(feedback.station_accuracy || 0) > 0) cards.push({ title: "修正地铁站与出入口", note: `${feedback.station_accuracy} 条反馈涉及站点或接驳。`, detail: "优先核对高频错误类型，不扩成综合地图。" });
  if (Number(summary?.result_without_compliant_searches || 0) > 0) cards.push({ title: "分析有路线但不合规", note: `${summary.result_without_compliant_searches} 次已有路线、却没有通过规则。`, detail: "区分真实超时与候选覆盖不足。" });
  if (Number(summary?.warning_searches || 0) > 0) cards.push({ title: "压低实时请求异常", note: `${summary.warning_searches} 次搜索出现 provider 警告。`, detail: "结合请求数和 P95 延迟定位。" });
  if (Number(summary?.alias_uplift?.count || 0) > 0) cards.push({ title: "继续验证别名策略", note: `别名上位 ${summary.alias_uplift.count} 次，平均节省 ${summary.alias_uplift.average_saved_min} 分钟。`, detail: "先用 20 个配对样本验证可重复性。" });
  return cards.slice(0, 4).map((card, index) => ({ ...card, rank: index + 1 }));
}

export function buildRecentRows(summary) {
  return (summary?.recent_searches || []).map((item) => ({
    requestId: item.request_id ? `${item.request_id.slice(0, 8)}…` : "-", environment: item.environment || "legacy",
    template: item.template || "-", duration: item.total_duration_min == null ? "-" : `${item.total_duration_min} 分钟`,
    compliance: item.is_compliant ? "系统合规·待复核" : item.result_type === "no_route" ? "未找到路线" : "有路线但不合规",
  }));
}

async function requestStats(environment) {
  const response = await fetch(`/api/stats?environment=${encodeURIComponent(environment)}`);
  if (!response.ok) throw new Error(`stats failed: ${response.status}`);
  return await response.json();
}

function pageElements() {
  if (typeof document === "undefined") return {};
  return {
    banner: document.querySelector("#stats-banner"), cards: document.querySelector("#stats-cards"),
    experimentCards: document.querySelector("#experiment-cards"), environment: document.querySelector("#stats-environment"),
    routeBody: document.querySelector("#route-distribution-body"), providerBody: document.querySelector("#provider-breakdown-body"),
    feedbackBody: document.querySelector("#feedback-theme-body"), recommendations: document.querySelector("#recommendation-list"),
    recentBody: document.querySelector("#recent-searches-body"),
  };
}

function renderCards(container, cards) {
  if (!container) return;
  container.innerHTML = cards.map((card) => `<article class="metric-card"><p>${card.title}</p><strong>${card.value}</strong><span>${card.note}</span></article>`).join("");
}

function renderTable(container, rows, cells, empty, colspan) {
  if (!container) return;
  container.innerHTML = rows.length ? rows.map((row) => `<tr>${cells.map((cell) => `<td>${row[cell]}</td>`).join("")}</tr>`).join("") : `<tr><td colspan="${colspan}">${empty}</td></tr>`;
}

function renderPage(elements, state) {
  if (!elements.banner) return;
  if (state.loading) elements.banner.innerHTML = "<strong>正在加载</strong><span>读取脱敏后的实验数据。</span>";
  else if (state.error) { elements.banner.className = "source-banner warning"; elements.banner.innerHTML = `<strong>读取失败</strong><span>${state.error}</span>`; }
  else { elements.banner.className = "source-banner"; elements.banner.innerHTML = `<strong>环境已隔离</strong><span>当前仅统计：${(state.summary.selected_environments || []).join("、") || "全部环境"}。默认不包含 demo、test、dev。</span>`; }
  renderCards(elements.cards, buildStatCards(state.summary));
  renderCards(elements.experimentCards, buildExperimentCards(state.summary));
  renderTable(elements.routeBody, buildRouteRows(state.summary), ["template", "matchedCount", "matchRate", "averageDuration"], "当前还没有路线模板统计。", 4);
  renderTable(elements.providerBody, buildProviderRows(state.summary), ["label", "count", "share"], "当前还没有地图源统计。", 3);
  renderTable(elements.feedbackBody, buildFeedbackThemeRows(state.summary), ["label", "count"], "当前还没有反馈主题。", 2);
  renderTable(elements.recentBody, buildRecentRows(state.summary), ["requestId", "environment", "template", "duration", "compliance"], "当前筛选环境还没有搜索摘要。", 5);
  if (elements.recommendations) {
    const cards = buildRecommendationCards(state.summary);
    elements.recommendations.innerHTML = cards.length ? cards.map((card) => `<article class="insight-card"><div class="insight-head"><span class="insight-rank">#${card.rank}</span><h3>${card.title}</h3></div><p>${card.note}</p><span>${card.detail}</span></article>`).join("") : `<p class="metric-empty">当前还没有足够证据生成迭代建议。</p>`;
  }
}

async function main() {
  const elements = pageElements();
  if (!elements.banner) return;
  const state = { loading: true, error: "", summary: {} };
  const load = async () => {
    state.loading = true; state.error = ""; renderPage(elements, state);
    try { state.summary = await requestStats(elements.environment?.value || "self_test,prod"); }
    catch (error) { state.error = "暂时无法读取数据看板，请确认服务已启动。"; }
    finally { state.loading = false; renderPage(elements, state); }
  };
  elements.environment?.addEventListener("change", load);
  await load();
}

main();
