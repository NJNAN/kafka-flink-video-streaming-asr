# StreamSense：基于 Kafka-Flink 的视频流语音转写与关键词分析系统

StreamSense 是一个课程设计级别的本地语音转写系统。它能把真实视频、摄像头、麦克风或直播流里的声音转成字幕，并且提供两套入口：

- `desktop-ui/`：离线字幕生成器，适合选择一个本地视频，生成最终 `SRT / VTT / TXT / JSON` 字幕文件。
- `desktop-ui-live/`：大数据实时字幕版，适合打开摄像头和麦克风，走 `Kafka + Flink + ASR + API` 链路实时显示字幕。

一句人话：这个项目把“视频/直播声音”变成“可展示、可导出、可分析的字幕和关键词”，并且能用 Kafka/Flink 说明它是一个流式大数据处理系统。

## 1. 先分清两个版本

| 版本 | 目录 | 是否走 Kafka/Flink | 适合做什么 | 入口 |
| --- | --- | --- | --- | --- |
| 离线字幕生成器 | `desktop-ui/` | 不走 | 处理一个已有视频，生成最终字幕文件 | `StreamSense.exe` |
| 大数据实时字幕版 | `desktop-ui-live/` | 走 | 摄像头/麦克风/直播流实时字幕，适合课程设计演示 | `StreamSenseLive.exe` |
| 后端流处理系统 | `services/` + `flink/` + `docker-compose.yml` | 走 | Kafka、Flink、ASR、API、Redis、Dashboard | `docker compose up` |

不要把这两个桌面端混在一起改：

- 想改“本地视频生成字幕”：看 `desktop-ui/`、`tools/generate_video_subtitles.py`。
- 想改“实时摄像头/麦克风字幕”：看 `desktop-ui-live/`、`desktop-ui-live/live-ingest/app.py`、`flink/transcription_job.py`。

## 2. 快速启动

### 2.1 启动完整后端链路

第一次运行先复制环境变量：

```powershell
Copy-Item .env.example .env
```

启动 Kafka、Flink、Redis、API、ASR、视频接入服务：

```powershell
docker compose up -d --build
```

打开检查：

- Dashboard：`http://localhost:8000`
- ASR 健康检查：`http://localhost:8001/health`
- Flink Web UI：`http://localhost:8081`

### 2.2 只生成一个视频的离线字幕

```powershell
python tools/generate_video_subtitles.py --media-path videos/input.mp4 --output-dir data/results/input --basename input
```

输出会在 `data/results/input/` 里，通常包括 `.srt`、`.vtt`、`.txt`、`.json`。

### 2.3 运行离线桌面端

```powershell
cd desktop-ui
npm install
npm run electron:dev
```

打包：

```powershell
cd desktop-ui
npm run dist
```

打包后的可执行文件：

```text
desktop-ui/release/win-unpacked/StreamSense.exe
desktop-ui/release/StreamSense Setup 0.1.0.exe
```

### 2.4 运行大数据实时字幕桌面端

开发模式：

```powershell
cd desktop-ui-live
npm install
npm run electron:dev
```

打包：

```powershell
cd desktop-ui-live
npm run dist
```

打包后的可执行文件：

```text
desktop-ui-live/release/win-unpacked/StreamSenseLive.exe
desktop-ui-live/release/StreamSense Live Setup 0.1.0.exe
```

如果实时版要手动启动大数据服务，可以在项目根目录执行：

```powershell
docker compose -f docker-compose.yml -f desktop-ui-live\docker-compose.live.yml up -d --no-build
```

如果是第一次构建镜像，改用：

```powershell
docker compose -f docker-compose.yml -f desktop-ui-live\docker-compose.live.yml up -d --build
```

## 3. 两条核心链路

### 3.1 离线字幕链路

这个链路目标是“最终字幕质量”，不强调实时性，也不走 Kafka/Flink。

```text
desktop-ui/src/App.tsx
  -> desktop-ui/electron/main.ts:createTask()
  -> desktop-ui/electron/main.ts:startTask()
  -> tools/generate_video_subtitles.py
  -> services/asr/app.py 或 services/asr/asr_service.py
  -> data/results/tasks/<task_id>/
```

适合场景：

