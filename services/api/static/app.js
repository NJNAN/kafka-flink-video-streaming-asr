const transcriptList = document.querySelector("#transcript-list");
const keywordList = document.querySelector("#keyword-list");
const transcriptCount = document.querySelector("#transcript-count");
const keywordCount = document.querySelector("#keyword-count");
const latestLatency = document.querySelector("#latest-latency");
const p95Latency = document.querySelector("#p95-latency");
const throughput = document.querySelector("#throughput");
const failedCount = document.querySelector("#failed-count");
const failedList = document.querySelector("#failed-list");
const metricsChart = document.querySelector("#metrics-chart");
const consumerDot = document.querySelector("#consumer-dot");
const consumerText = document.querySelector("#consumer-text");

function formatMs(value) {
  if (!value && value !== 0) return "-";
  if (value < 1000) return `${value} ms`;
  return `${(value / 1000).toFixed(1)} s`;
}

function formatVideoTime(ms) {
  const totalSeconds = Math.floor((ms || 0) / 1000);
  const minutes = String(Math.floor(totalSeconds / 60)).padStart(2, "0");
  const seconds = String(totalSeconds % 60).padStart(2, "0");
  return `${minutes}:${seconds}`;
}

function renderTranscripts(items) {
  if (!items.length) {
    transcriptList.innerHTML = `<div class="empty">等待视频字幕输出</div>`;
    return;
  }

  transcriptList.innerHTML = items
    .map((item) => {
      const text = item.text || "(空字幕)";
      return `
        <article class="item">
          <div class="meta">
            <span>${item.stream_id || "unknown"} / ${formatVideoTime(item.start_time_ms)}</span>
            <span>ASR ${formatMs(item.inference_time_ms)} / 总延迟 ${formatMs(item.end_to_end_time_ms)}</span>
          </div>
          <div class="text">${escapeHtml(text)}</div>
        </article>
      `;
    })
    .join("");
}

function renderKeywords(items) {
  if (!items.length) {
    keywordList.innerHTML = `<div class="empty">等待关键词事件</div>`;
    return;
  }

  keywordList.innerHTML = items
    .map((item) => {
      const tags = (item.keywords || [])
        .map((keyword) => `<span class="tag">${escapeHtml(keyword.word)}</span>`)
        .join("");
      return `
        <article class="item">
          <div class="meta">
            <span>${item.stream_id || "unknown"} / ${item.event_type || "keyword"}</span>
            <span>${formatVideoTime(item.start_time_ms)}</span>
          </div>
          <div class="tags">${tags || "<span class='tag'>无关键词</span>"}</div>
        </article>
      `;
    })
    .join("");
}

function renderFailures(items) {
  if (!items.length) {
    failedList.innerHTML = `<div class="empty">暂无失败片段</div>`;
    return;
  }

  failedList.innerHTML = items
    .map((item) => {
      return `
        <article class="item">
          <div class="meta">
            <span>${item.stream_id || "unknown"} / ${item.segment_id || "-"}</span>
            <span>retry ${item.retry_count || 0}</span>
          </div>
          <div class="text">${escapeHtml(item.error || "unknown error")}</div>
        </article>
      `;
    })
    .join("");
}

function drawMetricsHistory(items) {
  if (!metricsChart) return;
  const ctx = metricsChart.getContext("2d");
  const width = metricsChart.width;
  const height = metricsChart.height;
  ctx.clearRect(0, 0, width, height);
  ctx.fillStyle = "#ffffff";
  ctx.fillRect(0, 0, width, height);

  if (!items.length) {
    ctx.fillStyle = "#718096";
    ctx.font = "14px Microsoft YaHei, Arial";
    ctx.fillText("等待指标采样", 28, 42);
    return;
  }

  const padding = 34;
  const chartWidth = width - padding * 2;
  const chartHeight = height - padding * 2;
  const latencyValues = items.map((item) => Number(item.average_end_to_end_latency_ms || 0));
  const p95Values = items.map((item) => Number(item.p95_latency_ms || 0));
  const maxValue = Math.max(1000, ...latencyValues, ...p95Values);

  ctx.strokeStyle = "#e2e8f0";
  ctx.lineWidth = 1;
  for (let i = 0; i <= 4; i += 1) {
    const y = padding + (chartHeight / 4) * i;
    ctx.beginPath();
    ctx.moveTo(padding, y);
    ctx.lineTo(width - padding, y);
    ctx.stroke();
  }

  function point(index, value) {
    const x = padding + (items.length === 1 ? 0 : (chartWidth * index) / (items.length - 1));
    const y = padding + chartHeight - (Math.max(value, 0) / maxValue) * chartHeight;
    return [x, y];
  }

  function drawLine(values, color) {
    ctx.strokeStyle = color;
    ctx.lineWidth = 2;
    ctx.beginPath();
    values.forEach((value, index) => {
      const [x, y] = point(index, value);
      if (index === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    });
    ctx.stroke();
  }

  drawLine(latencyValues, "#2563eb");
  drawLine(p95Values, "#dc2626");

  ctx.fillStyle = "#334155";
  ctx.font = "12px Microsoft YaHei, Arial";
  ctx.fillText(`平均延迟`, padding, 18);
  ctx.fillStyle = "#2563eb";
  ctx.fillRect(padding + 58, 10, 16, 4);
  ctx.fillStyle = "#334155";
  ctx.fillText(`P95`, padding + 90, 18);
  ctx.fillStyle = "#dc2626";
  ctx.fillRect(padding + 120, 10, 16, 4);
  ctx.fillStyle = "#64748b";
  ctx.fillText(`${Math.round(maxValue)} ms`, padding, padding + 4);
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

async function refresh() {
  const [statusRes, transcriptRes, keywordRes, metricsRes, historyRes, failedRes] = await Promise.all([
    fetch("/api/status"),
    fetch("/api/transcripts?limit=30"),
    fetch("/api/keywords?limit=30"),
    fetch("/api/metrics"),
    fetch("/api/metrics/history?limit=120"),
    fetch("/api/failed-segments?limit=20"),
  ]);

  const status = await statusRes.json();
  const transcripts = await transcriptRes.json();
  const keywords = await keywordRes.json();
  const metrics = await metricsRes.json();
  const history = await historyRes.json();
  const failures = await failedRes.json();

  transcriptCount.textContent = status.transcript_count || 0;
  keywordCount.textContent = status.keyword_event_count || 0;
  latestLatency.textContent = transcripts[0] ? formatMs(transcripts[0].end_to_end_time_ms) : "-";
  p95Latency.textContent = formatMs(metrics.p95_latency_ms);
  throughput.textContent = `${metrics.throughput_segments_per_second || 0}/s`;
  failedCount.textContent = metrics.failed_segments || 0;

  consumerDot.classList.toggle("ok", Boolean(status.consumer_running));
  consumerText.textContent = status.consumer_running ? "Kafka 已连接" : "等待 Kafka";

  renderTranscripts(transcripts);
  renderKeywords(keywords);
  renderFailures(failures);
  drawMetricsHistory(history);
}

refresh().catch(console.error);
setInterval(() => refresh().catch(console.error), 2000);
