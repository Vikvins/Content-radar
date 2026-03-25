const state = {
  comparison: null,
  competitorsCount: 0,
  isBusy: false,
};

const FORMAT_LABELS = {
  post: "«Пост»",
  video: "«Видео»",
  carousel: "«Карусель»",
};

const statusEl = document.getElementById("status");
const compareForm = document.getElementById("compare-form");
const addCompetitorBtn = document.getElementById("add-competitor");
const loadCompareDemoBtn = document.getElementById("load-compare-demo");
const runCompareBtn = document.getElementById("run-compare");
const competitorsListEl = document.getElementById("competitors-list");

const myChannelNameInput = document.getElementById("my-channel-name");
const myChannelUrlInput = document.getElementById("my-channel-url");
const postsLimitInput = document.getElementById("posts-limit");

const winnerPanelEl = document.getElementById("winner-panel");
const rankingPanelEl = document.getElementById("ranking-panel");
const engagementInfoPanelEl = document.getElementById("engagement-info-panel");
const chartPanelEl = document.getElementById("chart-panel");
const insightsPanelEl = document.getElementById("insights-panel");
const detailsPanelEl = document.getElementById("details-panel");

const winnerCardEl = document.getElementById("winner-card");
const rankingTableBody = document.querySelector("#ranking-table tbody");
const channelsChartCanvas = document.getElementById("channels-chart");
const detailsCardsEl = document.getElementById("details-cards");
const formulaLineEl = document.getElementById("formula-line");

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

function setStatus(message, isError = false) {
  if (!statusEl) {
    return;
  }

  statusEl.textContent = message;
  statusEl.classList.toggle("error", isError);
  statusEl.classList.toggle("success", !isError && Boolean(message));
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function formatDateTime(value) {
  if (!value) {
    return "—";
  }

  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return "—";
  }

  const day = String(date.getDate()).padStart(2, "0");
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const year = String(date.getFullYear());
  const hours = String(date.getHours()).padStart(2, "0");
  const minutes = String(date.getMinutes()).padStart(2, "0");

  return `${day}.${month}.${year}, ${hours}:${minutes}`;
}

function formatNumber(value, digits = 1) {
  const num = Number(value);
  if (!Number.isFinite(num)) {
    return "—";
  }
  return num.toFixed(digits);
}

function formatContentFormat(formatName) {
  const normalized = String(formatName || "").trim().toLowerCase();
  return FORMAT_LABELS[normalized] || `«${String(formatName || "формат")}"`;
}

function replaceFormatTokens(text) {
  let result = String(text || "");
  result = result.replace(/«?carousel»?/gi, "«Карусель»");
  result = result.replace(/«?video»?/gi, "«Видео»");
  result = result.replace(/«?post»?/gi, "«Пост»");
  return result;
}

function normalizeWeakSideText(weakSideValue) {
  const normalized = String(weakSideValue || "").trim();
  if (!normalized || normalized === "—" || normalized === "-" || normalized.toLowerCase() === "n/a") {
    return "Нет явных слабых сторон";
  }
  return replaceFormatTokens(normalized);
}

function setActionButtonsState() {
  if (runCompareBtn) {
    runCompareBtn.disabled = state.isBusy;
    runCompareBtn.textContent = "Запустить сравнение";
  }

  if (loadCompareDemoBtn) {
    loadCompareDemoBtn.disabled = state.isBusy;
  }

  if (addCompetitorBtn) {
    addCompetitorBtn.disabled = state.isBusy;
  }
}

function setBusy(isBusy) {
  state.isBusy = isBusy;
  setActionButtonsState();
}

function clearResults() {
  setHidden(winnerPanelEl, true);
  setHidden(rankingPanelEl, true);
  setHidden(engagementInfoPanelEl, true);
  setHidden(chartPanelEl, true);
  setHidden(insightsPanelEl, true);
  setHidden(detailsPanelEl, true);

  setHtml(winnerCardEl, "");
  setHtml(rankingTableBody, "");
  setHtml(insightsPanelEl, "");
  setHtml(detailsCardsEl, "");

  drawChannelsLineChart([], "");
}

