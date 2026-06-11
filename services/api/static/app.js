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
const chartMeta = document.querySelector("#chart-meta");
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

function formatClock(ms) {
  if (!ms) return "--:--:--";
  return new Date(ms).toLocaleTimeString("zh-CN", { hour12: false });
}

function numberValue(value) {
  const parsed = Number(value || 0);
  return Number.isFinite(parsed) ? parsed : 0;
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
            <span>ASR ${formatMs(item.asr_inference_time_ms || item.inference_time_ms)} / 总延迟 ${formatMs(item.end_to_end_time_ms)}</span>
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
    if (chartMeta) chartMeta.textContent = "等待采样";
    ctx.fillStyle = "#718096";
    ctx.font = "14px Microsoft YaHei, Arial";
    ctx.fillText("等待指标采样", 28, 42);
    return;
  }

  const rows = [...items].sort((left, right) => numberValue(left.sampled_at_ms) - numberValue(right.sampled_at_ms));
  const padding = 34;
  const chartWidth = width - padding * 2;
  const chartHeight = height - padding * 2;
  const latencyValues = rows.map((item) => numberValue(item.latest_segment_latency_ms || item.average_end_to_end_latency_ms));
  const asrValues = rows.map((item) => numberValue(item.latest_asr_time_ms || item.asr_average_time_ms));
  const countValues = rows.map((item) => numberValue(item.success_segments || item.total_segments));
  const minCount = Math.min(...countValues);
  const maxCount = Math.max(...countValues);
  const countRange = Math.max(1, maxCount - minCount);
  const maxLatency = Math.max(1000, ...latencyValues, ...asrValues);
  const latest = rows[rows.length - 1];
  const latestLatency = latencyValues[latencyValues.length - 1] || 0;
  const latestDelta = numberValue(latest.segments_delta);

  if (chartMeta) {
    chartMeta.textContent = `最新采样 ${formatClock(latest.sampled_at_ms)} / 新增 ${latestDelta} 条 / 最新延迟 ${formatMs(latestLatency)}`;
  }

  ctx.strokeStyle = "#e2e8f0";
  ctx.lineWidth = 1;
  for (let i = 0; i <= 4; i += 1) {
    const y = padding + (chartHeight / 4) * i;
    ctx.beginPath();
    ctx.moveTo(padding, y);
    ctx.lineTo(width - padding, y);
    ctx.stroke();
  }

  function xPoint(index) {
    return padding + (rows.length === 1 ? chartWidth / 2 : (chartWidth * index) / (rows.length - 1));
  }

  function latencyPoint(index, value) {
    const x = xPoint(index);
    const y = padding + chartHeight - (Math.max(value, 0) / maxLatency) * chartHeight;
    return [x, y];
  }

  function countPoint(index, value) {
    const x = xPoint(index);
    const normalized = maxCount === minCount ? 0.5 : (value - minCount) / countRange;
    const y = padding + chartHeight - normalized * chartHeight;
    return [x, y];
  }

  function drawLine(values, color, pointFactory) {
    ctx.strokeStyle = color;
    ctx.lineWidth = 2;
    ctx.beginPath();
    values.forEach((value, index) => {
      const [x, y] = pointFactory(index, value);
      if (index === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    });
    ctx.stroke();

    const [lastX, lastY] = pointFactory(values.length - 1, values[values.length - 1]);
    ctx.fillStyle = color;
    ctx.beginPath();
    ctx.arc(lastX, lastY, 3.5, 0, Math.PI * 2);
    ctx.fill();
  }

  drawLine(latencyValues, "#2563eb", latencyPoint);
  drawLine(asrValues, "#7c3aed", latencyPoint);
  drawLine(countValues, "#16a34a", countPoint);

  ctx.fillStyle = "#334155";
  ctx.font = "12px Microsoft YaHei, Arial";
  ctx.fillText(`最新延迟`, padding, 18);
  ctx.fillStyle = "#2563eb";
  ctx.fillRect(padding + 58, 10, 16, 4);
  ctx.fillStyle = "#334155";
  ctx.fillText(`ASR`, padding + 90, 18);
  ctx.fillStyle = "#7c3aed";
  ctx.fillRect(padding + 116, 10, 16, 4);
  ctx.fillStyle = "#334155";
  ctx.fillText(`字幕数`, padding + 146, 18);
  ctx.fillStyle = "#16a34a";
  ctx.fillRect(padding + 188, 10, 16, 4);

  ctx.fillStyle = "#64748b";
  ctx.fillText(formatMs(maxLatency), padding, padding + 4);
  ctx.fillText("0 ms", padding, height - 12);
  ctx.textAlign = "right";
  ctx.fillText(`${maxCount} 条`, width - padding, padding + 4);
  ctx.fillText(`${minCount} 条`, width - padding, height - 12);
  ctx.fillText(formatClock(rows[0].sampled_at_ms), padding + 82, height - 12);
  ctx.fillText(formatClock(latest.sampled_at_ms), width - padding - 58, height - 12);
  ctx.textAlign = "left";
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
  const latestHistorySample = history[history.length - 1] || {};

  transcriptCount.textContent = status.transcript_count || 0;
  keywordCount.textContent = status.keyword_event_count || 0;
  latestLatency.textContent = formatMs(metrics.latest_segment_latency_ms || (transcripts[0] && transcripts[0].end_to_end_time_ms));
  p95Latency.textContent = formatMs(metrics.p95_latency_ms);
  throughput.textContent = `${latestHistorySample.recent_throughput_segments_per_second || metrics.throughput_segments_per_second || 0}/s`;
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
