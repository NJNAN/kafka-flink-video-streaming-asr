import { spawn, type ChildProcessWithoutNullStreams } from "node:child_process";
import { createRequire } from "node:module";
import { existsSync } from "node:fs";
import { copyFile, mkdir, readFile, readdir, rename, stat, writeFile } from "node:fs/promises";
import net from "node:net";
import path from "node:path";
import { fileURLToPath } from "node:url";
import type {
  BackendHealth,
  ComposeContainer,
  DesktopTask,
  EnvironmentCheck,
  IpcResult,
  LaunchNode,
  PathsInfo,
  SelectedVideo,
  TaskStartOptions
} from "./types.js";

const require = createRequire(import.meta.url);
const electron = require("electron") as typeof import("electron");
const { app, BrowserWindow, Menu, dialog, ipcMain, shell } = electron;
const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

let mainWindow: Electron.BrowserWindow | null = null;
let projectRoot = "";
let logsDir = "";
let logBuffer: string[] = [];
const activeTaskProcesses = new Map<string, ChildProcessWithoutNullStreams>();

const REQUIRED_PORTS = [
  { port: 8000, label: "API / Dashboard" },
  { port: 8001, label: "ASR" },
  { port: 8081, label: "Flink Web UI" },
  { port: 5173, label: "Vite dev server" },
  { port: 6379, label: "Redis" },
  { port: 9092, label: "Kafka internal" },
  { port: 29092, label: "Kafka external" }
];

const LAUNCH_NODES: LaunchNode[] = [
  { id: "environment", label: "环境检查", state: "idle", detail: "等待检查" },
  { id: "docker", label: "Docker Desktop", state: "idle", detail: "等待检查" },
  { id: "build", label: "镜像构建", state: "idle", detail: "等待启动" },
  { id: "kafka", label: "Kafka/Zookeeper", state: "idle", detail: "等待容器" },
  { id: "redis", label: "Redis", state: "idle", detail: "等待容器" },
  { id: "flink-jm", label: "Flink JobManager", state: "idle", detail: "等待容器" },
  { id: "flink-tm", label: "Flink TaskManager", state: "idle", detail: "等待容器" },
  { id: "asr", label: "ASR 服务", state: "idle", detail: "等待健康检查" },
  { id: "api", label: "API 服务", state: "idle", detail: "等待健康检查" },
  { id: "desktop", label: "Desktop UI", state: "success", detail: "Electron 已启动" },
  { id: "ready", label: "工作台就绪", state: "idle", detail: "等待后端就绪" }
];

function nowStamp() {
  const now = new Date();
  return now.toLocaleString("zh-CN", { hour12: false });
}

function appendLog(source: string, message: string, level: "INFO" | "OK" | "WARN" | "ERR" = "INFO") {
  const lines = String(message)
    .split(/\r?\n/)
    .map((line) => line.trimEnd())
    .filter(Boolean);

  for (const line of lines) {
    const entry = `[${nowStamp()}] [${level}] [${source}] ${line}`;
    logBuffer.push(entry);
    if (logBuffer.length > 1000) {
      logBuffer = logBuffer.slice(-1000);
    }
    mainWindow?.webContents.send("streamsense:log-line", entry);
  }
}

function toErrorMessage(error: unknown) {
  return error instanceof Error ? error.message : String(error);
}

async function ensureWorkspaceDirs() {
  const paths = getPathsInfo();
  await Promise.all([
    mkdir(paths.videosDir, { recursive: true }),
    mkdir(paths.resultsDir, { recursive: true }),
    mkdir(path.join(paths.resultsDir, "tasks"), { recursive: true }),
    mkdir(paths.logsDir, { recursive: true }),
    mkdir(paths.modelsDir, { recursive: true })
  ]);
}

function walkUpForCompose(startPath: string) {
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

  throw new Error("找不到 docker-compose.yml。请从 StreamSense 仓库内启动，或设置 STREAMSENSE_PROJECT_ROOT。");
}

function getPathsInfo(): PathsInfo {
  return {
    projectRoot,
    videosDir: path.join(projectRoot, "videos"),
    resultsDir: path.join(projectRoot, "data", "results"),
    logsDir: path.join(projectRoot, "logs"),
    modelsDir: path.join(projectRoot, "models")
  };
}

