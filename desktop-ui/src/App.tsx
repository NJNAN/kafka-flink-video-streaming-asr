import { useEffect, useMemo, useState } from "react";
import type { DesktopTask, PathsInfo, SelectedVideo } from "./types";

/*
 * 离线字幕生成器入口。
 *
 * 注意：这个文件属于 desktop-ui/，定位是“本地视频 -> 最终字幕文件”。
 * 它不负责摄像头/麦克风实时字幕，也不直接走 Kafka/Flink。
 *
 * 用户点击“生成字幕”后，真正执行的是 Electron 主进程里的：
 *   desktop-ui/electron/main.ts:startTask()
 *
 * startTask() 会启动：
 *   python tools/generate_video_subtitles.py ...
 *
 * 所以这里主要负责三件事：
 *   1. 让用户选择一个本地视频。
 *   2. 让用户选择字幕输出目录。
 *   3. 把任务交给 Electron 主进程，并显示任务进度。
 */

type UiStatus = "idle" | "ready" | "running" | "done" | "error";

function formatBytes(bytes: number) {
  // 文件选择后展示大小用。这里只是 UI 格式化，不参与字幕生成逻辑。
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

function shortPath(value: string) {
  // Windows 路径通常很长，界面上只显示首尾，避免把卡片撑爆。
  if (value.length <= 62) {
    return value;
  }
  return `${value.slice(0, 24)}...${value.slice(-34)}`;
}

function statusText(status: UiStatus, task?: DesktopTask | null) {
  // 把内部任务状态翻译成用户能看懂的短文本。
  // task.status 来自 Electron 主进程对 Python 字幕脚本的监听结果。
  if (task?.status === "completed") {
    return "字幕已生成";
  }
  if (task?.status === "failed") {
    return "生成失败";
  }
  if (task?.status === "needs_review") {
    return "已生成，建议复查";
  }
  if (status === "running") {
    return task?.current_stage || "正在生成字幕";
  }
  if (status === "done") {
    return "字幕已生成";
  }
  if (status === "error") {
    return "需要处理";
  }
  if (status === "ready") {
    return "已选择视频";
  }
  return "等待视频";
}

export function App() {
  // window.streamsense 是 preload.ts 暴露给浏览器页面的安全桥。
  // 只有 Electron 环境里才有它；普通浏览器 dev 页面没有完整本地文件权限。
  const desktopAvailable = typeof window !== "undefined" && Boolean(window.streamsense);
  const [video, setVideo] = useState<SelectedVideo | null>(null);
  const [outputDir, setOutputDir] = useState("");
  const [task, setTask] = useState<DesktopTask | null>(null);
  const [status, setStatus] = useState<UiStatus>("idle");
  const [message, setMessage] = useState(desktopAvailable ? "点击中间区域选择视频，或把视频拖进来。" : "Web 模式无法读取本地完整路径，请用 Electron 启动。");
  const [busy, setBusy] = useState(false);

  const progress = useMemo(() => {
    // Python 字幕脚本没有细粒度进度事件时，界面至少给用户一个稳定状态反馈。
    // 如果 Electron 主进程已经记录 task.progress，就优先使用真实任务进度。
    if (task) {
      return Math.max(0, Math.min(100, Math.round(task.progress)));
    }
    return status === "ready" ? 8 : status === "done" ? 100 : 0;
  }, [status, task]);

  useEffect(() => {
    // 初始化默认输出目录，并订阅 Electron 主进程推送的任务状态更新。
    // 这样 Python 子进程结束、失败、需要复查时，界面能立刻变化。
    if (!window.streamsense) {
      return;
    }
    window.streamsense.getPaths().then((result) => {
      if (result.ok && result.data) {
        const paths = result.data as PathsInfo;
        setOutputDir(`${paths.resultsDir}\\mini-subtitles`);
      }
    });
    const removeTask = window.streamsense.onTaskUpdate((nextTask) => {
      setTask((current) => {
        if (!current || current.task_id !== nextTask.task_id) {
          return current;
        }
        if (nextTask.status === "completed" || nextTask.status === "needs_review") {
          setStatus("done");
          setBusy(false);
          setMessage(`完成：${nextTask.output_dir || outputDir}`);
        } else if (nextTask.status === "failed") {
          setStatus("error");
          setBusy(false);
          setMessage(nextTask.error || "生成失败，请检查日志。");
        } else {
          setStatus("running");
          setMessage(nextTask.current_stage || "正在生成字幕...");
        }
        return nextTask;
      });
    });
    return removeTask;
  }, [outputDir]);

  const chooseVideo = async () => {
    // 通过 Electron dialog 选择真实本地文件。
    // 不能用普通 Web input 代替，因为浏览器拿不到完整 Windows 路径。
    if (!window.streamsense) {
      setStatus("error");
      setMessage("当前是 Web 模式，无法打开系统文件选择器。请运行 npm run electron:dev 或双击 StreamSense.exe。");
      return;
    }
    setBusy(true);
    const result = await window.streamsense.selectVideoFile();
    setBusy(false);
    if (result.ok && result.data) {
      setVideo(result.data);
      setTask(null);
      setStatus("ready");
      setMessage("视频已选择，可以开始生成字幕。");
    } else if (!result.ok) {
      setStatus("error");
      setMessage(result.error || "选择视频失败。");
    }
  };

  const chooseOutputDir = async () => {
    // 输出目录也必须走 Electron dialog，确保 Python 脚本能写入真实路径。
    if (!window.streamsense) {
      setMessage("Web 模式无法选择输出目录，请直接编辑输入框。");
      return;
    }
    const result = await window.streamsense.selectOutputFolder();
    if (result.ok && result.data) {
      setOutputDir(result.data);
    } else if (!result.ok) {
      setStatus("error");
      setMessage(result.error || "选择输出目录失败。");
    }
  };

  const handleDrop = (event: React.DragEvent<HTMLDivElement>) => {
    // Electron 里拖入文件时可以拿到 file.path。
    // 如果在普通浏览器中拖拽，file.path 通常为空，所以这里会提示用户用 exe。
    event.preventDefault();
    const file = event.dataTransfer.files[0] as (File & { path?: string }) | undefined;
    if (!file) {
      return;
    }
    if (!file.path) {
      setStatus("error");
      setMessage("浏览器拖拽拿不到完整文件路径，请点击选择视频。");
      return;
    }
    setVideo({
      path: file.path,
      name: file.name,
      sizeBytes: file.size,
      extension: `.${file.name.split(".").pop() || ""}`
    });
    setTask(null);
    setStatus("ready");
    setMessage("视频已放入，可以开始生成字幕。");
  };

  const start = async () => {
    // 离线生成的核心按钮。
    //
    // 这里没有直接调用 ASR，也没有直接处理视频。
    // 它只创建任务并交给 Electron 主进程，由主进程启动 Python：
    //   tools/generate_video_subtitles.py
    //
    // 这样设计是为了让渲染进程保持简单，也避免在网页环境里直接操作本地进程。
    if (!window.streamsense) {
      setStatus("error");
      setMessage("请在 Electron App 中生成字幕，Web 页面只保留展示。");
      return;
    }
    if (!video) {
      setStatus("error");
      setMessage("请先选择或拖入一个视频文件。");
      return;
    }
    if (!outputDir.trim()) {
      setStatus("error");
      setMessage("请填写字幕输出目录。");
      return;
    }

    setBusy(true);
    setStatus("running");
    setMessage("正在创建任务...");
    const created = await window.streamsense.createTask({
      sourcePath: video.path,
      copyToWorkspace: true,
      mode: "标准质量",
      model: "medium",
      outputDir: outputDir.trim()
    });
    if (!created.ok || !created.data) {
      setBusy(false);
      setStatus("error");
      setMessage(created.error || "创建任务失败。");
      return;
    }
    setTask(created.data);
    setMessage("任务已创建，正在启动字幕生成...");
    const started = await window.streamsense.startTask(created.data.task_id, { mode: "标准质量", model: "medium" });
    if (!started.ok || !started.data) {
      setBusy(false);
      setStatus("error");
      setMessage(started.error || "启动任务失败。");
      return;
    }
    setTask(started.data);
    setMessage(started.data.current_stage || "正在生成字幕...");
  };

  const openOutput = async () => {
    // 任务完成后打开输出目录，方便用户直接拿 srt/vtt/txt/json。
    if (!window.streamsense) {
      return;
    }
    if (task?.output_dir || outputDir.trim()) {
      await window.streamsense.openOutputFolder(task?.output_dir || outputDir.trim());
    } else {
      await window.streamsense.openResultsFolder();
    }
  };

  return (
    <main className="mini-shell">
      <section className="mini-card">
        <header className="mini-titlebar">
          <div>
            <h1>StreamSense</h1>
            <p>视频字幕生成器</p>
          </div>
          <span className={`mini-status mini-status-${status}`}>{statusText(status, task)}</span>
        </header>

        <div
          className={`drop-zone ${video ? "has-video" : ""}`}
          role="button"
          tabIndex={0}
          onClick={chooseVideo}
          onDragOver={(event) => event.preventDefault()}
          onDrop={handleDrop}
          onKeyDown={(event) => event.key === "Enter" && void chooseVideo()}
        >
          <div className="file-icon">▶</div>
          <strong>{video ? video.name : "点击选择视频，或拖入视频"}</strong>
          <span>{video ? `${formatBytes(video.sizeBytes)} · ${shortPath(video.path)}` : "支持 mp4 / mkv / mov / avi / flv"}</span>
        </div>

        <label className="path-row">
          <span>字幕输出地址</span>
          <div>
            <input value={outputDir} onChange={(event) => setOutputDir(event.target.value)} placeholder="选择字幕输出目录" />
            <button type="button" onClick={chooseOutputDir} disabled={!desktopAvailable}>浏览</button>
          </div>
        </label>

        <div className="progress-block" aria-label="生成进度">
          <div className="progress-line">
            <span style={{ width: `${progress}%` }} />
          </div>
          <div className="progress-meta">
            <span>{progress}%</span>
            <span>{message}</span>
          </div>
        </div>

        <footer className="mini-actions">
          <button type="button" className="secondary" onClick={chooseVideo} disabled={busy}>选择视频</button>
          <button type="button" className="primary" onClick={start} disabled={busy || !video}>{busy ? "生成中..." : "生成字幕"}</button>
          <button type="button" className="secondary" onClick={openOutput}>打开输出</button>
        </footer>
      </section>
    </main>
  );
}
