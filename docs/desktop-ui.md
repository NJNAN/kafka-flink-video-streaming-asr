# StreamSense 电脑端可视化 App 原型

本目录新增的是 `desktop-ui/`，用于展示 StreamSense 的“视频语音理解工作台”。现在它既能作为纯 Web 前端运行，也能作为 Electron Windows 桌面启动器运行。它不改动现有 Kafka、Flink、ASR、Redis、FastAPI 和 Docker Compose 主流程。

## 当前状态

- 技术栈：React + Vite + TypeScript + Electron。
- 数据来源：默认优先请求 `http://localhost:8000`，失败后回退 `src/data/mockData.ts`。
- 接口接入：`src/api/apiClient.ts` 已接入 `health`、`status`、`transcripts`、`keywords`、`results`、`logs`。
- 桌面能力：`electron/main.ts` 通过安全 IPC 暴露 Docker Compose 控制、视频选择、任务启动、日志导出、目录打开等能力。
- 视觉方向：早期 iOS / iOS 6 之前的拟物风格桌面工作台，使用 CSS 渐变、内阴影、外阴影、边框高光、纸张面板、玻璃状态灯和金属按钮实现，不依赖外部图片资源。

## 启动方式

在仓库根目录执行：

```powershell
cd desktop-ui
npm install
npm run dev
```

默认访问：

```text
http://localhost:5173
```

## 构建验证

```powershell
cd desktop-ui
npm run build
npm run electron:build
```

构建产物会输出到：

```text
desktop-ui/dist/
```

该目录是本地构建产物，已在 `.gitignore` 中忽略。

## 接入真实 FastAPI 的位置

强制 mock：

```text
VITE_USE_MOCK=true
```

如果要显式指定 FastAPI 地址，可以创建 `desktop-ui/.env.local`：

```text
VITE_API_BASE_URL=http://localhost:8000
```

现有后端已经有：

- `GET /health`
- `GET /api/status`
- `GET /api/transcripts`
- `GET /api/keywords`
- `GET /api/hotwords`
- `GET /api/results`
- `GET /api/results/report?path=...`
- `GET /api/results/file?path=...`
- `GET /api/logs?limit=300`

## Electron 运行与打包

开发模式：

```powershell
cd desktop-ui
npm run electron:dev
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

更多 Windows 桌面启动器说明见：

```text
docs/windows-launcher.md
```
