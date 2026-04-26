# StreamSense：基于 Kafka-Flink 的视频流语音转写与关键词分析系统

这是一个可以本地运行的课程项目原型。它读取真实视频文件或真实 RTSP/HTTP 视频流，用本地 `faster-whisper` 模型完成语音转写，再通过 Kafka、Flink、Redis 和 FastAPI 做流式处理、关键词分析、实时展示和字幕导出。

项目不是模拟数据演示。音频来自真实视频，字幕可以导出为 `SRT / VTT / TXT / JSON`，也可以通过 Web Dashboard 或 Electron 桌面工作台查看。

## 1. 一句话运行方式

先把视频放到 `videos/input.mp4`，然后在项目根目录执行：

```powershell
Copy-Item .env.example .env
docker compose up -d --build
```

打开：

- Dashboard：`http://localhost:8000`
- ASR 健康检查：`http://localhost:8001/health`
- Flink Web UI：`http://localhost:8081`

如果你只想生成最终字幕文件，执行：

```powershell
python tools/generate_video_subtitles.py --media-path videos/input.mp4 --output-dir data/results/input --basename input
```

更完整的傻瓜式步骤看：[docs/傻瓜式实现文档.md](./docs/%E5%82%BB%E7%93%9C%E5%BC%8F%E5%AE%9E%E7%8E%B0%E6%96%87%E6%A1%A3.md)。

## 2. 项目能做什么

- 接入本地视频文件、RTSP 摄像头、HTTP/FLV 视频流。
- 用 FFmpeg 从真实视频中抽取音频。
- 用 WebRTC VAD 按语音停顿动态切片，减少机械切断句子的问题。
- 把音频片段元数据写入 Kafka。
- 用 Flink 消费 Kafka 消息，并调用本地 ASR 服务。
- 用 `faster-whisper` 在本机 GPU 或 CPU 上转写中文语音。
- 提取关键词，发现动态热词，输出关键词事件。
- 用 Redis 和 JSONL 保存实时结果。
- 通过网页或桌面端查看字幕、服务状态和结果文件。
- 生成 `.srt`、`.vtt`、`.txt`、`.json` 字幕与报告。

## 3. 技术路线

```text
真实视频/视频流
  -> services/ingest：FFmpeg 抽音频 + VAD 切片
  -> Kafka audio-segment topic
  -> flink/transcription_job.py：消费切片并调度 ASR
  -> services/asr：faster-whisper 本地语音识别
  -> Kafka transcription-result topic
  -> services/api：句子缓冲、关键词提取、热词更新、结果落盘
  -> Redis + data/results + Dashboard/桌面端
```

详细原理看：[docs/原理解说.md](./docs/%E5%8E%9F%E7%90%86%E8%A7%A3%E8%AF%B4.md)。

## 4. 目录结构

```text
.
├── docker-compose.yml              # 一键启动 Kafka/Flink/Redis/API/ASR/ingest
├── .env.example                    # 环境变量模板
├── config/                         # 热词、纠错词表、领域 profile
├── data/
│   ├── audio/                      # 运行时音频切片，不提交 Git
│   └── results/                    # 字幕和报告输出，不提交 Git
├── desktop-ui/                     # React + Electron 桌面工作台
├── docs/                           # 操作文档、原理解说、Git 说明
├── flink/                          # PyFlink 转写调度任务
├── models/                         # 本地模型缓存，不提交 Git
├── services/
│   ├── api/                        # FastAPI Dashboard、结果接口、关键词分析
│   ├── asr/                        # faster-whisper HTTP 服务
│   └── ingest/                     # 视频接入和音频切片
├── tools/                          # 字幕生成、导出、批量验收脚本
└── videos/                         # 本地测试视频，不提交 Git
```

## 5. 推荐环境

- Windows 10/11
- Docker Desktop
- Python 3.10+
- Node.js / npm，仅桌面端开发需要
- NVIDIA GPU，推荐 RTX 4060 8GB 或以上

没有 GPU 也能跑，但要把 `.env` 里的 `ASR_DEVICE=cuda` 改成 `ASR_DEVICE=cpu`，速度会明显变慢。

## 6. 常用命令

