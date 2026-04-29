import { spawn } from "node:child_process";
import { createRequire } from "node:module";
import { existsSync } from "node:fs";
import { mkdir } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import type { HealthState, IpcResult } from "./types.js";

/*
 * StreamSense Live 的 Electron 主进程。
 *
 * 渲染进程 src/App.tsx 不能直接执行 docker、打开系统设置、读取真实路径。
 * 所以这些“系统级能力”统一放在主进程里，再通过 preload.ts 暴露给页面。
 *
 * 这个文件只服务 desktop-ui-live/ 实时版。
 * 离线字幕生成器的主进程在 desktop-ui/electron/main.ts。
 */

const require = createRequire(import.meta.url);
const electron = require("electron") as typeof import("electron");
const { app, BrowserWindow, Menu, ipcMain, session, shell } = electron;
const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

let mainWindow: Electron.BrowserWindow | null = null;
let projectRoot = "";
let logBuffer: string[] = [];

function nowStamp() {
  return new Date().toLocaleString("zh-CN", { hour12: false });
}

function appendLog(source: string, message: string, level: "INFO" | "OK" | "WARN" | "ERR" = "INFO") {
  // 把 docker compose、健康检查、IPC 错误都收集起来，实时推给界面“运行日志”。
  // Docker Compose 有时会把正常进度写到 stderr，所以看到 ERR 不一定代表失败，
  // 最终要看命令退出 code 是否为 0。
  const lines = String(message)
    .split(/\r?\n/)
    .map((line) => line.trimEnd())
    .filter(Boolean);
  for (const line of lines) {
    const entry = `[${nowStamp()}] [${level}] [${source}] ${line}`;
    logBuffer.push(entry);
    logBuffer = logBuffer.slice(-800);
    mainWindow?.webContents.send("live:log-line", entry);
  }
}

function toErrorMessage(error: unknown) {
  return error instanceof Error ? error.message : String(error);
}

function walkUpForCompose(startPath: string) {
  // 从当前目录向上找 docker-compose.yml。
  // 这样无论是 npm run electron:dev，还是打包后的 exe，
  // 只要能定位到项目根目录，就能启动大数据服务。
  let current = path.resolve(startPath);
  if (!existsSync(current)) {
    current = path.dirname(current);
  }
  for (let index = 0; index < 8; index += 1) {
    const composePath = path.join(current, "docker-compose.yml");
    if (existsSync(composePath)) {
      return current;
    }
    const parent = path.dirname(current);
    if (parent === current) {
      break;
    }
    current = parent;
  }
  return "";
}

function findProjectRoot() {
  const candidates = [
    process.env.STREAMSENSE_PROJECT_ROOT ?? "",
    process.cwd(),
    path.dirname(process.cwd()),
    app.getAppPath(),
    path.dirname(app.getAppPath()),
    path.join(process.resourcesPath ?? "", "project")
  ].filter(Boolean);

  for (const candidate of candidates) {
    const direct = walkUpForCompose(candidate);
    if (direct) {
      return direct;
    }
  }
  throw new Error("找不到 docker-compose.yml。请从仓库内启动，或设置 STREAMSENSE_PROJECT_ROOT。");
}

function composeArgs(command: string[]) {
  // 实时版要同时加载两个 compose 文件：
  //   1. 根目录 docker-compose.yml：Kafka/Flink/ASR/API/Redis
  //   2. desktop-ui-live/docker-compose.live.yml：额外的 live-ingest
  return ["compose", "-f", "docker-compose.yml", "-f", "desktop-ui-live/docker-compose.live.yml", ...command];
}

function runCommand(command: string, args: string[], source = command) {
  // 所有 docker 命令统一走这里。
  // 这里顺便给实时演示设置更快的默认 ASR 配置：
  //   small + int8_float16 + Flink 并行度 2
  // 这样比 large-v3 更适合课堂上的实时字幕演示。
  appendLog(source, `> ${command} ${args.join(" ")}`, "INFO");
  return new Promise<{ code: number; stdout: string; stderr: string }>((resolve, reject) => {
    const child = spawn(command, args, {
      cwd: projectRoot,
      env: {
        ...process.env,
        ASR_MODEL: process.env.STREAMSENSE_LIVE_ASR_MODEL ?? "small",
        ASR_COMPUTE_TYPE: process.env.STREAMSENSE_LIVE_ASR_COMPUTE_TYPE ?? "int8_float16",
        ASR_PRELOAD: "true",
        FLINK_JOB_PARALLELISM: process.env.STREAMSENSE_LIVE_FLINK_PARALLELISM ?? "2",
        LIVE_INGEST_MIN_DBFS: process.env.STREAMSENSE_LIVE_MIN_DBFS ?? "-45"
      },
      windowsHide: true
    });
    let stdout = "";
    let stderr = "";
    child.stdout.on("data", (chunk: Buffer) => {
      const text = chunk.toString("utf8");
      stdout += text;
      appendLog(source, text, "INFO");
    });
    child.stderr.on("data", (chunk: Buffer) => {
      const text = chunk.toString("utf8");
      stderr += text;
      appendLog(source, text, "ERR");
    });
    child.on("error", reject);
    child.on("close", (code) => {
      const exitCode = code ?? 0;
      appendLog(source, `命令退出，code=${exitCode}`, exitCode === 0 ? "OK" : "ERR");
      resolve({ code: exitCode, stdout, stderr });
    });
  });
}