- 给已有课程视频、会议视频、录屏生成字幕。
- 导出 `.srt` 给播放器或剪辑软件用。
- 答辩时展示“可用的字幕生成工具”。

### 3.2 大数据实时字幕链路

这个链路目标是“实时流处理演示”，核心价值是把实时音频拆成连续任务，交给 Kafka/Flink 调度。

```text
摄像头/麦克风
  -> desktop-ui-live/src/App.tsx：分段录音并上传
  -> desktop-ui-live/live-ingest/app.py：接收 WebM，转 WAV，过滤静音
  -> Kafka audio-segment topic
  -> flink/transcription_job.py：消费音频片段并调用 ASR
  -> services/asr/asr_service.py：faster-whisper 本地转写
  -> Kafka transcription-result topic
  -> services/api/app.py：聚合字幕、关键词、指标
  -> Redis + data/results + desktop-ui-live 实时显示
```

适合场景：

- 摄像头/麦克风实时字幕。
- 展示 Kafka 消息队列、Flink 流处理、ASR 服务解耦。
- 做多路流压测和课程设计答辩。

## 4. 项目目录

```text
.
├── docker-compose.yml              # 主后端：Kafka/Flink/Redis/API/ASR/ingest
├── .env.example                    # 环境变量模板
├── config/                         # 热词、纠错词表、领域 profile
├── data/
│   ├── audio/                      # 运行时音频切片，不提交 Git
│   └── results/                    # 字幕、报告、压测输出，不提交 Git
├── desktop-ui/                     # 离线字幕生成器 Electron 前端
├── desktop-ui-live/                # 大数据实时字幕 Electron 前端和 live-ingest 服务
├── docs/                           # 新手文档、原理解说、压测报告、Git 说明
├── flink/                          # PyFlink 转写调度任务
├── models/                         # 本地 Whisper 模型缓存，不提交 Git
├── services/
│   ├── api/                        # FastAPI Dashboard、字幕接口、关键词分析
│   ├── asr/                        # faster-whisper HTTP 转写服务
│   └── ingest/                     # 视频文件/视频流接入和音频切片
├── tools/                          # 离线字幕生成、批处理、压测脚本
└── videos/                         # 本地测试视频，不提交 Git
```

## 5. 核心配置

第一次运行：

```powershell
Copy-Item .env.example .env
```

常用配置：

```text
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

如果显存不够：

```text
ASR_MODEL=medium
ASR_COMPUTE_TYPE=int8_float16
```

如果没有 NVIDIA GPU：

```text
ASR_DEVICE=cpu
ASR_COMPUTE_TYPE=int8
```

实时桌面端为了降低等待时间，会在 `desktop-ui-live/electron/main.ts` 里给 Compose 进程设置更轻的默认值，例如 `ASR_MODEL=small`、`ASR_COMPUTE_TYPE=int8_float16`、`FLINK_JOB_PARALLELISM=2`。如果要追求准确率，可以改回更大的模型，但实时延迟会增加。

## 6. 常用命令

```powershell
# 启动完整后端
docker compose up -d --build

# 查看容器状态
docker compose ps

# 查看最近日志
docker compose logs -f --tail=200

# 停止服务
docker compose down

# 单个视频生成字幕
python tools/generate_video_subtitles.py --media-path videos/input.mp4 --output-dir data/results/input --basename input

# 批量处理多个视频
python tools/batch_generate_subtitles.py

# 跑 1/2/4 路性能压测
python tools/benchmark_streamsense.py --streams 1 2 4 --video-source /videos/input.mp4

# 离线桌面端
cd desktop-ui
npm run electron:dev

