import { useEffect, useRef, useState } from "react";

/*
 * StreamSense Live 大数据实时字幕界面。
 *
 * 这个文件属于 desktop-ui-live/，和 desktop-ui/ 的离线字幕生成器分开。
 *
 * 这版的目标不是“处理一个视频文件并导出字幕”，而是：
 *   摄像头/麦克风实时采集
 *   -> 上传到 live-ingest
 *   -> 写入 Kafka
 *   -> Flink 消费并调用 ASR
 *   -> API 汇总结果
 *   -> 当前界面轮询 API 显示字幕
 *
 * 也就是说，用户看到的是一个简单 Win11 风格界面，
 * 但背后仍然保留 Kafka + Flink 的大数据课程设计链路。
 */

type RunState = "idle" | "starting" | "running" | "error";

interface CaptionLine {
  id: string;
  time: string;
  text: string;
}

interface HealthState {
  api?: boolean;
  asr?: boolean;
  flink?: boolean;
  liveIngest?: boolean;
}

const LIVE_INGEST_URL = import.meta.env.VITE_LIVE_INGEST_URL ?? "http://localhost:8010";
const API_URL = import.meta.env.VITE_STREAMSENSE_API_BASE ?? "http://localhost:8000";
const STREAM_ID = "desktop-live";
const DROP_PATTERNS = ["Amara.org", "中文字幕志愿者", "字幕由", "字幕组"];

function formatClockRange(startValue: unknown, endValue: unknown) {
  // 直播演示时，用户更关心“刚才几点几分说的这句话”。
  // 所以优先显示 live-ingest 写进 Kafka 的真实墙钟时间：
  //   wall_start_at_ms -> wall_end_at_ms
  // 如果老数据里没有这些字段，再退回到相对时间。
  const startMs = Number(startValue);
  const endMs = Number(endValue);
  if (Number.isFinite(startMs) && startMs > 0) {
    const start = new Date(startMs).toLocaleTimeString("zh-CN", { hour12: false });
    const end = Number.isFinite(endMs) && endMs > 0 ? new Date(endMs).toLocaleTimeString("zh-CN", { hour12: false }) : start;
    return `${start}-${end}`;
  }
  return formatOffset(startValue);
}

function formatOffset(msValue: unknown) {
  // 老数据或异常数据兜底显示，例如 00:03。
  const ms = Number(msValue);
  if (!Number.isFinite(ms) || ms < 0) {
    return "--:--";
  }
  const totalSeconds = Math.floor(ms / 1000);
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  return `${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}`;
}

function cleanLiveText(value: unknown) {
  // Whisper 在很短、很安静的音频上容易出现字幕组模板幻觉。
  // 这里是前端兜底过滤；更重要的过滤在 live-ingest/app.py 的静音过滤。
  const text = String(value ?? "").trim();
  if (!text) {
    return "";
  }
  const compact = text.replace(/\s+/g, "");
  if (DROP_PATTERNS.some((pattern) => text.includes(pattern) || compact.includes(pattern.replace(/\s+/g, "")))) {
    return "";
  }
  return text;
}

function serviceText(health: HealthState) {
  // 4 个关键服务都在线时，实时链路才完整：
  // Live Ingest -> Kafka/Flink -> ASR -> API。
  const ok = [health.api, health.asr, health.flink, health.liveIngest].filter(Boolean).length;
  return `${ok}/4 在线`;
}