function createCompetitorRow(defaultName = "", defaultUrl = "") {
  state.competitorsCount += 1;
  const rowId = state.competitorsCount;

  return `
    <div class="split competitor-row" data-row-id="${rowId}">
      <label>
        Название конкурента
        <input type="text" class="competitor-name" placeholder="Конкурент ${rowId}" value="${escapeHtml(defaultName)}" required />
      </label>
      <label>
        Ссылка конкурента
        <div class="inline-actions">
          <input type="url" class="competitor-url" placeholder="https://t.me/competitor_${rowId}" value="${escapeHtml(defaultUrl)}" required />
          <button type="button" class="ghost remove-competitor">Удалить</button>
        </div>
      </label>
    </div>
  `;
}

function addCompetitorRow(defaultName = "", defaultUrl = "") {
  if (!competitorsListEl) {
    return;
  }

  competitorsListEl.insertAdjacentHTML("beforeend", createCompetitorRow(defaultName, defaultUrl));
}

function ensureMinimumCompetitors() {
  if (!competitorsListEl) {
    return;
  }

  const rows = competitorsListEl.querySelectorAll(".competitor-row");
  if (rows.length === 0) {
    addCompetitorRow();
  }
}

function parseCompetitors() {
  if (!competitorsListEl) {
    return [];
  }

  const rows = Array.from(competitorsListEl.querySelectorAll(".competitor-row"));
  return rows
    .map((row) => {
      const nameInput = row.querySelector(".competitor-name");
      const urlInput = row.querySelector(".competitor-url");

      const name = nameInput instanceof HTMLInputElement ? nameInput.value.trim() : "";
      const url = urlInput instanceof HTMLInputElement ? urlInput.value.trim() : "";

      if (!name && !url) {
        return null;
      }

      return { name, url };
    })
    .filter((item) => item && item.name && item.url);
}

function renderWinner(winner, myChannelName, ranking) {
  const myChannelRanking = (ranking || []).find((item) => item.name === myChannelName);
  const myRank = myChannelRanking ? `#${myChannelRanking.rank}` : "—";
  const lagValue = myChannelRanking ? Math.max(0, Number(-myChannelRanking.gap_vs_leader_pct || 0)) : null;
  const myLag = lagValue === null ? "—" : `${formatNumber(lagValue, 1)}%`;
  const winnerWeakSide = normalizeWeakSideText(winner?.weak_side);

  const html = `
    <article class="winner-hero">
      <p class="winner-kicker">Главный результат сравнения</p>
      <h2 class="winner-title">Победитель</h2>
      <p class="winner-channel-name">${escapeHtml(winner?.name || "—")}</p>
      <p class="winner-reason">${escapeHtml(replaceFormatTokens(winner?.reason || "Лидер определён по средней вовлечённости последних публикаций."))}</p>
      <p class="winner-weakness"><strong>Слабая сторона:</strong> ${escapeHtml(winnerWeakSide)}</p>
      <div class="winner-metrics">
        <div class="winner-metric">
          <span class="winner-metric-label">Вовлечённость лидера</span>
          <strong class="winner-metric-value">${escapeHtml(formatNumber(winner?.avg_engagement, 1))}</strong>
        </div>
        <div class="winner-metric">
          <span class="winner-metric-label">Позиция вашего канала</span>
          <strong class="winner-metric-value">${escapeHtml(myRank)}</strong>
        </div>
        <div class="winner-metric">
          <span class="winner-metric-label">Ваше отставание от лидера</span>
          <strong class="winner-metric-value">${escapeHtml(myLag)}</strong>
        </div>
      </div>
    </article>
  `;

  setHtml(winnerCardEl, html);
  setHidden(winnerPanelEl, false);
}

