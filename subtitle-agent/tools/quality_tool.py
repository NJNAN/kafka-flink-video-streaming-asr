from __future__ import annotations

import re
from collections import Counter


def local_quality_scan(items: list[dict], report: dict) -> dict:
    too_long = []
    too_short = []
    repeated = []
    texts = []
    for index, item in enumerate(items, start=1):
        text = str(item.get("text", "")).strip()
        start = int(item.get("start_ms", 0))
        end = int(item.get("end_ms", start))
        duration = end - start
        texts.append(text)
        if len(text) > 42:
            too_long.append({"index": index, "text": text, "length": len(text)})
        if duration < 450:
            too_short.append({"index": index, "text": text, "duration_ms": duration})
        if re.search(r"(.{2,8})\1{2,}", text):
            repeated.append({"index": index, "text": text})

    counts = Counter(texts)
    duplicate_texts = [{"text": text, "count": count} for text, count in counts.items() if text and count > 1]
    return {
        "subtitle_count": len(items),
        "too_long": too_long[:30],
        "too_short": too_short[:30],
        "repeated": repeated[:30],
        "duplicate_texts": duplicate_texts[:30],
        "blocking_gaps": report.get("blocking_uncovered_gaps_after_recovery", []),
        "ignored_gaps": report.get("ignored_uncovered_gaps_after_recovery", []),
        "hotwords": report.get("hotwords", []),
        "status": report.get("status", "unknown"),
    }
