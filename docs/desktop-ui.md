# StreamSense 电脑端可视化 App 原型

本目录新增的是 `desktop-ui/`，用于展示 StreamSense 的“视频语音理解工作台”原型。它只新增前端，不改动现有 Kafka、Flink、ASR、Redis、FastAPI 和 Docker Compose 主流程。

## 当前状态

- 技术栈：React + Vite + TypeScript。
- 数据来源：默认使用 `src/data/mockData.ts` 中的 mock 数据。
- 接口预留：`src/api/apiClient.ts` 已按后续 FastAPI 接入方向封装 `health`、`tasks`、`transcripts`、`keywords`、`results`、`logs`。
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
```

构建产物会输出到：

```text
desktop-ui/dist/
```

该目录是本地构建产物，已在 `.gitignore` 中忽略。

## 接入真实 FastAPI 的位置

第一版默认 mock：

```text
VITE_USE_MOCK=true
```

后续如果要接入已有 FastAPI，可以创建 `desktop-ui/.env.local`：

```text
VITE_USE_MOCK=false
VITE_STREAMSENSE_API_BASE=http://localhost:8000
```

现有后端已经有：

- `GET /health`
- `GET /api/status`
- `GET /api/transcripts`
- `GET /api/keywords`
- `GET /api/hotwords`

前端还预留了后续可补充的：

- `GET /api/tasks`
- `GET /api/results`
- `GET /api/logs`

这些接口未实现前请保持 mock 模式运行。
