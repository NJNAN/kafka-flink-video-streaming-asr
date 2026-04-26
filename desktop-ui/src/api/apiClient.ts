import { mockSnapshot } from "../data/mockData";
import type {
  DataSourceState,
  ExportFile,
  LogLine,
  QualityMetric,
  ServiceStatus,
  SubtitleSegment,
  TaskItem,
  TimelineData,
  WorkbenchLoadResult,
  WorkbenchSnapshot
} from "../types";

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? import.meta.env.VITE_STREAMSENSE_API_BASE ?? "http://localhost:8000";
const FORCE_MOCK = import.meta.env.VITE_USE_MOCK === "true";

async function requestJson<T>(path: string, timeoutMs = 1800): Promise<T> {
  const controller = new AbortController();
  const timer = window.setTimeout(() => controller.abort(), timeoutMs);
  try {
    const response = await fetch(`${API_BASE}${path}`, { signal: controller.signal });
    if (!response.ok) {
      throw new Error(`StreamSense API ${path} returned ${response.status}`);
    }
    return (await response.json()) as T;
  } finally {
    window.clearTimeout(timer);
  }
}

async function safeJson<T>(path: string, fallback: T, timeoutMs?: number): Promise<T> {
  try {
    return await requestJson<T>(path, timeoutMs);
  } catch {
    return fallback;
  }
}

function numberFrom(value: unknown, fallback = 0) {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : fallback;
}

