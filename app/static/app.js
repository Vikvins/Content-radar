const state = {
  analysis: null,
  insights: null,
  discoveredPosts: [],
  selectedCount: 0,
  preparedPostsCount: 0,
  canAnalyze: false,
};

const statusEl = document.getElementById("status");
const selectionStatusEl = document.getElementById("selection-status");
const sourceNoteEl = document.getElementById("discover-source-note");
const selectedCountEl = document.getElementById("selected-count");

const uploadForm = document.getElementById("upload-form");
const discoverForm = document.getElementById("discover-form");

const runAnalysisBtn = document.getElementById("run-analysis");
const loadDemoBtn = document.getElementById("load-demo");
const getInsightsBtn = document.getElementById("get-insights");
const selectPostsBtn = document.getElementById("select-posts");
const selectAllPostsBtn = document.getElementById("select-all-posts");
const clearSelectedPostsBtn = document.getElementById("clear-selected-posts");

const competitorsInput = document.getElementById("competitors");
const competitorNameInput = document.getElementById("competitor-name");
const fileInput = document.getElementById("posts-file");

const sourceUrlInput = document.getElementById("source-url");
const discoverCompetitorInput = document.getElementById("discover-competitor");
const discoverLimitInput = document.getElementById("discover-limit");

const discoverTableBody = document.querySelector("#discover-table tbody");
const postsTableBody = document.querySelector("#posts-table tbody");
const topicsList = document.getElementById("topics-list");
const formatsList = document.getElementById("formats-list");
const bestTimeEl = document.getElementById("best-time");
const summaryCardsEl = document.getElementById("summary-cards");
const recommendationsEl = document.getElementById("recommendations");
const topPostsEl = document.getElementById("top-posts");
const formulaCardEl = document.getElementById("formula-card");
const chartCanvas = document.getElementById("engagement-chart");

function setText(element, text) {
  if (!element) {
    return;
  }
  element.textContent = text;
}

function setHtml(element, html) {
  if (!element) {
    return;
  }
  element.innerHTML = html;
}

function setHidden(element, hidden) {
  if (!element) {
    return;
  }
  element.hidden = hidden;
}

function setDisabled(element, disabled) {
  if (!element) {
    return;
  }
  element.disabled = disabled;
}

function resetClassFlags(element, classNames) {
  if (!element) {
    return;
  }
  element.classList.remove(...classNames);
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function toValidDate(value) {
  if (!value) {
    return null;
  }
  const parsed = value instanceof Date ? value : new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    return null;
  }
  return parsed;
}

function padNumber(value) {
  return String(value).padStart(2, "0");
}

function formatDateTime(value) {
  const date = toValidDate(value);
  if (!date) {
    return "—";
  }

  const day = padNumber(date.getDate());
  const month = padNumber(date.getMonth() + 1);
  const year = date.getFullYear();
  const hours = padNumber(date.getHours());
  const minutes = padNumber(date.getMinutes());
  return `${day}.${month}.${year}, ${hours}:${minutes}`;
}

function formatDateOnly(value) {
  const date = toValidDate(value);
  if (!date) {
    return "—";
  }

  const day = padNumber(date.getDate());
  const month = padNumber(date.getMonth() + 1);
  const year = date.getFullYear();
  return `${day}.${month}.${year}`;
}

function setStatus(message, isError = false) {
  if (!statusEl) {
    return;
  }

  setText(statusEl, message);
  statusEl.classList.toggle("error", isError);
}

function setSelectionStatus(message, type = "info") {
  if (!selectionStatusEl) {
    return;
  }

  if (!message) {
    setHidden(selectionStatusEl, true);
    setText(selectionStatusEl, "");
    resetClassFlags(selectionStatusEl, ["success", "error"]);
    return;
  }

  setHidden(selectionStatusEl, false);
  setText(selectionStatusEl, message);
  resetClassFlags(selectionStatusEl, ["success", "error"]);
  if (type === "success") {
    selectionStatusEl.classList.add("success");
  }
  if (type === "error") {
    selectionStatusEl.classList.add("error");
  }
}