function runCommand(command: string, args: string[], options: { cwd?: string; env?: NodeJS.ProcessEnv; source?: string } = {}) {
  const cwd = options.cwd ?? projectRoot;
  const source = options.source ?? command;
  appendLog(source, `> ${command} ${args.join(" ")}`, "INFO");

  return new Promise<{ code: number; stdout: string; stderr: string; logs: string[] }>((resolve, reject) => {
    const child = spawn(command, args, {
      cwd,
      env: { ...process.env, ...options.env },
      windowsHide: true
    });
    let stdout = "";
    let stderr = "";
    const commandLogs: string[] = [];

    child.stdout.on("data", (chunk: Buffer) => {
      const text = chunk.toString("utf8");
      stdout += text;
      commandLogs.push(text);
      appendLog(source, text, "INFO");
    });

    child.stderr.on("data", (chunk: Buffer) => {
      const text = chunk.toString("utf8");
      stderr += text;
      commandLogs.push(text);
      appendLog(source, text, "ERR");
    });

    child.on("error", (error) => reject(error));
    child.on("close", (code) => {
      const exitCode = code ?? 0;
      appendLog(source, `命令退出，code=${exitCode}`, exitCode === 0 ? "OK" : "ERR");
      resolve({ code: exitCode, stdout, stderr, logs: commandLogs });
    });
  });
}

async function runChecked(command: string, args: string[], source?: string) {
  const result = await runCommand(command, args, { source });
  if (result.code !== 0) {
    throw new Error(result.stderr.trim() || `${command} ${args.join(" ")} 执行失败，code=${result.code}`);
  }
  return result;
}

async function isPortOccupied(port: number) {
  return new Promise<boolean>((resolve) => {
    const socket = new net.Socket();
    socket.setTimeout(800);
    socket.once("connect", () => {
      socket.destroy();
      resolve(true);
    });
    socket.once("timeout", () => {
      socket.destroy();
      resolve(false);
    });
    socket.once("error", () => resolve(false));
    socket.connect(port, "127.0.0.1");
  });
}

async function httpProbe(url: string, timeoutMs = 1800): Promise<{ ok: boolean; data?: unknown; error?: string }> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const response = await fetch(url, { signal: controller.signal });
    const contentType = response.headers.get("content-type") ?? "";
    const data = contentType.includes("application/json") ? await response.json() : await response.text();
    return response.ok ? { ok: true, data } : { ok: false, data, error: `HTTP ${response.status}` };
  } catch (error) {
    return { ok: false, error: toErrorMessage(error) };
  } finally {
    clearTimeout(timer);
  }
}

async function checkEnvironment(): Promise<EnvironmentCheck> {
  await ensureWorkspaceDirs();
  const nodes = LAUNCH_NODES.map((node) => ({ ...node }));
  nodes[0].state = "running";
  nodes[0].detail = "检查 Docker、Compose、端口和项目路径";

  let dockerVersion = "";
  let composeVersion = "";
  let dockerDaemon = false;

  try {
    const docker = await runChecked("docker", ["--version"], "env");
    dockerVersion = docker.stdout.trim();
    nodes[0].state = "success";
    nodes[0].detail = "Docker CLI 可用";
  } catch (error) {
    nodes[0].state = "error";
    nodes[0].detail = "Docker 未安装或不可用";
    appendLog("env", `Docker 检查失败：${toErrorMessage(error)}`, "ERR");
  }

  try {
    const compose = await runChecked("docker", ["compose", "version"], "env");
    composeVersion = compose.stdout.trim();
  } catch (error) {
    appendLog("env", `docker compose 检查失败：${toErrorMessage(error)}`, "ERR");
  }

  nodes[1].state = "running";
  nodes[1].detail = "连接 Docker daemon";
  try {
    await runChecked("docker", ["info"], "env");
    dockerDaemon = true;
    nodes[1].state = "success";
    nodes[1].detail = "Docker Desktop 已连接";
  } catch (error) {
    nodes[1].state = "error";
    nodes[1].detail = "请先启动 Docker Desktop";
    appendLog("env", `Docker daemon 不可连接：${toErrorMessage(error)}`, "ERR");
  }

  const ports = await Promise.all(
    REQUIRED_PORTS.map(async (item) => {
      const occupied = await isPortOccupied(item.port);
      return {
        ...item,
        occupied,
        warning: occupied ? `${item.label} 端口 ${item.port} 已被占用，可能是 StreamSense 服务已在运行，也可能是其他程序占用。` : ""
      };
    })
  );

  const hardConflicts = ports.filter((item) => item.occupied && item.port !== 5173);
  if (hardConflicts.length > 0 && nodes[0].state !== "error") {
    nodes[0].state = "warning";
    nodes[0].detail = `发现 ${hardConflicts.length} 个服务端口已被占用`;
  }

  return {
    projectRoot,
    dockerVersion,
    composeVersion,
    dockerDaemon,
    ports,
    nodes
  };
}