function renderRanking(ranking, myChannelName) {
  const html = (ranking || [])
    .map((row) => {
      const lagPct = Math.max(0, Number(-row.gap_vs_leader_pct || 0));
      const isMyChannel = row.name === myChannelName;
      const rowClass = isMyChannel ? ' class="ranking-row-my-channel"' : "";
      return `
      <tr${rowClass}>
        <td>${row.rank}</td>
        <td>${escapeHtml(row.name)}</td>
        <td>${escapeHtml(formatNumber(row.avg_engagement, 1))}</td>
        <td>${escapeHtml(formatNumber(lagPct, 1))}%</td>
        <td>${escapeHtml(replaceFormatTokens(row.strong_side))}</td>
        <td>${escapeHtml(normalizeWeakSideText(row.weak_side))}</td>
      </tr>
    `;
    })
    .join("");

  setHtml(rankingTableBody, html);
  setHidden(rankingPanelEl, false);
}

function renderInsights(insights, actions) {
  if (!insightsPanelEl) {
    return;
  }

  const safeInsights = Array.isArray(insights) && insights.length
    ? insights
    : ["Лидер стабильно показывает лучший отклик аудитории по ключевым форматам."];
  const safeActions = Array.isArray(actions) && actions.length
    ? actions
    : ["Сконцентрируйтесь на форматах и времени публикации лидера и замерьте прирост за неделю."];

  const whyMain = safeInsights.slice(0, 3);
  const whySignals = safeInsights.slice(3, 5);
  const actionSprint = safeActions.slice(0, 3);
  const actionTests = safeActions.slice(3, 6);

  const renderGroup = (title, items) => {
    if (!items.length) {
      return "";
    }

    const listHtml = items
      .map((item) => `<li>${escapeHtml(replaceFormatTokens(item))}</li>`)
      .join("");

    return `
      <section class="insight-group">
        <h3>${escapeHtml(title)}</h3>
        <ul class="insight-list-structured">${listHtml}</ul>
      </section>
    `;
  };

  const html = `
    <div class="insights-grid-enhanced">
      <article class="insight-block insight-why">
        <h2>Почему лидеры сильнее</h2>
        ${renderGroup("Ключевые причины", whyMain)}
        ${renderGroup("Сигналы из сравнения", whySignals)}
      </article>
      <article class="insight-block insight-actions">
        <h2>Что делать вашему каналу</h2>
        ${renderGroup("Приоритет на ближайшие 7 дней", actionSprint)}
        ${renderGroup("Тесты на 2 недели", actionTests)}
      </article>
    </div>
  `;

  setHtml(insightsPanelEl, html);
  setHidden(insightsPanelEl, false);
}

