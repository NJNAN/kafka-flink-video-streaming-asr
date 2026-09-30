# StreamSense 的 SLI、SLO 与错误预算

这些目标用于本地实验与容量决策，不是对外 SLA。实验窗口与 30 天生产窗口分别报告。

| SLI | 分子 / 分母 | 实验目标 | 无数据处理 |
|---|---|---|---|
| 原始片段成功率 | status=ok 的唯一片段 / 生产者确认的输入片段 | ≥99% | 输入清单缺失时，仅报告已观察结果；缺失量未知 |
| 延迟达标率 | 成功且端到端≤10s 的唯一片段 / 输入片段 | ≥95% | 缺失延迟保守记为未达标，不当作 0ms |
| 故障后追平 | 停止生产后，结果齐全且 consumer committed lag=0 | 停止生产后≤60s | offset 未提交、broker 不可访问都记为 unknown |

片段身份为 `(stream_id, run_id, segment_id)`。成功的重放不增加分母；失败后成功重放可升级最终状态。空文本可能是能量过滤的正确结果，不能视为失败。字幕句子聚合会改变条目数量，**不能用句子条目或各次 P95 的平均数计算片段 SLI**。

预算：`允许失败数=N×(1-target)`；`剩余比例=1-(N-good)/允许失败数`；`燃烧率=((N-good)/N)/(1-target)`。负剩余表示已超支，保留负值。空窗口返回 null。99% 的 40 个输入仅允许 0.4 个失败，短样本不能证明长期 99% 可用性。

```bash
python tools/slo_report.py --events events.json --expected expected_ids.json
python -m tools.reliability_report --check
```

`events.json` 是 `/api/reliability/segments?run_id=...` 的原始片段列表；expected_ids 是生产者确认清单中的三元组。历史 metrics_history.jsonl 缺少完整原始分母与锁埋点，不能回填“历史锁等待”或可靠性承诺。

30 天预算需要连续保存该窗口的输入账本和原始结果；目前公开结果仅为短时本地演练。预算余额>75%：正常实验；25–75%：缩小变更；<25%：优先可靠性；超支：暂停性能优化并排查失败/缺失。低流量窗口须人工复核。

告警可从成功/延迟 SLI 的实际事件计算燃烧率；推理锁队列持续升高先限流，再选择模型或吞吐策略。实验中 10s 阈值是预先配置的验收目标，不会为使结果通过而在测后调整。

方法参考：[Google SRE 的 SLO 定义](https://sre.google/sre-book/service-level-objectives/)。
