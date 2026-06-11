import { useEffect, useMemo, useRef, useState } from "react";

type AppState = "idle" | "recording" | "finishing" | "done";

interface SpeechRecognitionEventLike {
  results: {
    length: number;
    [index: number]: {
      isFinal: boolean;
      [index: number]: {
        transcript: string;
      };
    };
  };
}

interface SpeechRecognitionLike {
  lang: string;
  continuous: boolean;
  interimResults: boolean;
  onresult: ((event: SpeechRecognitionEventLike) => void) | null;
  onerror?: (() => void) | null;
  onend: (() => void) | null;
  start: () => void;
  stop: () => void;
}

type SpeechRecognitionConstructor = new () => SpeechRecognitionLike;

interface StreamSegment {
  segment_id?: string;
  run_id?: string;
  text?: string;
}

const DEFAULT_BACKEND_HOST = import.meta.env.VITE_STREAMSENSE_BACKEND_HOST ?? "192.168.123.242";
const isNativeShell = typeof window !== "undefined" && window.location.protocol === "capacitor:";
const API_BASE = import.meta.env.VITE_STREAMSENSE_API_BASE ?? (isNativeShell ? `http://${DEFAULT_BACKEND_HOST}:8000` : "");
const LIVE_INGEST_URL = import.meta.env.VITE_STREAMSENSE_LIVE_INGEST_URL ?? (isNativeShell ? `http://${DEFAULT_BACKEND_HOST}:8010` : "");
const STREAM_ID = import.meta.env.VITE_STREAMSENSE_STREAM_ID ?? "meetflow-tablet";
const CHUNK_MS = 1800;
const POLL_MS = 700;
const HOTWORDS = "会议纪要,待办,客户,接口,排期,跟进,确认,交付,项目,风险,本周,明天";
const actionWords = ["需要", "请", "麻烦", "我会", "我们会", "负责", "跟进", "确认", "发送", "补充", "整理", "输出", "同步", "安排", "完成", "提供", "推进"];
const timeWords = ["今天", "明天", "本周", "周一", "周二", "周三", "周四", "周五", "月底", "下班前", "中午前", "下午", "上午"];

function formatDuration(totalSeconds: number) {
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  return `${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}`;
}

function cleanText(value: string) {
  return value.replace(/\s+/g, " ").trim();
}

function splitSentences(value: string) {
  return cleanText(value)
    .split(/[。！？!?；;\n]+/)
    .map((item) => item.trim())
    .filter(Boolean);
}

function inferTitle(sentences: string[]) {
  const text = sentences.join(" ");
  if (/客户|续费|回访|投诉|合同|接口/.test(text)) {
    return "客户沟通纪要";
  }
  if (/产品|需求|版本|灰度|体验|功能/.test(text)) {
    return "产品讨论纪要";
  }
  if (/上线|交付|排期|进度|项目|风险/.test(text)) {
    return "项目同步纪要";
  }
  if (/周会|例会|晨会|复盘|团队/.test(text)) {
    return "团队会议纪要";
  }
  const first = sentences[0]?.replace(/[，,：:]/g, " ").trim().slice(0, 10);
  return first ? `${first}纪要` : "会议纪要";
}

function sentenceScore(sentence: string) {
  let score = Math.min(sentence.length, 42);
  if (actionWords.some((word) => sentence.includes(word))) {
    score += 24;
  }
  if (timeWords.some((word) => sentence.includes(word))) {
    score += 18;
  }
  if (/结论|决定|重点|风险|客户|上线|交付|接口|续费/.test(sentence)) {
    score += 16;
  }
  return score;
}

function buildSummary(sentences: string[]) {
  if (sentences.length === 0) {
    return "还没有识别到清晰的谈话内容。请重新开始记录，或确认浏览器已获得麦克风权限。";
  }
  if (sentences.length <= 2) {
    return `${sentences.join("。")}。`;
  }
  const important = [...sentences]
    .sort((left, right) => sentenceScore(right) - sentenceScore(left))
    .slice(0, 2)
    .sort((left, right) => sentences.indexOf(left) - sentences.indexOf(right));
  return `${important.join("。")}。`;
}