function renderDetails(details, isDemoMode, ranking) {
  const rankingByName = new Map((ranking || []).map((item) => [item.name, item]));

  const html = (details || [])
    .map((item) => {
      const rankInfo = rankingByName.get(item.name);
      const lagPct = rankInfo ? Math.max(0, Number(-rankInfo.gap_vs_leader_pct || 0)) : 0;
      const sourceMode = item.source_mode === "public" ? "Открытые данные" : "Демоданные";
      const sourceLabel = isDemoMode ? "Источник: демосценарий" : `Источник: ${escapeHtml(item.source_url)}`;
      const warningText = !isDemoMode && item.warning
        ? `<p class="notice warning top-gap">${escapeHtml(item.warning)}</p>`
        : "";

      const topTopics = (item.top_topics || []).length
        ? (item.top_topics || []).map((topic) => `<span class="chip">${escapeHtml(topic)}</span>`).join("")
        : '<span class="chip">Нет выраженных тем</span>';

      const topFormats = (item.top_formats || []).length
        ? (item.top_formats || []).map((formatName) => `<span class="chip">${escapeHtml(formatContentFormat(formatName))}</span>`).join("")
        : '<span class="chip">Нет приоритета формата</span>';

      const focusText = lagPct > 0
        ? `Приоритет: сократить отставание ${formatNumber(lagPct, 1)}% через усиление форматов и времени лидера.`
        : "Приоритет: удерживать лидерство и масштабировать лучшие форматы.";

      return `
        <article class="detail-channel-card">
          <div class="detail-header">
            <p class="detail-rank">Место #${escapeHtml(rankInfo?.rank ?? "—")}</p>
            <h3 class="detail-name">${escapeHtml(item.name)}</h3>
          </div>

          <div class="detail-metrics">
            <div class="detail-metric">
              <span class="detail-metric-label">Средняя вовлечённость</span>
              <strong class="detail-metric-value">${escapeHtml(formatNumber(item.avg_engagement, 1))}</strong>
            </div>
            <div class="detail-metric">
              <span class="detail-metric-label">Ваше отставание от лидера</span>
              <strong class="detail-metric-value">${escapeHtml(formatNumber(lagPct, 1))}%</strong>
            </div>
            <div class="detail-metric">
              <span class="detail-metric-label">Лучшее время</span>
              <strong class="detail-metric-value">${escapeHtml(item.best_time || "—")}</strong>
            </div>
          </div>

          <p class="detail-text"><strong>Режим:</strong> ${escapeHtml(sourceMode)} · <strong>Постов:</strong> ${escapeHtml(item.posts_count)}</p>
          <p class="detail-text"><strong>${escapeHtml(replaceFormatTokens(rankInfo?.strong_side || "Сильная сторона"))}</strong></p>
          <p class="detail-text"><strong>${escapeHtml(normalizeWeakSideText(rankInfo?.weak_side || "Зона роста"))}</strong></p>
          <p class="detail-text">${escapeHtml(focusText)}</p>

          <div class="detail-tags-block">
            <p class="detail-subtitle">Топ темы</p>
            <div class="chips-row">${topTopics}</div>
          </div>

          <div class="detail-tags-block">
            <p class="detail-subtitle">Топ форматы</p>
            <div class="chips-row">${topFormats}</div>
          </div>

          <p class="detail-source">${sourceLabel}</p>
          ${warningText}
        </article>
      `;
    })
    .join("");

  setHtml(detailsCardsEl, html);
  setHidden(detailsPanelEl, false);
}