function parseComposeText(text: string): ComposeContainer[] {
  return text
    .split(/\r?\n/)
    .slice(1)
    .map((line) => line.trim())
    .filter(Boolean)
    .map((line) => {
      const chunks = line.split(/\s{2,}/);
      return {
        name: chunks[0] ?? line,
        service: chunks[1] ?? "",
        state: chunks[2] ?? "",
        status: chunks.slice(3).join(" "),
        publishedPorts: ""
      };
    });
}

const STARTUP_LONG_RUNNING_SERVICES = new Set([
  "zookeeper",
  "kafka",
  "redis",
  "asr",
  "flink-jobmanager",
  "flink-taskmanager",
  "api"
]);

function composeServiceKey(container: ComposeContainer) {
  return (container.service || container.name).trim().toLowerCase();
}

function composeStatusText(container: ComposeContainer) {
  return `${container.state} ${container.status}`.trim().toLowerCase();
}

function isComposeServiceUp(container: ComposeContainer) {
  const text = composeStatusText(container);
  return text.startsWith("up") || text.includes("running");
}

function isComposeOneShotSuccessful(container: ComposeContainer) {
  const text = composeStatusText(container);
  return text.startsWith("exited (0)") || text.includes("exited (0)");
}

function getComposeStartupIssues(compose: ComposeContainer[]) {
  const byService = new Map(compose.map((item) => [composeServiceKey(item), item]));
  const issues: string[] = [];

  for (const service of STARTUP_LONG_RUNNING_SERVICES) {
    const container = byService.get(service);
    if (!container) {
      issues.push(`${service} 未出现在 docker compose ps`);
      continue;
    }

    const statusText = composeStatusText(container);
    if (statusText.includes("exited (") || statusText.includes("dead") || statusText.includes("error")) {
      issues.push(`${service}=${container.status || container.state || "unknown"}`);
      continue;
    }

    if (!isComposeServiceUp(container)) {
      issues.push(`${service}=${container.status || container.state || "unknown"}`);
    }
  }

  const topicInit = byService.get("topic-init");
  if (!topicInit) {
    issues.push("topic-init 未出现在 docker compose ps");
  } else if (!isComposeOneShotSuccessful(topicInit)) {
    issues.push(`topic-init=${topicInit.status || topicInit.state || "unknown"}`);
  }

  return issues;
}

async function delay(ms: number) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function waitForComposeStartup(maxAttempts = 15, intervalMs = 2000) {
  let compose = await getComposeStatus();
  let issues = getComposeStartupIssues(compose);

  for (let attempt = 0; attempt < maxAttempts && issues.length > 0; attempt += 1) {
    const hasHardFailure = issues.some((issue) => /exited \((?!0)\d+\)|dead|error/i.test(issue));
    if (hasHardFailure) {
      return { compose, issues, hasHardFailure: true };
    }

    if (attempt < maxAttempts - 1) {
      await delay(intervalMs);
      compose = await getComposeStatus();
      issues = getComposeStartupIssues(compose);
    }
  }

  return { compose, issues, hasHardFailure: false };
}

