# StreamSense —— 基于 Kafka-Flink 的视频流语音转写与关键词分析系统

[![Python](https://img.shields.io/badge/Python-3.11+-blue)](https://www.python.org/)
[![Docker](https://img.shields.io/badge/Docker-支持-blue)](https://www.docker.com/)
[![License](https://img.shields.io/badge/License-MIT-green)](./LICENSE)
[![Flink](https://img.shields.io/badge/Flink-1.18-orange)](https://flink.apache.org/)

**视频进去，字幕出来。中间发生了什么，你全看得见。**

普通转写工具：丢视频 → 等几分钟 → 下载字幕。中间发生了什么？不知道。

StreamSense 不一样。它把视频语音处理做成了实时流：音频按语音停顿自动切片进入 Kafka，Flink 调度 GPU 推理，字幕逐句生成，关键词同步提取，延迟实时展示。数据流到哪里、卡在哪里、每条数据在每个环节耗时多少毫秒——Dashboard 上全部可查。不是跑完看结果，而是一边跑一边看。

Docker 一行命令启动，多路视频并发处理，SRT/VTT 多格式导出，内建质量评测——从实验到报告，一步到位。

这套架构的价值不在纸面上，在具体场景里。答辩演示时，打开 Dashboard，数据怎么流的、每步延迟多少、关键词是什么——实时可见，不用靠嘴解释"系统确实在跑"。写实验报告时，SQLite 里每条片段的端到端时间线可以直接导出，哪个环节慢了、慢了多少，数据说话。想验证字幕质量？拿一份人工标注参考文本，跑 evaluate_subtitles.py，字错率、词错率、关键词命中率全部量化输出——好就是好，差就是差，不靠感觉。把数据处理从黑盒变成可观测、可追溯、可验证的过程——这才是架构创新的落脚点，也是 StreamSense 区别于"调一个 API 出字幕"的核心所在。

放眼更大市场，这套架构的可复制性远不止课设。在线教育平台需要为海量课程视频自动生成字幕和知识点索引——Kafka-Flink 管线天然支持高并发，GPU 本地化部署保障数据不出内网。企业会议与呼叫中心每天产生数万小时语音，传统方案只能抽样质检，而 StreamSense 的实时流架构可以做到全量转写、关键词触发、异常实时告警。视频内容平台用它做合规审核和广告位匹配，医疗教育用它做医患对话的结构化归档。任何一个需要把"非结构化语音变成可检索、可分析的结构化数据"的行业，都是这套架构的落地空间。数据不出内网、处理实时可见、质量可量化验证——这三个能力组合在一起，构成了面向企业级实时语音分析的技术护城河。

---

## 目录

- [0. 快速预览](#0-快速预览)
- [1. 案例选型（5%）](#1-案例选型)
- [2. 技术选型（5%）](#2-技术选型)
- [3. 开发环境（5%）](#3-开发环境)
- [4. 核心技术（10%）](#4-核心技术)
- [5. 数据规格（20%）](#5-数据规格)
- [6. 功能实现（20%）](#6-功能实现)
- [7. 代码规范（10%）](#7-代码规范)
- [8. 实验结果](#8-实验结果)
- [9. 说明文档（20%）](#9-说明文档)
- [10. 遇到的问题与解决方法](#10-遇到的问题与解决方法)
- [11. 限制与后续方向](#11-限制与后续方向)

---

## 0. 快速预览

### 快速启动

```powershell
# 1. 把视频丢进 videos/ 目录
cp 你的视频.mp4 videos/input.mp4

# 2. 一行命令启动全部服务
docker compose up -d --build

# 3. 打开浏览器看实时转写
# http://localhost:8000
```

视频放入 `videos/`，启动 Docker，打开浏览器——字幕实时滚动，关键词同步提取，延迟曲线实时跳动。

### 启动后能做什么

| 做什么              | 怎么操作                                                                                                             |
| ------------------- | -------------------------------------------------------------------------------------------------------------------- |
| 看实时字幕和关键词  | 浏览器打开 `http://localhost:8000`                                                                                 |
| 导出 SRT/VTT 字幕   | `http://localhost:8000/api/streams/demo-video/export?format=srt`                                                   |
| 查看 Flink 作业状态 | `http://localhost:8081`                                                                                            |
| 检查系统是否正常    | `python tools/smoke_check.py`（6 项自动检查）                                                                      |
| 生成离线字幕文件    | `python tools/generate_video_subtitles.py --media-path videos/input.mp4 --output-dir data/results/demo`            |
| 评测字幕质量        | `python tools/evaluate_subtitles.py --candidate data/results/demo/xxx.vtt --reference data/reference/参考文本.txt` |
| 多路并发压测        | `python tools/benchmark_streamsense.py --help`                                                                     |
| 使用桌面端          | `desktop-ui/`（离线字幕）和 `desktop-ui-live/`（实时采集）分别 `npm install && npm run electron:dev`           |

### 实测数据（2 路视频并发）

| 指标           | 数值               |
| -------------- | ------------------ |
| 处理片段数     | 230 个（全部成功） |
| 平均端到端延迟 | 约 4 秒            |
| P95 延迟       | 约 6.8 秒          |
| 失败片段       | 0 个               |

---

## 1. 案例选型

### 为什么选"视频语音转写"？

视频语音转写是一个**天然适合大数据管线**的场景：

1. **数据本身是"流"**：视频音频是持续到达的，不是一次性文件处理——这正好对应课程中"流式计算"的核心概念
2. **问题可拆解**：从音频采集到字幕输出，中间需要缓冲、调度、识别、分析、存储——每一步对应大数据课程的一个知识点
3. **效果看得见**：不像纯后端系统只能看日志，转写结果直接以字幕形式呈现，Dashboard 可视化可直观展示系统运行状态

### 与传统"视频转字幕脚本"的区别

| 维度     | 普通脚本           | StreamSense                                         |
| -------- | ------------------ | --------------------------------------------------- |
| 处理方式 | 整个视频一次性转写 | 音频按语音停顿切片，流式进入 Kafka                  |
| 扩展性   | 单文件串行处理     | Flink 按 stream_id 并行调度多路视频                 |
| 容错性   | 出错从头再来       | 失败片段进入死信队列，支持追踪和复查                |
| 可观测性 | 跑完才知道结果     | Dashboard 实时展示每条数据的处理状态                |
| 输出     | 一个字幕文件       | 字幕 + 关键词 + 热词 + 指标 + 数据库                |
| 课程覆盖 | 只涉及 API 调用    | Kafka + Flink + VAD + ASR + Redis + SQLite + Docker |

---

## 2. 技术选型

每种技术的选择都有明确的原因，并对应课程中的知识点。按层次分组如下：

### 基础设施与容器化

| 技术                          | 版本   | 解决的问题                                   | 课程知识点 |
| ----------------------------- | ------ | -------------------------------------------- | ---------- |
| **Docker**              | -      | 统一开发与运行环境，消除"在我机器上能跑"问题 | 容器化     |
| **Docker Compose**      | -      | 9 个服务的一键编排与启动                     | 服务编排   |
| **NVIDIA CUDA + cuDNN** | 12.4.1 | GPU 加速推理                                 | GPU 计算   |

### 消息队列

| 技术                       | 版本              | 解决的问题                                         | 课程知识点                  |
| -------------------------- | ----------------- | -------------------------------------------------- | --------------------------- |
| **Apache Kafka**     | 7.6.1 (Confluent) | 音频片段、转写结果、关键词事件、热词更新的异步传递 | 消息队列、生产者/消费者模型 |
| **Apache ZooKeeper** | 7.6.1             | Kafka 集群元数据管理与协调                         | 分布式协调                  |
| **aiokafka**         | 0.12.0            | API 与 ASR 服务的异步 Kafka 消费与生产             | 异步 I/O、消息队列          |
| **kafka-python**     | 2.0.2             | Ingest 服务的同步 Kafka 生产                       | 消息队列                    |

### 流式计算

| 技术                                | 版本       | 解决的问题                                          | 课程知识点 |
| ----------------------------------- | ---------- | --------------------------------------------------- | ---------- |
| **Apache Flink**              | 1.18.1     | 流处理引擎：消费 Kafka 音频片段、调度 ASR、写回结果 | 流式计算   |
| **PyFlink**                   | 1.18.1     | Flink DataStream API 的 Python 绑定                 | 流式计算   |
| **flink-sql-connector-kafka** | 3.1.0-1.18 | Flink 与 Kafka 的连接器                             | 流式计算   |

### 语音处理

| 技术                       | 版本                | 解决的问题                                 | 课程知识点       |
| -------------------------- | ------------------- | ------------------------------------------ | ---------------- |
| **FFmpeg**           | -                   | 视频音频提取、格式转换、静音检测           | 多媒体处理       |
| **WebRTC VAD**       | 2.0.14              | 按语音停顿动态切片，避免固定切片的断句问题 | 语音信号处理     |
| **faster-whisper**   | 1.1.0 (CTranslate2) | 本地语音识别，离线可用、GPU 加速           | 机器学习模型部署 |
| **Whisper large-v3** | -                   | 语音识别的预训练模型                       | 深度学习模型     |
| **hf_transfer**      | 0.1.9               | 加速 Hugging Face 模型下载                 | 模型管理         |

### 后端服务

| 技术                       | 版本    | 解决的问题                                 | 课程知识点         |
| -------------------------- | ------- | ------------------------------------------ | ------------------ |
| **FastAPI**          | 0.115.6 | API 服务的 Web 框架，自动生成 OpenAPI 文档 | Web 服务、REST API |
| **uvicorn**          | 0.34.0  | ASGI 服务器，运行 FastAPI 应用             | Web 服务           |
| **pydantic**         | 2.10.4  | 请求/响应数据校验                          | 数据验证           |
| **python-multipart** | 0.0.20  | 桌面端音频上传的表单解析                   | HTTP 文件上传      |

### 存储

| 技术             | 版本          | 解决的问题                         | 课程知识点           |
| ---------------- | ------------- | ---------------------------------- | -------------------- |
| **Redis**  | 7-alpine      | Dashboard 实时数据缓存，毫秒级查询 | 缓存系统、内存数据库 |
| **SQLite** | Python stdlib | 结构化实验数据持久化，支持统计查询 | 关系型数据库         |
| **JSONL**  | -             | 追加式日志存储，支持实验追溯与回放 | 数据持久化           |

### 中文 NLP

| 技术             | 版本   | 解决的问题                                      | 课程知识点   |
| ---------------- | ------ | ----------------------------------------------- | ------------ |
| **jieba**  | 0.42.1 | 中文分词、TextRank 关键词提取、词性标注         | 自然语言处理 |
| **OpenCC** | 0.1.7  | 繁简体中文统一转换（Traditional → Simplified） | 文本预处理   |

### 前端与桌面端

| 技术                       | 版本 | 解决的问题                 | 课程知识点   |
| -------------------------- | ---- | -------------------------- | ------------ |
| **Electron**         | 39   | 跨平台桌面应用框架         | 桌面应用开发 |
| **React**            | 19   | 前端 UI 组件化开发         | 前端开发     |
| **TypeScript**       | 5.9  | 类型安全的 JavaScript 开发 | 编程语言     |
| **Vite**             | 7    | 前端构建与开发服务器       | 前端工程化   |
| **electron-builder** | 26   | Windows 安装包打包与分发   | 软件分发     |

### 可选扩展（AI 字幕增强）

| 技术                                | 版本     | 解决的问题                           | 课程知识点     |
| ----------------------------------- | -------- | ------------------------------------ | -------------- |
| **Textual**                   | ≥0.85.0 | 终端交互式 UI（TUI）框架             | 交互式应用     |
| **OpenAI-compatible LLM API** | -        | 字幕的上下文审校、术语统一、语义润色 | 大语言模型应用 |
| **RAG**                       | -        | 基于领域知识库的检索增强生成         | 检索增强生成   |

### 字幕格式与评测

| 技术                   | 用途                              |
| ---------------------- | --------------------------------- |
| **SRT** (SubRip) | 标准字幕格式，兼容主流视频播放器  |
| **VTT** (WebVTT) | Web 标准字幕格式，兼容 HTML5 视频 |
| **CER / WER**    | 字错率 / 词错率，衡量字幕识别质量 |
| **MIT License**  | 开源许可协议                      |

---

## 3. 开发环境

### 3.1 需要什么

| 软件                            | 用途                           |
| ------------------------------- | ------------------------------ |
| Docker Desktop + Docker Compose | 运行全部后端服务               |
| FFmpeg                          | 视频音频提取                   |
| Python 3.11+                    | 运行离线工具脚本               |
| NVIDIA GPU（推荐）              | 加速语音识别；CPU 模式也可运行 |

### 3.2 三步启动

```powershell
# 1. 配置环境
Copy-Item .env.example .env

# 2. 一键启动全部服务（Kafka、Flink、ASR、API、Redis、Dashboard）
docker compose up -d --build

# 3. 放入测试视频，开始转写
# 将视频放到 videos/input.mp4，系统自动处理
```

首次启动时 ASR 服务会自动下载模型（约 3GB），耗时取决于网络。

### 3.3 启动后可访问

| 页面                | 地址                         | 用途                       |
| ------------------- | ---------------------------- | -------------------------- |
| **Dashboard** | http://localhost:8000        | 实时字幕、关键词、指标曲线 |
| API 健康检查        | http://localhost:8000/health | 确认聚合服务正常           |
| ASR 健康检查        | http://localhost:8001/health | 确认模型已加载             |
| Flink Web UI        | http://localhost:8081        | 查看流处理作业状态         |

### 3.4 验证系统运行

```powershell
docker compose ps                    # 查看所有服务状态
python tools/smoke_check.py          # 6 项自动检查
```

`smoke_check.py` 自动检查：① API 健康 ② ASR 健康 ③ Flink 作业 ④ Docker 核心服务 ⑤ Kafka Topic 完整性 ⑥ 指标接口可访问性。

> CPU 环境：修改 `.env` 中 `ASR_MODEL=medium`、`ASR_DEVICE=cpu`、`ASR_COMPUTE_TYPE=int8`，并删除 `docker-compose.yml` 中 `asr` 服务的 `gpus: all`。

---

## 4. 核心技术

### 4.1 数据是如何流动的？

整个系统像一条**流水线**，每个环节只做一件事，通过 Kafka（消息队列）传递数据：

```mermaid
flowchart LR
    subgraph Input["数据输入"]
        Video["视频文件"]
        Camera["摄像头"]
        Mic["麦克风"]
    end

    subgraph Ingest["语音接入层"]
        FFmpeg["FFmpeg 抽取音频"]
        VAD["VAD 按语音停顿切片"]
    end

    subgraph Stream["流处理层"]
        AudioTopic["Kafka<br/>audio-segment"]
        Flink["PyFlink<br/>调度引擎"]
        ASR["faster-whisper<br/>语音识别"]
        ResultTopic["Kafka<br/>transcription-result"]
    end

    subgraph Analysis["分析层"]
        API["FastAPI 聚合服务"]
        Keywords["关键词提取"]
        Hotwords["热词发现"]
        Sentence["句子缓冲"]
    end

    subgraph Output["输出层"]
        Dashboard["Web Dashboard"]
        Redis["Redis 实时缓存"]
        JSONL["JSONL 追溯文件"]
        SQLite["SQLite 数据库"]
        Subtitle["SRT / VTT 字幕"]
        Desktop["Electron 桌面端"]
    end

    Video --> FFmpeg
    Camera --> FFmpeg
    Mic --> FFmpeg
    FFmpeg --> VAD --> AudioTopic --> Flink --> ASR --> ResultTopic --> API
    API --> Sentence --> Keywords --> Hotwords
    API --> Dashboard
    API --> Redis
    API --> JSONL
    API --> SQLite
    API --> Subtitle
    API --> Desktop
```

### 4.2 每一步发生了什么？

```mermaid
sequenceDiagram
    participant Source as  视频/麦克风
    participant Ingest as  Ingest + VAD
    participant Kafka as  Kafka
    participant Flink as  PyFlink
    participant ASR as  faster-whisper
    participant API as  FastAPI
    participant UI as  Dashboard

    Source->>Ingest: 连续音频流
    Ingest->>Ingest: VAD 检测语音停顿<br/>按自然句边界切片
    Ingest->>Kafka: 音频片段消息<br/>（含路径、时间戳）
    Kafka->>Flink: 持续消费片段
    Flink->>ASR: HTTP 转写请求<br/>（附加热词提示）
    ASR-->>Flink: 识别文本 + 置信度<br/>+ 推理耗时
    Flink->>Kafka: 转写结果<br/>（含各阶段耗时）
    Kafka->>API: 消费转写结果
    API->>API: 句子缓冲合并<br/>关键词提取<br/>热词自动发现
    API->>UI: 字幕实时推送<br/>关键词标签<br/>延迟和状态
```

### 4.3 架构层次一览

| 层次     | 技术                             | 代码位置                                       | 职责                                   |
| -------- | -------------------------------- | ---------------------------------------------- | -------------------------------------- |
| 数据接入 | FFmpeg + WebRTC VAD              | `services/ingest/`                           | 视频音频抽取、按语音停顿切片           |
| 消息队列 | Kafka + Zookeeper                | `docker-compose.yml`                         | 解耦各服务，5 个 Topic 分工明确        |
| 流处理   | PyFlink                          | `flink/`                                     | 消费片段、调度 ASR、记录耗时、失败路由 |
| 语音识别 | FastAPI + faster-whisper         | `services/asr/`                              | 加载本地模型、GPU 推理、质量过滤       |
| 聚合分析 | FastAPI + jieba + Redis + SQLite | `services/api/`                              | 句子合并、关键词提取、热词发现、持久化 |
| 可视化   | HTML/CSS/JS + Electron + React   | `services/api/static/`、`desktop-ui-live/` | 实时 Dashboard、桌面端                 |
| AI 增强  | RAG + LLM                        | `subtitle-agent/`                            | 可选：术语统一、语义审校、样式字幕     |

### 4.4 Kafka 五个 Topic 的分工

| Topic                           | 传递什么数据                     | 谁生产      | 谁消费           |
| ------------------------------- | -------------------------------- | ----------- | ---------------- |
| `audio-segment`               | 音频切片的路径、时间戳、来源信息 | Ingest 服务 | Flink 作业       |
| `transcription-result`        | 识别文本、各阶段耗时、置信度     | Flink 作业  | API 服务         |
| `keyword-event`               | 提取的关键词、主题变化事件       | API 服务    | （供下游扩展）   |
| `streamsense.hotword.updates` | 动态发现的热词列表               | API 服务    | ASR 服务         |
| `transcription-failed`        | 重试后仍失败的片段               | Flink 作业  | API 服务（追踪） |

---

## 5. 数据规格

整个系统的数据格式设计遵循统一原则：**每个环节保留完整的时间戳，可以精确追踪每条数据在链路中的停留时间**。

### 5.1 音频片段消息（`audio-segment` Topic）

音频数据不直接放入 Kafka（体积太大），而是将音频保存为 WAV 文件，消息中携带文件路径和元信息：

```json
{
  "segment_id":       "demo-video-a3f2b1c0-000001",
  "stream_id":        "demo-video",
  "run_id":           "a3f2b1c0",
  "file_path":        "/data/audio/demo-video_a3f2b1c0_000001.wav",
  "start_time":       0.0,
  "end_time":         3.0,
  "duration":         3.0,
  "start_time_ms":    0,
  "end_time_ms":      3000,
  "duration_ms":      3000,
  "sample_rate":      16000,
  "created_at":       1713960000123,
  "kafka_sent_at":    1713960000456,
  "source_type":      "file"
}
```

> **关键字段说明**：`start_time_ms`/`end_time_ms` 记录这段音频在原视频中的位置；`kafka_sent_at` 标记消息何时发送到 Kafka；`sample_rate=16000` 表示 16kHz 单声道 WAV，这是语音识别的标准输入格式。

### 5.2 转写结果消息（`transcription-result` Topic）

Flink 调用 ASR 后将识别结果与性能数据合并，写回 Kafka：

```json
{
  "segment_id":       "demo-video-a3f2b1c0-000001",
  "stream_id":        "demo-video",
  "session_id":       "demo-video:a3f2b1c0",
  "text":             "本节课介绍 Kafka 在实时数据处理中的作用",
  "language":         "zh",
  "language_probability": 0.98,
  "segments": [
    {
      "start": 0.0, "end": 1.5,
      "text": "本节课介绍 Kafka",
      "avg_logprob": -0.32,
      "no_speech_prob": 0.05
    }
  ],
  "audio_dbfs":       -22.5,
  "hotwords_used":    ["Kafka", "Flink"],
  "inference_time_ms": 1180,
  "model":            "large-v3",
  "device":           "cuda",
  "compute_type":     "float16",
  "status":           "ok",
  "retry_count":      0,
  "end_to_end_time_ms": 1788,
  "flink_process_time_ms": 1300,
  "kafka_flink_dispatch_time_ms": 44
}
```

> **关键字段说明**：`text` 是识别出的中文文本；`segments` 是 Whisper 模型输出的逐段结果，包含 `avg_logprob`（平均对数概率，衡量识别置信度）和 `no_speech_prob`（无语音概率，用于过滤静音段）；`end_to_end_time_ms` 是从音频创建到结果写回的总耗时；`status: "ok"` 表示处理成功。

### 5.3 关键词事件消息（`keyword-event` Topic）

API 服务对每个完整句子提取关键词后发布：

```json
{
  "event_id":         "e7f3a1b2c4d5",
  "stream_id":        "demo-video",
  "session_id":       "demo-video:a3f2b1c0",
  "event_type":       "custom_hit",
  "keywords": [
    {"word": "Kafka",      "score": 1.0, "source": "custom"},
    {"word": "实时数据",    "score": 1.0, "source": "custom"},
    {"word": "消息队列",    "score": 0.85, "source": "textrank"}
  ],
  "source_text":      "本节课介绍 Kafka 在实时数据处理中的作用",
  "start_time_ms":    0,
  "end_time_ms":      5200,
  "created_at_ms":    1713960020000
}
```

> **事件类型说明**：`custom_hit`——命中了自定义词表中的关键词（优先展示）；`keyword`——通过 TextRank 算法从文本中自动提取；`topic_shift`——当前句子的关键词与上一句重叠度低于阈值（35%），表示话题可能发生了变化。

### 5.4 热词更新消息（`streamsense.hotword.updates` Topic）

系统自动从转写文本中发现高频专业词汇，广播给 ASR 服务用于提升后续识别准确率：

```json
{
  "stream_id":  "demo-video",
  "session_id": "demo-video:a3f2b1c0",
  "terms": [
    {
      "word":          "Kafka",
      "count":         15,
      "recent_count":  5,
      "score":         17.5,
      "source":        "auto_discovery",
      "confirmed":      true
    }
  ],
  "created_at_ms": 1713960025000
}
```

> **热词自动学习机制**：系统维护一个 5 分钟的滑动窗口，统计近期转写文本中名词和动词的出现频率。当某个词的出现次数超过阈值（默认 5 次）且平均识别置信度达标时，自动加入热词列表并广播给 ASR 服务——下一轮识别就会带上这个词作为提示，形成"越识别越准"的正向循环。

### 5.5 存储策略：三层分工

| 存储层                     | 存什么                         | 用途                                   |
| -------------------------- | ------------------------------ | -------------------------------------- |
| **Redis**（内存）    | 最近 200 条字幕 + 500 条关键词 | Dashboard 实时查询，毫秒级响应         |
| **JSONL**（文件）    | 每条转写结果追加一行 JSON      | 实验追溯、Bug 排查、写报告时回溯       |
| **SQLite**（数据库） | 结构化统计表                   | 按 stream 查平均延迟、成功率、重试次数 |

---

## 6. 功能实现

### 6.1 核心功能清单

| 功能                          | 实现方式                                           | 验证方式                                  |
| ----------------------------- | -------------------------------------------------- | ----------------------------------------- |
| **视频接入**            | FFmpeg 读取音轨，支持本地文件、RTSP、HTTP/FLV      | 实时 Dashboard 可观察                     |
| **VAD 动态切片**        | WebRTC VAD 按语音停顿拆分（30ms 粒度），避免断句   | 对比固定切片与 VAD 切片结果               |
| **Kafka 消息队列**      | 5 个 Topic，3 分区，解耦上下游                     | `smoke_check.py` 自动检查               |
| **Flink 流处理**        | PyFlink 作业消费→调度 ASR→写回结果，支持失败重试 | Flink Web UI 查看作业状态                 |
| **本地语音识别**        | faster-whisper large-v3，GPU 推理                  | ASR 健康检查 + 转写结果                   |
| **关键词分析**          | 自定义词表优先 → TextRank → 词频兜底             | Dashboard 关键词标签                      |
| **动态热词**            | 滑动窗口自动发现高频词，广播提升识别准确率         | 热词 API + Dashboard                      |
| **三层存储**            | Redis（实时）+ JSONL（追溯）+ SQLite（统计）       | `/api/database/summary`                 |
| **可视化 Dashboard**    | 实时字幕、关键词、延迟曲线、系统状态               | 浏览器直接访问                            |
| **双桌面端**            | 在线端（麦克风+摄像头）+ 离线端（视频文件）        | Electron 独立运行                         |
| **自动化验收**          | 6 项检查：API、ASR、Flink、Docker、Topic、指标     | `python tools/smoke_check.py`           |
| **字幕导出**            | SRT / VTT / JSON / TXT 多格式                      | `/api/streams/{id}/export`              |
| **质量评测**            | CER（字错率）、WER（词错率）、关键词命中率         | `python tools/evaluate_subtitles.py`    |
| **性能压测**            | 支持多路并发，记录分阶段延迟                       | `python tools/benchmark_streamsense.py` |
| **AI 字幕增强**（可选） | LLM + RAG 上下文审校、术语统一                     | `subtitle-agent/` 独立模块              |

### 6.2 字幕质量控制

ASR 服务内置多层过滤机制，减少静音、噪声和模型幻觉产生的错误字幕：

| 过滤层       | 方法                                       | 效果                      |
| ------------ | ------------------------------------------ | ------------------------- |
| 音频能量过滤 | 检测音频 dBFS，跳过近静音片段              | 减少无声段的错误输出      |
| VAD 语音检测 | WebRTC VAD 判断是否有语音                  | 过滤纯背景音乐和噪声      |
| 置信度过滤   | `no_speech_prob` 和 `avg_logprob` 阈值 | 过滤低质量转写结果        |
| 重复模式过滤 | 检测单字重复（"鸟、鸟、鸟"）               | 过滤模型幻觉输出          |
| 固定模板过滤 | 匹配常见幻觉文本（"感谢观看"等）           | 过滤 Whisper 已知幻觉模式 |
| 繁简转换     | OpenCC t2s 统一输出简体中文                | 避免繁简混合输出          |

---

## 7. 代码规范

### 7.1 项目目录结构

```text
.
├── config/                        # 配置：自定义关键词、纠错表、领域词包
│   ├── custom_keywords.txt        #   跨视频通用关键词
│   ├── asr_corrections.txt        #   常见误识别纠正表
│   └── profiles/                  #   领域 Profile（大数据/会议/课程）
├── services/                      # Docker 化的微服务（各司其职）
│   ├── ingest/                    #   视频接入 + VAD 切片
│   │   ├── ingest_video.py        #     主程序（FFmpeg + WebRTC VAD）
│   │   └── requirements.txt       #     kafka-python, webrtcvad
│   ├── asr/                       #   语音识别服务
│   │   ├── asr_service.py         #     主程序（faster-whisper + 质量过滤）
│   │   └── requirements.txt       #     faster-whisper, opencc, fastapi
│   ├── api/                       #   聚合分析 + Dashboard
│   │   ├── app.py                 #     主程序（句子缓冲 + 关键词 + 热词 + 指标）
│   │   ├── storage.py             #     SQLite 数据库操作
│   │   ├── static/                #     Dashboard 前端页面
│   │   └── requirements.txt       #     fastapi, jieba, redis, aiokafka
│   └── ...
├── flink/                         # PyFlink 流处理作业
│   ├── transcription_job.py       #   核心作业：消费→调用 ASR→写回
│   └── Dockerfile                 #   基于 apache/flink:1.18.1
├── tools/                         # 离线工具（不依赖 Docker）
│   ├── generate_video_subtitles.py #   离线字幕一键生成
│   ├── evaluate_subtitles.py      #   字幕质量评测（CER/WER）
│   ├── benchmark_streamsense.py   #   性能压测
│   ├── smoke_check.py             #   自动化验收（6 项检查）
│   └── query_results.py           #   SQLite 结果查询
├── desktop-ui/                    # Electron 离线桌面端
├── desktop-ui-live/               # Electron 实时桌面端
├── subtitle-agent/                # AI 字幕增强（可选扩展）
├── docs/                          # 19 篇文档
├── examples/                      # 脱敏示范案例
├── docker-compose.yml             # 9 个服务的统一编排
├── .env.example                   # 60+ 配置项模板
└── README.md                      # 本文件
```

### 7.2 代码组织原则

- **垂直拆分**：按数据流经的环节划分模块，每个 `services/` 子目录是一个独立的 Docker 服务
- **单一职责**：每个服务只有一个主 Python 文件 + 独立的 `requirements.txt`
- **配置外置**：所有可变参数通过 `.env` 环境变量控制（60+ 项），代码中无硬编码
- **关注点分离**：Flink 负责调度（不装 CUDA）、ASR 服务负责推理（独占 GPU）、API 负责分析（无状态）

---

## 8. 实验结果

下面是在真实 Docker 环境中完成的性能压测结果。测试链路为完整 7 步：

```text
FFmpeg 音频抽取 → VAD 切片 → Kafka 缓冲 → Flink 调度 → ASR 识别 → API 聚合 → Redis/JSONL/SQLite 存储
```

| 场景                     | 成功片段 | 失败 | 平均延迟 | P95 延迟 |                       说明 |  |
| ------------------------ | -------- | ---- | -------: | -------: | -------------------------: | - |
| **2 路视频并发**  | 230      | 0    |  ~4.1 秒 |  ~6.8 秒 | **推荐用于课程报告** |  |
| 4 路视频并发             | 39       | 0    |  ~9.9 秒 | ~14.5 秒 | 排队延迟增加，仍可稳定运行 |  |

> 推荐以 **2 路视频并发** 的实验结果作为课程报告数据：零失败、平均延迟约 4 秒、P95 延迟约 6.8 秒——充分证明了 Kafka-Flink 管线在处理多路实时视频时的稳定性和有效性。

完整实验过程、瓶颈分析和各阶段耗时分解见：[docs/本次性能压测实验报告.md](./docs/本次性能压测实验报告.md)。

此外，我们还完成了 **模型对比实验**（large-v3 / medium / small 三种模型在识别准确率和推理速度上的对比），详见：[docs/模型对比实验报告.md](./docs/模型对比实验报告.md)。

---

## 9. 说明文档

项目配套了完整的文档体系，覆盖从原理到操作、从验收到评测的各个环节：

| #  |                                                   文档 | 解决什么问题                                 |
| -- | -----------------------------------------------------: | -------------------------------------------- |
| 1  |                                  [README.md](./README.md) | 项目全貌：是什么、怎么做、效果如何           |
| 2  |                         [原理解说.md](./docs/原理解说.md) | 为什么这样设计？Kafka/Flink/VAD/ASR 各做什么 |
| 3  |                 [新手上手文档.md](./docs/新手上手文档.md) | 从克隆仓库到成功运行，逐步操作               |
| 4  |             [自动化验收说明.md](./docs/自动化验收说明.md) | 如何用 smoke_check.py 验证系统完整性         |
| 5  |             [结果数据库说明.md](./docs/结果数据库说明.md) | Redis / JSONL / SQLite 三层存储的分工        |
| 6  |             [system_metrics.md](./docs/system_metrics.md) | 指标字段含义和 API 用法                      |
| 7  |                       [benchmark.md](./docs/benchmark.md) | 如何运行性能压测                             |
| 8  | [本次性能压测实验报告.md](./docs/本次性能压测实验报告.md) | 2 路、4 路并发的实验结果与瓶颈分析           |
| 9  |         [模型对比实验报告.md](./docs/模型对比实验报告.md) | large-v3 vs medium vs small 模型对比         |
| 10 |         [字幕质量评测说明.md](./docs/字幕质量评测说明.md) | CER/WER 计算和关键词命中率评估               |
| 11 |           [领域Profile说明.md](./docs/领域Profile说明.md) | 如何切换不同领域（大数据/会议/课程）的词表   |
| 12 |       [Git提交与仓库说明.md](./docs/Git提交与仓库说明.md) | 仓库发布规范，哪些内容不上传                 |
| 13 |     [问题解决与拓展路线.md](./docs/问题解决与拓展路线.md) | 开发中遇到的问题、解决方法和未来方向         |
| 14 |                         [文档导航.md](./docs/文档导航.md) | 文档分类和推荐阅读顺序                       |

此外，`examples/` 目录提供了一份脱敏后的完整演示案例（字幕 + 关键词 + 指标），可以直接打开浏览，了解系统的输出效果：[examples/README.md](./examples/README.md)。

---

## 10. 遇到的问题与解决方法

开发过程中重点解决了以下问题，每个问题都有明确的解决方案和代码对应：

| 问题                     | 现象                                              | 解决方法                                                                      | 效果                         |
| ------------------------ | ------------------------------------------------- | ----------------------------------------------------------------------------- | ---------------------------- |
| 固定切片截断句子         | 固定 6 秒切片会把一句话从中间切断                 | 改用 WebRTC VAD 按语音停顿动态切片 + API 层句子缓冲                           | Dashboard 字幕更接近自然句子 |
| 专业词识别不准           | "Kafka"被识别成"卡夫卡"，"Flink"误识              | 自定义关键词表 + 纠错表 + 动态热词自动发现                                    | 领域词识别准确率持续提升     |
| 静音/噪声误出字幕        | 背景音乐中 Whisper 输出流畅但错误的文本           | 能量过滤 + no_speech_prob 阈值 + 重复模式过滤 + 常见幻觉文本匹配              | 无效字幕大幅减少             |
| ASR 偶发失败丢片段       | 网络抖动导致 HTTP 请求超时，片段丢失              | Flink 调用 ASR 时增加 3 次重试（指数退避），失败写入 `transcription-failed` | 失败片段可追踪、可复查       |
| Docker 重启后 Kafka 故障 | Zookeeper 旧 broker 注册未过期导致 Kafka 无法启动 | 等待 ZK 临时节点过期后重启，再重新初始化 Topic                                | 已通过 6/6 冒烟测试验证      |
| 仓库发布文件过大         | 模型、视频、结果文件体积超 GB                     | `.gitignore` 精确排除大体积目录，仓库只保留源码和文档                       | GitHub 仓库精简              |

---

## 11. 限制与后续方向

### 当前限制

- 默认配置使用 NVIDIA GPU；CPU 环境需手动调整 `.env`（详见第 3 节说明）
- 首次运行需要下载 faster-whisper 模型（约 3GB）
- 当前定位为课程设计和本地实验，不是多节点生产集群部署
- AI 字幕增强（`subtitle-agent/`）是可选模块，需要单独配置 LLM API Key

### 后续拓展路线

```mermaid
flowchart LR
    Current["当前<br/>单机 Kafka-Flink<br/>+ 本地 ASR"]
    Short["短期<br/>补充单测<br/>冷启动优化<br/>可视化报告"]
    Mid["中期<br/>说话人分离<br/>RTSP 实时流接入<br/>单文件离线评测"]
    Long["长期<br/>多节点 Flink 集群<br/>对象存储<br/>模型服务化"]
  
    Current --> Short --> Mid --> Long
```

---

## License

本项目采用 [MIT License](./LICENSE)。