function drawChannelsLineChart(timelines, myChannelName) {
  if (!channelsChartCanvas) {
    return;
  }

  const context = channelsChartCanvas.getContext("2d");
  if (!context) {
    return;
  }

  const width = channelsChartCanvas.width;
  const height = channelsChartCanvas.height;
  context.clearRect(0, 0, width, height);

  if (!Array.isArray(timelines) || timelines.length === 0) {
    context.fillStyle = "#94a3b8";
    context.font = "16px Inter";
    context.fillText("Нет данных для визуализации динамики", 24, 40);
    return;
  }

  const normalizedSeries = timelines
    .map((series) => {
      const points = Array.isArray(series?.points)
        ? series.points
            .map((point) => {
              const timestamp = new Date(point?.date || "").getTime();
              const engagement = Number(point?.engagement);
              if (!Number.isFinite(timestamp) || !Number.isFinite(engagement)) {
                return null;
              }
              return {
                timestamp,
                engagement,
                dateLabel: formatDateTime(point.date),
              };
            })
            .filter((point) => point)
            .sort((a, b) => a.timestamp - b.timestamp)
        : [];

      return {
        name: String(series?.name || "Канал"),
        points,
      };
    })
    .filter((series) => series.points.length > 0);

  if (normalizedSeries.length === 0) {
    context.fillStyle = "#94a3b8";
    context.font = "16px Inter";
    context.fillText("Нет корректных точек для построения графика", 24, 40);
    return;
  }

  const paddingLeft = 70;
  const paddingRight = 24;
  const paddingTop = 24;
  const paddingBottom = 56;

  const chartWidth = width - paddingLeft - paddingRight;
  const chartHeight = height - paddingTop - paddingBottom;

  const allPoints = normalizedSeries.flatMap((series) => series.points);
  const minTs = Math.min(...allPoints.map((point) => point.timestamp));
  const maxTs = Math.max(...allPoints.map((point) => point.timestamp));
  const maxEngagement = Math.max(...allPoints.map((point) => point.engagement), 1);
  const tsRange = Math.max(maxTs - minTs, 1);

  const yTicks = 4;
  for (let i = 0; i <= yTicks; i += 1) {
    const ratio = i / yTicks;
    const y = paddingTop + chartHeight * ratio;
    const value = maxEngagement * (1 - ratio);

    context.strokeStyle = "#334155";
    context.lineWidth = 1;
    context.beginPath();
    context.moveTo(paddingLeft, y);
    context.lineTo(width - paddingRight, y);
    context.stroke();

    context.fillStyle = "#94a3b8";
    context.font = "12px Inter";
    context.fillText(formatNumber(value, 0), 18, y + 4);
  }

  const xTicks = 4;
  for (let i = 0; i <= xTicks; i += 1) {
    const ratio = i / xTicks;
    const ts = minTs + tsRange * ratio;
    const x = paddingLeft + chartWidth * ratio;

    context.strokeStyle = "#334155";
    context.beginPath();
    context.moveTo(x, height - paddingBottom);
    context.lineTo(x, height - paddingBottom + 6);
    context.stroke();

    context.fillStyle = "#94a3b8";
    context.font = "11px Inter";
    const label = formatDateTime(new Date(ts).toISOString()).replace(", ", " ");
    context.save();
    context.translate(x, height - 18);
    context.rotate(-0.25);
    context.fillText(label, -44, 0);
    context.restore();
  }

  const palette = ["#10B981", "#6366F1", "#22D3EE", "#F59E0B", "#A78BFA", "#FB7185"];

  normalizedSeries.forEach((series, index) => {
    const isMyChannel = series.name === myChannelName;
    const color = isMyChannel ? "#22D3EE" : palette[index % palette.length];

    context.strokeStyle = color;
    context.lineWidth = isMyChannel ? 4.2 : 3.1;
    context.lineCap = "round";
    context.lineJoin = "round";
    context.beginPath();

    series.points.forEach((point, pointIndex) => {
      const x = paddingLeft + ((point.timestamp - minTs) / tsRange) * chartWidth;
      const y = paddingTop + (1 - point.engagement / maxEngagement) * chartHeight;

      if (pointIndex === 0) {
        context.moveTo(x, y);
      } else {
        context.lineTo(x, y);
      }
    });
    context.stroke();

    series.points.forEach((point) => {
      const x = paddingLeft + ((point.timestamp - minTs) / tsRange) * chartWidth;
      const y = paddingTop + (1 - point.engagement / maxEngagement) * chartHeight;

      const pointRadius = isMyChannel ? 5.2 : 4.2;

      context.fillStyle = color;
      context.beginPath();
      context.arc(x, y, pointRadius, 0, Math.PI * 2);
      context.fill();

      context.strokeStyle = "#0b1220";
      context.lineWidth = 1.5;
      context.beginPath();
      context.arc(x, y, pointRadius, 0, Math.PI * 2);
      context.stroke();
    });
  });

  let legendX = paddingLeft;
  const legendY = 14;
  normalizedSeries.forEach((series, index) => {
    const isMyChannel = series.name === myChannelName;
    const color = isMyChannel ? "#22D3EE" : palette[index % palette.length];

    context.fillStyle = color;
    context.fillRect(legendX, legendY, 12, 12);

    context.fillStyle = "#E2E8F0";
    context.font = "12px Inter";
    const legendLabel = isMyChannel ? `${series.name} (ваш канал)` : series.name;
    context.fillText(legendLabel, legendX + 16, legendY + 10);

    legendX += Math.max(140, context.measureText(legendLabel).width + 28);
  });

  setHidden(chartPanelEl, false);
}

function renderFormula(formula) {
  if (!formulaLineEl || !formula?.description) {
    return;
  }

  setText(formulaLineEl, formula.description);
}

function renderComparison(payload) {
  renderWinner(payload.winner, payload.my_channel_name, payload.ranking || []);
  renderRanking(payload.ranking || [], payload.my_channel_name || "");
  renderFormula(payload.engagement_formula || null);
  setHidden(engagementInfoPanelEl, false);
  drawChannelsLineChart(payload.timelines || [], payload.my_channel_name || "");
  renderInsights(payload.insights || [], payload.actions || []);
  renderDetails(payload.channel_details || [], Boolean(payload.is_demo_mode), payload.ranking || []);
}