function setSourceNote(message, type = "info") {
  if (!sourceNoteEl) {
    return;
  }

  if (!message) {
    setHidden(sourceNoteEl, true);
    setText(sourceNoteEl, "");
    resetClassFlags(sourceNoteEl, ["warning", "success"]);
    return;
  }

  setHidden(sourceNoteEl, false);
  setText(sourceNoteEl, message);
  resetClassFlags(sourceNoteEl, ["warning", "success"]);
  sourceNoteEl.classList.add(type === "warning" ? "warning" : "success");
}

function updateAnalyzeAvailability() {
  setDisabled(runAnalysisBtn, !state.canAnalyze);
}

function setPreparedPostsCount(count) {
  state.preparedPostsCount = Math.max(0, Number(count) || 0);
  state.canAnalyze = state.preparedPostsCount > 0;
  updateAnalyzeAvailability();
}

function updateSelectedCount() {
  state.selectedCount = getSelectedDiscoveredIds().length;
  setText(selectedCountEl, `Выбрано постов: ${state.selectedCount}`);

  const hasDiscovered = state.discoveredPosts.length > 0;
  const hasSelected = state.selectedCount > 0;
  setDisabled(selectPostsBtn, !hasSelected);
  setDisabled(clearSelectedPostsBtn, !hasSelected);
  setDisabled(selectAllPostsBtn, !hasDiscovered);
}

function clearOutput() {
  setHtml(postsTableBody, "");
  setHtml(topicsList, "");
  setHtml(formatsList, "");
  setHtml(bestTimeEl, "");
  setHtml(summaryCardsEl, "");
  setHtml(recommendationsEl, "");
  setHtml(topPostsEl, "");

  // Optional block: formula container may be absent in the template.
  setHtml(formulaCardEl, "");

  drawEngagementChart([]);
}

function parseCompetitors() {
  if (!competitorsInput) {
    return [];
  }

  return competitorsInput.value
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
}

function renderSummary(summary) {
  const cards = [
    { label: "Всего постов", value: summary.total_posts ?? 0 },
    { label: "Средняя вовлечённость", value: summary.avg_engagement ?? 0 },
    {
      label: "Конкуренты в анализе",
      value: (summary.competitors_in_scope || []).join(", ") || "—",
    },
    {
      label: "Время анализа",
      value: formatDateTime(summary.analyzed_at),
    },
  ];

  const html = cards
    .map(
      (card) => `
      <article class="card">
        <div class="label">${escapeHtml(card.label)}</div>
        <div class="value">${escapeHtml(card.value)}</div>
      </article>
    `,
    )
    .join("");

  setHtml(summaryCardsEl, html);
}

function renderFormula(formula) {
  // The separate formula panel is optional and can be removed from UI.
  if (!formulaCardEl) {
    return;
  }

  if (!formula || !formula.description) {
    setHtml(formulaCardEl, "");
    return;
  }

  setHtml(
    formulaCardEl,
    `
    <article class="card formula">
      <div class="label">${escapeHtml(formula.title || "Формула")}</div>
      <div class="formula-text">${escapeHtml(formula.description)}</div>
    </article>
  `,
  );
}

function renderDiscoveredPosts(posts) {
  const html = (posts || [])
    .map(
      (post) => `
      <tr>
        <td><input type="checkbox" class="post-check" data-id="${post.discovered_id}" /></td>
        <td>${post.discovered_id + 1}</td>
        <td>${escapeHtml(formatDateTime(post.date))}</td>
        <td>${escapeHtml(post.competitor || "—")}</td>
        <td>${escapeHtml(post.format)}</td>
        <td>${escapeHtml(post.text)}</td>
        <td>${post.likes}</td>
        <td>${post.comments}</td>
        <td>${post.shares}</td>
        <td>${post.views}</td>
      </tr>
    `,
    )
    .join("");

  setHtml(discoverTableBody, html);
  updateSelectedCount();
}

function setDiscoveredPosts(posts) {
  state.discoveredPosts = Array.isArray(posts) ? posts : [];
  renderDiscoveredPosts(state.discoveredPosts);
}

function getSelectedDiscoveredIds() {
  return Array.from(document.querySelectorAll(".post-check:checked"))
    .map((el) => Number(el.dataset.id))
    .filter((value) => Number.isInteger(value));
}

