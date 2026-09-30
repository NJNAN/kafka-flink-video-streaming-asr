# USE 资源清单与观测接口

| 资源 | Utilization | Saturation | Errors | 数据来源 |
|---|---|---|---|---|
| ASR 全局推理锁 | 持锁秒数/进程存活秒数（包含正在持锁） | 当前排队数、逐请求 wait P95 | 锁内异常累计数 | ASR `/runtime`、`/metrics` |
| GPU | nvidia-smi utilization.gpu | memory.used / memory.total、OOM 日志 | CUDA / CTranslate2 异常 | 宿主机 nvidia-smi；非锁利用率 |
| Kafka | 输入/输出消息数、速率 | 已提交 offset 的 consumer lag | broker、producer 超时 | 实验逐片段 offset 与采样 |
| Flink | 作业/算子状态 | REST backpressure、checkpoint 延迟 | restart 与 checkpoint failed | `/jobs/<job>/checkpoints`、Flink UI |
| API / SQLite | 原始结果数 | pending projection 数 | 持久化/消费异常 | API `/metrics`、原始账本 |

锁的 `lock_wait_time_ms` 与 `lock_hold_time_ms` 单独返回；hold 覆盖 faster-whisper 返回的生成器遍历。使用单调时钟计时，异常也会释放锁并记录分布。原字段 inference_time_ms 保留：含等待与后处理，不代表纯 GPU kernel 时间，也不包含首次模型加载。

Prometheus histogram 采用秒单位，固定 11 个 bucket，不使用 stream/run/片段标签，避免高基数。进程重启后计数器归零；lock_utilization 是进程生命周期平均，不是滑动窗口容量结论。API 原始账本 gauge 是当前数据库视图，不能当作进程 counter 使用。

```bash
curl http://localhost:8001/metrics
curl http://localhost:8001/runtime
curl http://localhost:8000/metrics
curl 'http://localhost:8000/api/reliability/segments?run_id=YOUR_RUN'
```

独立实验分别用 18001、18000、18081。`experiments/prometheus.yml` 提供 scrape 与锁队列告警配置；可接入现有 Prometheus，不依赖 Grafana。Kafka lag 的未知值不替换为零；原来的 `/api/metrics` 仍用于句子聚合看板。

方法参考：[USE Method 的软件资源定义](https://www.brendangregg.com/usemethod.html)。

原始文件中的源码 SHA256 是实验当时本机文件的字节指纹；Git 换行转换及后续改动可能使当前检出字节不同。公开数据文件设置为 -text，跨平台保持原始 SHA256。
