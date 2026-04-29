# StreamSense 压测说明

## 前置条件

先启动完整后端，并确认 `videos/input.mp4` 存在：

```powershell
docker compose up -d --build
docker compose ps
```

压测脚本复用现有 `ingest` 镜像，不改变一键启动方式。单路、2 路、4 路测试都可以复用同一个视频源，但每一路会自动生成不同的 `stream_id`。

## 运行压测

单路：

```powershell
python tools/benchmark_streamsense.py --streams 1 --video-source /videos/input.mp4
```

连续跑 1、2、4 路：

```powershell
python tools/benchmark_streamsense.py --streams 1 2 4 --video-source /videos/input.mp4
```

脚本会执行：

1. 检查 `http://localhost:8000/health`。
2. 使用 `docker compose run --rm --no-deps ingest` 拉起多路 ingest。
3. 每一路设置不同 `STREAM_ID`。
4. 等待 API 收到字幕片段并稳定。
5. 读取 `/api/metrics`、`/api/streams/{stream_id}/segments`。
6. 通过 Kafka 容器查询 consumer group lag。
7. 输出 JSON 和 Markdown 报告。

## 输出文件

默认输出目录：

```text
data/results/benchmark/
```

主要文件：

- `benchmark_report.json`：最后一次或多次压测的机器可读汇总。
- `benchmark_report.md`：最后一次压测的可读报告。
- `benchmark_report_1streams.json` / `.md`：单路结果。
- `benchmark_report_2streams.json` / `.md`：2 路结果。
- `benchmark_report_4streams.json` / `.md`：4 路结果。

## 报告指标

报告至少包含：

- 端到端延迟：`created_at -> result_written_at`。
- ASR 推理耗时：`asr_inference_time_ms` 或 `inference_time_ms`。
- Kafka/Flink 调度耗时：`kafka_sent_at -> flink_received_at`。
- API 聚合耗时：`api_received_at -> result_written_at`。
- P50 / P95 / P99 延迟。
- 成功片段数、失败片段数。
- 吞吐量：成功片段数 / 压测墙钟时间。
- Kafka 积压：consumer group lag。
- Redis 写入耗时：`redis_write_time_ms`。

## 注意事项

- 首次运行如果 ASR 模型还没有加载，延迟会明显偏高；正式记录前建议先跑一次预热。
- `large-v3 + cuda + float16` 准确率高，但 4 路并发会受单机 GPU 显存和推理锁影响。
- 如果 Docker Desktop 没启动，脚本会在 API 健康检查或 `docker compose run` 阶段失败。
