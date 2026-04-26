const transcriptList = document.querySelector("#transcript-list");
const keywordList = document.querySelector("#keyword-list");
const transcriptCount = document.querySelector("#transcript-count");
const keywordCount = document.querySelector("#keyword-count");
const latestLatency = document.querySelector("#latest-latency");
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

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

async function refresh() {
  const [statusRes, transcriptRes, keywordRes] = await Promise.all([
    fetch("/api/status"),
    fetch("/api/transcripts?limit=30"),
    fetch("/api/keywords?limit=30"),
  ]);

  const status = await statusRes.json();
  const transcripts = await transcriptRes.json();
  const keywords = await keywordRes.json();

  transcriptCount.textContent = status.transcript_count || 0;
  keywordCount.textContent = status.keyword_event_count || 0;
  latestLatency.textContent = transcripts[0] ? formatMs(transcripts[0].end_to_end_time_ms) : "-";

  consumerDot.classList.toggle("ok", Boolean(status.consumer_running));
  consumerText.textContent = status.consumer_running ? "Kafka 已连接" : "等待 Kafka";

  renderTranscripts(transcripts);
  renderKeywords(keywords);
}

refresh().catch(console.error);
setInterval(() => refresh().catch(console.error), 2000);

