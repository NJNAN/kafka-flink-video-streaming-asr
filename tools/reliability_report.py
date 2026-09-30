"""Deterministically recompute published metrics from raw requests and events."""
import argparse
import hashlib
import json
from pathlib import Path
from tools.reliability_lab import percentile
from tools.slo_report import report as slo_report
from tools.evaluate_subtitles import normalize_text, edit_distance

ROOT = Path(__file__).resolve().parents[1]

def quality(rows, fixtures):
    reference = {str(i+1): f['reference'] for i,f in enumerate(fixtures)}
    distance = total = 0
    for row in rows:
        ref = normalize_text(reference[str(int(row['request']['segment_id'])%4+1)])
        hyp = normalize_text(row['response']['text'])
        distance += edit_distance(list(ref), list(hyp))
        total += len(ref)
    return dict(char_edits=distance, reference_chars=total, cer=distance/total if total else None)

def summarize(path):
    raw = json.loads(path.read_text(encoding='utf-8'))
    result = dict(file=path.name, sha256=hashlib.sha256(path.read_bytes()).hexdigest(), kind=raw['kind'])
    if raw['kind'] == 'direct_asr_capacity':
        trials = []
        for t in raw['trials']:
            rows = t['rows']
            latencies = [r['http_elapsed_ms'] for r in rows]
            waits = [r['response']['lock_wait_time_ms'] for r in rows]
            holds = [r['response']['lock_hold_time_ms'] for r in rows]
            trials.append(dict(concurrency=t['concurrency'], count=len(rows),
                               throughput=round(len(rows)/t['elapsed_seconds'],3),
                               p50_ms=round(percentile(latencies,.5),2), p95_ms=round(percentile(latencies,.95),2),
                               p99_ms=round(percentile(latencies,.99),2),
                               wait_p95_ms=round(percentile(waits,.95),2), hold_p95_ms=round(percentile(holds,.95),2),
                               max_queue=max(s.get('lock_queue_depth',0) for s in t['runtime_samples']),
                               quality=quality(rows,raw['metadata']['fixtures'])))
        result['trials'] = trials
    elif raw['kind'] == 'failed_replay':
        final = raw['final_results']
        result.update(replayed_count=len(raw['replay_plan']), final_success_count=sum(e.get('status')=='ok' for e in final),
                      logical_result_count=len(final),
                      logical_duplicates=len(final)-len({(e['stream_id'],e['run_id'],e['segment_id']) for e in final}),
                      parent_sha256=raw['parent_sha256'])
    else:
        expected = [[r['payload'][k] for k in ('stream_id','run_id','segment_id')] for r in raw['input_manifest']]
        events = raw['results']
        started = next(e['at_ms'] for e in raw['events'] if e['action']=='start_started')
        complete = next(e['at_ms'] for e in raw['events'] if e['action']=='result_check_finished')
        stop = next(e['at_ms'] for e in raw['events'] if e['action']=='stop_started')
        stopped = next(e['at_ms'] for e in raw['events'] if e['action']=='stopped')
        after_restore = [e['api_received_at'] for e in events if e.get('status')=='ok' and e.get('api_received_at',0)>=started]
        lag0 = [s['at_ms'] for s in raw['samples'] if s.get('lag')==0 and s['at_ms']>=complete]
        last_ack = max(r['acknowledged_at_ms'] for r in raw['input_manifest'])
        lags = [s['lag'] for s in raw['samples'] if s.get('lag') is not None]
        result.update(service=raw['service'], input_count=len(expected), result_count=len(events),
                      success_count=sum(e.get('status')=='ok' for e in events),
                      replay_deliveries=sum(e.get('deliveries',1)-1 for e in events),
                      logical_duplicates=len(events)-len({(e['stream_id'],e['run_id'],e['segment_id']) for e in events}),
                      missing=len(set(map(tuple,expected))-{(e['stream_id'],e['run_id'],e['segment_id']) for e in events}),
                      stop_duration_ms=stopped-stop,
                      first_result_after_start_seconds=round((min(after_restore)-started)/1000,3) if after_restore else None,
                      drain_after_last_ack_seconds=round((min(lag0)-last_ack)/1000,3) if lag0 else None,
                      full_recovery_seconds=round((min(lag0)-started)/1000,3) if lag0 else None,
                      max_lag=max(lags) if lags else None, lag_unknown_samples=sum(s.get('lag') is None for s in raw['samples']),
                      slo=slo_report(events,expected), checkpoint_completed_before=raw['baseline_checkpoint']['counts']['completed'],
                      checkpoint_restore_observed=max(s.get('checkpoints',{}).get('counts',{}).get('restored',0) for s in raw['samples']) > raw['baseline_checkpoint']['counts']['restored'],
                      producer_error_count=len(raw.get('producer_errors',[])))
    return result

