# StreamSense

> 面向中文视频的 AI 字幕 Agent：本地 ASR 初稿、RAG 上下文增强、LLM 审校、Kafka/Flink 实时流处理、ASS 样式字幕导出。  
> AI-powered Chinese video subtitle agent with local ASR, RAG, LLM revision, Kafka/Flink streaming, and styled ASS subtitle export.

![Python](https://img.shields.io/badge/Python-3.11-3776AB?style=flat-square&logo=python&logoColor=white)
![TypeScript](https://img.shields.io/badge/TypeScript-Electron-3178C6?style=flat-square&logo=typescript&logoColor=white)
![Docker](https://img.shields.io/badge/Docker-Compose-2496ED?style=flat-square&logo=docker&logoColor=white)
![Kafka](https://img.shields.io/badge/Kafka-Streaming-231F20?style=flat-square&logo=apachekafka&logoColor=white)
![Flink](https://img.shields.io/badge/Flink-Processing-E6526F?style=flat-square&logo=apacheflink&logoColor=white)
![Textual](https://img.shields.io/badge/Textual-TUI-7C3AED?style=flat-square)
![LLM](https://img.shields.io/badge/LLM-OpenAI--compatible-10A37F?style=flat-square)

## 项目简介 / Introduction

StreamSense 是一个围绕“中文视频字幕生成与字幕体验优化”构建的本地工程项目。它可以把真实视频、摄像头、麦克风或直播流里的声音转成字幕，并进一步用 **AI Agent + RAG** 做错词修正、术语一致性、字幕节奏优化和样式化导出。

StreamSense is a local engineering project for Chinese video transcription and subtitle refinement. It converts audio from videos, cameras, microphones, or live streams into subtitles, then improves them with an AI Agent, RAG context, LLM-based revision, rhythm tuning, and styled ASS export.

这个仓库包含两条能力线：

- **Subtitle Agent**：面向本地视频的离线字幕 Agent，重点是字幕质量、可读性和可解释审校。
- **Kafka/Flink Streaming ASR**：面向课程设计和大数据演示的实时字幕链路，重点是流式处理、服务解耦和可观测性。

This repository contains two major tracks:

- **Subtitle Agent**: an offline subtitle refinement agent for local videos.
- **Kafka/Flink Streaming ASR**: a real-time streaming transcription pipeline for data-engineering demos.

## 为什么做这个项目 / Why This Project

普通 ASR 工具通常只输出一份初稿字幕。StreamSense 更进一步，把字幕后处理做成一条可追踪的 Agent 工作流：先生成字幕初稿，再检索上下文，最后由 AI 分阶段完成审校、统一、排版和导出。

Most ASR tools only generate a raw transcript. StreamSense goes further by turning subtitle post-processing into a traceable Agent workflow: draft generation, context retrieval, staged AI review, consistency enforcement, readability tuning, and export.

```text
Video
  -> local ASR draft
  -> RAG context retrieval
  -> full-video AI context brief
  -> dynamic glossary
  -> segment-level correction
  -> global term consistency
  -> semantic subtitle polish
  -> rhythm and readability tuning
  -> SRT / ASS / report outputs
```

## 核心亮点 / Highlights

| 能力 / Capability | 说明 / What It Does |
| --- | --- |
| 本地 ASR 初稿 / Local ASR draft | 调用项目原有离线字幕链路生成第一版字幕。 |
| AI 字幕 Agent / AI Subtitle Agent | 使用 OpenAI-compatible LLM API 做上下文感知字幕审校。 |
| RAG 上下文增强 / RAG grounding | 检索项目文档、领域 profile、历史字幕和 Agent 知识作为参考。 |
| 动态术语表 / Dynamic glossary | 根据当前视频动态归纳术语，而不是只依赖静态替换表。 |
| 全局术语一致性 / Term consistency | 检查同一视频里反复出现的 ASR 变体，并统一高置信度词汇。 |
| 语义排版优化 / Semantic polish | 在不改写原意的前提下，改善不自然断句和阅读体验。 |
| 字幕节奏优化 / Rhythm tuning | 调整字幕显示时长和行宽，让字幕更容易看清。 |
| ASS 样式导出 / Styled ASS export | 导出 clean 和 creator 两种 ASS 字幕样式。 |
| 可解释输出 / Traceable outputs | 保存 JSON / Markdown 报告，方便查看 Agent 改了什么、为什么改。 |
| 实时流处理 / Streaming demo | 包含 Kafka、Flink、ASR、Redis、FastAPI 和实时桌面端。 |

## Agent 输出示例 / Agent Output Example

Agent 不会静默改字幕，而是保存每一处修改记录。  
The Agent keeps revision records instead of silently changing text.

```json
{
  "original_text": "今天我们来瑞屏这个角色",
  "revised_text": "今天我们来锐评这个角色",
  "reason": "同音误识别，结合上下文应为网络词“锐评”。",
  "confidence": 0.95,
  "source": "llm_dynamic_segment_revision"
}
```

典型任务输出 / Typical task outputs:

```text
data/results/agent_tasks/<agent_task_id>/
├── original.srt
├── revised.srt
├── revised.ass
├── revised.clean.ass
├── revised.creator.ass
├── ai_context_brief.json
├── ai_glossary.json
├── ai_segment_revisions.json
├── term_consistency_report.json
├── semantic_edit_report.json
├── rhythm_report.json
├── subtitle_integrity_report.json
├── agent_suggestions.json
├── agent_report.md
└── run_log.txt
```

## 快速开始：Subtitle Agent / Quick Start

如果你只想体验 AI 字幕 Agent，建议从这里开始。  
If you only want to try the AI subtitle workflow, start here.

```powershell
cd subtitle-agent
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
```

编辑 `subtitle-agent/.env`：

```env
LLM_API_BASE=https://api.deepseek.com
LLM_API_KEY=your_api_key_here
LLM_MODEL=deepseek-v4-flash
```

启动 Textual TUI：

```powershell
python app.py
```

进入界面后粘贴视频路径，然后输入：

```text
:run
```

快捷键 / Hotkeys:

| 按键 / Key | 功能 / Action |
| --- | --- |
| `v` | 设置视频路径 / Set video path |
| `p` | 设置领域 Profile / Set domain profile |
| `g` | 运行 Agent / Run Agent |
| `l` | 清空日志 / Clear log |
| `q` | 退出 / Quit |

命令行模式 / CLI mode:

```powershell
python agent_main.py --video ..\input2.mp4 --profile bigdata --goal "生成高质量字幕并检查专业词"
```

## 快速开始：Kafka/Flink 实时链路 / Streaming Stack

如果你想运行大数据实时字幕链路：

```powershell
Copy-Item .env.example .env
docker compose up -d --build
```

打开服务 / Open services:

| 服务 / Service | 地址 / URL |
| --- | --- |
| Dashboard | http://localhost:8000 |
| ASR health | http://localhost:8001/health |
| Flink Web UI | http://localhost:8081 |

运行实时桌面端 / Run live desktop app:

```powershell
cd desktop-ui-live
npm install
npm run electron:dev
```

## 原始离线字幕生成器 / Offline Subtitle Generator

如果你只想运行不带 Agent 的原始离线字幕生成：

```powershell
python tools/generate_video_subtitles.py --media-path videos/input.mp4 --output-dir data/results/input --basename input
```

桌面端 / Desktop UI:

```powershell
cd desktop-ui
npm install
npm run electron:dev
```

## 架构 / Architecture

### Subtitle Agent Pipeline

```text
subtitle-agent/app.py
  -> agent/executor.py
  -> tools/generate_video_subtitles.py
  -> RAG index
  -> context_analyzer.py
  -> glossary.py
  -> ai_corrector.py
  -> consistency_agent.py
  -> semantic_editor.py
  -> readability_tool.py + rhythm_tool.py
  -> export_tool.py
  -> revised.srt / revised.ass / reports
```

### Streaming Pipeline

```text
Camera / microphone / video stream
  -> live-ingest
  -> Kafka audio-segment topic
  -> PyFlink transcription job
  -> local faster-whisper ASR service
  -> Kafka transcription-result topic
  -> FastAPI aggregation
  -> Redis + result files + dashboard + desktop live UI
```

## 项目目录 / Project Layout

```text
.
├── subtitle-agent/                 # AI 字幕 Agent 和 Textual TUI
├── desktop-ui/                     # 离线字幕桌面端
├── desktop-ui-live/                # 实时字幕桌面端
├── services/
│   ├── api/                        # FastAPI dashboard and result API
│   ├── asr/                        # local faster-whisper ASR service
│   └── ingest/                     # video/audio ingest
├── flink/                          # PyFlink transcription job
├── tools/                          # subtitle generation, batch scripts, benchmark tools
├── config/                         # domain profiles, hotwords, ASR correction hints
├── docs/                           # detailed docs, reports, teaching material
├── data/                           # runtime outputs, ignored by Git
├── models/                         # local ASR model cache, ignored by Git
└── docker-compose.yml              # Kafka/Flink/Redis/API/ASR stack
```

## 为什么它算 Agent / What Makes It an Agent

`subtitle-agent/` 被拆成多个可检查阶段，而不是一个隐藏的单次 prompt。

The `subtitle-agent/` workflow is intentionally split into inspectable stages instead of a single hidden prompt.

| 阶段 / Stage | 输出 / Output | 目的 / Purpose |
| --- | --- | --- |
| 任务规划 / Planning | `agent_plan.json` | 记录任务处理策略。 |
| RAG 检索 / RAG | `rag_hits.json`, `rag_index.jsonl` | 在纠错前检索上下文。 |
| 全片理解 / Context brief | `ai_context_brief.json` | 理解主题、口吻、术语和字幕策略。 |
| 动态术语 / Dynamic glossary | `ai_glossary.json` | 从当前视频和 RAG 中归纳术语。 |
| 逐段修正 / Segment revision | `ai_segment_revisions.json` | 保存修正前后文本、理由和置信度。 |
| 术语一致性 / Consistency | `term_consistency_report.json` | 统一全片反复出现的高置信度术语。 |
| 语义排版 / Semantic edit | `semantic_edit_report.json` | 改善字幕可读性，但尽量不改写说话含义。 |
| 节奏优化 / Rhythm | `rhythm_report.json` | 调整显示时长和阅读速度。 |
| 完整性检查 / Integrity | `subtitle_integrity_report.json` | 避免导出后出现空白字幕段。 |

## 字幕样式 / Subtitle Styles

| 文件 / File | 用途 / Use Case |
| --- | --- |
| `revised.srt` | 普通字幕文件，适合播放器和剪辑软件。 |
| `revised.clean.ass` | 干净通用版 ASS 字幕。 |
| `revised.creator.ass` | 更适合短视频和创作者内容的 ASS 字幕。 |

`revised.ass` 当前默认指向 clean 风格，方便兼容播放器和剪辑软件。

## 配置 / Configuration

实时链路常用 `.env`：

```env
VIDEO_SOURCE=/videos/input.mp4
STREAM_ID=demo-video
INGEST_SEGMENT_MODE=vad
ASR_MODEL=large-v3
ASR_DEVICE=cuda
ASR_COMPUTE_TYPE=float16
SENTENCE_BUFFER_ENABLED=true
HOTWORD_AUTO_DISCOVERY_ENABLED=true
FLINK_JOB_PARALLELISM=1
```

低资源机器可以改成：

```env
ASR_MODEL=medium
ASR_DEVICE=cpu
ASR_COMPUTE_TYPE=int8
```

Subtitle Agent 的 LLM 配置位于 `subtitle-agent/.env`：

```env
LLM_API_BASE=https://api.deepseek.com
LLM_API_KEY=your_api_key_here
LLM_MODEL=deepseek-v4-flash
SUBTITLE_AGENT_PROFILE=bigdata
SUBTITLE_AGENT_AI_BATCH_SIZE=18
```

## 压测快照 / Benchmark Snapshot

本仓库包含一次真实 Docker 链路压测，测试路径为：

```text
FFmpeg real-time read -> VAD -> Kafka -> Flink -> ASR -> Kafka -> API -> Redis/JSONL/metrics
```

| 场景 / Scenario | 成功片段 | 失败片段 | 平均端到端延迟 | P95 | 说明 / Notes |
| --- | ---: | ---: | ---: | ---: | --- |
| 1 stream | 83 | 0 | 296086 ms | 467350 ms | 受历史 Kafka 积压影响，不作为干净基准。 |
| 2 streams | 230 | 0 | 4084 ms | 6805 ms | 当前最适合作为报告结果。 |
| 4 streams smoke | 39 | 0 | 9865 ms | 14463 ms | 证明 4 路可跑，但排队延迟上升。 |

详细报告 / Detailed report: [docs/本次性能压测实验报告.md](./docs/%E6%9C%AC%E6%AC%A1%E6%80%A7%E8%83%BD%E5%8E%8B%E6%B5%8B%E5%AE%9E%E9%AA%8C%E6%8A%A5%E5%91%8A.md)

## 文档 / Documentation

| 文档 / Document | 用途 / Purpose |
| --- | --- |
| [subtitle-agent/README.md](./subtitle-agent/README.md) | Subtitle Agent setup and outputs. |
| [desktop-ui/README.md](./desktop-ui/README.md) | Offline desktop subtitle generator. |
| [desktop-ui-live/README.md](./desktop-ui-live/README.md) | Real-time live-caption desktop app. |
| [docs/新手上手文档.md](./docs/%E6%96%B0%E6%89%8B%E4%B8%8A%E6%89%8B%E6%96%87%E6%A1%A3.md) | Beginner-friendly onboarding. |
| [docs/原理解说.md](./docs/%E5%8E%9F%E7%90%86%E8%A7%A3%E8%AF%B4.md) | Kafka, Flink, ASR, VAD, keyword analysis explained. |
| [docs/字幕质量评测说明.md](./docs/%E5%AD%97%E5%B9%95%E8%B4%A8%E9%87%8F%E8%AF%84%E6%B5%8B%E8%AF%B4%E6%98%8E.md) | CER/WER and subtitle quality evaluation. |
| [docs/benchmark.md](./docs/benchmark.md) | Benchmark scripts and metrics. |
| [docs/文档导航.md](./docs/%E6%96%87%E6%A1%A3%E5%AF%BC%E8%88%AA.md) | Full documentation map. |

## 常用命令 / Useful Commands

```powershell
# 启动完整实时后端 / Start full streaming backend
docker compose up -d --build

# 查看容器 / Check containers
docker compose ps

# 查看日志 / Tail logs
docker compose logs -f --tail=200

# 停止服务 / Stop stack
docker compose down

# 原始离线字幕生成 / Offline subtitle generation
python tools/generate_video_subtitles.py --media-path videos/input.mp4 --output-dir data/results/input --basename input

# Subtitle Agent TUI
cd subtitle-agent
.\.venv\Scripts\python.exe app.py

# 字幕质量评测 / Subtitle quality evaluation
python tools/evaluate_subtitles.py --candidate data/results/single_test/input2.vtt --reference data/reference/input2_reference.txt --output-dir data/results/evaluation --basename input2

# 冒烟测试 / Smoke check
python tools/smoke_check.py
```

## 当前限制 / Current Limitations

- LLM-based Agent 需要 OpenAI-compatible API key。
- 字幕准确率取决于源音频质量、本地 ASR 模型、领域词汇和 LLM 审校质量。
- Agent 可以改善明显 ASR 错词和可读性，但没有人工参考字幕时不能保证完美。
- 大模型 ASR 对 CPU/GPU 资源有要求。
- Kafka/Flink 链路主要面向本地演示和课程设计实验，不是生产部署模板。

English summary:

- The LLM-based Agent requires an OpenAI-compatible API key.
- Subtitle quality depends on audio quality, ASR model, domain vocabulary, and LLM review.
- The Agent improves obvious ASR errors and readability, but it does not guarantee perfect subtitles without human review.
- Large ASR models require meaningful CPU/GPU resources.
- The Kafka/Flink pipeline is intended for local demos and course-project experiments, not production deployment.

## 路线图 / Roadmap

- [x] 本地离线字幕生成 / Local offline subtitle generation
- [x] Kafka/Flink 实时字幕链路 / Kafka/Flink real-time subtitle pipeline
- [x] Textual TUI 字幕 Agent / Textual TUI for Subtitle Agent
- [x] RAG-assisted LLM subtitle correction
- [x] 动态术语表和逐段修正记录 / Dynamic glossary and revision trace
- [x] 术语一致性、语义排版、节奏优化 / Term consistency, semantic polish, rhythm tuning
- [x] clean / creator ASS 字幕导出 / Styled ASS export
- [ ] HTML 可视化报告 / HTML visual report with before/after comparison
- [ ] GitHub demo 示例包 / Example demo package for GitHub preview
- [ ] 说话人分离 / Optional speaker diarization
- [ ] 更多 Agent profile：course, creator, meeting, tech, anime

## Git 提交注意 / Git Hygiene

不要提交运行产物和密钥：

```text
.env
subtitle-agent/.env
models/
videos/
data/audio/
data/results/
desktop-ui/node_modules/
desktop-ui/release/
desktop-ui-live/node_modules/
desktop-ui-live/release/
```

提交前检查：

```powershell
git status --short
```

## License

本项目采用 MIT License，版权归属为 `Copyright (c) 2026 NJNAN`。  
This project is licensed under the MIT License: `Copyright (c) 2026 NJNAN`.
