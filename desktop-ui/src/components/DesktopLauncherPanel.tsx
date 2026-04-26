import type { BackendHealth, ComposeContainer, EnvironmentCheck, LaunchNode } from "../types";

interface DesktopLauncherPanelProps {
  desktopAvailable: boolean;
  environment: EnvironmentCheck | null;
  compose: ComposeContainer[];
  backendHealth: BackendHealth | null;
  logs: string[];
  busy: boolean;
  message: string;
  onCheckEnvironment: () => void;
  onStartServices: () => void;
  onStopServices: () => void;
  onRestartServices: () => void;
  onClearLogs: () => void;
  onCopyLogs: () => void;
  onExportLogs: () => void;
  onOpenProject: () => void;
  onOpenResults: () => void;
  onOpenVideos: () => void;
}

const fallbackNodes: LaunchNode[] = [
  { id: "environment", label: "环境检查", state: "idle", detail: "等待检查" },
  { id: "docker", label: "Docker Desktop", state: "idle", detail: "等待检查" },
  { id: "build", label: "镜像构建", state: "idle", detail: "等待启动" },
  { id: "kafka", label: "Kafka/Zookeeper", state: "idle", detail: "等待容器" },
  { id: "redis", label: "Redis", state: "idle", detail: "等待容器" },
  { id: "flink", label: "Flink", state: "idle", detail: "等待容器" },
  { id: "asr", label: "ASR 服务", state: "idle", detail: "等待健康检查" },
  { id: "api", label: "API 服务", state: "idle", detail: "等待健康检查" },
  { id: "ready", label: "工作台就绪", state: "idle", detail: "等待后端就绪" }
];

function healthText(backendHealth: BackendHealth | null) {
  if (!backendHealth) {
    return "未检查";
  }
  return `API ${backendHealth.api} · ASR ${backendHealth.asr} · Flink ${backendHealth.flink}`;
}

export function DesktopLauncherPanel({
  desktopAvailable,
  environment,
  compose,
  backendHealth,
  logs,
  busy,
  message,
  onCheckEnvironment,
  onStartServices,
  onStopServices,
  onRestartServices,
  onClearLogs,
  onCopyLogs,
  onExportLogs,
  onOpenProject,
  onOpenResults,
  onOpenVideos
}: DesktopLauncherPanelProps) {
  const nodes = environment?.nodes ?? fallbackNodes;
  const portWarnings = environment?.ports.filter((item) => item.occupied && item.warning) ?? [];

  return (
    <section className="launcher-console">
      <div className="launcher-head">
        <div>
          <h2>StreamSense 桌面启动器</h2>
          <p>{desktopAvailable ? "Electron 安全桥接已启用，后端仍由本机 Docker Compose 运行。" : "当前是 Web 模式，桌面服务控制不可用。"}</p>
        </div>
        <div className="launcher-health">
          <span>{healthText(backendHealth)}</span>
          <strong>{environment?.dockerDaemon ? "Docker Ready" : "Docker 未确认"}</strong>
        </div>
      </div>

      <div className="launcher-actions">
        <button className="skeuo-button" type="button" disabled={!desktopAvailable || busy} onClick={onCheckEnvironment}>检查环境</button>
        <button className="skeuo-button primary" type="button" disabled={!desktopAvailable || busy} onClick={onStartServices}>启动 Docker 服务</button>
        <button className="skeuo-button" type="button" disabled={!desktopAvailable || busy} onClick={onRestartServices}>重启服务</button>
        <button className="skeuo-button danger" type="button" disabled={!desktopAvailable || busy} onClick={onStopServices}>停止服务</button>
        <button className="skeuo-button" type="button" disabled={!desktopAvailable} onClick={onOpenProject}>项目目录</button>
        <button className="skeuo-button" type="button" disabled={!desktopAvailable} onClick={onOpenVideos}>视频目录</button>
        <button className="skeuo-button" type="button" disabled={!desktopAvailable} onClick={onOpenResults}>结果目录</button>
      </div>

      {message && <div className="launcher-message">{message}</div>}

      <div className="launch-node-track">
        {nodes.map((node) => (
          <div className={`launch-node launch-${node.state}`} key={node.id}>
            <span>{node.label}</span>
            <strong>{node.state}</strong>
            <small>{node.detail}</small>
          </div>
        ))}
      </div>

      {portWarnings.length > 0 && (
        <div className="port-warning-strip">
          {portWarnings.map((item) => (
            <span key={item.port}>{item.warning}</span>
          ))}
        </div>
      )}

      <div className="compose-strip">
        {compose.length === 0 ? (
          <span>docker compose ps：暂无容器状态</span>
        ) : (
          compose.map((container) => (
            <span key={`${container.name}-${container.service}`}>
              <strong>{container.service || container.name}</strong>
              {container.state || container.status || "unknown"}
            </span>
          ))
        )}
      </div>

      <div className="launcher-log-actions">
        <button type="button" onClick={onClearLogs}>清空日志</button>
        <button type="button" onClick={onCopyLogs}>复制日志</button>
        <button type="button" onClick={onExportLogs}>导出日志</button>
      </div>

      <div className="launcher-lcd">
        {(logs.length ? logs : ["[等待] 启动器日志会显示在这里。"]).slice(-9).map((line, index) => (
          <p className={line.includes("[ERR]") ? "is-error" : line.includes("[WARN]") ? "is-warn" : ""} key={`${line}-${index}`}>
            {line}
          </p>
        ))}
      </div>
    </section>
  );
}