async function runChecked(command: string, args: string[], source = command) {
  const result = await runCommand(command, args, source);
  if (result.code !== 0) {
    throw new Error(result.stderr.trim() || `${command} ${args.join(" ")} 执行失败`);
  }
  return result;
}

async function httpOk(url: string) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 1800);
  try {
    const response = await fetch(url, { signal: controller.signal });
    return response.ok;
  } catch {
    return false;
  } finally {
    clearTimeout(timer);
  }
}

async function health(): Promise<HealthState> {
  // 4/4 在线才表示完整实时链路可用。
  // live-ingest 在线只说明前端能上传音频；
  // Flink/ASR/API 也在线，字幕才会从大数据链路回来。
  const [api, asr, flink, liveIngest] = await Promise.all([
    httpOk("http://localhost:8000/health"),
    httpOk("http://localhost:8001/health"),
    httpOk("http://localhost:8081"),
    httpOk("http://localhost:8010/health")
  ]);
  return { api, asr, flink, liveIngest };
}

async function startServices() {
  // 默认先 --no-build，避免每次点击按钮都访问 Docker Hub。
  // 如果本地没有镜像，才退回 --build。
  await mkdir(path.join(projectRoot, "data", "audio"), { recursive: true });
  await mkdir(path.join(projectRoot, "data", "results"), { recursive: true });
  try {
    await runChecked("docker", composeArgs(["up", "-d", "--no-build"]), "compose-live");
  } catch (error) {
    appendLog("compose-live", `复用本地镜像失败，尝试重新构建：${toErrorMessage(error)}`, "WARN");
    await runChecked("docker", composeArgs(["up", "-d", "--build"]), "compose-live");
  }
  return health();
}

async function stopServices() {
  await runChecked("docker", composeArgs(["down"]), "compose-live");
  return health();
}

function register<TPayload, TData>(channel: string, handler: (payload: TPayload) => Promise<TData> | TData) {
  ipcMain.handle(channel, async (_event, payload: TPayload): Promise<IpcResult<TData>> => {
    try {
      const data = await handler(payload);
      return { ok: true, data, logs: logBuffer.slice(-800) };
    } catch (error) {
      const message = toErrorMessage(error);
      appendLog("ipc", `${channel} 失败：${message}`, "ERR");
      return { ok: false, error: message, logs: logBuffer.slice(-800) };
    }
  });
}

function registerIpc() {
  // 这里定义渲染进程能调用的所有主进程能力。
  // preload.ts 会把它们封装到 window.streamsenseLive。
  register("live:start-services", () => startServices());
  register("live:stop-services", () => stopServices());
  register("live:health", () => health());
  register("live:get-logs", () => logBuffer);
  register("live:open-microphone-settings", () => shell.openExternal("ms-settings:privacy-microphone"));
  register("live:open-camera-settings", () => shell.openExternal("ms-settings:privacy-webcam"));
}

async function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1120,
    height: 760,
    minWidth: 900,
    minHeight: 620,
    title: "StreamSense Live",
    backgroundColor: "#eef5fb",
    autoHideMenuBar: true,
    show: false,
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      nodeIntegration: false,
      contextIsolation: true,
      sandbox: false
    }
  });
  mainWindow.once("ready-to-show", () => mainWindow?.show());
  mainWindow.on("closed", () => {
    mainWindow = null;
  });

  const devServerUrl = process.env.VITE_DEV_SERVER_URL;
  if (devServerUrl) {
    await mainWindow.loadURL(devServerUrl);
  } else {
    await mainWindow.loadFile(path.join(app.getAppPath(), "dist", "index.html"));
  }
}

app.whenReady().then(async () => {
  Menu.setApplicationMenu(null);
  // 直播版必须申请摄像头/麦克风权限。
  // Windows 仍可能在系统隐私设置里拒绝，所以界面里也提供了权限设置跳转按钮。
  session.defaultSession.setPermissionRequestHandler((_webContents, permission, callback) => {
    callback(["media", "camera", "microphone"].includes(permission));
  });
  session.defaultSession.setPermissionCheckHandler((_webContents, permission) => {
    return ["media", "camera", "microphone"].includes(permission);
  });
  projectRoot = findProjectRoot();
  appendLog("launcher", `项目根目录：${projectRoot}`, "OK");
  registerIpc();
  await createWindow();
});

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") {
    app.quit();
  }
});
