# 基于 Kafka-Flink 的视频流语音转写与关键词分析系统

这是一个面向本科毕设和课程项目的完整原型系统。它使用**真实视频文件**或**真实 RTSP/HTTP 视频流**作为输入，在本地容器中完成语音转写、关键词分析和字幕导出，不依赖线上付费 ASR API。

当前版本的重点不是“演示概念”，而是把下面三件事真正做稳：

1. 用本地模型生成可直接使用的字幕文件。
2. 尽量避免字幕中间漏段。
3. 在多个不同视频上保持可接受的速度和泛化能力。

## 1. 项目亮点

- 真实视频输入，不使用模拟流。
- 本地 `faster-whisper` 推理，不依赖线上付费接口。
- `Kafka + Flink + Redis` 构成完整流式处理链路。
- `WebRTC VAD + FFmpeg` 做语音检测和动态切块。
- 最终字幕生成采用“整段转写 + 有声区间补漏”方案。
- 支持输出 `SRT / VTT / TXT / JSON`。
- 支持批量跑多个视频，并生成验收报告。
- 热词、上下文和状态按 `stream_id:run_id` 隔离，避免旧视频污染新视频。

## 2. 文档导航

仓库里现有文档较多，建议按下面顺序阅读：

1. [README.md](./README.md)：项目总入口。
2. [docs/文档导航.md](./docs/文档导航.md)：所有文档的用途说明。
3. [基于 Kafka-Flink 的视频流语音转写与关键词分析系统_需求文档.md](./基于%20Kafka-Flink%20的视频流语音转写与关键词分析系统_需求文档.md)：原始需求。
4. [优化版课题与实施方案.md](./优化版课题与实施方案.md)：课题包装和实施路线。
5. [StreamSense_问题解决方案.md](./StreamSense_问题解决方案.md)：问题分析与参考改进方向。
6. [StreamSense_泛化字幕生成优化说明.md](./StreamSense_%E6%B3%9B%E5%8C%96%E5%AD%97%E5%B9%95%E7%94%9F%E6%88%90%E4%BC%98%E5%8C%96%E8%AF%B4%E6%98%8E.md)：当前最终落地方案说明。
7. [docs/Git提交与仓库说明.md](./docs/Git提交与仓库说明.md)：Git 使用与提交约定。

## 3. 项目结构

```text
.
├── docker-compose.yml
├── .env.example
├── .gitignore
├── .gitattributes
├── config/
│   ├── custom_keywords.txt
│   ├── asr_corrections.txt
│   └── profiles/
├── data/
│   ├── audio/                      # 运行时音频切片目录，默认不提交 Git
│   └── results/                    # 字幕和报告输出目录，默认不提交 Git
├── docs/
│   ├── 文档导航.md
│   └── Git提交与仓库说明.md
├── flink/
│   └── transcription_job.py
├── models/                         # 本地模型缓存目录，默认不提交 Git
├── services/
│   ├── api/
│   ├── asr/
│   └── ingest/
├── tools/
│   ├── export_subtitles.py
│   ├── generate_video_subtitles.py
│   └── batch_generate_subtitles.py
└── videos/                         # 本地测试视频目录，默认不提交 Git
```

## 4. 系统能力

系统当前支持：

- 从本地视频文件、RTSP、HTTP 视频流中抽取音频。
- 使用 `WebRTC VAD + FFmpeg` 做动态切块。
- 将切片元数据写入 Kafka。
- 使用 Flink 消费 Kafka 消息并调用本地 ASR 服务。
- 通过本地 Whisper/faster-whisper 生成转写结果。
- 对字幕做关键词提取和关键词事件检测。
- 将结果写入 Redis 和 `data/results/*.jsonl`。
- 生成可直接挂到视频上的 `.srt` / `.vtt` 字幕文件。
- 通过 Dashboard 查看实时字幕和关键词状态。

## 5. 运行环境

推荐环境：

- Windows 10/11
- Docker Desktop
- NVIDIA GPU（推荐 RTX 4060 8GB 及以上）
- 已安装 NVIDIA Container Toolkit 或等效 Docker GPU 支持

如果没有 GPU，也可以用 CPU 跑，但速度和准确率会明显下降。

## 6. 快速启动

### 6.1 准备视频

把真实视频放到：

```text
videos/input.mp4
```

支持常见格式：`mp4`、`mkv`、`avi`、`mov`。视频必须带音轨。

### 6.2 创建环境变量

```powershell
Copy-Item .env.example .env
```

默认常用配置：

