# StreamSense

> AI-powered Chinese video subtitle agent with local ASR, RAG, LLM revision, Kafka/Flink streaming, and styled ASS subtitle export.

![Python](https://img.shields.io/badge/Python-3.11-3776AB?style=flat-square&logo=python&logoColor=white)
![TypeScript](https://img.shields.io/badge/TypeScript-Electron-3178C6?style=flat-square&logo=typescript&logoColor=white)
![Docker](https://img.shields.io/badge/Docker-Compose-2496ED?style=flat-square&logo=docker&logoColor=white)
![Kafka](https://img.shields.io/badge/Kafka-Streaming-231F20?style=flat-square&logo=apachekafka&logoColor=white)
![Flink](https://img.shields.io/badge/Flink-Processing-E6526F?style=flat-square&logo=apacheflink&logoColor=white)
![Textual](https://img.shields.io/badge/Textual-TUI-7C3AED?style=flat-square)
![LLM](https://img.shields.io/badge/LLM-OpenAI--compatible-10A37F?style=flat-square)

StreamSense 是一个面向中文视频的字幕生成与字幕体验优化项目。它把真实视频、摄像头、麦克风或直播流里的声音转成字幕，并进一步用 **AI Agent + RAG** 做错词修正、术语一致性、字幕节奏优化和样式化导出。

这个仓库同时保留了两条能力线：

- **Subtitle Agent**：面向本地视频的离线字幕 Agent，重点是字幕质量、可读性和可解释审校。
- **Kafka/Flink Streaming ASR**：面向课程设计/大数据演示的实时字幕链路，重点是流式处理、服务解耦和可观测性。

## Why This Project

普通 ASR 工具通常只输出一份初稿字幕。StreamSense 更进一步，把字幕后处理做成一条可追踪的 Agent 工作流：

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

也就是说，它不只是“识别语音”，而是尝试完成一部分人工字幕审校工作。

## Highlights

| Capability | What It Does |
| --- | --- |
| Local ASR draft | Uses the existing offline subtitle pipeline to generate the first transcript. |
| AI Subtitle Agent | Uses an OpenAI-compatible LLM API for context-aware subtitle revision. |
| RAG grounding | Retrieves project docs, domain profiles, previous subtitles, and Agent knowledge as context. |
| Dynamic glossary | Infers video-specific terms instead of relying only on static replacement lists. |
| Term consistency | Detects and unifies repeated ASR variants across the whole video. |
| Semantic polish | Conservatively improves subtitle readability without rewriting the speaker's meaning. |
| Rhythm tuning | Adjusts subtitle duration and line width for a more comfortable viewing experience. |
| Styled ASS export | Exports `clean` and `creator` ASS subtitle styles for different video scenarios. |
| Traceable outputs | Saves JSON/Markdown reports so users can inspect what the Agent changed and why. |
| Streaming demo | Includes Kafka, Flink, ASR, Redis, FastAPI, and desktop live-caption UI. |

## Agent Output Example

The Agent keeps correction records instead of silently changing text.

```json
{
  "original_text": "今天我们来瑞屏这个角色",
  "revised_text": "今天我们来锐评这个角色",
  "reason": "同音误识别，结合上下文应为网络词“锐评”。",
  "confidence": 0.95,
  "source": "llm_dynamic_segment_revision"
}
```

Typical Agent task outputs:

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

## Quick Start: Subtitle Agent

The Subtitle Agent is the most GitHub-friendly entry point if you want to try the AI subtitle workflow first.

```powershell
cd subtitle-agent
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
```

Edit `subtitle-agent/.env`:

```env
LLM_API_BASE=https://api.deepseek.com
LLM_API_KEY=your_api_key_here
LLM_MODEL=deepseek-v4-flash
```

Launch the Textual TUI:

```powershell
python app.py
```

Then paste a video path and type:

```text
:run
```

Useful keys:

| Key | Action |
| --- | --- |
| `v` | Set video path |
| `p` | Set domain profile |
| `g` | Run Agent |
| `l` | Clear log |
| `q` | Quit |

Command-line mode:

```powershell
python agent_main.py --video ..\input2.mp4 --profile bigdata --goal "生成高质量字幕并检查专业词"
```

## Quick Start: Streaming Stack

If you want the Kafka/Flink real-time pipeline:

```powershell
Copy-Item .env.example .env
docker compose up -d --build
```

Open:

| Service | URL |
| --- | --- |
| Dashboard | http://localhost:8000 |
| ASR health | http://localhost:8001/health |
| Flink Web UI | http://localhost:8081 |

Run the live desktop app:

```powershell
cd desktop-ui-live
npm install
npm run electron:dev
```

## Offline Subtitle Generator

If you only want the original offline subtitle generator without the AI Agent:

```powershell
python tools/generate_video_subtitles.py --media-path videos/input.mp4 --output-dir data/results/input --basename input
```

Desktop UI:

```powershell
cd desktop-ui
npm install
npm run electron:dev
```

## Architecture

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

## Project Layout

```text
.
├── subtitle-agent/                 # AI Subtitle Agent and Textual TUI
├── desktop-ui/                     # Offline subtitle desktop app
├── desktop-ui-live/                # Real-time desktop live-caption app
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

## What Makes It an Agent

The `subtitle-agent/` workflow is intentionally split into inspectable stages:

| Stage | Output | Purpose |
| --- | --- | --- |
| Planning | `agent_plan.json` | Decide how to process the task. |
| RAG | `rag_hits.json`, `rag_index.jsonl` | Retrieve context before correction. |
| Context brief | `ai_context_brief.json` | Understand video topic, tone, likely terms, and subtitle policy. |
| Dynamic glossary | `ai_glossary.json` | Infer terms from the current video and RAG context. |
| Segment revision | `ai_segment_revisions.json` | Correct ASR errors with reasons and confidence. |
| Consistency | `term_consistency_report.json` | Keep repeated terms consistent across the full video. |
| Semantic edit | `semantic_edit_report.json` | Improve subtitle readability conservatively. |
| Rhythm | `rhythm_report.json` | Tune display duration and reading speed. |
| Integrity | `subtitle_integrity_report.json` | Avoid blank subtitle intervals after export. |

This design makes the LLM behavior easier to inspect and debug than a single hidden prompt.

## Subtitle Styles

The Agent exports three subtitle entry points:

| File | Use Case |
| --- | --- |
| `revised.srt` | Plain subtitle file for players and editors. |
| `revised.clean.ass` | Clean, readable ASS subtitle style for general videos. |
| `revised.creator.ass` | Larger creator-style subtitle for short videos and social platforms. |

`revised.ass` currently points to the clean style for compatibility.

## Configuration

Common `.env` options for the streaming stack:

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

Lower-resource machine:

```env
ASR_MODEL=medium
ASR_DEVICE=cpu
ASR_COMPUTE_TYPE=int8
```

Subtitle Agent LLM config lives in `subtitle-agent/.env`:

```env
LLM_API_BASE=https://api.deepseek.com
LLM_API_KEY=your_api_key_here
LLM_MODEL=deepseek-v4-flash
SUBTITLE_AGENT_PROFILE=bigdata
SUBTITLE_AGENT_AI_BATCH_SIZE=18
```

## Benchmark Snapshot

This repository includes one real Docker-chain benchmark run for the streaming path:

```text
FFmpeg real-time read -> VAD -> Kafka -> Flink -> ASR -> Kafka -> API -> Redis/JSONL/metrics
```

| Scenario | Successful Segments | Failed Segments | Avg End-to-End Latency | P95 | Notes |
| --- | ---: | ---: | ---: | ---: | --- |
| 1 stream | 83 | 0 | 296086 ms | 467350 ms | Affected by historical Kafka backlog; not a clean baseline. |
| 2 streams | 230 | 0 | 4084 ms | 6805 ms | Best current reportable result. |
| 4 streams smoke | 39 | 0 | 9865 ms | 14463 ms | Shows 4 streams can run, but queueing delay increases. |

Detailed report: [docs/本次性能压测实验报告.md](./docs/%E6%9C%AC%E6%AC%A1%E6%80%A7%E8%83%BD%E5%8E%8B%E6%B5%8B%E5%AE%9E%E9%AA%8C%E6%8A%A5%E5%91%8A.md)

## Documentation

| Document | Purpose |
| --- | --- |
| [subtitle-agent/README.md](./subtitle-agent/README.md) | Subtitle Agent setup and outputs. |
| [desktop-ui/README.md](./desktop-ui/README.md) | Offline desktop subtitle generator. |
| [desktop-ui-live/README.md](./desktop-ui-live/README.md) | Real-time live-caption desktop app. |
| [docs/新手上手文档.md](./docs/%E6%96%B0%E6%89%8B%E4%B8%8A%E6%89%8B%E6%96%87%E6%A1%A3.md) | Beginner-friendly onboarding. |
| [docs/原理解说.md](./docs/%E5%8E%9F%E7%90%86%E8%A7%A3%E8%AF%B4.md) | Kafka, Flink, ASR, VAD, keyword analysis explained. |
| [docs/字幕质量评测说明.md](./docs/%E5%AD%97%E5%B9%95%E8%B4%A8%E9%87%8F%E8%AF%84%E6%B5%8B%E8%AF%B4%E6%98%8E.md) | CER/WER and subtitle quality evaluation. |
| [docs/benchmark.md](./docs/benchmark.md) | Benchmark scripts and metrics. |
| [docs/文档导航.md](./docs/%E6%96%87%E6%A1%A3%E5%AF%BC%E8%88%AA.md) | Full documentation map. |

## Useful Commands

```powershell
# Start full streaming backend
docker compose up -d --build

# Check containers
docker compose ps

# Tail logs
docker compose logs -f --tail=200

# Stop stack
docker compose down

# Offline subtitle generation
python tools/generate_video_subtitles.py --media-path videos/input.mp4 --output-dir data/results/input --basename input

# Subtitle Agent TUI
cd subtitle-agent
.\.venv\Scripts\python.exe app.py

# Subtitle quality evaluation
python tools/evaluate_subtitles.py --candidate data/results/single_test/input2.vtt --reference data/reference/input2_reference.txt --output-dir data/results/evaluation --basename input2

# Smoke check
python tools/smoke_check.py
```

## Current Limitations

- The LLM-based Agent requires an OpenAI-compatible API key.
- Subtitle accuracy depends on the source audio, local ASR model, domain vocabulary, and LLM review quality.
- The Agent can improve obvious ASR errors and readability, but it does not guarantee perfect subtitles without human review.
- Large local ASR models need significant CPU/GPU resources.
- The Kafka/Flink path is designed for local demo and course-project style experimentation, not production deployment.

## Roadmap

- [x] Local offline subtitle generation
- [x] Kafka/Flink real-time subtitle pipeline
- [x] Textual TUI for the Subtitle Agent
- [x] RAG-assisted LLM subtitle correction
- [x] Dynamic glossary and segment-level revision trace
- [x] Term consistency, semantic polish, rhythm tuning
- [x] Styled ASS export: clean and creator variants
- [ ] HTML visual report with before/after subtitle comparison
- [ ] Example demo package for GitHub preview
- [ ] Optional speaker diarization
- [ ] More profile presets: course, creator, meeting, tech, anime

## Git Hygiene

Do not commit runtime artifacts or secrets:

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

Check before committing:

```powershell
git status --short
```

## License

No license file is currently included. Add a license before publishing as a public open-source project.
