# StreamSense Live 大数据实时字幕版

这个目录是独立的直播/麦克风实时字幕桌面端。

它和 `desktop-ui/` 的离线字幕生成器分开，原因是两者目标完全不同：

- `desktop-ui/`：处理一个已经存在的视频文件，偏“最终字幕文件质量”。
- `desktop-ui-live/`：采集摄像头/麦克风，偏“实时流处理演示”，必须走 Kafka + Flink。

## 实时链路

```text
Electron 摄像头/麦克风
-> desktop-ui-live/src/App.tsx 分段录音
-> desktop-ui-live/live-ingest/app.py 接收音频
-> FFmpeg 转 wav
-> 静音过滤
-> Kafka audio-segment
-> flink/transcription_job.py
-> services/asr/asr_service.py
-> Kafka transcription-result
-> services/api/app.py
-> desktop-ui-live/src/App.tsx 轮询 /api/streams/desktop-live/segments 显示字幕
```

## 启动方式

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

打包后的 exe：

```text
desktop-ui-live/release/win-unpacked/StreamSenseLive.exe
```

## 关键文件

- `src/App.tsx`：实时字幕界面，负责录音、上传、轮询字幕。
- `electron/main.ts`：Electron 主进程，负责启动 Docker Compose 大数据服务。
- `live-ingest/app.py`：实时音频接入服务，负责音频转 wav、静音过滤、写 Kafka。
- `docker-compose.live.yml`：给原项目额外加 `live-ingest` 服务。

## 课程设计表达

这版可以说是“大数据实时流处理版”，因为实时音频不是直接请求 ASR，而是进入 Kafka，再由 Flink 调度 ASR，最后由 API 汇总展示。
