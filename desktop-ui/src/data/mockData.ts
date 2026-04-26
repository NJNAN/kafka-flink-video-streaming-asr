import type { WorkbenchSnapshot } from "../types";

export const mockSnapshot: WorkbenchSnapshot = {
  services: [
    {
      name: "Kafka",
      state: "online",
      headline: "topic-init ready",
      latencyMs: 18,
      metrics: {
        topic: "audio-segment",
        inflow: "128 msg/min",
        partitions: 3
      }
    },
    {
      name: "Flink",
      state: "busy",
      headline: "job running",
      latencyMs: 42,
      metrics: {
        parallelism: 2,
        checkpoint: "12s ago",
        backpressure: "low"
      }
    },
    {
      name: "ASR",
      state: "busy",
      headline: "large-v3 cuda",
      latencyMs: 860,
      metrics: {
        model: "large-v3",
        device: "cuda",
        cuda: true,
        avgInference: "0.86s"
      }
    },
    {
      name: "Redis",
      state: "online",
      headline: "cache connected",
      latencyMs: 7,
      metrics: {
        keys: 92,
        transcripts: 188,
        hotwords: 34
      }
    },
    {
      name: "API",
      state: "online",
      headline: "consumer running",
      latencyMs: 24,
      metrics: {
        consumer_running: true,
        transcript_count: 188,
        keyword_event_count: 174,
        last_message_time_ms: 1230
      }
    }
  ],
  tasks: [
    {
      id: "task-dino",
      title: "input10.mp4 真实视频转写",
      source: "D:/.../input10.mp4",
      status: "running",
      progress: 72,
      elapsed: "03:48",
      duration: "05:13",
      mode: "高质量",
      thumbnailTone: "teal",
      reportPath: "data/results/batch/input10/input10_report.json"
    },
    {
      id: "task-batch",
      title: "batch/input8 字幕补漏复查",
      source: "data/results/batch/input8",
      status: "review",
      progress: 100,
      elapsed: "02:12",
      duration: "04:36",
      mode: "标准质量",
      thumbnailTone: "amber",
      reportPath: "data/results/batch/input8/input8_report.json"
    },
    {
      id: "task-live",
      title: "RTSP camera-01 演示流",
      source: "rtsp://camera-01/stream1",
      status: "queued",
      progress: 18,
      elapsed: "00:38",
      duration: "live",
      mode: "快速演示",
      thumbnailTone: "steel"
    }
  ],
  pipeline: [
    { id: "load", label: "视频加载", state: "done", detail: "input10.mp4" },
    { id: "extract", label: "音频抽取", state: "done", detail: "ffmpeg pcm16" },
    { id: "vad", label: "VAD 切块", state: "done", detail: "3.0s target" },
    { id: "kafka", label: "Kafka 入队", state: "done", detail: "audio-segment" },
    { id: "flink", label: "Flink 调度", state: "running", detail: "job active" },
    { id: "asr", label: "ASR 转写", state: "running", detail: "large-v3" },
    { id: "keyword", label: "关键词分析", state: "waiting", detail: "textrank" },
    { id: "recover", label: "字幕补漏", state: "waiting", detail: "coverage scan" },
    { id: "export", label: "结果导出", state: "waiting", detail: "srt/vtt/json" }
  ],
  timeline: {
    durationSeconds: 312,
    voiceRanges: [
      { id: "voice-001", start: 8, end: 39 },
      { id: "voice-002", start: 47, end: 93 },
      { id: "voice-003", start: 101, end: 141 },
      { id: "voice-004", start: 158, end: 218 },
      { id: "voice-005", start: 229, end: 292 }
    ],
    subtitleSegments: [
      {
        id: "sub-001",
        start: 8,
        end: 24,
        text: "这段视频会演示 StreamSense 如何从真实视频里抽取语音。",
        status: "ok",
        processingMs: 760,
        keywords: ["真实视频", "语音", "StreamSense"]
      },
      {
        id: "sub-002",
        start: 25,
        end: 39,
        text: "FFmpeg 先把音轨变成可切分的 PCM 数据。",
        status: "ok",
        processingMs: 690,
        keywords: ["FFmpeg", "音轨", "PCM"]
      },
      {
        id: "sub-003",
        start: 47,
        end: 77,
        text: "VAD 会根据停顿动态切块，再把片段写入 Kafka 队列。",
        status: "ok",
        processingMs: 842,
        keywords: ["VAD", "动态切块", "Kafka"]
      },
      {
        id: "sub-004",
        start: 101,
        end: 126,
        text: "Flink 负责调度 ASR 服务，并把识别结果送回关键词分析。",
        status: "ok",
        processingMs: 910,
        keywords: ["Flink", "ASR", "关键词"]
      },
      {
        id: "sub-005",
        start: 176,
        end: 205,
        text: "补漏模块会检查有声区间和字幕覆盖率，发现缺口后再次转写。",
        status: "recovered",
        processingMs: 1180,
        keywords: ["补漏", "字幕覆盖率", "再次转写"]
      }
    ],
    gapSegments: [
      { id: "recover-001", start: 176, end: 205, kind: "recovery", label: "补" },
      { id: "gap-001", start: 78, end: 93, kind: "gap", label: "疑似缺口" },
      { id: "gap-002", start: 229, end: 242, kind: "gap", label: "疑似缺口" }
    ]
  },
  quality: {
    mediaDuration: "05:13",
    elapsed: "02:28",
    hotwords: ["Kafka", "Flink", "Whisper", "字幕补漏", "VAD", "CUDA", "关键词"],
    metrics: [
      {
        key: "duration",
        label: "视频时长",
        value: "05:13",
        state: "pass",
        hint: "media duration"
      },
      {
        key: "elapsed",
        label: "处理耗时",
        value: "02:28",
        state: "pass",
        hint: "wall clock"
      },
      {
        key: "speed",
        label: "speed_ratio_elapsed_over_media",
        value: "0.47",
        state: "pass",
        hint: "低于 0.50"
      },
      {
        key: "items",
        label: "subtitle_items",
        value: "188",
        state: "pass",
        hint: "句子级字幕"
      },
      {
        key: "hotwords",
        label: "hotwords",
        value: "34",
        state: "pass",
        hint: "动态热词"
      },
      {
        key: "before",
        label: "uncovered_gaps_before_recovery",
        value: "5",
        state: "review",
        hint: "补漏前"
      },
      {
        key: "after",
        label: "blocking_uncovered_gaps_after_recovery",
        value: "0",
        state: "pass",
        hint: "补漏后"
      },
      {
        key: "status",
        label: "当前状态",
        value: "ASR 转写中",
        state: "review",
        hint: "pipeline live"
      }
    ]
  },
  exports: [
    {
      type: "SRT",
      fileName: "input10.srt",
      path: "data/results/input10/input10.srt",
      size: "18 KB",
      status: "ready"
    },
    {
      type: "VTT",
      fileName: "input10.vtt",
      path: "data/results/input10/input10.vtt",
      size: "19 KB",
      status: "ready"
    },
    {
      type: "TXT",
      fileName: "input10_subtitle.txt",
      path: "data/results/input10/input10_subtitle.txt",
      size: "15 KB",
      status: "ready"
    },
    {
      type: "JSON",
      fileName: "input10_final_segments.json",
      path: "data/results/input10/input10_final_segments.json",
      size: "64 KB",
      status: "ready"
    },
    {
      type: "REPORT",
      fileName: "input10_report.json",
      path: "data/results/input10/input10_report.json",
      size: "9 KB",
      status: "ready"
    }
  ],
  logs: [
    {
      id: "log-001",
      time: "14:28:21",
      level: "OK",
      source: "Kafka",
      message: "audio-segment offset 314 committed"
    },
    {
      id: "log-002",
      time: "14:28:22",
      level: "INFO",
      source: "Flink",
      message: "dispatch segment input10-000189 to ASR service"
    },
    {
      id: "log-003",
      time: "14:28:23",
      level: "INFO",
      source: "ASR",
      message: "large-v3 cuda float16 inference 842ms"
    },
    {
      id: "log-004",
      time: "14:28:23",
      level: "OK",
      source: "API",
      message: "sentence buffer flushed 1 transcript, 4 keywords"
    },
    {
      id: "log-005",
      time: "14:28:24",
      level: "WARN",
      source: "Coverage",
      message: "voice range 00:01:18-00:01:33 needs recovery scan"
    }
  ]
};
