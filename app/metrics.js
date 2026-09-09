const state = {
  token: "",
  summary: null,
  error: "",
  loading: false,
};

export function formatPercent(numerator, denominator) {
  if (!denominator) {
    return "0.0%";
  }
  return `${((Number(numerator || 0) / Number(denominator || 0)) * 100).toFixed(1)}%`;
}

// 中文注释：把聚合指标整理成固定卡片，避免模板渲染层直接耦合原始接口字段。
export function buildMetricCards(summary) {
  const total = Number(summary?.total_searches || 0);
  const success = Number(summary?.successful_searches || 0);
  const empty = Number(summary?.empty_searches || 0);
  const compliant = Number(summary?.compliant_searches || 0);
  const alias = Number(summary?.alias_searches || 0);
  const liveFailed = Number(summary?.live_failed_searches || 0);

  return [
    { title: "总搜索次数", value: String(total), note: "用于观察整体试用量。" },
    { title: "有结果搜索", value: String(success), note: `结果命中率 ${formatPercent(success, total)}` },
    { title: "空结果搜索", value: String(empty), note: `空结果率 ${formatPercent(empty, total)}` },
    { title: "合规命中", value: String(compliant), note: `合规命中率 ${formatPercent(compliant, total)}` },
    { title: "别名命中", value: String(alias), note: `别名参与率 ${formatPercent(alias, total)}` },
    { title: "Live 失败", value: String(liveFailed), note: `Live 失败率 ${formatPercent(liveFailed, total)}` },
  ];
}

export function buildTemplateRows(summary) {
  return Object.entries(summary?.template_breakdown || {})
    .sort((left, right) => right[1] - left[1] || left[0].localeCompare(right[0]))
    .map(([template, count]) => ({
      template,
      count: Number(count || 0),
    }));
}

async function requestMetrics(token) {
  const response = await fetch(`/api/metrics?token=${encodeURIComponent(token)}`);
  if (!response.ok) {
    throw new Error(`metrics failed: ${response.status}`);
  }
  return await response.json();
}

function metricElements() {
  // 中文注释：测试环境没有 document，这里直接返回空元素，避免导入模块时崩溃。
  if (typeof document === "undefined") {
    return {
      form: null,
      tokenInput: null,
      banner: null,
      cards: null,
      templates: null,
    };
  }
  return {
    form: document.querySelector("#metrics-form"),
    tokenInput: document.querySelector("#metrics-token"),
    banner: document.querySelector("#metrics-banner"),
    cards: document.querySelector("#metrics-cards"),
    templates: document.querySelector("#template-breakdown"),
  };
}

function renderBanner(elements) {
  if (!elements.banner) {
    return;
  }
  if (state.error) {
    elements.banner.className = "source-banner warning";
    elements.banner.innerHTML = `<strong>读取失败</strong><span>${state.error}</span>`;
    return;
  }
  if (state.loading) {
    elements.banner.className = "source-banner";
    elements.banner.innerHTML = "<strong>正在加载</strong><span>正在读取脱敏后的搜索统计。</span>";
    return;
  }
  if (!state.summary) {
    elements.banner.className = "source-banner";
    elements.banner.innerHTML =
      "<strong>内部看板</strong><span>输入 metrics token 后查看搜索成功率、空结果率、合规命中率和模板分布。</span>";
    return;
  }
  elements.banner.className = "source-banner";
  elements.banner.innerHTML =
    "<strong>脱敏统计</strong><span>当前只展示聚合指标，不展示完整地址原文。</span>";
}

function renderCards(elements) {
  if (!elements.cards) {
    return;
  }
  if (!state.summary) {
    elements.cards.innerHTML = "";
    return;
  }
  elements.cards.innerHTML = buildMetricCards(state.summary)
    .map(
      (card) => `
        <article class="metric-card">
          <p>${card.title}</p>
          <strong>${card.value}</strong>
          <span>${card.note}</span>
        </article>
      `,
    )
    .join("");
}

function renderTemplates(elements) {
  if (!elements.templates) {
    return;
  }
  const rows = buildTemplateRows(state.summary);
  if (!state.summary) {
    elements.templates.innerHTML = `<p class="metric-empty">输入 token 后显示模板分布。</p>`;
    return;
  }
  if (!rows.length) {
    elements.templates.innerHTML = `<p class="metric-empty">当前还没有模板分布数据。</p>`;
    return;
  }
  elements.templates.innerHTML = rows
    .map(
      (row) => `
        <div class="template-row">
          <span>${row.template}</span>
          <strong>${row.count}</strong>
        </div>
      `,
    )
    .join("");
}

function renderPage(elements) {
  renderBanner(elements);
  renderCards(elements);
  renderTemplates(elements);
}

async function handleSubmit(event, elements) {
  event.preventDefault();
  state.token = elements.tokenInput?.value.trim() || "";
  state.loading = true;
  state.error = "";
  renderPage(elements);
  try {
    state.summary = await requestMetrics(state.token);
  } catch (error) {
    state.summary = null;
    state.error = "token 不正确，或服务暂时不可用。";
  } finally {
    state.loading = false;
    renderPage(elements);
  }
}

function main() {
  // 中文注释：仅在真实浏览器页面里挂载事件，Node 测试环境下直接跳过。
  const elements = metricElements();
  if (!elements.form) {
    return;
  }
  elements.form.addEventListener("submit", (event) => {
    handleSubmit(event, elements);
  });
  renderPage(elements);
}

main();
