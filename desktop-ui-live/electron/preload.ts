import { createRequire } from "node:module";
import type { IpcResult } from "./types.js";

const require = createRequire(import.meta.url);
const electron = require("electron") as typeof import("electron");
const { contextBridge, ipcRenderer } = electron;

const invoke = <T = unknown>(channel: string, payload?: unknown): Promise<IpcResult<T>> => {
  return ipcRenderer.invoke(channel, payload) as Promise<IpcResult<T>>;
};

contextBridge.exposeInMainWorld("streamsenseLive", {
  startServices: () => invoke("live:start-services"),
  stopServices: () => invoke("live:stop-services"),
  health: () => invoke("live:health"),
  getLogs: () => invoke("live:get-logs"),
  openMicrophoneSettings: () => invoke("live:open-microphone-settings"),
  openCameraSettings: () => invoke("live:open-camera-settings"),
  onLogLine: (callback: (line: string) => void) => {
    const listener = (_event: Electron.IpcRendererEvent, line: string) => callback(line);
    ipcRenderer.on("live:log-line", listener);
    return () => ipcRenderer.removeListener("live:log-line", listener);
  }
});
