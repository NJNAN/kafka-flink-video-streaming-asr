# StreamSense Windows 桌面启动器

`desktop-ui/` 现在同时支持两种形态：

- Web 开发模式：只运行 Vite 页面，适合调 UI。
- Electron 桌面模式：提供 `StreamSense Studio` 桌面窗口，能检查环境、控制 Docker Compose、查看日志、选择视频、创建任务并调用现有字幕脚本。

Electron 不会把 Docker、Kafka、Flink、Whisper 模型或 CUDA 运行时打进 exe。它只是桌面启动器 + 工作台 + 服务控制台。后端仍然通过本机 Docker Desktop 和当前仓库的 `docker-compose.yml` 运行。

## 前置条件

Windows 10/11 推荐环境：

- Node.js / npm
- Python，可通过 `python` 命令启动
- Docker Desktop
- 可选 NVIDIA GPU 与 Docker GPU 支持

首次运行 `large-v3` 模型时，ASR 服务可能需要下载模型到 `models/`，耗时取决于网络和磁盘。

## Web 开发模式

```powershell
cd desktop-ui
npm install
npm run dev
```

访问：

```text
http://localhost:5173
```

Web 模式没有 Electron 桌面 IPC，所以不能启动 Docker、选择本地视频或打开目录。

## Electron 开发模式

```powershell
cd desktop-ui
npm install
npm run electron:dev
```

该命令会先启动 Vite，再打开 `StreamSense Studio` 桌面窗口。

## 构建

只构建前端静态文件：

```powershell
cd desktop-ui
npm run build
```

只编译 Electron 主进程：

```powershell
cd desktop-ui
npm run electron:build
```

打包 Windows exe：

```powershell
cd desktop-ui
npm run dist
```

输出目录：

```text
desktop-ui/release/
```

可执行文件名由 electron-builder 配置为：

```text
StreamSense.exe
```

## 桌面启动器能力

桌面窗口中可以执行：

- 检查 Docker CLI、docker compose、Docker daemon。
- 检查 `8000 / 8001 / 8081 / 5173 / 6379 / 9092 / 29092` 端口占用。
- 执行 `docker compose up -d --build`。
- 执行 `docker compose down`。
- 查看 `docker compose ps` 状态。
- 轮询 API、ASR、Flink 健康状态。
- 选择 `mp4/mkv/avi/mov/flv` 视频。
- 复制视频到项目 `videos/` 目录。
- 创建任务并调用：

```powershell
python tools/generate_video_subtitles.py --media-path videos/xxx.mp4 --output-dir data/results/tasks/<task_id> --basename <task_id>
```

- 查看启动日志和任务日志。
- 导出日志到 `logs/`。
- 编辑字幕并重新导出 `SRT/VTT/TXT`。
- 打开项目、视频、结果目录。

## 真实后端与 Mock fallback

前端默认优先访问：

```text
http://localhost:8000
```

如果后端不可达，会自动回退到 mock 数据，顶部会显示 `Mock Mode`。

可通过环境变量覆盖：

```text
VITE_API_BASE_URL=http://localhost:8000
VITE_USE_MOCK=true
```

## 常见故障

### Docker 未安装

启动器会显示 Docker CLI 检查失败。请安装 Docker Desktop，并确认 `docker --version` 可执行。

### Docker Desktop 未启动

环境检查会显示“请先启动 Docker Desktop”。启动 Docker Desktop 后重新点击“检查环境”。

### docker compose 不可用

确认命令可用：

```powershell
docker compose version
```

### 端口被占用

启动器会列出端口警告。若不是 StreamSense 自己的容器占用，请先关闭占用进程。

### 后端 health 超时

先看启动日志，再检查：

```powershell
docker compose ps
docker compose logs --tail=200
```

### ASR 模型下载慢

首次使用 `large-v3` 可能较慢。现场演示可选择“快速演示”或提前准备 `models/` 缓存。

### GPU 不可用

把模式改成 CPU 或修改设置中的 `ASR_DEVICE=cpu`，速度会明显下降。

### 视频文件不存在或容器访问不到

使用桌面窗口里的“复制到 videos 目录”选项。这样脚本和 Docker 容器都能从项目目录访问视频。

### 任务脚本失败

查看 LCD 日志中的 Python 输出。常见原因是 Python 环境、视频路径、模型下载或 FFmpeg 问题。

## 清理服务

在桌面窗口点击“停止服务”，或手动执行：

```powershell
docker compose down
```

## 回退到 Web 模式

如果 Electron 打包或桌面能力暂时不可用，仍可使用：

```powershell
cd desktop-ui
npm run dev
```

然后浏览器打开 `http://localhost:5173`。