def homepage_evidence(data):
    capacity = next(e for e in data['experiments'] if e['kind']=='direct_asr_capacity')['trials']
    faults = [e for e in data['experiments'] if e['kind']=='pipeline_fault']
    lines = ['<!-- reliability-evidence:start -->', '## 故障恢复证据', '',
             '**把“能转写”推进到“出故障后能追溯、重放和验收”。** 2026-10-01 在隔离 Compose 栈上运行真实 Kafka → Flink → GPU ASR → API → SQLite 演练，逐片段核对输入与原始结果。', '',
             '| 停机对象 | 输入 / 原始结果 / 成功 | 缺失 / 逻辑重复 | 重放交付 | 启动后首个成功 |',
             '| :--- | :---: | :---: | ---: | ---: |']
    for e in faults:
        recovery = 'unknown' if e['first_result_after_start_seconds'] is None else f"{e['first_result_after_start_seconds']:.2f}s"
        lines.append(f"| {e['service']} | {e['input_count']} / {e['result_count']} / {e['success_count']} | {e['missing']} / {e['logical_duplicates']} | {e['replay_deliveries']} | {recovery} |")
    first, last = capacity[0], capacity[-1]
    lines += ['', f"**容量结论也有边界。** 1/2/3/4/6 并发各 24 次固定 ASR 请求（共 120 次）；从 1 到 6 并发，HTTP P95 从 **{first['p95_ms']:.0f}ms** 升至 **{last['p95_ms']:.0f}ms**，锁等待 P95 达 **{last['wait_p95_ms']:.0f}ms**，吞吐没有按并发数增长。各档同样本 CER 均为 **{first['quality']['cer']*100:.2f}%**。这组是 ASR 服务容量测试，历史视频链路测试在下方单独说明。", '',
              '![固定容量与推理排队](docs/assets/reliability/capacity.png)', '',
              '**失败和恢复分别记录。** ASR 停机期间有明确失败结果；初始成功率与延迟 SLO 的超支照常公开。补偿重放不会改写初始数据，也不将短时演练称为 30 天可用性或端到端 exactly-once。', '',
              '[原始数据与自动报告](docs/可靠性实测报告.md) · [复现与恢复 Runbook](docs/可靠性实验操作手册.md) · [USE 指标](docs/USE资源清单.md) · [SLO / 错误预算](docs/SLO.md) · [评测口径](docs/评测口径说明.md)', '',
              '<!-- reliability-evidence:end -->']
    return "\n".join(lines)

