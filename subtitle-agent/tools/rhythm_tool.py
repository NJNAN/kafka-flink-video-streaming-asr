from __future__ import annotations

import re


def text_len(text: str) -> int:
    return len(re.sub(r"\s+", "", text))


def optimize_subtitle_rhythm(
    items: list[dict],
    min_duration_ms: int = 900,
    max_duration_ms: int = 5800,
    target_cps: float = 13.0,
    bridge_gap_ms: int = 160,
) -> tuple[list[dict], dict]:
    """Rule-based timing pass for easier reading without changing order or text."""

    ordered = sorted([dict(item) for item in items], key=lambda item: int(item.get("start_ms", item.get("start_time_ms", 0))))
    changes: list[dict] = []
    for index, item in enumerate(ordered):
        start = int(item.get("start_ms", item.get("start_time_ms", 0)))
        end = int(item.get("end_ms", item.get("end_time_ms", start + 2500)))
        text = str(item.get("text", "")).strip()
        chars = text_len(text)
        wanted = int(max(min_duration_ms, min(max_duration_ms, chars / max(target_cps, 1.0) * 1000)))
        original = {"start_ms": start, "end_ms": end}
        if end - start < wanted:
            end = start + wanted
        if end - start > max_duration_ms:
            end = start + max_duration_ms
        if index + 1 < len(ordered):
            next_start = int(ordered[index + 1].get("start_ms", ordered[index + 1].get("start_time_ms", end + 1)))
            gap = next_start - end
            if 0 < gap <= bridge_gap_ms:
                end = next_start
            elif end > next_start - 80:
                end = next_start - 80
        if end <= start:
            end = start + 300
        item["start_ms"] = start
        item["end_ms"] = end
        if original != {"start_ms": start, "end_ms": end}:
            changes.append(
                {
                    "index": index + 1,
                    "text": text,
                    "before": original,
                    "after": {"start_ms": start, "end_ms": end},
                    "chars": chars,
                }
            )
    return ordered, {"changes": changes, "change_count": len(changes), "target_cps": target_cps}