```text
VIDEO_SOURCE=/videos/input.mp4
STREAM_ID=demo-video
INGEST_SEGMENT_MODE=vad
INGEST_VAD_TARGET_CHUNK_MS=3000
INGEST_VAD_HARD_MAX_CHUNK_MS=4500
INGEST_VAD_MAX_SILENCE_MS=1400
ASR_MODEL=large-v3
ASR_DEVICE=cuda
ASR_COMPUTE_TYPE=float16
```

### 6.3 启动整套系统

```powershell
docker compose up --build
```

启动后可访问：

- Dashboard：`http://localhost:8000`
- ASR 健康检查：`http://localhost:8001/health`
- Flink Web UI：`http://localhost:8081`
- Kafka 外部地址：`localhost:29092`

## 7. 输入源说明

### 7.1 本地视频

默认读取：

```text
VIDEO_SOURCE=/videos/input.mp4
```

### 7.2 RTSP 摄像头或直播流

```text
VIDEO_SOURCE=rtsp://用户名:密码@摄像头IP:554/stream1
STREAM_ID=camera-01
```

### 7.3 HTTP 视频流

```text
VIDEO_SOURCE=http://example.com/live.flv
STREAM_ID=live-01
```

系统不会生成模拟数据。音频始终来自真实视频源。

## 8. 本地模型说明

本项目默认使用本地 `faster-whisper` 推理。

两种常见方式：

1. 直接配置公开模型名，例如：

```text
ASR_MODEL=large-v3
```

首次运行会把模型下载到 `models/`。

2. 手动把模型放到本地目录，例如：

```text
ASR_MODEL_PATH=/models/whisper-base
```

如果答辩环境不能联网，建议提前把模型准备好。

## 9. 关键参数说明

### 9.1 推荐默认值

```text
INGEST_SEGMENT_MODE=vad
INGEST_VAD_TARGET_CHUNK_MS=3000
INGEST_VAD_HARD_MAX_CHUNK_MS=4500
INGEST_VAD_MAX_SILENCE_MS=1400
ASR_MODEL=large-v3
ASR_DEVICE=cuda
ASR_COMPUTE_TYPE=float16
SENTENCE_BUFFER_ENABLED=true
SENTENCE_MAX_CHARS=110
SENTENCE_FLUSH_GAP_MS=1500
SENTENCE_STALE_FLUSH_MS=3000
ASR_ENABLE_ENERGY_FILTER=true
ASR_ENERGY_THRESHOLD_DBFS=-42
```

### 9.2 参数含义

- `INGEST_SEGMENT_MODE=vad`：按语音停顿动态切块。
- `INGEST_VAD_TARGET_CHUNK_MS=3000`：目标切块长度。
- `INGEST_VAD_HARD_MAX_CHUNK_MS=4500`：最长强制切块长度。
- `SENTENCE_*`：把短切片合并成更自然的句子级输出。
- `ASR_ENABLE_ENERGY_FILTER=true`：过滤近静音片段，减少幻觉字幕。

### 9.3 速度与准确率折中

- `tiny/base`：速度快，但中文准确率偏低。
- `small`：中低配置可用。
- `medium`：速度和准确率比较均衡。
- `large-v3`：当前默认值，适合优先保证字幕质量。

## 10. 生成最终字幕

推荐使用最终字幕脚本，而不是直接从流式 `jsonl` 拼字幕。

### 10.1 单个视频

```powershell
python tools/generate_video_subtitles.py
```

默认行为：

1. 读取 `videos/input.mp4`
2. 先做整段真实视频转写
3. 自动检测有声区间
4. 对“有声音但没有字幕覆盖”的小段做补转写
5. 生成最终输出文件

默认输出：

- `data/results/input.srt`
- `data/results/input.vtt`
- `data/results/input_subtitle.txt`
- `data/results/input_final_segments.json`
- `data/results/input_report.json`
- `data/results/input_hotwords.json`

如果要处理根目录其他视频，例如 `input2.mp4`：

```powershell
python tools/generate_video_subtitles.py --media-path input2.mp4 --output-dir data/results/input2 --basename input2
```

如果要做两遍增强：

```powershell
python tools/generate_video_subtitles.py --passes 2
```

### 10.2 批量验收多个视频

```powershell
python tools/batch_generate_subtitles.py
```

批量输出：

- `data/results/batch/<视频名>/<视频名>.srt`
- `data/results/batch/<视频名>/<视频名>.vtt`
- `data/results/batch/<视频名>/<视频名>_subtitle.txt`
- `data/results/batch/<视频名>/<视频名>_report.json`
- `data/results/batch/batch_report.md`
- `data/results/batch/batch_report.json`

