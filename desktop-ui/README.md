# StreamSense 离线字幕生成器

这个目录只负责“选择一个本地视频，然后生成最终字幕文件”的桌面端。

它的定位是实用工具，不走 Kafka/Flink 实时链路。用户点击“生成字幕”后，Electron 主进程会调用：

```text
python tools/generate_video_subtitles.py
```

核心链路是：

```text
Electron 选择视频
-> desktop-ui/electron/main.ts:createTask()
-> desktop-ui/electron/main.ts:startTask()
-> tools/generate_video_subtitles.py
-> services/asr:/transcribe-media
-> data/results/tasks/<task_id>/ 输出 srt/vtt/txt/json
```

适合场景：

- 给一个已有视频生成字幕文件。
- 答辩时展示“离线高质量字幕生成”。
- 不强调 Kafka/Flink 流处理，只强调可用性和最终字幕质量。

不要把大数据实时直播代码放到这里。实时版放在：

```text
desktop-ui-live/
```