async function getComposeStatus(): Promise<ComposeContainer[]> {
  try {
    const result = await runChecked("docker", ["compose", "ps", "--format", "json"], "compose");
    const text = result.stdout.trim();
    if (!text) {
      return [];
    }
    const parsed = JSON.parse(text);
    const items = Array.isArray(parsed) ? parsed : [parsed];
    return items.map((item: Record<string, unknown>) => ({
      name: String(item.Name ?? item.name ?? ""),
      service: String(item.Service ?? item.service ?? ""),
      state: String(item.State ?? item.state ?? ""),
      status: String(item.Status ?? item.status ?? ""),
      publishedPorts: String(item.Publishers ?? item.Ports ?? "")
    }));
  } catch (error) {
    appendLog("compose", `JSON 状态不可用，回退到文本解析：${toErrorMessage(error)}`, "WARN");
    const result = await runChecked("docker", ["compose", "ps"], "compose");
    return parseComposeText(result.stdout);
  }
}

async function getBackendHealth(): Promise<BackendHealth> {
  const [api, asr, flink, dashboard] = await Promise.all([
    httpProbe("http://localhost:8000/health"),
    httpProbe("http://localhost:8001/health"),
    httpProbe("http://localhost:8081"),
    httpProbe("http://localhost:8000")
  ]);

  return {
    api: api.ok ? "online" : "starting",
    asr: asr.ok ? "online" : "starting",
    flink: flink.ok ? "online" : "starting",
    dashboard: dashboard.ok ? "online" : "starting",
    detail: {
      api: api.data ?? api.error,
      asr: asr.data ?? asr.error,
      flink: flink.ok ? "Flink Web UI reachable" : flink.error,
      dashboard: dashboard.ok ? "API root reachable" : dashboard.error
    }
  };
}

async function startServices(options?: unknown) {
  appendLog("launcher", "开始启动 Docker Compose 服务", "INFO");
  await checkEnvironment();
  await runChecked("docker", ["compose", "up", "-d", "--build"], "compose");
  let composeState = await waitForComposeStartup();

  if (composeState.issues.length > 0) {
    appendLog("launcher", `关键服务未就绪，执行 clean restart：${composeState.issues.join("；")}`, "WARN");
    await runChecked("docker", ["compose", "down", "--remove-orphans"], "compose");
    await runChecked("docker", ["compose", "up", "-d", "--build"], "compose");
    composeState = await waitForComposeStartup();
  }

  if (composeState.issues.length > 0) {
    appendLog("launcher", `启动后仍有未就绪服务：${composeState.issues.join("；")}`, "WARN");
  }

  const health = await getBackendHealth();
  return { compose: composeState.compose, health, options };
}

async function stopServices() {
  appendLog("launcher", "停止 Docker Compose 服务", "WARN");
  await runChecked("docker", ["compose", "down"], "compose");
  return getComposeStatus();
}

async function restartServices() {
  appendLog("launcher", "重启 Docker Compose 服务", "WARN");
  await runCommand("docker", ["compose", "down"], { source: "compose" });
  return startServices();
}

async function tailComposeLogs() {
  const result = await runChecked("docker", ["compose", "logs", "--tail=300"], "compose-log");
  return result.stdout.split(/\r?\n/).filter(Boolean).slice(-300);
}

function tasksFile() {
  return path.join(getPathsInfo().resultsDir, "tasks.json");
}

async function readTasks(): Promise<DesktopTask[]> {
  try {
    const text = await readFile(tasksFile(), "utf8");
    const data = JSON.parse(text);
    return Array.isArray(data) ? data : [];
  } catch {
    return [];
  }
}

async function writeTasks(tasks: DesktopTask[]) {
  await mkdir(path.dirname(tasksFile()), { recursive: true });
  await writeFile(tasksFile(), JSON.stringify(tasks, null, 2), "utf8");
}

async function updateTask(task: DesktopTask) {
  const tasks = await readTasks();
  const index = tasks.findIndex((item) => item.task_id === task.task_id);
  if (index >= 0) {
    tasks[index] = task;
  } else {
    tasks.unshift(task);
  }
  await writeTasks(tasks);
  mainWindow?.webContents.send("streamsense:task-update", task);
}

function taskOutputDir(taskId: string, outputDir?: string) {
  return outputDir || path.join(getPathsInfo().resultsDir, "tasks", taskId);
}

async function listTaskOutputs(taskId: string, outputDir?: string) {
  const dir = taskOutputDir(taskId, outputDir);
  try {
    const entries = await readdir(dir);
    return entries.map((entry) => path.join(dir, entry));
  } catch {
    return [];
  }
}