function renderTopPosts(posts) {
  const html = (posts || [])
    .map(
      (post, index) => `
      <article class="card top-post-card">
        <div class="label">Топ ${index + 1}</div>
        <div class="value small">${escapeHtml(post.format)} · ${escapeHtml(formatDateOnly(post.date))}</div>
        <p>${escapeHtml(post.text)}</p>
        <div class="metric">Вовлечённость: <strong>${post.engagement_score}</strong></div>
      </article>
    `,
    )
    .join("");

  setHtml(topPostsEl, html);
}

function renderPostsTable(posts) {
  const html = (posts || [])
    .map(
      (post, index) => `
      <tr>
        <td>${index + 1}</td>
        <td>${escapeHtml(formatDateTime(post.date))}</td>
        <td>${escapeHtml(post.format)}</td>
        <td>${escapeHtml(post.competitor || "—")}</td>
        <td>${escapeHtml(post.text)}</td>
        <td>${post.likes}</td>
        <td>${post.comments}</td>
        <td>${post.shares}</td>
        <td>${post.views}</td>
        <td>${post.engagement_score}</td>
      </tr>
    `,
    )
    .join("");

  setHtml(postsTableBody, html);
}

function renderTopics(topics) {
  const html = (topics || [])
    .map((topic, index) => {
      const rankClass = index === 0 ? "topic-item top-topic" : "topic-item";
      return `
        <li class="${rankClass}">
          <span class="topic-badge">#${index + 1}</span>
          <span class="topic-name">${escapeHtml(topic.topic)}</span>
          <span class="topic-meta">Средняя вовлечённость: ${topic.avg_engagement}</span>
          <span class="topic-meta">Постов: ${topic.posts_count}</span>
        </li>
      `;
    })
    .join("");

  setHtml(topicsList, html);
}

function renderFormats(formats) {
  const html = (formats || [])
    .map(
      (item) =>
        `<li><strong>${escapeHtml(item.format)}</strong> — средняя вовлечённость: ${item.avg_engagement}, постов: ${item.posts_count}</li>`,
    )
    .join("");

  setHtml(formatsList, html);
}

function renderBestTime(bestTime) {
  if (!bestTime) {
    setHtml(bestTimeEl, "");
    return;
  }

  const cards = [
    {
      label: "Лучший период",
      value: bestTime.best_bucket || "—",
    },
    {
      label: "Лучший час",
      value:
        bestTime.best_hour !== null && bestTime.best_hour !== undefined
          ? `${padNumber(bestTime.best_hour)}:00`
          : "—",
    },
  ];

  const html = cards
    .map(
      (card) => `
      <article class="card">
        <div class="label">${escapeHtml(card.label)}</div>
        <div class="value">${escapeHtml(card.value)}</div>
      </article>
    `,
    )
    .join("");

  setHtml(bestTimeEl, html);
}

function renderRecommendations(recommendations) {
  const html = (recommendations || [])
    .map((item) => `<li>${escapeHtml(item)}</li>`)
    .join("");

  setHtml(recommendationsEl, html);
}

function drawEngagementChart(posts) {
  if (!chartCanvas) {
    return;
  }

  const ctx = chartCanvas.getContext("2d");
  if (!ctx) {
    return;
  }

  const width = chartCanvas.width;
  const height = chartCanvas.height;

  ctx.clearRect(0, 0, width, height);

  if (!posts.length) {
    ctx.fillStyle = "#63708a";
    ctx.font = "16px Arial";
    ctx.fillText("Нет данных для графика", 20, 40);
    return;
  }

  const values = posts.map((post) => post.engagement_score || 0);
  const max = Math.max(...values, 1);
  const padding = 28;
  const plotWidth = width - padding * 2;
  const plotHeight = height - padding * 2;
  const stepX = values.length > 1 ? plotWidth / (values.length - 1) : plotWidth;

  ctx.strokeStyle = "#d8dfec";
  ctx.lineWidth = 1;
  ctx.beginPath();
  ctx.moveTo(padding, padding);
  ctx.lineTo(padding, height - padding);
  ctx.lineTo(width - padding, height - padding);
  ctx.stroke();

  ctx.strokeStyle = "#3b82f6";
  ctx.lineWidth = 2;
  ctx.beginPath();

  values.forEach((value, index) => {
    const x = padding + index * stepX;
    const y = height - padding - (value / max) * plotHeight;
    if (index === 0) {
      ctx.moveTo(x, y);
    } else {
      ctx.lineTo(x, y);
    }
  });

  ctx.stroke();

  ctx.fillStyle = "#3b82f6";
  values.forEach((value, index) => {
    const x = padding + index * stepX;
    const y = height - padding - (value / max) * plotHeight;
    ctx.beginPath();
    ctx.arc(x, y, 3, 0, Math.PI * 2);
    ctx.fill();
  });
}