当前批量验收关注两条硬指标：

- `speed_ratio_elapsed_over_media <= 0.5`
- `blocking_uncovered_gaps_after_recovery = []`

这两条分别对应：

- 10 分钟视频最慢 5 分钟内跑完
- 补漏后不应再出现正文语音漏字幕的大段空洞

## 11. 静态词表与泛化说明

当前方案不再只依赖静态热词表。

- API 会从真实转写结果里发现高频领域词。
- 新热词会通过 Kafka 广播给 ASR 服务。
- 热词、上下文和句子缓冲都按 `stream_id:run_id` 隔离。
- `config/custom_keywords.txt` 和 `config/asr_corrections.txt` 默认保持泛化模式。

如果你确实要对固定领域做定向增强，建议显式使用 `config/profiles/` 下的词表，而不是直接污染默认配置。

示例：

```powershell
python tools/generate_video_subtitles.py --mode full --use-static-hints --custom-keywords config/profiles/dino_keywords.txt --corrections config/profiles/dino_corrections.txt
```

## 12. Git 与仓库管理

这个项目包含大量本地大文件，因此仓库已经补齐了基础 Git 配置：

- `.gitignore`
- `.gitattributes`
- `docs/Git提交与仓库说明.md`

默认不会提交的内容包括：

- `.env`
- `models/` 里的模型缓存
- `videos/` 里的测试视频
- 根目录 `input*.mp4`
- `data/audio/` 和 `data/results/` 里的运行产物

如果你准备上传到 GitHub 或 Gitee，先看：

1. [docs/Git提交与仓库说明.md](./docs/Git提交与仓库说明.md)
2. [.gitignore](./.gitignore)
3. [.env.example](./.env.example)

## 13. 常用命令

```powershell
# 启动系统
docker compose up --build

# 生成单个视频字幕
python tools/generate_video_subtitles.py

# 处理其他视频
python tools/generate_video_subtitles.py --media-path input2.mp4 --output-dir data/results/input2 --basename input2

# 批量跑所有视频并验收
python tools/batch_generate_subtitles.py

# 从 JSONL 临时导出字幕
python tools/export_subtitles.py
```

## 14. 当前适用边界

这个项目当前更适合：

- 中文解说视频
- 科普视频
- 单人或少人主讲视频
- 有明确音轨、背景音乐不过强的视频

对于多人抢话、强背景音乐、方言密集、影视混剪这类复杂场景，字幕质量仍然受本地模型本身限制。当前工程层面已经重点解决了“生成不完整、容易漏段、跨视频状态污染、批量验收不清楚”这些问题。

默认会读取 `data/results/transcripts.jsonl`，输出：

- `data/results/input.srt`
- `data/results/input.vtt`
- `data/results/input_subtitle.txt`

如果想保留片尾模板、字幕组等内容，可以加：

```powershell
python tools/export_subtitles.py --keep-boilerplate
```

## 8. 主要 Topic

| Topic | 说明 |
|---|---|
| `audio-segment` | 视频接入服务写入的音频片段元数据 |
| `transcription-result` | Flink 写入的字幕识别结果 |
| `keyword-event` | API 服务写入的关键词事件 |
| `streamsense.hotword.updates` | API 广播的动态热词更新 |

`topic-init` 容器会在系统启动时自动创建这些 Topic，避免没有视频输入时 Flink 因 Topic 不存在而重启。

## 9. 适合论文描述的技术点

- Kafka 解耦视频接入、流处理和 AI 推理。
- Flink 作为实时流处理层，负责消费音频片段并调度 ASR。
- ASR 模型服务化，避免把深度学习依赖直接塞进 Flink 作业。
- Redis 保存实时字幕和关键词事件，方便 Dashboard 查询。
- JSONL 文件保存历史结果，便于论文实验复现。
- SRT/VTT 字幕导出让系统结果可以直接导入播放器或剪辑软件。
- 系统记录切片时间、ASR 耗时、端到端耗时，便于做性能实验。

## 10. 常见问题

### Docker daemon 不可连接

如果 `docker compose up` 报 Docker 连接失败，请先启动 Docker Desktop，并确认 WSL2 后端正常。

### 视频没有字幕输出

优先检查：

- `videos/input.mp4` 是否真实存在。
- 视频是否有音频轨道。
- ASR 服务是否启动成功。
- Flink UI 中是否有运行中的作业。
- Kafka 是否出现 `audio-segment` 消息。

### 模型下载失败

可以提前手动下载 faster-whisper 模型到 `models/`，然后配置 `ASR_MODEL_PATH`。