async function copyVideoToWorkspace(sourcePath: string): Promise<SelectedVideo> {
  if (!sourcePath || !existsSync(sourcePath)) {
    throw new Error("视频文件不存在，无法复制。");
  }

  const videosDir = getPathsInfo().videosDir;
  await mkdir(videosDir, { recursive: true });
  const parsed = path.parse(sourcePath);
  const stamp = new Date().toISOString().replace(/[-:T.Z]/g, "").slice(0, 14);
  const target = path.join(videosDir, `${parsed.name}_${stamp}${parsed.ext.toLowerCase()}`);
  await copyFile(sourcePath, target);
  const info = await stat(target);
  appendLog("video", `已复制视频到 ${target}`, "OK");
  return {
    path: target,
    name: path.basename(target),
    sizeBytes: info.size,
    extension: parsed.ext.toLowerCase()
  };
}

function modeToModel(mode: string) {
  if (mode.includes("快速")) {
    return "small";
  }
  if (mode.includes("标准")) {
    return "medium";
  }
  return "large-v3";
}

async function createTask(payload: {
  sourcePath?: string;
  copyToWorkspace?: boolean;
  mode?: string;
  model?: string;
  outputDir?: string;
}): Promise<DesktopTask> {
  const sourcePath = payload.sourcePath ?? "";
  if (!sourcePath || !existsSync(sourcePath)) {
    throw new Error("请先选择一个真实存在的视频文件。");
  }

  const copied = payload.copyToWorkspace === false ? null : await copyVideoToWorkspace(sourcePath);
  const workspacePath = copied?.path ?? sourcePath;
  const now = new Date();
  const stamp = now.toISOString().replace(/[-:T.Z]/g, "").slice(0, 14);
  const taskId = `task_${stamp}_${Math.random().toString(16).slice(2, 8)}`;
  const mode = payload.mode ?? "高质量";
  const outputDir = payload.outputDir?.trim() || taskOutputDir(taskId);
  const task: DesktopTask = {
    task_id: taskId,
    name: path.basename(workspacePath),
    source_path: sourcePath,
    workspace_path: workspacePath,
    stream_id: `stream_${taskId}`,
    run_id: stamp,
    mode,
    model: payload.model ?? modeToModel(mode),
    status: "created",
    progress: 0,
    current_stage: "任务已创建",
    created_at: now.toISOString(),
    outputs: [],
    output_dir: outputDir
  };
  await mkdir(outputDir, { recursive: true });
  await updateTask(task);
  appendLog("task", `任务已创建：${taskId}`, "OK");
  return task;
}

function relativeToProject(filePath: string) {
  const relative = path.relative(projectRoot, filePath);
  return relative.startsWith("..") ? filePath : relative;
}

