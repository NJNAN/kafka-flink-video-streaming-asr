import { useState } from "react";
import type { SelectedVideo, TaskItem } from "../types";

interface VideoPreviewPanelProps {
  selectedTask: TaskItem;
  selectedVideo: SelectedVideo | null;
  desktopAvailable: boolean;
  onSelectVideo: () => void;
  onStartVideoTask: (mode: TaskItem["mode"], copyToWorkspace: boolean) => void;
  onOpenVideosFolder: () => void;
}

const modes = [
  {
    name: "快速演示",
    model: "small / base",
    speed: "约 0.20x",
    quality: "可快速看链路",
    gpu: "低占用"
  },
  {
    name: "标准质量",
    model: "medium",
    speed: "约 0.35x",
    quality: "速度质量均衡",
    gpu: "中占用"
  },
  {
    name: "高质量",
    model: "large-v3",
    speed: "约 0.47x",
    quality: "答辩推荐",
    gpu: "高占用"
  }
];

const advancedSettings = [
  ["ASR_MODEL", "large-v3"],
  ["ASR_DEVICE", "cuda"],
  ["ASR_COMPUTE_TYPE", "float16"],
  ["INGEST_VAD_TARGET_CHUNK_MS", "3000"],
  ["INGEST_VAD_HARD_MAX_CHUNK_MS", "4500"],
  ["INGEST_VAD_MAX_SILENCE_MS", "1400"],
  ["ASR_BEAM_SIZE", "5"],
  ["字幕最大字符数", "110"],
  ["启用补漏", "true"]
];

function formatBytes(bytes: number) {
  if (!bytes) {
    return "-";
  }
  const units = ["B", "KB", "MB", "GB"];
  let value = bytes;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }
  return `${value.toFixed(unit === 0 ? 0 : 1)} ${units[unit]}`;
}

export function VideoPreviewPanel({
  selectedTask,
  selectedVideo,
  desktopAvailable,
  onSelectVideo,
  onStartVideoTask,
  onOpenVideosFolder
}: VideoPreviewPanelProps) {
  const [selectedMode, setSelectedMode] = useState(selectedTask.mode);
  const [advancedOpen, setAdvancedOpen] = useState(false);
  const [copyToWorkspace, setCopyToWorkspace] = useState(true);

  return (
    <section className="video-workbench">
      <div className="video-screen">
        <div className="screen-reflection" />
        <div className="screen-content">
          <span className="video-tag">STREAM PREVIEW</span>
          <h2>{selectedTask.title}</h2>
          <p>{selectedTask.source}</p>
          <div className="video-timebar">
            <span style={{ width: `${selectedTask.progress}%` }} />
          </div>
        </div>
      </div>

      <div className="input-board">
        <label className="rtsp-input">
          <span>RTSP / HTTP 地址</span>
          <input value="rtsp://camera-01.local:554/stream1" readOnly />
        </label>

        <div className="drop-slot" role="button" tabIndex={0} onClick={onSelectVideo} onKeyDown={(event) => event.key === "Enter" && onSelectVideo()}>
          <span className="paper-stack" />
          <strong>{selectedVideo ? selectedVideo.name : "选择 / 拖入视频"}</strong>
          <small>
            {selectedVideo
              ? `${selectedVideo.extension} · ${formatBytes(selectedVideo.sizeBytes)} · ${selectedVideo.path}`
              : "支持 mp4 / mkv / mov / avi，也可使用真实 RTSP/HTTP 视频流"}
          </small>
        </div>
      </div>

      <div className="mode-rack">
        {modes.map((mode) => (
          <button
            className={`mode-card ${selectedMode === mode.name ? "is-active" : ""}`}
            type="button"
            key={mode.name}
            onClick={() => setSelectedMode(mode.name as TaskItem["mode"])}
          >
            <strong>{mode.name}</strong>
            <span>{mode.model}</span>
            <dl>
              <div>
                <dt>速度</dt>
                <dd>{mode.speed}</dd>
              </div>
              <div>
                <dt>质量</dt>
                <dd>{mode.quality}</dd>
              </div>
              <div>
                <dt>GPU</dt>
                <dd>{mode.gpu}</dd>
              </div>
            </dl>
          </button>
        ))}
      </div>

      <div className="start-strip">
        <button className="skeuo-button" type="button" disabled={!desktopAvailable} onClick={onSelectVideo}>选择视频</button>
        <button className="skeuo-button primary" type="button" disabled={!desktopAvailable} onClick={() => onStartVideoTask(selectedMode, copyToWorkspace)}>
          创建并启动任务
        </button>
        <button className="skeuo-button" type="button" onClick={() => setAdvancedOpen((value) => !value)}>
          {advancedOpen ? "收起高级设置" : "展开高级设置"}
        </button>
        <button className="skeuo-button" type="button" disabled={!desktopAvailable} onClick={onOpenVideosFolder}>打开 videos</button>
        <label className="copy-toggle">
          <input type="checkbox" checked={copyToWorkspace} onChange={(event) => setCopyToWorkspace(event.target.checked)} />
          <span>复制到 videos 目录</span>
        </label>
      </div>

      {advancedOpen && (
        <div className="advanced-panel">
          {advancedSettings.map(([key, value]) => (
            <label key={key}>
              <span>
                {key}
                <em title="后续接入 FastAPI 后可从环境变量或任务配置读取">?</em>
              </span>
              <input value={value} readOnly />
            </label>
          ))}
        </div>
      )}
    </section>
  );
}