async function runComparison(payload) {
  try {
    setBusy(true);
    setStatus("Сравниваю каналы...");
    clearResults();

    const response = await fetch("/compare_channels", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify(payload),
    });

    const body = await response.json();
    if (!response.ok) {
      throw new Error(body.detail || "Не удалось выполнить сравнение каналов");
    }

    state.comparison = body;
    renderComparison(body);

    if (body.is_demo_mode) {
      setStatus("Сравнение выполнено на демоданных. Ниже — готовая структура для питча.");
    } else if (Array.isArray(body.warnings) && body.warnings.length) {
      setStatus(`${body.message} Некоторые источники ограничили часть метрик, но сравнение готово.`);
    } else {
      setStatus(body.message);
    }
  } catch (error) {
    setStatus(error.message || "Ошибка сравнения", true);
  } finally {
    setBusy(false);
  }
}

function buildPayloadFromForm() {
  const myChannelName = myChannelNameInput?.value?.trim() || "";
  const myChannelUrl = myChannelUrlInput?.value?.trim() || "";
  const competitors = parseCompetitors();

  const parsedLimit = Number(postsLimitInput?.value);
  const postsLimit = Number.isFinite(parsedLimit) ? parsedLimit : 12;

  if (!myChannelName || !myChannelUrl) {
    throw new Error("Заполните название и ссылку вашего канала.");
  }

  if (competitors.length < 1) {
    throw new Error("Добавьте минимум одного конкурента для сравнения.");
  }

  return {
    my_channel_name: myChannelName,
    my_channel_url: myChannelUrl,
    competitors,
    posts_limit: postsLimit,
  };
}

async function handleCompareSubmit(event) {
  event.preventDefault();

  try {
    const payload = buildPayloadFromForm();
    await runComparison(payload);
  } catch (error) {
    setStatus(error.message || "Ошибка валидации формы", true);
  }
}

function handleCompareDemoLoad() {
  const demoPayload = {
    my_channel_name: "МаркетПульс",
    my_channel_url: "https://t.me/s/marketpulse_brand",
    competitors: [
      { name: "ЛаймКонтент Медиа", url: "https://t.me/s/limecontent_leader" },
      { name: "ТрафикЛаб", url: "https://t.me/s/trafficlab_challenger" },
    ],
    posts_limit: 12,
  };

  if (myChannelNameInput) {
    myChannelNameInput.value = demoPayload.my_channel_name;
  }
  if (myChannelUrlInput) {
    myChannelUrlInput.value = demoPayload.my_channel_url;
  }
  if (postsLimitInput) {
    postsLimitInput.value = String(demoPayload.posts_limit);
  }

  if (competitorsListEl) {
    competitorsListEl.innerHTML = "";
    state.competitorsCount = 0;
    demoPayload.competitors.forEach((item) => addCompetitorRow(item.name, item.url));
  }

  state.comparison = null;
  clearResults();
  setStatus("Демосценарий загружен в форму. Нажмите «Запустить сравнение», чтобы получить результаты.");
}

if (addCompetitorBtn) {
  addCompetitorBtn.addEventListener("click", () => {
    addCompetitorRow();
  });
}

if (competitorsListEl) {
  competitorsListEl.addEventListener("click", (event) => {
    const target = event.target;
    if (!(target instanceof HTMLElement)) {
      return;
    }

    if (!target.classList.contains("remove-competitor")) {
      return;
    }

    const rows = competitorsListEl.querySelectorAll(".competitor-row");
    if (rows.length <= 1) {
      setStatus("Нужен минимум один конкурент для сравнения.", true);
      return;
    }

    const row = target.closest(".competitor-row");
    if (row) {
      row.remove();
    }
  });
}

if (compareForm) {
  compareForm.addEventListener("submit", handleCompareSubmit);
}

if (loadCompareDemoBtn) {
  loadCompareDemoBtn.addEventListener("click", handleCompareDemoLoad);
}

ensureMinimumCompetitors();
clearResults();
setActionButtonsState();
setStatus("Готово к работе: заполните каналы и запустите сравнение.");