async function startTask(payload: { taskId: string; options?: TaskStartOptions }) {
  const tasks = await readTasks();
  const task = tasks.find((item) => item.task_id === payload.taskId);
  if (!task) {
    throw new Error(`任务不存在：${payload.taskId}`);
  }
  if (!existsSync(task.workspace_path)) {
    throw new Error(`视频文件不存在：${task.workspace_path}`);
  }
  if (activeTaskProcesses.has(task.task_id)) {
    throw new Error("该任务已经在运行。");
  }

  const options: TaskStartOptions = payload.options ?? { mode: task.mode };
  const model = options.model || task.model || modeToModel(task.mode);
  const outputDir = task.output_dir || taskOutputDir(task.task_id);
  await mkdir(outputDir, { recursive: true });

  task.status = "starting";
  task.progress = 12;
  task.current_stage = "启动字幕生成脚本";
  task.started_at = new Date().toISOString();
  task.model = model;
  await updateTask(task);

  const env: NodeJS.ProcessEnv = {
    ASR_MODEL: model,
    ASR_DEVICE: options.device ?? "cuda",
    ASR_COMPUTE_TYPE: options.computeType ?? "float16",
    INGEST_VAD_TARGET_CHUNK_MS: String(options.vadTargetChunkMs ?? 3000),
    INGEST_VAD_HARD_MAX_CHUNK_MS: String(options.vadHardMaxChunkMs ?? 4500),
    INGEST_VAD_MAX_SILENCE_MS: String(options.vadMaxSilenceMs ?? 1400)
  };
  const args = [
    "tools/generate_video_subtitles.py",
    "--media-path",
    relativeToProject(task.workspace_path),
    "--output-dir",
    outputDir,
    "--basename",
    task.task_id,
    "--passes",
    String(options.passes ?? 1)
  ];
  if (options.profile) {
    args.push("--profile", options.profile);
    args.push("--use-static-hints");
  }
  if (options.enableRecovery === false) {
    args.push("--no-recover-gaps");
  }

  appendLog("task", `启动任务 ${task.task_id}，模型 ${model}`, "INFO");
  const child = spawn("python", args, {
    cwd: projectRoot,
    env: { ...process.env, ...env },
    windowsHide: true
  });
  activeTaskProcesses.set(task.task_id, child);

  const markRunning = async (message: string) => {
    task.status = "running";
    task.progress = Math.max(task.progress, 35);
    task.current_stage = message || "字幕生成中";
    await updateTask(task);
  };

  child.stdout.on("data", (chunk: Buffer) => {
    const text = chunk.toString("utf8");
    appendLog(`task:${task.task_id}`, text, "INFO");
    void markRunning("字幕生成中");
  });

  child.stderr.on("data", (chunk: Buffer) => {
    const text = chunk.toString("utf8");
    appendLog(`task:${task.task_id}`, text, "ERR");
    void markRunning("字幕生成中（有警告）");
  });

  child.on("error", async (error) => {
    activeTaskProcesses.delete(task.task_id);
    task.status = "failed";
    task.error = toErrorMessage(error);
    task.current_stage = "任务脚本启动失败";
    task.finished_at = new Date().toISOString();
    await updateTask(task);
  });

  child.on("close", async (code) => {
    activeTaskProcesses.delete(task.task_id);
    task.finished_at = new Date().toISOString();
    task.outputs = await listTaskOutputs(task.task_id, outputDir);
    task.report_path = path.join(outputDir, `${task.task_id}_report.json`);
    if (code === 0) {
      task.progress = 100;
      task.current_stage = "任务完成";
      task.status = "completed";
      try {
        const report = JSON.parse(await readFile(task.report_path, "utf8"));
        if ((report.blocking_uncovered_gaps_after_recovery ?? []).length > 0) {
          task.status = "needs_review";
          task.current_stage = "任务完成，存在需复查缺口";
        }
      } catch (error) {
        task.status = "needs_review";
        task.current_stage = "任务完成，但 report.json 缺失或解析失败";
        task.error = toErrorMessage(error);
      }
      appendLog("task", `任务 ${task.task_id} 完成`, "OK");
    } else {
      task.status = "failed";
      task.current_stage = "任务脚本失败";
      task.error = `python 退出码 ${code}`;
      appendLog("task", `任务 ${task.task_id} 失败，code=${code}`, "ERR");
    }
    await updateTask(task);
  });

  task.status = "running";
  task.progress = 25;
  task.current_stage = "字幕生成中";
  await updateTask(task);
  return task;
}

async function cancelTask(taskId: string) {
  const child = activeTaskProcesses.get(taskId);
  if (child) {
    child.kill();
    activeTaskProcesses.delete(taskId);
  }
  const tasks = await readTasks();
  const task = tasks.find((item) => item.task_id === taskId);
  if (task) {
    task.status = "cancelled";
    task.current_stage = "用户取消";
    task.finished_at = new Date().toISOString();
    await updateTask(task);
  }
  return task ?? null;
}

function formatSrtTime(seconds: number, sep = ",") {
  const value = Math.max(0, seconds);
  const h = Math.floor(value / 3600);
  const m = Math.floor((value % 3600) / 60);
  const s = Math.floor(value % 60);
  const ms = Math.round((value - Math.floor(value)) * 1000);
  return `${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}${sep}${String(ms).padStart(3, "0")}`;
}

async function backupIfNeeded(filePath: string) {
  if (!existsSync(filePath)) {
    return;
  }
  const parsed = path.parse(filePath);
  const backupPath = path.join(parsed.dir, `${parsed.name}.original${parsed.ext}`);
  if (!existsSync(backupPath)) {
    await copyFile(filePath, backupPath);
  }
}