```powershell
# 启动完整后端
docker compose up -d --build

# 查看服务状态
docker compose ps

# 看日志
docker compose logs -f --tail=200

# 停止服务
docker compose down

# 单个视频生成字幕
python tools/generate_video_subtitles.py --media-path videos/input.mp4 --output-dir data/results/input --basename input

# 批量处理多个视频
python tools/batch_generate_subtitles.py

# 启动桌面端 Web 开发模式
cd desktop-ui
npm install
npm run dev

# 启动 Electron 桌面模式
cd desktop-ui
npm run electron:dev
```

## 7. 核心配置

常用配置都在 `.env` 里，第一次运行从模板复制：

```powershell
Copy-Item .env.example .env
```

推荐默认值：

```text
VIDEO_SOURCE=/videos/input.mp4
STREAM_ID=demo-video
INGEST_SEGMENT_MODE=vad
ASR_MODEL=large-v3
ASR_DEVICE=cuda
ASR_COMPUTE_TYPE=float16
SENTENCE_BUFFER_ENABLED=true
HOTWORD_AUTO_DISCOVERY_ENABLED=true
```

如果显存不够，可以改成：

```text
ASR_MODEL=medium
ASR_COMPUTE_TYPE=int8_float16
```

如果没有 GPU：

```text
ASR_DEVICE=cpu
ASR_COMPUTE_TYPE=int8
```

## 8. 文档导航

- [docs/傻瓜式实现文档.md](./docs/%E5%82%BB%E7%93%9C%E5%BC%8F%E5%AE%9E%E7%8E%B0%E6%96%87%E6%A1%A3.md)：从零开始，按步骤运行项目。
- [docs/原理解说.md](./docs/%E5%8E%9F%E7%90%86%E8%A7%A3%E8%AF%B4.md)：解释每个模块为什么这样设计。
- [docs/文档导航.md](./docs/%E6%96%87%E6%A1%A3%E5%AF%BC%E8%88%AA.md)：所有文档的用途说明。
- [docs/Git提交与仓库说明.md](./docs/Git%E6%8F%90%E4%BA%A4%E4%B8%8E%E4%BB%93%E5%BA%93%E8%AF%B4%E6%98%8E.md)：哪些文件该提交，哪些文件不能提交。
- [docs/desktop-ui.md](./docs/desktop-ui.md)：Web/Electron 工作台运行方式。
- [docs/windows-launcher.md](./docs/windows-launcher.md)：Windows 桌面启动器和打包说明。
- [优化版课题与实施方案.md](./%E4%BC%98%E5%8C%96%E7%89%88%E8%AF%BE%E9%A2%98%E4%B8%8E%E5%AE%9E%E6%96%BD%E6%96%B9%E6%A1%88.md)：课题包装、技术路线和答辩材料。

## 9. Git 说明

仓库只提交源码、配置模板和文档。下面这些内容默认不提交：

- `.env`
- `models/` 模型缓存
- `videos/` 测试视频
- 根目录 `input*.mp4`
- `data/audio/` 音频切片
- `data/results/` 字幕和报告
- `desktop-ui/release/`、`desktop-ui/release-*` 打包产物
- `desktop-ui/dist/`、`desktop-ui/dist-electron/` 构建产物

提交前建议执行：

```powershell
git status --short
```

确认没有把视频、模型、字幕结果、exe 安装包提交进去。

## 10. 常见问题

### Docker 连接失败

先启动 Docker Desktop，再执行：

```powershell
docker compose ps
```

### 视频没有字幕

按顺序检查：

1. `videos/input.mp4` 是否存在。
2. 视频是否有音轨。
3. `http://localhost:8001/health` 是否正常。
4. `http://localhost:8081` 里 Flink 作业是否运行。
5. `docker compose logs -f --tail=200` 里是否有报错。

### 首次运行很慢

第一次使用 `large-v3` 会下载模型到 `models/`。答辩或演示前建议提前跑一次。

### 字幕有错字

通用纠错写到：

```text
config/asr_corrections.txt
```

固定领域热词写到：

```text
config/custom_keywords.txt
```

不要把某个视频专属词强行写进默认配置，专属词建议放到 `config/profiles/`。