def evidence_markdown(data):
    lines = ["# StreamSense 可靠性与容量实测（2026-10-01）", "",
             "本页由原始 JSON 自动生成；`python -m tools.reliability_report --check` 可复核数字和输入哈希。", "",
             "## ASR 固定负载容量", "",
             "small / CUDA / float16 / beam=5；四句公开合成音频，每档 24 请求，预热排除。HTTP 计时包含服务端等待，未经过 Kafka / Flink / 视频 VAD。", "",
             "| 并发 | 请求数 | 吞吐（段/s） | HTTP P95（ms） | wait P95（ms） | hold P95（ms） | 最大队列 | CER |",
             "|---:|---:|---:|---:|---:|---:|---:|---:|"]
    capacity = next(e for e in data['experiments'] if e['kind']=='direct_asr_capacity')
    for t in capacity['trials']:
        lines.append(f"| {t['concurrency']} | {t['count']} | {t['throughput']:.3f} | {t['p95_ms']:.2f} | {t['wait_p95_ms']:.2f} | {t['hold_p95_ms']:.2f} | {t['max_queue']} | {t['quality']['cer']*100:.2f}% |")
    lines += ["", "吞吐在这组负载上进入平台期，额外并发增加锁等待。五档文本编辑数相同；合成音频精度不能外推到自然会议。没有使用非稳态短突发数据验证 Little’s Law。", "",
              "![容量与排队](assets/reliability/capacity.png)", "", "## 真实故障演练", "",
              "隔离 Compose 项目 streamsense-lab，每组固定 40 个输入，间隔 1.3s，在持续生产时停一个容器 3s 后启动。stop 命令本身另有耗时；ASR 加载与 Flink 重调度均计入恢复。默认项目未被操作。", "",
              "| 故障对象 | 输入/原始结果/成功 | 缺失 | 逻辑重复 | 重放交付 | 启动后首个成功（s） | 停止生产后追平（s） | max lag | 成功 SLI | ≤10s SLI |",
              "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|"]
    def value(x):
        return 'unknown' if x is None else f'{x:.3f}'
    faults = [e for e in data['experiments'] if e['kind']=='pipeline_fault']
    for e in faults:
        lines.append(f"| {e['service']} | {e['input_count']}/{e['result_count']}/{e['success_count']} | {e['missing']} | {e['logical_duplicates']} | {e['replay_deliveries']} | {value(e['first_result_after_start_seconds'])} | {value(e['drain_after_last_ack_seconds'])} | {e['max_lag']} | {e['slo']['success']['sli']*100:.1f}% | {e['slo']['deadline']['sli']*100:.1f}% |")
    lines += ["", "![故障与追平](assets/reliability/fault-lag.png)", "",
              "首个成功以启动命令发起→API 收到第一个成功片段计；追平必须同时满足生产结束、原始结果齐全和 committed lag=0，包含 checkpoint 提交延迟。运行中无提交且非空的分区、broker 不可访问均为 unknown；从未有记录的空分区为零 backlog。采样周期约 1s，资源探测会增加间隔。", "",
              "### 负面结果与预算", "",
              "目标预设为片段成功率≥99%、≤10s 比例≥95%、停止生产后≤60s 追平。失败片段照常持久化，不能因为账本齐全就称为零失败。"]
    for e in faults:
        success, deadline = e['slo']['success'], e['slo']['deadline']
        lines.append(f"- {e['service']}：成功预算剩余 {success['budget_remaining_fraction']:.2f}，燃烧率 {success['burn_rate']:.2f}；延迟预算剩余 {deadline['budget_remaining_fraction']:.2f}，燃烧率 {deadline['burn_rate']:.2f}。Flink checkpoint 恢复观测：{e['checkpoint_restore_observed']}；生产者瞬时错误 {e['producer_error_count']} 次。")
    for e in data['experiments']:
        if e['kind']=='failed_replay':
            lines.append(f"- 独立补偿阶段：按原始输入 ID 重放 {e['replayed_count']} 个失败片段，最终成功 {e['final_success_count']}/{e['logical_result_count']}，逻辑重复 {e['logical_duplicates']}。补偿不会改写上表初始失败或初始 SLO。")
    lines += ["", "## 语义边界与复现", "",
              "Flink 默认 30s checkpoint 已存在；实验设为 5s 并存到隔离 data/checkpoints。Kafka Sink 为 AT_LEAST_ONCE，HTTP 推理是非事务副作用。SQLite 原始账本以 stream/run/segment 主键幂等，处理完成后才提交 API offset；成功结果不会因不同转写文本而重复入原始账本。Redis、关键词事件、JSONL 与内存句子缓冲不是一个事务，不能宣称端到端 exactly-once。进程崩溃时句子投影可能重复或待修复，但已收原始片段可查询、重放。", "",
              "实验采用 Docker stop/start 脚本，未引入 Trogdor/Toxiproxy。单机、单 broker、短时固定合成负载，不能证明集群容灾或 30 天 SLO。旧的 4 路视频测试是 60s 冒烟，仍保留其证据并与新容量表分开。", "",
              "复现命令和安全隔离约束见 [实验操作手册](可靠性实验操作手册.md)，指标见 [USE](USE资源清单.md)，预算见 [SLO](SLO.md)，精度见 [评测口径](评测口径说明.md)。", "",
              "## 原始文件 SHA256", "", "| 文件 | SHA256 |", "|---|---|"]
    for e in data['experiments']:
        lines.append(f"| [{e['file']}](../benchmarks/reliability/20261001/{e['file']}) | `{e['sha256']}` |")
    return "\n".join(lines)+"\n"

def main():
    p = argparse.ArgumentParser()
    p.add_argument('--directory', default='benchmarks/reliability/20261001')
    p.add_argument('--check', action='store_true')
    a = p.parse_args()
    folder = ROOT/a.directory
    summaries = [summarize(p) for p in sorted(folder.glob('*.json')) if p.name != 'summary.json']
    data = dict(schema_version=1, quantile='linear interpolation at (n-1)*q', experiments=summaries)
    text = json.dumps(data, ensure_ascii=False, indent=2)+'\n'
    destination = folder/'summary.json'
    markdown = evidence_markdown(data)
    homepage = homepage_evidence(data)
    readme_path = ROOT/'README.md'
    readme = readme_path.read_text(encoding='utf-8')
    before, remainder = readme.split('<!-- reliability-evidence:start -->',1)
    _, after = remainder.split('<!-- reliability-evidence:end -->',1)
    updated_readme = before+homepage+after
    report_path = ROOT/'docs/可靠性实测报告.md'
    if a.check:
        if destination.read_text(encoding='utf-8') != text:
            raise SystemExit('DRIFT: summary differs from recomputed raw data')
        if report_path.read_text(encoding='utf-8') != markdown:
            raise SystemExit('DRIFT: report differs from raw data')
        if updated_readme != readme:
            raise SystemExit('DRIFT: README evidence differs from raw data')
        print('OK: README, summary, report and raw-data hashes match')
    else:
        destination.write_text(text, encoding='utf-8')
        report_path.write_text(markdown, encoding='utf-8')
        readme_path.write_text(updated_readme, encoding='utf-8')
        print(text)

if __name__ == '__main__':
    main()