function markDataPrepared(postsCount, sourceMessage) {
  setPreparedPostsCount(postsCount);
  if (sourceMessage) {
    setStatus(sourceMessage);
  }
}

async function handleUpload(event) {
  event.preventDefault();

  if (!fileInput) {
    setStatus("Поле загрузки файла недоступно в текущем шаблоне.", true);
    return;
  }

  const file = fileInput.files?.[0];
  if (!file) {
    setStatus("Выберите JSON или CSV-файл для загрузки.", true);
    return;
  }

  const formData = new FormData();
  formData.append("file", file);

  const competitorName = competitorNameInput?.value?.trim() || "";
  if (competitorName) {
    formData.append("competitor", competitorName);
  }

  try {
    setStatus("Загружаю файл...");
    const response = await fetch("/upload_posts", {
      method: "POST",
      body: formData,
    });

    const payload = await response.json();
    if (!response.ok) {
      throw new Error(payload.detail || "Ошибка загрузки файла");
    }

    state.analysis = null;
    state.insights = null;
    clearOutput();
    markDataPrepared(payload.posts_count, `${payload.message}. Постов: ${payload.posts_count}`);
    setSelectionStatus("");
    setSourceNote("");
  } catch (error) {
    setStatus(error.message, true);
  }
}

async function handleDiscover(event) {
  event.preventDefault();

  const sourceUrl = sourceUrlInput?.value?.trim() || "";
  if (!sourceUrl) {
    setStatus("Введите ссылку источника.", true);
    return;
  }

  const limitValue = Number(discoverLimitInput?.value);
  const payload = {
    source_url: sourceUrl,
    competitor: discoverCompetitorInput?.value?.trim() || null,
    limit: Number.isFinite(limitValue) ? limitValue : 12,
  };

  try {
    setStatus("Получаю доступные посты...");
    const response = await fetch("/discover_posts", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify(payload),
    });

    const body = await response.json();
    if (!response.ok) {
      throw new Error(body.detail || "Ошибка получения постов");
    }

    setDiscoveredPosts(body.posts || []);
    setPreparedPostsCount(0);
    setSelectionStatus("");

    const normalizedUrlText = body.source_url ? `Источник: ${body.source_url}.` : "";
    const sourceModeText = body.source_mode === "public" ? "Режим: открытые данные." : "Режим: demo fallback.";
    if (body.warning) {
      setSourceNote(`${normalizedUrlText} ${sourceModeText} ${body.warning}`.trim(), "warning");
    } else {
      setSourceNote(`${normalizedUrlText} ${sourceModeText} ${body.source_details || ""}`.trim(), "success");
    }

    setStatus(`${body.message} Найдено постов: ${body.posts_count}`);
  } catch (error) {
    setStatus(error.message, true);
    setSourceNote("");
  }
}

async function handleSelectPosts() {
  const selectedIds = getSelectedDiscoveredIds();
  if (!selectedIds.length) {
    setSelectionStatus("Отметьте хотя бы один пост для анализа.", "error");
    setStatus("Не выбраны посты для сохранения.", true);
    return;
  }

  try {
    setStatus("Сохраняю выбранные посты...");
    const response = await fetch("/select_posts", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ selected_ids: selectedIds }),
    });

    const payload = await response.json();
    if (!response.ok) {
      throw new Error(payload.detail || "Ошибка выбора постов");
    }

    state.analysis = null;
    state.insights = null;
    clearOutput();
    setPreparedPostsCount(payload.posts_count);
    setSelectionStatus(`Сохранено ${payload.posts_count} постов для анализа.`, "success");
    setStatus("Выбор сохранён. Нажмите «Запустить анализ» для расчёта.");
  } catch (error) {
    setStatus(error.message, true);
    setSelectionStatus(error.message, "error");
  }
}

