# MeetFlow 手机/平板会议纪要 App

MeetFlow 是 StreamSense 的移动端会议纪要入口。它把手机或平板麦克风采集到的语音切成短音频片段，上传到 StreamSense Live 后端，后续仍由 Kafka、Flink、ASR、FastAPI 完成实时识别和结果聚合；移动端只负责“开始记录、实时显示、结束生成纪要”这条最短用户路径。

当前支持两种运行形态：

- **HTTPS PWA**：同一局域网内用手机/平板浏览器访问 Vite HTTPS 地址，适合快速联调。
- **Android APK**：通过 Capacitor 封装为原生 Android WebView 应用，包名为 `com.streamsense.meetflow`。

## 技术栈

| 层次 | 技术 | 用途 |
| --- | --- | --- |
| UI | React 19 + TypeScript 5.9 | 会议记录状态、实时文字、纪要卡片和待办列表 |
| 构建 | Vite 7 | 本地开发服务、HTTPS 调试、生产构建 |
| 录音 | `getUserMedia` + `MediaRecorder` | 获取麦克风权限并按 1.8 秒切片上传 |
| 实时回显 | `fetch` + 轮询 API | 每 0.7 秒读取 `meetflow-tablet` 流的转写片段 |
| 兜底识别 | Web Speech API | 后端未连通或浏览器支持时提供低延迟文字兜底 |
| Android 封装 | Capacitor Core / Android 8.4 | 将 Web App 打包为 Android APK |
| Android 工程 | minSdk 24, targetSdk 36 | 声明 `RECORD_AUDIO`、`INTERNET`、明文局域网访问配置 |

## 数据流

```text
手机/平板麦克风
  -> MediaRecorder 每 1.8 秒生成 webm/opus 音频片段
  -> POST /live/audio，携带 stream_id、run_id、chunk_index、hotwords
  -> StreamSense Live Ingest
  -> Kafka audio-segment
  -> Flink 调度 ASR
  -> Kafka transcription-result
  -> FastAPI 聚合到 /api/streams/meetflow-tablet/segments
  -> App 轮询回显，并在结束后生成摘要、待办和原文摘录
```

默认流 ID 是 `meetflow-tablet`。每次点击“开始记录”都会生成新的 `run_id`，App 只合并本次会议的识别片段，避免和历史演示数据混在一起。

## 运行 HTTPS PWA

```powershell
cd meeting-assistant-tablet
npm install
npm run dev:https
```

电脑和手机/平板连接同一个 Wi-Fi 后，在移动设备浏览器访问 Vite 输出的局域网 HTTPS 地址，例如：

```text
https://192.168.123.242:5180
```

第一次访问会看到自签名证书提示，接受后再点击“开始记录”。多数移动浏览器不允许普通 `http://电脑IP:5180` 页面打开麦克风，所以联调移动端时优先使用 `npm run dev:https`。

浏览器支持时，可以通过“添加到桌面”以 PWA 方式运行，视觉和交互会更接近独立 App。

## 构建 Android APK

Capacitor 配置：

```text
appId: com.streamsense.meetflow
appName: MeetFlow
webDir: dist
```

构建 debug APK：

```powershell
$env:ANDROID_HOME="C:\Users\28952\AppData\Local\Android\Sdk"
$env:ANDROID_SDK_ROOT="C:\Users\28952\AppData\Local\Android\Sdk"
npm run build
npx cap sync android
.\android\gradlew.bat -p android assembleDebug
```

输出位置：

```text
android/app/build/outputs/apk/debug/app-debug.apk
```

如需在仓库根目录保留一份本地安装包，可手动复制为 `MeetFlow-debug.apk`。APK、Gradle build 目录、Capacitor 同步产物都已在 `.gitignore` 中排除，不会进入公开仓库。

## 后端地址配置

Capacitor 原生壳运行时无法走 Vite 代理，因此默认会访问：

```text
API:         http://192.168.123.242:8000
Live Ingest: http://192.168.123.242:8010
```

电脑 IP 变化时，构建前设置：

```powershell
$env:VITE_STREAMSENSE_BACKEND_HOST="新的电脑IP"
npm run build
npx cap sync android
```

也可以分别指定两个服务地址：

```powershell
$env:VITE_STREAMSENSE_API_BASE="http://电脑IP:8000"
$env:VITE_STREAMSENSE_LIVE_INGEST_URL="http://电脑IP:8010"
$env:VITE_STREAMSENSE_STREAM_ID="meetflow-tablet"
npm run dev:https
```

开发服务默认把同源请求代理到本机实时后端：

```text
/live/audio -> http://127.0.0.1:8010/live/audio
/api/...    -> http://127.0.0.1:8000/api/...
```

## 产品能力

- 一键开始记录，申请麦克风权限并实时上传音频片段。
- 录音时显示“正在听”文字卡片，后端结果返回后自动刷新。
- 一键结束，根据真实转写文本生成标题、摘要、待办和原文摘录。
- 没有识别到清晰内容时明确提示，不伪造示例纪要。
- 支持复制 Markdown 格式纪要，方便粘贴到聊天、文档或项目记录中。

## 验证清单

| 检查项 | 预期结果 |
| --- | --- |
| `npm run dev:https` | 手机/平板能打开 HTTPS 页面并申请麦克风权限 |
| StreamSense 后端已启动 | 点击开始后几秒内出现实时文字或服务连接提示 |
| `/api/streams/meetflow-tablet/segments` | 可以看到本次 `run_id` 对应的识别片段 |
| `npm run build` | TypeScript 类型检查和 Vite 构建通过 |
| `npx cap sync android` | Web 构建产物同步到 Android 工程 |
| `assembleDebug` | 生成可安装的 Android debug APK |