export function App() {
  const [state, setState] = useState<RunState>("idle");
  const [message, setMessage] = useState("等待启动");
  const [health, setHealth] = useState<HealthState>({});
  const [captions, setCaptions] = useState<CaptionLine[]>([]);
  const [logs, setLogs] = useState<string[]>([]);
  const [cameraEnabled, setCameraEnabled] = useState(true);
  const [chunkMs, setChunkMs] = useState(3500);
  const [busy, setBusy] = useState(false);
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const recorderRef = useRef<MediaRecorder | null>(null);
  const runIdRef = useRef("");
  const chunkIndexRef = useRef(0);
  const pollTimerRef = useRef<number | null>(null);
  const liveRunningRef = useRef(false);

  const refreshHealth = async () => {
    // 定时问 Electron 主进程当前服务状态。
    // 主进程会分别探测 API、ASR、Flink Web UI、live-ingest。
    const result = await window.streamsenseLive?.health();
    if (result?.ok && result.data) {
      setHealth(result.data as HealthState);
    }
  };

  const startServices = async () => {
    // 启动大数据实时链路。
    //
    // 这个按钮不是只启动前端，而是让 Electron 主进程执行：
    //   docker compose -f docker-compose.yml -f desktop-ui-live/docker-compose.live.yml up -d --no-build
    //
    // 其中原 docker-compose.yml 提供 Kafka/Flink/ASR/API，
    // docker-compose.live.yml 额外增加 live-ingest。
    if (!window.streamsenseLive) {
      setState("error");
      setMessage("请用 StreamSense Live exe 启动");
      return;
    }
    setBusy(true);
    setMessage("正在启动 Kafka/Flink/ASR/Live Ingest");
    const result = await window.streamsenseLive.startServices();
    setBusy(false);
    if (!result.ok) {
      setState("error");
      setMessage(result.error || "服务启动失败");
      setLogs(result.logs ?? []);
      return;
    }
    setHealth(result.data as HealthState);
    setMessage("服务已启动");
    setState("idle");
  };

  const stopServices = async () => {
    setBusy(true);
    const result = await window.streamsenseLive?.stopServices();
    setBusy(false);
    if (result?.ok && result.data) {
      setHealth(result.data as HealthState);
      setMessage("服务已停止");
    } else if (result && !result.ok) {
      setState("error");
      setMessage(result.error || "停止失败");
    }
  };

  const openMicrophoneSettings = () => {
    void window.streamsenseLive?.openMicrophoneSettings();
  };

  const openCameraSettings = () => {
    void window.streamsenseLive?.openCameraSettings();
  };

  const clearCaptions = async () => {
    // 清空字幕要同时做两件事：
    //   1. 清空当前界面的 React state。
    //   2. 请求 API 删除 desktop-live 这一路的历史结果。
    //
    // 如果只做第 1 步，下一次 pollCaptions() 又会把旧字幕刷回来。
    setCaptions([]);
    try {
      await fetch(`${API_URL}/api/streams/${STREAM_ID}/segments`, { method: "DELETE" });
      setMessage("字幕已清空");
    } catch {
      setMessage("界面字幕已清空，后端历史清理失败");
    }
  };

  const uploadChunk = async (blob: Blob) => {
    // 把浏览器录到的一小段音频上传给 live-ingest。
    //
    // 注意：这里没有直接请求 ASR。
    // live-ingest 会先把音频转成 wav，再写入 Kafka 的 audio-segment topic。
    // 后面由 Flink 调 ASR，这样才能体现大数据实时处理链路。
    const form = new FormData();
    form.append("file", blob, `chunk_${chunkIndexRef.current}.webm`);
    form.append("stream_id", STREAM_ID);
    form.append("run_id", runIdRef.current);
    form.append("chunk_index", String(chunkIndexRef.current));
    form.append("chunk_ms", String(chunkMs));
    form.append("hotwords", "测试,听得到,实时字幕,麦克风,摄像头,Kafka,Flink,大数据,课程设计");
    chunkIndexRef.current += 1;

    const response = await fetch(`${LIVE_INGEST_URL}/live/audio`, {
      method: "POST",
      body: form
    });
    if (!response.ok) {
      throw new Error(`live-ingest HTTP ${response.status}`);
    }
  };

  const recordOneChunk = () => {
    // 每次单独录一段完整 WebM，再上传。
    //
    // 不能使用 MediaRecorder.start(timeslice) 的连续切片模式：
    // 后续切片可能没有完整 WebM 文件头，容器里的 FFmpeg 会报
    // “Invalid data found when processing input”。
    //
    // 所以这里采用 start -> 等 chunkMs -> stop -> 上传 -> 再下一段 的方式。
    if (!liveRunningRef.current || !streamRef.current) {
      return;
    }
    const audioTracks = streamRef.current.getAudioTracks();
    if (audioTracks.length === 0) {
      setState("error");
      setMessage("没有可用麦克风音轨");
      stopLive(false);
      return;
    }

    const audioStream = new MediaStream(audioTracks);
    const mimeType = MediaRecorder.isTypeSupported("audio/webm;codecs=opus") ? "audio/webm;codecs=opus" : "audio/webm";
    const chunks: Blob[] = [];
    const recorder = new MediaRecorder(audioStream, { mimeType });
    recorderRef.current = recorder;
    recorder.ondataavailable = (event) => {
      if (event.data.size > 0) {
        chunks.push(event.data);
      }
    };
    recorder.onstop = () => {
      if (chunks.length > 0) {
        const blob = new Blob(chunks, { type: mimeType });
        uploadChunk(blob).catch((error) => {
          setMessage(error instanceof Error ? `${error.message}，已跳过该音频片段` : "上传失败，已跳过该音频片段");
        });
      }
      if (liveRunningRef.current) {
        window.setTimeout(recordOneChunk, 80);
      }
    };
    recorder.start();
    window.setTimeout(() => {
      if (recorder.state === "recording") {
        recorder.stop();
      }
    }, chunkMs);
  };

  const pollCaptions = async () => {
    // 从 API 读取 desktop-live 这一路已经完成的字幕。
    //
    // 字幕不是上传音频后立即返回的，因为中间要经过：
    // Kafka -> Flink -> ASR -> Kafka -> API。
    // 所以前端用轮询方式每 1.2 秒取一次最新结果。
    try {
      const response = await fetch(`${API_URL}/api/streams/${STREAM_ID}/segments?limit=40`);
      if (!response.ok) {
        return;
      }
      const rows = (await response.json()) as Array<Record<string, unknown>>;
      const mapped = rows
        .map((row) => ({
          id: String(row.segment_id ?? crypto.randomUUID()),
          time: formatClockRange(row.wall_start_at_ms ?? row.created_at_ms ?? row.created_at, row.wall_end_at_ms ?? row.result_written_at),
          text: cleanLiveText(row.text)
        }))
        .filter((item) => item.text)
        .filter((item, index, items) => {
          const previous = items[index - 1];
          return !previous || previous.text !== item.text || previous.time !== item.time;
        })
        .slice(-30)
        .reverse();
      setCaptions(mapped);
    } catch {
      // Polling is best-effort; service status covers hard failures.
    }
  };

  const startLive = async () => {
    // 开始实时字幕。
    //
    // 这里先申请摄像头/麦克风权限。
    // 如果摄像头失败但用户勾选了摄像头，会自动降级为只用麦克风，
    // 因为实时字幕真正必须的是音频，不是画面。
    setState("starting");
    setMessage("正在打开摄像头和麦克风");
    try {
      runIdRef.current = new Date().toISOString().replace(/[-:T.Z]/g, "").slice(0, 14);
      chunkIndexRef.current = 0;
      setCaptions([]);
      let stream: MediaStream;
      try {
        stream = await navigator.mediaDevices.getUserMedia({
          audio: { echoCancellation: true, noiseSuppression: true },
          video: cameraEnabled ? { width: 1280, height: 720 } : false
        });
      } catch (error) {
        if (!cameraEnabled) {
          throw error;
        }
        setMessage("摄像头被系统拒绝，尝试只打开麦克风");
        stream = await navigator.mediaDevices.getUserMedia({
          audio: { echoCancellation: true, noiseSuppression: true },
          video: false
        });
      }
      streamRef.current = stream;
      if (videoRef.current) {
        videoRef.current.srcObject = stream;
      }
      liveRunningRef.current = true;
      recordOneChunk();
      pollTimerRef.current = window.setInterval(() => void pollCaptions(), 1200);
      setState("running");
      setMessage("实时采集中：麦克风 -> Kafka -> Flink -> ASR -> API");
    } catch (error) {
      setState("error");
      const rawMessage = error instanceof Error ? error.message : String(error);
      if (/permission|denied|notallowed/i.test(rawMessage)) {
        setMessage("系统拒绝摄像头/麦克风权限，请在 Windows 隐私设置里允许桌面应用访问麦克风和摄像头");
      } else {
        setMessage(rawMessage);
      }
    }
  };

  const stopLive = (setIdle = true) => {
    // 停止实时采集：关闭录音器、释放摄像头/麦克风、停止轮询。
    // 不会停止 Kafka/Flink/ASR/API 服务，服务由“停止服务”按钮单独控制。
    liveRunningRef.current = false;
    if (recorderRef.current?.state === "recording") {
      recorderRef.current.stop();
    }
    recorderRef.current = null;
    streamRef.current?.getTracks().forEach((track) => track.stop());
    streamRef.current = null;
    if (videoRef.current) {
      videoRef.current.srcObject = null;
    }
    if (pollTimerRef.current !== null) {
      window.clearInterval(pollTimerRef.current);
      pollTimerRef.current = null;
    }
    if (setIdle) {
      setState("idle");
      setMessage("实时采集已停止");
    }
  };

  useEffect(() => {
    void refreshHealth();
    const timer = window.setInterval(() => void refreshHealth(), 4000);
    const removeLog = window.streamsenseLive?.onLogLine((line) => {
      setLogs((items) => [line, ...items].slice(0, 80));
    });
    return () => {
      window.clearInterval(timer);
      removeLog?.();
      stopLive(false);
    };
  }, []);

  return (
    <main className="shell">
      <section className="window">
        <header className="titlebar">
          <div>
            <h1>StreamSense Live</h1>
            <p>摄像头/麦克风实时字幕，走 Kafka + Flink 大数据链路</p>
          </div>
          <div className={`status status-${state}`}>
            <strong>{serviceText(health)}</strong>
            <span>{message}</span>
          </div>
        </header>

        <div className="service-row">
          <span className={health.liveIngest ? "ok" : ""}>Live Ingest</span>
          <span className={health.flink ? "ok" : ""}>Flink</span>
          <span className={health.asr ? "ok" : ""}>ASR</span>
          <span className={health.api ? "ok" : ""}>API</span>
        </div>

        <div className="main-grid">
          <div className="preview">
            <video ref={videoRef} autoPlay playsInline muted />
            <div className="preview-label">CAMERA</div>
          </div>

          <div className="captions">
            {captions.length === 0 ? (
              <div className="empty">字幕会从 Kafka/Flink 链路返回到这里</div>
            ) : (
              captions.map((item) => (
                <article key={item.id} className="caption">
                  <time>{item.time}</time>
                  <p>{item.text}</p>
                </article>
              ))
            )}
          </div>
        </div>

        <footer className="toolbar">
          <label>
            <input type="checkbox" checked={cameraEnabled} disabled={state === "running"} onChange={(event) => setCameraEnabled(event.target.checked)} />
            摄像头
          </label>
          <label>
            分段
            <select value={chunkMs} disabled={state === "running"} onChange={(event) => setChunkMs(Number(event.target.value))}>
              <option value={2500}>2.5 秒</option>
              <option value={3500}>3.5 秒</option>
              <option value={4500}>4.5 秒</option>
            </select>
          </label>
          <div className="grow" />
          <button type="button" onClick={startServices} disabled={busy || state === "running"}>{busy ? "启动中" : "启动大数据服务"}</button>
          <button type="button" onClick={clearCaptions}>清空字幕</button>
          <button type="button" onClick={openMicrophoneSettings}>麦克风权限</button>
          <button type="button" onClick={openCameraSettings}>相机权限</button>
          <button type="button" onClick={stopServices} disabled={busy || state === "running"}>停止服务</button>
          <button type="button" onClick={() => stopLive()} disabled={state !== "running"}>停止字幕</button>
          <button type="button" className="primary" onClick={startLive} disabled={state === "running" || state === "starting"}>开始实时字幕</button>
        </footer>

        <details className="logs">
          <summary>运行日志</summary>
          <pre>{logs.join("\n") || "暂无日志"}</pre>
        </details>
      </section>
    </main>
  );
}