function toAction(sentence: string) {
  return sentence
    .replace(/^(然后|另外|还有|所以|结论是|决定是|我们决定|我建议|建议|请|麻烦)/, "")
    .replace(/[。！？!?；;]$/g, "")
    .trim();
}

function extractActions(sentences: string[]) {
  const picked = sentences
    .filter((sentence) => actionWords.some((word) => sentence.includes(word)) || timeWords.some((word) => sentence.includes(word)))
    .map(toAction)
    .filter(Boolean);
  return Array.from(new Set(picked)).slice(0, 4);
}

function buildMinutes(rawText: string) {
  const text = cleanText(rawText);
  const sentences = splitSentences(text);
  const actions = extractActions(sentences);
  return {
    title: inferTitle(sentences),
    summary: buildSummary(sentences),
    actions: actions.length ? actions : ["未识别到明确待办，可继续补充发言后再生成"],
    original: text,
    hasContent: sentences.length > 0
  };
}

export function App() {
  const [state, setState] = useState<AppState>("idle");
  const [seconds, setSeconds] = useState(0);
  const [liveText, setLiveText] = useState("");
  const [finalText, setFinalText] = useState("");
  const [notice, setNotice] = useState("");
  const [copied, setCopied] = useState(false);
  const recognitionRef = useRef<SpeechRecognitionLike | null>(null);
  const mediaStreamRef = useRef<MediaStream | null>(null);
  const recorderRef = useRef<MediaRecorder | null>(null);
  const runIdRef = useRef("");
  const chunkIndexRef = useRef(0);
  const pollTimerRef = useRef<number | null>(null);
  const liveRunningRef = useRef(false);
  const liveTextRef = useRef("");
  const backendErrorShownRef = useRef(false);
  const uploadErrorCountRef = useRef(0);

  const minutes = useMemo(() => buildMinutes(finalText), [finalText]);
  const currentSpeechText = liveText || notice || "正在等待第一句话...";
  const isRecording = state === "recording";
  const isFinishing = state === "finishing";

  useEffect(() => {
    if (state !== "recording") {
      return;
    }
    const timer = window.setInterval(() => setSeconds((value) => value + 1), 1000);
    return () => window.clearInterval(timer);
  }, [state]);

  const updateLiveText = (value: string) => {
    const cleaned = cleanText(value);
    liveTextRef.current = cleaned;
    setLiveText(cleaned);
  };

  const stopPolling = () => {
    if (pollTimerRef.current !== null) {
      window.clearInterval(pollTimerRef.current);
      pollTimerRef.current = null;
    }
  };

  const stopBrowserSpeech = () => {
    const recognition = recognitionRef.current;
    recognitionRef.current = null;
    try {
      recognition?.stop();
    } catch {
      // Best-effort cleanup only.
    }
  };

  const pollBackendTranscript = async () => {
    if (!runIdRef.current) {
      return;
    }
    try {
      const response = await fetch(`${API_BASE}/api/streams/${STREAM_ID}/segments?limit=80`);
      if (!response.ok) {
        return;
      }
      const rows = (await response.json()) as StreamSegment[];
      const parts = rows
        .filter((row) => row.run_id === runIdRef.current || String(row.segment_id ?? "").includes(runIdRef.current))
        .map((row) => cleanText(String(row.text ?? "")))
        .filter(Boolean);
      const merged = Array.from(new Set(parts)).join(" ");
      if (merged) {
        updateLiveText(merged);
        setNotice("");
      }
    } catch {
      // Upload errors produce the actionable service message; polling can stay quiet.
    }
  };

  const uploadChunk = async (blob: Blob) => {
    const form = new FormData();
    form.append("file", blob, `chunk_${chunkIndexRef.current}.webm`);
    form.append("stream_id", STREAM_ID);
    form.append("run_id", runIdRef.current);
    form.append("chunk_index", String(chunkIndexRef.current));
    form.append("chunk_ms", String(CHUNK_MS));
    form.append("hotwords", HOTWORDS);
    chunkIndexRef.current += 1;

    try {
      const response = await fetch(`${LIVE_INGEST_URL}/live/audio`, {
        method: "POST",
        body: form
      });
      if (!response.ok) {
        throw new Error(`HTTP ${response.status}`);
      }
      const payload = (await response.json()) as { status?: string; reason?: string };
      if (payload.status === "skipped" && !liveTextRef.current) {
        setNotice("正在听，请稍微靠近平板说话。");
      } else {
        uploadErrorCountRef.current = 0;
      }
    } catch {
      uploadErrorCountRef.current += 1;
      if (uploadErrorCountRef.current >= 3 && !backendErrorShownRef.current && !liveTextRef.current) {
        backendErrorShownRef.current = true;
        setNotice("实时识别服务未连接。请先启动 StreamSense Live 后端，或在支持语音识别的浏览器中使用。");
      }
    }
  };

  const recordOneChunk = () => {
    if (!liveRunningRef.current || !mediaStreamRef.current) {
      return;
    }
    const audioTracks = mediaStreamRef.current.getAudioTracks();
    if (audioTracks.length === 0) {
      setNotice("没有可用麦克风音轨。");
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
        void uploadChunk(new Blob(chunks, { type: mimeType }));
      }
      if (liveRunningRef.current) {
        window.setTimeout(recordOneChunk, 60);
      }
    };
    recorder.start();
    window.setTimeout(() => {
      if (recorder.state === "recording") {
        recorder.stop();
      }
    }, CHUNK_MS);
  };

  const startBrowserSpeechFallback = () => {
    const speechWindow = window as Window & {
      SpeechRecognition?: SpeechRecognitionConstructor;
      webkitSpeechRecognition?: SpeechRecognitionConstructor;
    };
    const Recognition = speechWindow.SpeechRecognition ?? speechWindow.webkitSpeechRecognition;
    if (!Recognition) {
      return;
    }

    const recognition = new Recognition();
    recognition.lang = "zh-CN";
    recognition.continuous = true;
    recognition.interimResults = true;
    recognition.onresult = (event) => {
      let nextText = "";
      for (let index = 0; index < event.results.length; index += 1) {
        nextText += event.results[index][0].transcript;
      }
      if (nextText.trim()) {
        updateLiveText(nextText);
        setNotice("");
      }
    };
    const restartRecognition = () => {
      recognitionRef.current = null;
      if (liveRunningRef.current) {
        window.setTimeout(startBrowserSpeechFallback, 360);
      }
    };
    recognition.onerror = restartRecognition;
    recognition.onend = () => {
      restartRecognition();
    };
    recognitionRef.current = recognition;
    try {
      recognition.start();
    } catch {
      recognitionRef.current = null;
    }
  };

  const startRecording = async () => {
    setSeconds(0);
    updateLiveText("");
    setFinalText("");
    setNotice("");
    setCopied(false);
    stopPolling();
    stopBrowserSpeech();
    runIdRef.current = new Date().toISOString().replace(/[-:T.Z]/g, "").slice(0, 14);
    chunkIndexRef.current = 0;
    liveRunningRef.current = false;
    backendErrorShownRef.current = false;
    uploadErrorCountRef.current = 0;
    setState("recording");

    try {
      if (!navigator.mediaDevices?.getUserMedia) {
        throw new Error("mediaDevices unavailable");
      }
      mediaStreamRef.current = await navigator.mediaDevices?.getUserMedia({
        audio: { echoCancellation: true, noiseSuppression: false, autoGainControl: true }
      });
    } catch {
      const insecureLan =
        window.location.protocol !== "https:" && !["localhost", "127.0.0.1"].includes(window.location.hostname);
      setNotice(insecureLan ? "平板浏览器需要 HTTPS 才能打开麦克风。请改用 HTTPS 访问或打包成 App。" : "麦克风权限未开启，无法获取真实谈话内容。");
      return;
    }

    if (typeof MediaRecorder === "undefined") {
      setNotice("当前浏览器不支持分段录音，正在尝试浏览器自带实时识别。");
      startBrowserSpeechFallback();
      return;
    }

    setNotice("正在连接实时识别服务，第一段文字通常需要几秒。");
    void fetch(`${API_BASE}/api/streams/${STREAM_ID}/segments`, { method: "DELETE" }).catch(() => undefined);
    liveRunningRef.current = true;
    recordOneChunk();
    pollTimerRef.current = window.setInterval(() => void pollBackendTranscript(), POLL_MS);
    startBrowserSpeechFallback();
  };

  const finishRecording = async () => {
    if (state !== "recording") {
      return;
    }
    setState("finishing");
    setNotice("正在整理最后一段语音...");
    liveRunningRef.current = false;
    if (recorderRef.current?.state === "recording") {
      recorderRef.current.stop();
    }
    stopBrowserSpeech();
    mediaStreamRef.current?.getTracks().forEach((track) => track.stop());
    mediaStreamRef.current = null;
    for (let index = 0; index < 10 && !liveTextRef.current; index += 1) {
      await new Promise((resolve) => window.setTimeout(resolve, POLL_MS));
      await pollBackendTranscript();
    }
    stopPolling();
    setFinalText(liveTextRef.current);
    setState("done");
  };

  const copyMinutes = async () => {
    const content = [
      `# ${minutes.title}`,
      "",
      `摘要：${minutes.summary}`,
      "",
      "待办：",
      ...minutes.actions.map((action) => `- ${action}`),
      "",
      minutes.original ? `原文：${minutes.original}` : "原文：未识别到清晰谈话内容"
    ].join("\n");
    try {
      await navigator.clipboard.writeText(content);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1800);
    } catch {
      setCopied(false);
    }
  };

  const reset = () => {
    liveRunningRef.current = false;
    stopPolling();
    stopBrowserSpeech();
    mediaStreamRef.current?.getTracks().forEach((track) => track.stop());
    mediaStreamRef.current = null;
    setState("idle");
    setSeconds(0);
    updateLiveText("");
    setFinalText("");
    setNotice("");
    setCopied(false);
  };

  return (
    <main className={`phone-app ${state}`}>
      <section className="app-card">
        <header className="app-header">
          <div className="logo-mark">M</div>
          <div>
            <strong>MeetFlow</strong>
            <span>一键会议纪要</span>
          </div>
        </header>

        <section className="hero">
          <p>{isRecording ? "正在记录" : isFinishing ? "正在整理" : state === "done" ? "纪要已生成" : "打开就能用"}</p>
          <h1>{state === "idle" ? "按一下，开始记录会议。" : isRecording ? formatDuration(seconds) : isFinishing ? "生成纪要中" : minutes.title}</h1>
          <span>
            {state === "idle"
              ? "适合客户回访、团队例会和项目同步。结束后自动整理摘要和待办。"
              : isRecording
                ? "请正常开会，谈话内容会实时显示，并在结束后整理成纪要。"
                : isFinishing
                  ? "正在等待最后一段识别结果，马上生成真实纪要。"
                : minutes.summary}
          </span>
          {isRecording || isFinishing ? (
            <div className="live-caption" aria-live="polite">
              <div>
                <i />
                <strong>正在听</strong>
              </div>
              <p>{currentSpeechText}</p>
            </div>
          ) : null}
        </section>

        {state !== "done" ? (
          <button className="record-button" onClick={isRecording ? finishRecording : startRecording} disabled={isFinishing}>
            <span className="mic-symbol" aria-hidden="true">
              <i />
            </span>
            <strong>{isRecording ? "完成并生成纪要" : isFinishing ? "正在生成纪要" : "开始记录"}</strong>
          </button>
        ) : (
          <section className="minutes-card">
            <div className="minutes-block">
              <span>摘要</span>
              <p>{minutes.summary}</p>
            </div>
            {minutes.hasContent ? (
              <div className="minutes-block original-block">
                <span>原文摘录</span>
                <p>{minutes.original}</p>
              </div>
            ) : null}
            <div className="minutes-block">
              <span>待办</span>
              {minutes.actions.map((action) => (
                <label key={action}>
                  <input type="checkbox" />
                  <strong>{action}</strong>
                </label>
              ))}
            </div>
            <div className="button-row">
              <button className="secondary-action" onClick={reset}>再记一场</button>
              <button className="share-action" onClick={copyMinutes}>{copied ? "已复制" : "复制纪要"}</button>
            </div>
          </section>
        )}
      </section>
    </main>
  );
}
