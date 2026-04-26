import { createRequire } from "node:module";
import type { IpcResult } from "./types.js";

const require = createRequire(import.meta.url);
const electron = require("electron") as typeof import("electron");
const { contextBridge, ipcRenderer } = electron;
const invoke = <T = unknown>(channel: string, payload?: unknown): Promise<IpcResult<T>> => {
  return ipcRenderer.invoke(channel, payload) as Promise<IpcResult<T>>;
};

contextBridge.exposeInMainWorld("streamsense", {
  checkEnvironment: () => invoke("streamsense:check-environment"),
  startServices: (options?: unknown) => invoke("streamsense:start-services", options),
  stopServices: () => invoke("streamsense:stop-services"),
  restartServices: () => invoke("streamsense:restart-services"),
  getComposeStatus: () => invoke("streamsense:get-compose-status"),
  getBackendHealth: () => invoke("streamsense:get-backend-health"),
  tailComposeLogs: () => invoke("streamsense:tail-compose-logs"),
  clearLogs: () => invoke("streamsense:clear-logs"),
  exportLogs: () => invoke("streamsense:export-logs"),
  getLogs: () => invoke("streamsense:get-logs"),
  openProjectFolder: () => invoke("streamsense:open-project-folder"),
  openResultsFolder: () => invoke("streamsense:open-results-folder"),
  openVideosFolder: () => invoke("streamsense:open-videos-folder"),
  openOutputFolder: (folderPath: string) => invoke("streamsense:open-output-folder", folderPath),
  selectOutputFolder: () => invoke("streamsense:select-output-folder"),
  openTaskOutputFolder: (taskId: string) => invoke("streamsense:open-task-output-folder", taskId),
  selectVideoFile: () => invoke("streamsense:select-video-file"),
  copyVideoToWorkspace: (sourcePath: string) => invoke("streamsense:copy-video-to-workspace", sourcePath),
  createTask: (payload: unknown) => invoke("streamsense:create-task", payload),
  startTask: (taskId: string, options?: unknown) => invoke("streamsense:start-task", { taskId, options }),
  cancelTask: (taskId: string) => invoke("streamsense:cancel-task", taskId),
  getTasks: () => invoke("streamsense:get-tasks"),
  saveEditedSubtitles: (payload: unknown) => invoke("streamsense:save-edited-subtitles", payload),
  exportTaskZip: (taskId: string) => invoke("streamsense:export-task-zip", taskId),
  openExternalUrl: (url: string) => invoke("streamsense:open-external-url", url),
  getAppVersion: () => invoke("streamsense:get-app-version"),
  getPaths: () => invoke("streamsense:get-paths"),
  onLogLine: (callback: (line: string) => void) => {
    const listener = (_event: Electron.IpcRendererEvent, line: string) => callback(line);
    ipcRenderer.on("streamsense:log-line", listener);
    return () => ipcRenderer.removeListener("streamsense:log-line", listener);
  },
  onTaskUpdate: (callback: (task: unknown) => void) => {
    const listener = (_event: Electron.IpcRendererEvent, task: unknown) => callback(task);
    ipcRenderer.on("streamsense:task-update", listener);
    return () => ipcRenderer.removeListener("streamsense:task-update", listener);
  }
});
