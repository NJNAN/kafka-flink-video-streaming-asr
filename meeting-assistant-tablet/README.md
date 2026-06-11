# MeetFlow 一键会议纪要

面向华为平板的极简会议纪要 App。用户打开后只做一件事：按下按钮记录会议，录音时实时显示正在谈话的文字，结束后自动生成摘要和待办。

## 运行

```powershell
cd meeting-assistant-tablet
npm install
npm run dev
```

华为平板需要麦克风权限时，建议用 HTTPS 开发服务：

```powershell
npm run dev:https
```

电脑和华为平板连接同一个 Wi-Fi 后，在平板浏览器访问 Vite 输出的局域网地址，例如：

```text
https://192.168.123.242:5180
```

浏览器支持时，可以通过“添加到桌面”以 PWA 方式运行，视觉和交互会更接近平板 App。

## APK

当前已支持 Capacitor Android 打包，默认后端主机写入为：

```text
192.168.123.242
```

构建 debug APK：

```powershell
$env:ANDROID_HOME="C:\Users\28952\AppData\Local\Android\Sdk"
$env:ANDROID_SDK_ROOT="C:\Users\28952\AppData\Local\Android\Sdk"
npm run build
npx cap sync android
.\android\gradlew.bat -p android assembleDebug
```

输出文件：

```text
MeetFlow-debug.apk
android/app/build/outputs/apk/debug/app-debug.apk
```

如果电脑 IP 变化，重新构建前设置：

```powershell
$env:VITE_STREAMSENSE_BACKEND_HOST="新的电脑IP"
```

## 后端数据

默认使用浏览器麦克风录音，并把音频片段发送到 StreamSense Live 实时后端识别；如果浏览器自带语音识别可用，也会作为低延迟兜底。录音中会显示“正在听”文字卡片。结束后，标题、摘要和待办会根据本次真实识别到的文本生成；如果没有识别到清晰内容，会明确提示未识别，而不会伪造示例纪要。

当前前端使用快速模式：

- 每 1.8 秒上传一段音频
- 每 0.7 秒轮询一次识别结果
- 浏览器本地语音识别会自动重启，尽量保持实时文字不断
- 平板麦克风声音偏小时，live-ingest 的静音过滤阈值已放宽到 `LIVE_INGEST_MIN_DBFS=-55`

开发服务默认把同源请求代理到本机实时后端：

```text
/live/audio -> http://127.0.0.1:8010/live/audio
/api/...    -> http://127.0.0.1:8000/api/...
```

如果服务地址不同，可以手动指定：

```powershell
$env:VITE_STREAMSENSE_API_BASE="http://电脑IP:8000"
$env:VITE_STREAMSENSE_LIVE_INGEST_URL="http://电脑IP:8010"
npm run dev
```

注意：很多平板浏览器不允许在 `http://电脑IP:5180` 这种非 HTTPS 页面里打开麦克风。遇到麦克风无法开启时，用 `npm run dev:https`，在平板浏览器接受一次自签名证书提示后再点“开始记录”。

## 产品定位

这个应用不展示课程项目、科研流程或控制台指标，只保留一个普通用户能理解的功能：

- 一键开始记录，并实时显示正在谈话的文字
- 一键结束并根据真实转写文本生成纪要
- 输出真实摘要、待办和原文摘录
