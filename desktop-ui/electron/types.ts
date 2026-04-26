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
