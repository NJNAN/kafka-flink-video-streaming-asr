# StreamSense 脱敏示范案例

本目录用于让 GitHub 访问者在不下载模型、不准备视频的情况下，直接理解系统输出。

## 场景

假设输入是一段“大数据课程介绍”中文视频。系统按以下顺序处理：

```text
视频 -> VAD 音频切片 -> Kafka -> Flink -> ASR -> Kafka -> API -> 字幕与关键词
```

## 文件

| 文件 | 说明 |
| --- | --- |
| `demo_transcript.srt` | 可直接用播放器打开的字幕示例。 |
| `demo_transcripts.jsonl` | API 聚合后的句子级字幕示例。 |
| `demo_keyword_events.jsonl` | 每句字幕对应的关键词事件。 |
| `demo_metrics.json` | 本次示例的指标摘要。 |

## 可观察到的处理结果

1. ASR 结果带有 `stream_id`、`segment_id` 和时间戳。
2. Flink 和 ASR 的耗时会写入结果，便于分析链路瓶颈。
3. API 会为字幕生成关键词事件。
4. `Kafka`、`Flink`、`实时数据` 等课程领域词会被优先识别为关键词。

这些文件是脱敏静态示例，不是脚本运行时自动读取的输入数据。