async function saveEditedSubtitles(payload: {
  taskId: string;
  segments: Array<{ start: number; end: number; text: string }>;
}) {
  const dir = taskOutputDir(payload.taskId);
  await mkdir(dir, { recursive: true });
  const srtPath = path.join(dir, `${payload.taskId}.srt`);
  const vttPath = path.join(dir, `${payload.taskId}.vtt`);
  const txtPath = path.join(dir, `${payload.taskId}_subtitle.txt`);
  await backupIfNeeded(srtPath);
  await backupIfNeeded(vttPath);
  await backupIfNeeded(txtPath);

  const srt = payload.segments
    .map((segment, index) => `${index + 1}\n${formatSrtTime(segment.start)} --> ${formatSrtTime(segment.end)}\n${segment.text.trim()}\n`)
    .join("\n");
  const vtt = `WEBVTT\n\n${payload.segments
    .map((segment) => `${formatSrtTime(segment.start, ".")} --> ${formatSrtTime(segment.end, ".")}\n${segment.text.trim()}\n`)
    .join("\n")}`;
  const txt = payload.segments.map((segment) => segment.text.trim()).join("\n");
  await writeFile(srtPath, srt, "utf8");
  await writeFile(vttPath, vtt, "utf8");
  await writeFile(txtPath, txt, "utf8");
  appendLog("subtitle", `已重新导出字幕：${srtPath}`, "OK");
  return { srtPath, vttPath, txtPath };
}

async function exportTaskZip(taskId: string) {
  const dir = taskOutputDir(taskId);
  if (!existsSync(dir)) {
    throw new Error("任务结果目录不存在，无法导出 ZIP。");
  }
  const zipPath = path.join(dir, `${taskId}_exports.zip`);
  const command = `Compress-Archive -LiteralPath '${dir.replace(/'/g, "''")}' -DestinationPath '${zipPath.replace(/'/g, "''")}' -Force`;
  await runChecked("powershell.exe", ["-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", command], "zip");
  return zipPath;
}

async function exportLogs() {
  await mkdir(logsDir, { recursive: true });
  const stamp = new Date().toISOString().replace(/[-:T.Z]/g, "").slice(0, 14);
  const filePath = path.join(logsDir, `streamsense-desktop-${stamp}.log`);
  await writeFile(filePath, logBuffer.join("\n"), "utf8");
  appendLog("log", `日志已导出：${filePath}`, "OK");
  return filePath;
}

async function openPathOrThrow(targetPath: string) {
  if (!existsSync(targetPath)) {
    await mkdir(targetPath, { recursive: true });
  }
  const error = await shell.openPath(targetPath);
  if (error) {
    throw new Error(error);
  }
  return targetPath;
}