# 大数据实时桌面端
cd desktop-ui-live
npm run electron:dev
```

## 7. 本次性能压测结论

本项目已经完成一次真实 Docker 链路压测，测试对象是完整实时流式链路：

```text
FFmpeg 实时读视频 -> VAD 切片 -> Kafka -> Flink -> ASR -> Kafka -> API -> Redis/JSONL/指标
```

| 测试场景 | 成功片段 | 失败片段 | 平均端到端延迟 | P95 | 结论 |
| --- | ---: | ---: | ---: | ---: | --- |
| 单路 | 83 | 0 | 296086 ms | 467350 ms | 受历史 Kafka 积压影响，不作为干净基准 |
| 2 路并发 | 230 | 0 | 4084 ms | 6805 ms | 最适合作为本次报告主结果 |
| 4 路短冒烟 | 39 | 0 | 9865 ms | 14463 ms | 证明 4 路可跑，但排队延迟明显上升 |

详细实验过程、指标解释和瓶颈分析见：[docs/本次性能压测实验报告.md](./docs/%E6%9C%AC%E6%AC%A1%E6%80%A7%E8%83%BD%E5%8E%8B%E6%B5%8B%E5%AE%9E%E9%AA%8C%E6%8A%A5%E5%91%8A.md)。

## 8. 文档导航

- [docs/新手上手文档.md](./docs/%E6%96%B0%E6%89%8B%E4%B8%8A%E6%89%8B%E6%96%87%E6%A1%A3.md)：1～2 天读懂项目、跑起来、改一个小功能。
- [docs/傻瓜式实现文档.md](./docs/%E5%82%BB%E7%93%9C%E5%BC%8F%E5%AE%9E%E7%8E%B0%E6%96%87%E6%A1%A3.md)：从零开始照着跑项目。
- [docs/原理解说.md](./docs/%E5%8E%9F%E7%90%86%E8%A7%A3%E8%AF%B4.md)：解释 Kafka、Flink、ASR、VAD、关键词分析为什么这样设计。
- [docs/文档导航.md](./docs/%E6%96%87%E6%A1%A3%E5%AF%BC%E8%88%AA.md)：所有文档的用途和阅读顺序。
- [desktop-ui/README.md](./desktop-ui/README.md)：离线字幕生成器说明。
- [desktop-ui-live/README.md](./desktop-ui-live/README.md)：大数据实时字幕版说明。
- [docs/desktop-ui.md](./docs/desktop-ui.md)：原桌面工作台运行方式。
- [docs/benchmark.md](./docs/benchmark.md)：压测脚本、输出报告和指标含义。
- [docs/system_metrics.md](./docs/system_metrics.md)：时间戳字段、监控接口和动态热词池说明。
- [docs/Git提交与仓库说明.md](./docs/Git%E6%8F%90%E4%BA%A4%E4%B8%8E%E4%BB%93%E5%BA%93%E8%AF%B4%E6%98%8E.md)：哪些文件该提交，哪些文件不能提交。

## 9. Git 提交注意

仓库只提交源码、配置模板和文档。下面这些内容不要提交：

- `.env`
- `models/` 模型缓存
- `videos/` 测试视频
- `data/audio/` 音频切片
- `data/results/` 字幕、报告、压测输出
- `desktop-ui/node_modules/`
- `desktop-ui/dist/`、`desktop-ui/dist-electron/`、`desktop-ui/release/`
- `desktop-ui-live/node_modules/`
- `desktop-ui-live/dist/`、`desktop-ui-live/dist-electron/`、`desktop-ui-live/release/`

提交前检查：

```powershell
git status --short
```

如果看到视频、模型、字幕结果、安装包、`node_modules`，先检查 `.gitignore`，不要直接提交。

## 10. 常见问题

### Docker 拉镜像超时

这通常不是“权限没给”，而是 Docker Hub 网络超时。可以重试，或者先手动拉基础镜像：

```powershell
docker pull python:3.11-slim
docker pull apache/flink:1.18.1-scala_2.12-java17
```

### 实时版提示摄像头/麦克风被拒绝

打开 Windows 设置：

```text
设置 -> 隐私和安全性 -> 摄像头 / 麦克风
```

确认允许“桌面应用”访问摄像头和麦克风。

### 实时版半天不出字幕

优先检查：

1. `docker compose ps` 是否所有核心服务都在运行。
2. `http://localhost:8001/health` 是否正常。
3. 麦克风是否真的有声音输入。
4. `ASR_MODEL` 是否太大，显存不够时先用 `small` 或 `medium`。

### 字幕有错字或幻觉

通用纠错写到：

```text
config/asr_corrections.txt
```

固定领域热词写到：

```text
config/custom_keywords.txt
```

实时版还在 `desktop-ui-live/src/App.tsx` 里给 live-ingest 传了一组常用热词，适合课程设计演示时稳定识别“Kafka / Flink / 大数据 / 实时字幕”等词。