function handleSelectAll() {
  const checkboxes = Array.from(document.querySelectorAll(".post-check"));
  checkboxes.forEach((checkbox) => {
    checkbox.checked = true;
  });
  updateSelectedCount();
}

function handleClearSelected() {
  const checkboxes = Array.from(document.querySelectorAll(".post-check"));
  checkboxes.forEach((checkbox) => {
    checkbox.checked = false;
  });
  updateSelectedCount();
}

async function handleAnalyze() {
  if (!state.canAnalyze) {
    setStatus("Сначала подготовьте данные: загрузите файл или сохраните выбранные посты.", true);
    return;
  }

  try {
    setStatus("Выполняю анализ...");
    const response = await fetch("/analyze_content", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ competitors: parseCompetitors() }),
    });

    const payload = await response.json();
    if (!response.ok) {
      throw new Error(payload.detail || "Ошибка анализа");
    }

    state.analysis = payload;
    renderSummary(payload.summary || {});
    renderFormula(payload.engagement_formula || null);
    renderPostsTable(payload.posts || []);
    renderTopPosts(payload.top_posts || []);
    renderTopics(payload.top_topics || []);
    renderFormats(payload.top_formats || []);
    renderBestTime(payload.best_time || null);
    renderRecommendations(payload.recommendations || []);
    drawEngagementChart(payload.posts || []);
    setStatus("Анализ завершён.");
  } catch (error) {
    setStatus(error.message, true);
  }
}

async function handleInsights() {
  try {
    setStatus("Обновляю рекомендации...");
    const response = await fetch("/insights");
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(payload.detail || "Ошибка получения рекомендаций");
    }

    state.insights = payload;
    renderRecommendations(payload.recommendations || []);
    renderFormula(payload.engagement_formula || null);
    if (!state.analysis && payload.summary) {
      renderSummary(payload.summary);
    }
    setStatus("Рекомендации обновлены.");
  } catch (error) {
    setStatus(error.message, true);
  }
}

async function handleLoadDemo() {
  try {
    setStatus("Загружаю демоданные...");
    const response = await fetch("/load_demo", { method: "POST" });
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(payload.detail || "Ошибка загрузки демоданных");
    }

    state.analysis = null;
    state.insights = null;
    clearOutput();

    // При загрузке демо полностью заменяем список доступных постов,
    // чтобы таблица не показывала старые Telegram-данные.
    setDiscoveredPosts(payload.posts || []);

    markDataPrepared(payload.posts_count, `${payload.message}. Постов: ${payload.posts_count}`);
    setSelectionStatus("");
    setSourceNote("Источник: встроенный демонабор. Режим: demo.", "success");
  } catch (error) {
    setStatus(error.message, true);
  }
}

if (uploadForm) {
  uploadForm.addEventListener("submit", handleUpload);
}
if (discoverForm) {
  discoverForm.addEventListener("submit", handleDiscover);
}
if (selectPostsBtn) {
  selectPostsBtn.addEventListener("click", handleSelectPosts);
}
if (selectAllPostsBtn) {
  selectAllPostsBtn.addEventListener("click", handleSelectAll);
}
if (clearSelectedPostsBtn) {
  clearSelectedPostsBtn.addEventListener("click", handleClearSelected);
}
if (runAnalysisBtn) {
  runAnalysisBtn.addEventListener("click", handleAnalyze);
}
if (getInsightsBtn) {
  getInsightsBtn.addEventListener("click", handleInsights);
}
if (loadDemoBtn) {
  loadDemoBtn.addEventListener("click", handleLoadDemo);
}

if (discoverTableBody) {
  discoverTableBody.addEventListener("change", (event) => {
    const target = event.target;
    if (target instanceof HTMLInputElement && target.classList.contains("post-check")) {
      updateSelectedCount();
    }
  });
}

setPreparedPostsCount(0);
setSelectionStatus("");
setSourceNote("");
setStatus("Готово к работе: загрузите файл или получите посты по ссылке.");
drawEngagementChart([]);