function formatClock(seconds: number) {
  const totalSeconds = Math.max(0, Math.floor(seconds));
  const hours = Math.floor(totalSeconds / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const remainingSeconds = totalSeconds % 60;
  if (hours > 0) {
    return `${String(hours).padStart(2, "0")}:${String(minutes).padStart(2, "0")}:${String(remainingSeconds).padStart(2, "0")}`;
  }
  return `${String(minutes).padStart(2, "0")}:${String(remainingSeconds).padStart(2, "0")}`;
}

function parseClockText(value: string) {
  const parts = value.trim().split(":").map((part) => Number(part));
  if (parts.some((part) => !Number.isFinite(part))) {
    return null;
  }
  if (parts.length === 2) {
    return parts[0] * 60 + parts[1];
  }
  if (parts.length === 3) {
    return parts[0] * 3600 + parts[1] * 60 + parts[2];
  }
  return null;
}

function normalizeResultPath(pathValue: string) {
  return pathValue.replace(/\\/g, "/");
}

function resultDirectoryFromPath(pathValue: string) {
  const normalized = normalizeResultPath(pathValue);
  const marker = "data/results/";
  const lower = normalized.toLowerCase();
  const markerIndex = lower.lastIndexOf(marker);
  const relative = markerIndex >= 0 ? normalized.slice(markerIndex + marker.length) : normalized;
  const slashIndex = relative.lastIndexOf("/");
  return slashIndex >= 0 ? relative.slice(0, slashIndex + 1) : "";
}

function siblingJsonPath(pathValue: string, suffix: string) {
  const normalized = normalizeResultPath(pathValue);
  if (/_report\.json$/i.test(normalized)) {
    return normalized.replace(/_report\.json$/i, `_${suffix}.json`);
  }
  if (/report\.json$/i.test(normalized)) {
    return normalized.replace(/report\.json$/i, `${suffix}.json`);
  }
  if (/\.json$/i.test(normalized)) {
    return normalized.replace(/\.json$/i, `_${suffix}.json`);
  }
  return normalized;
}

function durationTextFromReport(report: Record<string, unknown>, fallback = "-") {
  const durationMs = report.duration_ms;
  if (typeof durationMs === "number" && Number.isFinite(durationMs)) {
    return formatClock(durationMs / 1000);
  }

  const durationSeconds = report.media_duration_seconds ?? report.duration_seconds;
  if (typeof durationSeconds === "number" && Number.isFinite(durationSeconds)) {
    return formatClock(durationSeconds);
  }

  const textValue = typeof report.mediaDuration === "string" && report.mediaDuration.trim()
    ? report.mediaDuration.trim()
    : typeof report.duration === "string" && report.duration.trim()
      ? report.duration.trim()
      : "";
  if (textValue) {
    const parsed = parseClockText(textValue);
    return parsed === null ? textValue : formatClock(parsed);
  }

  return fallback;
}

function elapsedTextFromReport(report: Record<string, unknown>, fallback = "-") {
  const elapsedMs = report.elapsed_ms;
  if (typeof elapsedMs === "number" && Number.isFinite(elapsedMs)) {
    return formatClock(elapsedMs / 1000);
  }

  const elapsedSeconds = report.elapsed_seconds;
  if (typeof elapsedSeconds === "number" && Number.isFinite(elapsedSeconds)) {
    return formatClock(elapsedSeconds);
  }

  const textValue = typeof report.elapsed === "string" && report.elapsed.trim() ? report.elapsed.trim() : "";
  if (textValue) {
    const parsed = parseClockText(textValue);
    return parsed === null ? textValue : formatClock(parsed);
  }

  return fallback;
}

function hotwordCountText(report: Record<string, unknown>, fallback = "-") {
  const hotwords = report.hotwords;
  if (Array.isArray(hotwords)) {
    return String(hotwords.length);
  }
  if (typeof hotwords === "number" && Number.isFinite(hotwords)) {
    return String(hotwords);
  }
  if (typeof hotwords === "string" && hotwords.trim()) {
    return hotwords.trim();
  }
  return fallback;
}

function secondsFromRow(row: Record<string, unknown>, msKeys: string[], secondKeys: string[], fallback = 0) {
  for (const key of msKeys) {
    const value = row[key];
    if (typeof value === "number" && Number.isFinite(value)) {
      return value / 1000;
    }
  }
  for (const key of secondKeys) {
    const value = row[key];
    if (typeof value === "number" && Number.isFinite(value)) {
      return value;
    }
  }
  return fallback;
}

function subtitleSegmentsFromFinalSegments(data: unknown): SubtitleSegment[] {
  const rows = Array.isArray(data)
    ? data
    : Array.isArray((data as Record<string, unknown>)?.items)
      ? ((data as Record<string, unknown>).items as unknown[])
      : Array.isArray((data as Record<string, unknown>)?.segments)
        ? ((data as Record<string, unknown>).segments as unknown[])
        : [];

  return rows
    .map((item, index) => {
      const row = item as Record<string, unknown>;
      const start = secondsFromRow(row, ["start_ms", "start_time_ms"], ["start", "start_time"]);
      const end = secondsFromRow(row, ["end_ms", "end_time_ms"], ["end", "end_time"], start);
      const keywords = Array.isArray(row.keywords)
        ? row.keywords
            .map((keyword) => (typeof keyword === "string" ? keyword : String((keyword as Record<string, unknown>).word ?? "")))
            .filter(Boolean)
        : [];
      return {
        id: String(row.segment_id ?? row.id ?? `final-sub-${index}`),
        start,
        end,
        text: String(row.text ?? row.source_text ?? ""),
        status: row.recovered || row.status === "recovered" ? "recovered" : "ok",
        processingMs: numberFrom(row.processing_ms, numberFrom(row.inference_time_ms, 0)),
        keywords
      } satisfies SubtitleSegment;
    })
    .filter((segment) => segment.text || segment.end > segment.start);
}

function durationSecondsFromReport(report: Record<string, unknown>, fallback: number) {
  const durationMs = report.duration_ms;
  if (typeof durationMs === "number" && Number.isFinite(durationMs)) {
    return durationMs / 1000;
  }

  const durationSeconds = report.media_duration_seconds ?? report.duration_seconds;
  if (typeof durationSeconds === "number" && Number.isFinite(durationSeconds)) {
    return durationSeconds;
  }

  const textValue = typeof report.mediaDuration === "string" && report.mediaDuration.trim()
    ? report.mediaDuration.trim()
    : typeof report.duration === "string" && report.duration.trim()
      ? report.duration.trim()
      : "";
  if (textValue) {
    const parsed = parseClockText(textValue);
    if (parsed !== null) {
      return parsed;
    }
  }

  return fallback;
}

function serviceFromStatus(status: Record<string, unknown>): ServiceStatus[] {
  return [
    mockSnapshot.services[0],
    mockSnapshot.services[1],
    mockSnapshot.services[2],
    mockSnapshot.services[3],
    {
      name: "API",
      state: status.consumer_running ? "online" : "warning",
      headline: status.consumer_running ? "consumer running" : "consumer not ready",
      latencyMs: numberFrom(status.last_message_time_ms, 0),
      metrics: {
        consumer_running: Boolean(status.consumer_running),
        transcript_count: numberFrom(status.transcript_count, 0),
        keyword_event_count: numberFrom(status.keyword_event_count, 0),
        last_message_time_ms: numberFrom(status.last_message_time_ms, 0)
      }
    }
  ];
}

function taskFromDesktopLike(item: Record<string, unknown>, index: number): TaskItem {
  const status = String(item.status ?? "running");
  const mappedStatus: TaskItem["status"] =
    status === "completed" ? "done" : status === "failed" ? "failed" : status === "needs_review" ? "review" : status === "created" ? "queued" : "running";
  return {
    id: String(item.task_id ?? item.id ?? `backend-task-${index}`),
    title: String(item.name ?? item.title ?? "StreamSense 任务"),
    source: String(item.workspace_path ?? item.source_path ?? item.source ?? ""),
    status: mappedStatus,
    progress: numberFrom(item.progress, 0),
    elapsed: String(item.elapsed ?? "--:--"),
    duration: String(item.duration ?? "--:--"),
    mode: (String(item.mode ?? "高质量") as TaskItem["mode"]) || "高质量",
    thumbnailTone: index % 3 === 0 ? "teal" : index % 3 === 1 ? "amber" : "steel",
    reportPath: typeof item.report_path === "string" ? item.report_path : undefined,
    outputs: Array.isArray(item.outputs) ? item.outputs.map((output) => String(output)) : undefined
  };
}

function subtitleFromTranscript(item: Record<string, unknown>, index: number): SubtitleSegment {
  const start = numberFrom(item.start_time_ms, numberFrom(item.start, 0)) / (item.start_time_ms ? 1000 : 1);
  const end = numberFrom(item.end_time_ms, numberFrom(item.end, start + 2)) / (item.end_time_ms ? 1000 : 1);
  const keywords = Array.isArray(item.keywords)
    ? item.keywords.map((keyword) => (typeof keyword === "string" ? keyword : String((keyword as Record<string, unknown>).word ?? ""))).filter(Boolean)
    : [];
  return {
    id: String(item.segment_id ?? item.id ?? `live-sub-${index}`),
    start,
    end,
    text: String(item.text ?? item.source_text ?? ""),
    status: item.recovered ? "recovered" : "ok",
    processingMs: numberFrom(item.asr_inference_time_ms, numberFrom(item.inference_time_ms, 0)),
    keywords
  };
}

function exportFilesFromResults(results: unknown): ExportFile[] {
  const rawFiles = Array.isArray(results)
    ? results
    : Array.isArray((results as Record<string, unknown>)?.files)
      ? ((results as Record<string, unknown>).files as unknown[])
      : [];
  if (rawFiles.length === 0) {
    return mockSnapshot.exports;
  }
  return rawFiles.map((item, index) => {
    const file = item as Record<string, unknown>;
    const fileName = String(file.fileName ?? file.name ?? file.path ?? `result-${index}`);
    const upper = fileName.toUpperCase();
    const type = upper.endsWith(".SRT")
      ? "SRT"
      : upper.endsWith(".VTT")
        ? "VTT"
        : upper.endsWith(".TXT")
          ? "TXT"
          : upper.includes("REPORT")
            ? "REPORT"
            : "JSON";
    return {
      type,
      fileName,
      path: String(file.path ?? fileName),
      size: String(file.size ?? file.size_human ?? "-"),
      status: "ready"
    };
  });
}

function qualityFromResults(results: unknown): QualityMetric[] {
  const report = (results as Record<string, unknown>)?.latest_report as Record<string, unknown> | undefined;
  if (!report) {
    return mockSnapshot.quality.metrics;
  }
  const blocking = Array.isArray(report.blocking_uncovered_gaps_after_recovery) ? report.blocking_uncovered_gaps_after_recovery.length : 0;
  const before = Array.isArray(report.uncovered_gaps_before_recovery) ? report.uncovered_gaps_before_recovery.length : 0;
  return [
    { key: "duration", label: "视频时长", value: durationTextFromReport(report), state: "pass", hint: "media duration" },
    { key: "elapsed", label: "处理耗时", value: elapsedTextFromReport(report), state: "pass", hint: "wall clock" },
    {
      key: "speed",
      label: "speed_ratio_elapsed_over_media",
      value: String(report.speed_ratio_elapsed_over_media ?? report.speedRatioElapsedOverMedia ?? "-"),
      state: numberFrom(report.speed_ratio_elapsed_over_media, 9) <= 0.5 ? "pass" : "review",
      hint: "低于 0.50"
    },
    { key: "items", label: "subtitle_items", value: String(report.subtitle_items ?? report.subtitleItems ?? "-"), state: "pass", hint: "句子级字幕" },
    { key: "hotwords", label: "hotwords", value: hotwordCountText(report), state: "pass", hint: "动态热词" },
    {
      key: "before",
      label: "uncovered_gaps_before_recovery",
      value: String(before),
      state: "review",
      hint: "补漏前"
    },
    {
      key: "after",
      label: "blocking_uncovered_gaps_after_recovery",
      value: String(blocking),
      state: blocking === 0 ? "pass" : "fail",
      hint: "补漏后"
    }
  ];
}

function timelineFromReport(base: TimelineData, results: unknown, transcripts: SubtitleSegment[]): TimelineData {
  const report = (results as Record<string, unknown>)?.latest_report as Record<string, unknown> | undefined;
  if (!report) {
    return { ...base, subtitleSegments: transcripts.length ? transcripts : base.subtitleSegments };
  }
  const duration = durationSecondsFromReport(report, base.durationSeconds);
  const rangesFrom = (key: string) => {
    const rows = Array.isArray(report[key]) ? (report[key] as Array<Record<string, unknown>>) : [];
    return rows.map((row, index) => ({
      id: `${key}-${index}`,
      start: secondsFromRow(row, ["start_ms", "start_time_ms"], ["start", "start_time"]),
      end: secondsFromRow(row, ["end_ms", "end_time_ms"], ["end", "end_time"], secondsFromRow(row, ["start_ms", "start_time_ms"], ["start", "start_time"]))
    }));
  };
  const blocking = rangesFrom("blocking_uncovered_gaps_after_recovery").map((item) => ({ ...item, kind: "gap" as const, label: "需复查" }));
  const before = rangesFrom("uncovered_gaps_before_recovery").map((item) => ({ ...item, kind: "recovery" as const, label: "补" }));
  return {
    durationSeconds: duration || base.durationSeconds,
    voiceRanges: rangesFrom("speech_intervals"),
    subtitleSegments: transcripts.length ? transcripts : base.subtitleSegments,
    gapSegments: [...before, ...blocking]
  };
}

export async function fetchWorkbenchSnapshot(selectedReportPath?: string): Promise<WorkbenchLoadResult> {
  if (FORCE_MOCK) {
    await new Promise((resolve) => window.setTimeout(resolve, 180));
    return { snapshot: mockSnapshot, dataSource: "mock" };
  }

  try {
    await requestJson("/health", 3000);
  } catch (error) {
    const message = error instanceof Error && error.name === "AbortError" ? "请求超时或后端服务未启动" : error instanceof Error ? error.message : String(error);
    return { snapshot: mockSnapshot, dataSource: "mock", error: message };
  }

  const [status, transcriptsRaw, keywordsRaw, resultsRaw, logsRaw] = await Promise.all([
    safeJson<Record<string, unknown>>("/api/status", {}),
    safeJson<Array<Record<string, unknown>>>("/api/transcripts?limit=100", []),
    safeJson<Array<Record<string, unknown>>>("/api/keywords?limit=100", []),
    safeJson<unknown>("/api/results", { files: [] }),
    safeJson<Array<Record<string, unknown>>>("/api/logs?limit=300", [])
  ]);

  const transcriptSegments = transcriptsRaw.map(subtitleFromTranscript);
  const hotwords = keywordsRaw
    .flatMap((event) => (Array.isArray(event.keywords) ? event.keywords : []))
    .map((keyword) => (typeof keyword === "string" ? keyword : String((keyword as Record<string, unknown>).word ?? "")))
    .filter(Boolean)
    .slice(0, 30);

  const selectedResultDirectory = selectedReportPath ? resultDirectoryFromPath(selectedReportPath) : "";
  const selectedSegmentsPath = selectedReportPath ? siblingJsonPath(selectedReportPath, "final_segments") : "";
  const [selectedReport, selectedSegments] = await Promise.all([
    selectedReportPath ? safeJson<Record<string, unknown> | null>(`/api/results/report?path=${encodeURIComponent(selectedReportPath)}`, null, 1000) : Promise.resolve(null),
    selectedSegmentsPath ? safeJson<unknown>(`/api/results/report?path=${encodeURIComponent(selectedSegmentsPath)}`, null, 1000) : Promise.resolve(null)
  ]);

  const activeResults: unknown = selectedReport ? { ...(resultsRaw as Record<string, unknown>), latest_report: selectedReport } : resultsRaw;
  const activeTranscriptSegments = selectedSegments ? subtitleSegmentsFromFinalSegments(selectedSegments) : transcriptSegments;
  const activeHotwords = selectedReport && Array.isArray(selectedReport.hotwords) && selectedReport.hotwords.length
    ? selectedReport.hotwords
        .map((hotword) => (typeof hotword === "string" ? hotword : String((hotword as Record<string, unknown>).word ?? "")))
        .filter(Boolean)
    : hotwords.length
      ? [...new Set(hotwords)]
      : mockSnapshot.quality.hotwords;

  const files = Array.isArray((resultsRaw as Record<string, unknown>)?.files) ? ((resultsRaw as Record<string, unknown>)?.files as Array<Record<string, unknown>>) : [];
  const filteredFiles = selectedResultDirectory
    ? files.filter((file) => normalizeResultPath(String(file.path ?? file.name ?? "")).startsWith(selectedResultDirectory))
    : files;

  const logs: LogLine[] = logsRaw.map((item, index) => ({
    id: String(item.id ?? `api-log-${index}`),
    time: String(item.time ?? "--:--:--"),
    level: (String(item.level ?? "INFO") as LogLine["level"]) || "INFO",
    source: String(item.source ?? "API"),
    message: String(item.message ?? "")
  }));

  const snapshot: WorkbenchSnapshot = {
    ...mockSnapshot,
    services: serviceFromStatus(status),
    tasks: Array.isArray((resultsRaw as Record<string, unknown>)?.tasks)
      ? ((resultsRaw as Record<string, unknown>).tasks as Array<Record<string, unknown>>).map(taskFromDesktopLike)
      : mockSnapshot.tasks,
    timeline: timelineFromReport(mockSnapshot.timeline, activeResults, activeTranscriptSegments),
    quality: {
      ...mockSnapshot.quality,
      metrics: qualityFromResults(activeResults),
      hotwords: activeHotwords
    },
    exports: exportFilesFromResults({ ...(resultsRaw as Record<string, unknown>), files: filteredFiles }),
    logs: logs.length ? logs : mockSnapshot.logs
  };

  return { snapshot, dataSource: "backend-connected" };
}
