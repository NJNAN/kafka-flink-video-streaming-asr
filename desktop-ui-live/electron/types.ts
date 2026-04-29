export interface IpcResult<T = unknown> {
  ok: boolean;
  data?: T;
  error?: string;
  logs?: string[];
}

export interface HealthState {
  api: boolean;
  asr: boolean;
  flink: boolean;
  liveIngest: boolean;
}
