# StreamSense 指标与多路流接口

## 片段时间戳字段

每个音频片段会保留业务字段：

- `stream_id`
- `segment_id`
- `start_time`
- `end_time`
- `duration`
- `start_time_ms`
- `end_time_ms`
- `duration_ms`

并补齐链路时间戳：

- `created_at`：ingest 创建片段消息的时间。
- `vad_start_at`：VAD 切片阶段开始时间。
- `vad_end_at`：VAD 切片阶段结束时间。
- `kafka_sent_at`：ingest 写入 Kafka 的时间。
- `flink_received_at`：Flink 收到片段消息的时间。
- `asr_start_at`：Flink 开始请求 ASR 的时间。
- `asr_end_at`：ASR 请求返回的时间。
- `api_received_at`：API 消费到转写结果的时间。
- `result_written_at`：API 写入 Redis / 文件后的时间。

这些字段用于计算端到端延迟、调度耗时、ASR 耗时、API 聚合耗时和 Redis 写入耗时。

## API

### `/api/metrics`

返回全局指标，也支持 `?stream_id=xxx` 查看单路指标。

核心字段：

- `active_stream_count`
- `total_segments`
- `success_segments`
- `failed_segments`
- `average_end_to_end_latency_ms`
- `p50_latency_ms`
- `p95_latency_ms`
- `p99_latency_ms`
- `asr_average_time_ms`
- `kafka_flink_average_dispatch_ms`
- `api_average_aggregation_ms`
- `redis_average_write_ms`
- `retry_count_average`
- `retry_count_max`
- `pending_segments`
- `recent_errors`
- `hotwords_top10`

### `/api/metrics/history`

返回最近一段时间的指标采样，默认最多返回 120 个点：

```text
/api/metrics/history
/api/metrics/history?limit=120
/api/metrics/history?stream_id=demo-video
```

这些采样也会追加写入：

```text
data/results/metrics_history.jsonl
```

并写入 SQLite：

```text
data/results/streamsense.db
```

### `/api/failed-segments`

返回最近失败片段：

```text
/api/failed-segments?limit=50
```

失败片段会包含：

- `stream_id`
- `run_id`
- `segment_id`
- `error`
- `retry_count`
- `created_at_ms`

### `/api/database/summary`

返回 SQLite 里的结构化统计：

```text
/api/database/summary
/api/database/summary?stream_id=demo-video
```

这个接口适合答辩时解释“实验结果不只是日志，也能结构化查询”。

### `/api/streams`

返回当前已观测到的所有 `stream_id`，以及每一路的指标和 Top 热词。

### `/api/streams/{stream_id}`

返回单路流摘要，包括片段数量、最新片段和该流指标。

### `/api/streams/{stream_id}/segments`

按 `start_time_ms` 和 `segment_id` 顺序返回该流字幕片段。不同流可以并行处理，同一路输出保持时间顺序。

### `/api/streams/{stream_id}/hotwords`

返回该流动态热词池。

### `/api/streams/{stream_id}/export`

导出单路字幕结果：

```text
/api/streams/demo-video/export?format=json
/api/streams/demo-video/export?format=srt
/api/streams/demo-video/export?format=vtt
/api/streams/demo-video/export?format=txt
```

## 动态热词

当前实现是轻量工程版：

- 从最近 5 分钟或最近 N 个片段中统计候选词。
- 过滤停用词、过短词、纯数字和无意义符号。
- 综合累计次数、最近窗口次数、出现时间和 ASR 置信度估计分数。
- 达到阈值后进入动态热词池，并广播给 ASR 服务。
- 状态保存到 `data/results/dynamic_hotwords.json`，服务重启后会恢复。

用户操作接口：

```text
POST /api/hotwords/action
```

请求示例：

```json
{
  "stream_id": "demo-video",
  "run_id": "",
  "word": "Kafka",
  "action": "confirm"
}
```

支持动作：

- `confirm`：确认热词，提高权重。
- `ignore`：忽略热词，加入 blocklist。
- `correct`：纠错，需提供 `correction` 字段。