async function createWindow() {
  mainWindow = new BrowserWindow({
    width: 900,
    height: 680,
    minWidth: 760,
    minHeight: 560,
    title: "StreamSense Studio",
    backgroundColor: "#18110d",
    autoHideMenuBar: true,
    show: false,
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      nodeIntegration: false,
      contextIsolation: true,
      sandbox: false
    }
  });

  mainWindow.setMenuBarVisibility(false);
  mainWindow.webContents.on("did-fail-load", (_event, errorCode, errorDescription, validatedURL) => {
    appendLog("renderer", `页面加载失败 ${errorCode}: ${errorDescription} (${validatedURL})`, "ERR");
  });
  mainWindow.webContents.on("render-process-gone", (_event, details) => {
    appendLog("renderer", `渲染进程退出：${details.reason}`, "ERR");
  });
  mainWindow.webContents.on("console-message", (_event, level, message) => {
    if (level >= 2) {
      appendLog("renderer", message, "ERR");
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
    const indexPath = path.join(app.getAppPath(), "dist", "index.html");
    appendLog("renderer", `加载本地页面：${indexPath}`, "INFO");
    if (!existsSync(indexPath)) {
      throw new Error(`Electron 页面不存在：${indexPath}`);
    }
    await mainWindow.loadFile(indexPath);
  }
}

function register<TPayload, TData>(channel: string, handler: (payload: TPayload) => Promise<TData> | TData) {
  ipcMain.handle(channel, async (_event, payload: TPayload): Promise<IpcResult<TData>> => {
    try {
      const data = await handler(payload);
      return { ok: true, data, logs: logBuffer.slice(-1000) };
    } catch (error) {
      const message = toErrorMessage(error);
      appendLog("ipc", `${channel} 失败：${message}`, "ERR");
      return { ok: false, error: message, logs: logBuffer.slice(-1000) };
    }
  });
}

function registerIpc() {
  register("streamsense:check-environment", () => checkEnvironment());
  register("streamsense:start-services", (options) => startServices(options));
  register("streamsense:stop-services", () => stopServices());
  register("streamsense:restart-services", () => restartServices());
  register("streamsense:get-compose-status", () => getComposeStatus());
  register("streamsense:get-backend-health", () => getBackendHealth());
  register("streamsense:tail-compose-logs", () => tailComposeLogs());
  register("streamsense:clear-logs", () => {
    logBuffer = [];
    appendLog("log", "日志已清空", "OK");
    return [];
  });
  register("streamsense:export-logs", () => exportLogs());
  register("streamsense:get-logs", () => logBuffer);
  register("streamsense:open-project-folder", () => openPathOrThrow(projectRoot));
  register("streamsense:open-results-folder", () => openPathOrThrow(getPathsInfo().resultsDir));
  register("streamsense:open-videos-folder", () => openPathOrThrow(getPathsInfo().videosDir));
  register("streamsense:open-output-folder", (folderPath: string) => openPathOrThrow(folderPath));
  register("streamsense:select-output-folder", async () => {
    const result = await dialog.showOpenDialog({
      title: "选择字幕输出目录",
      defaultPath: getPathsInfo().resultsDir,
      properties: ["openDirectory", "createDirectory"]
    });
    return result.canceled ? null : result.filePaths[0];
  });
  register("streamsense:open-task-output-folder", (taskId: string) => openPathOrThrow(taskOutputDir(taskId)));
  register("streamsense:select-video-file", async () => {
    const result = await dialog.showOpenDialog({
      title: "选择视频文件",
      properties: ["openFile"],
      filters: [{ name: "Video", extensions: ["mp4", "mkv", "avi", "mov", "flv"] }]
    });
    if (result.canceled || result.filePaths.length === 0) {
      return null;
    }
    const filePath = result.filePaths[0];
    const info = await stat(filePath);
    return {
      path: filePath,
      name: path.basename(filePath),
      sizeBytes: info.size,
      extension: path.extname(filePath).toLowerCase()
    } satisfies SelectedVideo;
  });
  register("streamsense:copy-video-to-workspace", (sourcePath: string) => copyVideoToWorkspace(sourcePath));
  register("streamsense:create-task", (payload) => createTask(payload as Parameters<typeof createTask>[0]));
  register("streamsense:start-task", (payload) => startTask(payload as { taskId: string; options?: TaskStartOptions }));
  register("streamsense:cancel-task", (taskId: string) => cancelTask(taskId));
  register("streamsense:get-tasks", () => readTasks());
  register("streamsense:save-edited-subtitles", (payload) => saveEditedSubtitles(payload as Parameters<typeof saveEditedSubtitles>[0]));
  register("streamsense:export-task-zip", (taskId: string) => exportTaskZip(taskId));
  register("streamsense:open-external-url", (url: string) => {
    if (!/^https?:\/\//i.test(url) && !/^file:\/\//i.test(url)) {
      throw new Error("只允许打开 http、https 或 file URL。");
    }
    return shell.openExternal(url);
  });
  register("streamsense:get-app-version", () => app.getVersion());
  register("streamsense:get-paths", () => getPathsInfo());
}

app.whenReady().then(async () => {
  Menu.setApplicationMenu(null);
  projectRoot = findProjectRoot();
  logsDir = path.join(projectRoot, "logs");
  await ensureWorkspaceDirs();
  appendLog("launcher", `项目根目录：${projectRoot}`, "OK");
  registerIpc();
  await createWindow();
});

app.on("activate", () => {
  if (BrowserWindow.getAllWindows().length === 0) {
    void createWindow();
  }
});

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") {
    app.quit();
  }
});
