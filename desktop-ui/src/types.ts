export type AppTab = "workbench" | "monitor" | "results" | "settings";

export type DataSourceState = "backend-connected" | "backend-starting" | "backend-error" | "mock";

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
  reportPath?: string;
  outputs?: string[];
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

export interface WorkbenchLoadResult {
  snapshot: WorkbenchSnapshot;
  dataSource: DataSourceState;
  error?: string;
}

export interface IpcResult<T = unknown> {
  ok: boolean;
  data?: T;
  error?: string;
  logs?: string[];
}

export type LaunchNodeState = "idle" | "running" | "success" | "warning" | "error";

export interface LaunchNode {
  id: string;
  label: string;
  state: LaunchNodeState;
  detail: string;
}

export interface PortCheck {
  port: number;
  label: string;
  occupied: boolean;
  warning: string;
}

export interface EnvironmentCheck {
  projectRoot: string;
  dockerVersion?: string;
  composeVersion?: string;
  dockerDaemon: boolean;
  ports: PortCheck[];
  nodes: LaunchNode[];
}

export interface ComposeContainer {
  name: string;
  service: string;
  state: string;
  status: string;
  publishedPorts?: string;
}

export interface BackendHealth {
  api: "online" | "starting" | "error";
  asr: "online" | "starting" | "error";
  flink: "online" | "starting" | "error";
  dashboard: "online" | "starting" | "error";
  detail: Record<string, unknown>;
}

export type DesktopTaskStatus =
  | "created"
  | "starting"
  | "running"
  | "completed"
  | "needs_review"
  | "failed"
  | "cancelled";

export interface DesktopTask {
  task_id: string;
  name: string;
  source_path: string;
  workspace_path: string;
  stream_id: string;
  run_id: string;
  mode: string;
  model: string;
  status: DesktopTaskStatus;
  progress: number;
  current_stage: string;
  created_at: string;
  started_at?: string;
  finished_at?: string;
  outputs: string[];
  output_dir?: string;
  report_path?: string;
  error?: string;
}

export interface SelectedVideo {
  path: string;
  name: string;
  sizeBytes: number;
  extension: string;
}

export interface TaskStartOptions {
  mode: string;
  model?: string;
  device?: string;
  computeType?: string;
  passes?: number;
  enableRecovery?: boolean;
  profile?: string;
  vadTargetChunkMs?: number;
  vadHardMaxChunkMs?: number;
  vadMaxSilenceMs?: number;
}

export interface PathsInfo {
  projectRoot: string;
  videosDir: string;
  resultsDir: string;
  logsDir: string;
  modelsDir: string;
}

export interface DesktopApi {
  checkEnvironment: () => Promise<IpcResult<EnvironmentCheck>>;
  startServices: (options?: unknown) => Promise<IpcResult<{ compose: ComposeContainer[]; health: BackendHealth }>>;
  stopServices: () => Promise<IpcResult<ComposeContainer[]>>;
  restartServices: () => Promise<IpcResult<{ compose: ComposeContainer[]; health: BackendHealth }>>;
  getComposeStatus: () => Promise<IpcResult<ComposeContainer[]>>;
  getBackendHealth: () => Promise<IpcResult<BackendHealth>>;
  tailComposeLogs: () => Promise<IpcResult<string[]>>;
  clearLogs: () => Promise<IpcResult<string[]>>;
  exportLogs: () => Promise<IpcResult<string>>;
  getLogs: () => Promise<IpcResult<string[]>>;
  openProjectFolder: () => Promise<IpcResult<string>>;
  openResultsFolder: () => Promise<IpcResult<string>>;
  openVideosFolder: () => Promise<IpcResult<string>>;
  openOutputFolder: (folderPath: string) => Promise<IpcResult<string>>;
  selectOutputFolder: () => Promise<IpcResult<string | null>>;
  openTaskOutputFolder: (taskId: string) => Promise<IpcResult<string>>;
  selectVideoFile: () => Promise<IpcResult<SelectedVideo | null>>;
  copyVideoToWorkspace: (sourcePath: string) => Promise<IpcResult<SelectedVideo>>;
  createTask: (payload: { sourcePath: string; copyToWorkspace: boolean; mode: string; model?: string; outputDir?: string }) => Promise<IpcResult<DesktopTask>>;
  startTask: (taskId: string, options?: TaskStartOptions) => Promise<IpcResult<DesktopTask>>;
  cancelTask: (taskId: string) => Promise<IpcResult<DesktopTask | null>>;
  getTasks: () => Promise<IpcResult<DesktopTask[]>>;
  saveEditedSubtitles: (payload: { taskId: string; segments: Array<{ start: number; end: number; text: string }> }) => Promise<IpcResult<{ srtPath: string; vttPath: string; txtPath: string }>>;
  exportTaskZip: (taskId: string) => Promise<IpcResult<string>>;
  openExternalUrl: (url: string) => Promise<IpcResult<void>>;
  getAppVersion: () => Promise<IpcResult<string>>;
  getPaths: () => Promise<IpcResult<PathsInfo>>;
  onLogLine: (callback: (line: string) => void) => () => void;
  onTaskUpdate: (callback: (task: DesktopTask) => void) => () => void;
}
