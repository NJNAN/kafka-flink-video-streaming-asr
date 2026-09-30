"""Compute event-based SLOs. Aggregated percentile snapshots are not denominators."""
import argparse
import json
from pathlib import Path

def report(events, expected_ids=None, deadline_ms=10000, success_target=0.99, deadline_target=0.95):
    canonical = {}
    for item in events:
        key = (str(item.get('stream_id', '')), str(item.get('run_id', '')), str(item['segment_id']))
        if key not in canonical or canonical[key].get('status') != 'ok':
            canonical[key] = item
    if expected_ids is not None:
        expected = {tuple(str(i) for i in k) for k in expected_ids}
        canonical = {k: v for k, v in canonical.items() if k in expected}
        total = len(expected)
        missing = total - len(canonical)
    else:
        total = len(canonical)
        missing = None
    success = sum(i.get('status') == 'ok' for i in canonical.values())
    timely = sum(i.get('status') == 'ok' and isinstance(i.get('end_to_end_time_ms'), (int, float))
                 and 0 <= i['end_to_end_time_ms'] <= deadline_ms for i in canonical.values())
    unknown_latency = sum(i.get('status') == 'ok' and (not isinstance(i.get('end_to_end_time_ms'), (int, float))
                          or i['end_to_end_time_ms'] < 0) for i in canonical.values())
    def budget(good, target):
        allowance = total * (1 - target)
        bad = total - good
        return dict(target=target, good=good, total=total, sli=good / total if total else None,
                    allowed_bad_events=allowance, bad_events=bad,
                    budget_remaining_fraction=1-bad/allowance if allowance else None,
                    burn_rate=(bad/total)/(1-target) if total and target < 1 else None)
    return dict(window='observed events only; not a 30-day availability claim',
                denominator='expected input manifest' if expected_ids is not None else 'observed results; missing input unknown',
                missing_inputs=missing, unknown_latency_events=unknown_latency, deadline_ms=deadline_ms,
                success=budget(success, success_target), deadline=budget(timely, deadline_target))

def main():
    p = argparse.ArgumentParser()
    p.add_argument('--events', required=True, help='JSON list or JSONL of canonical raw segment results')
    p.add_argument('--expected', help='JSON list of [stream_id, run_id, segment_id]')
    p.add_argument('--deadline-ms', type=int, default=10000)
    a = p.parse_args()
    text = Path(a.events).read_text(encoding='utf-8')
    events = json.loads(text) if text.lstrip().startswith('[') else [json.loads(line) for line in text.splitlines() if line.strip()]
    expected = json.loads(Path(a.expected).read_text(encoding='utf-8')) if a.expected else None
    print(json.dumps(report(events, expected, a.deadline_ms), indent=2, ensure_ascii=False))

if __name__ == '__main__':
    main()
