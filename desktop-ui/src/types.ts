export type AppTab = "workbench" | "monitor" | "results" | "settings";

export type ServiceName = "Kafka" | "Flink" | "ASR" | "Redis" | "API";

export type ServiceState = "online" | "busy" | "warning" | "offline";

export type StepState = "waiting" | "running" | "done" | "failed";

export type TaskState = "running" | "queued" | "done" | "review" | "failed";

export interface ServiceStatus {
  name: ServiceName;
  state: ServiceState;
  headline: string;
  metrics: Record<string, string | number | boolean>;
  latencyMs?: number;
}

export interface TaskItem {
  id: string;
  title: string;
  source: string;
  status: TaskState;
  progress: number;
  elapsed: string;
  duration: string;
  mode: "快速演示" | "标准质量" | "高质量";
  thumbnailTone: "teal" | "amber" | "steel";
}

export interface PipelineStep {
  id: string;
  label: string;
  state: StepState;
  detail: string;
}

export interface TimelineRange {
  id: string;
  start: number;
  end: number;
}

export interface SubtitleSegment extends TimelineRange {
  text: string;
  status: "ok" | "recovered" | "warning";
  processingMs: number;
  keywords: string[];
}

export interface GapSegment extends TimelineRange {
  kind: "recovery" | "gap";
  label: string;
}

export interface TimelineData {
  durationSeconds: number;
  voiceRanges: TimelineRange[];
  subtitleSegments: SubtitleSegment[];
  gapSegments: GapSegment[];
}

export interface QualityMetric {
  key: string;
  label: string;
  value: string;
  state: "pass" | "review" | "fail";
  hint: string;
}

export interface QualityReport {
  mediaDuration: string;
  elapsed: string;
  metrics: QualityMetric[];
  hotwords: string[];
}

export interface ExportFile {
  type: "SRT" | "VTT" | "TXT" | "JSON" | "REPORT";
  fileName: string;
  path: string;
  size: string;
  status: "ready" | "draft";
}

export interface LogLine {
  id: string;
  time: string;
  level: "INFO" | "WARN" | "OK" | "ERR";
  source: string;
  message: string;
}

export interface WorkbenchSnapshot {
  services: ServiceStatus[];
  tasks: TaskItem[];
  pipeline: PipelineStep[];
  timeline: TimelineData;
  quality: QualityReport;
  exports: ExportFile[];
  logs: LogLine[];
}
