from __future__ import annotations

import re


INVISIBLE_RE = re.compile(r"[\u200b-\u200f\u202a-\u202e\u2060\ufeff]")


def item_start(item: dict) -> int:
    return int(item.get("start_ms", item.get("start_time_ms", 0)))


def item_end(item: dict) -> int:
    start = item_start(item)
    return int(item.get("end_ms", item.get("end_time_ms", start + 2500)))


def clean_subtitle_text(text: object) -> str:
    cleaned = INVISIBLE_RE.sub("", str(text or ""))
    cleaned = cleaned.replace("\r\n", "\n").replace("\r", "\n")
    cleaned = re.sub(r"[ \t]+", " ", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


def overlap_ms(left: dict, right: dict) -> int:
    return max(0, min(item_end(left), item_end(right)) - max(item_start(left), item_start(right)))


def normalize_item(
    item: dict,
    fallback_text: str = "",
    min_duration_ms: int = 700,
    source_index: int | None = None,
) -> tuple[dict | None, dict | None]:
    start = max(0, item_start(item))
    end = max(0, item_end(item))
    text = clean_subtitle_text(item.get("text", ""))
    action = None

    if not text and fallback_text:
        text = clean_subtitle_text(fallback_text)
        action = "fallback_text"
    if not text:
        return None, {"action": "drop_empty", "start_ms": start, "end_ms": end}

    if end <= start:
        end = start + 1800
        action = "fix_bad_time"
    elif end - start < min_duration_ms:
        end = start + min_duration_ms
        action = "extend_short_duration"

    normalized = dict(item)
    normalized["start_ms"] = start
    normalized["end_ms"] = end
    normalized["text"] = text
    if source_index is not None and "__source_index" not in normalized:
        normalized["__source_index"] = source_index
    if action:
        return normalized, {"action": action, "start_ms": start, "end_ms": end, "text": text}
    return normalized, None


def repair_index_aligned_items(original_items: list[dict], candidate_items: list[dict]) -> tuple[list[dict], list[dict]]:
    repaired: list[dict] = []
    fixes: list[dict] = []
    total = max(len(original_items), len(candidate_items))
    for index in range(total):
        original = original_items[index] if index < len(original_items) else {}
        candidate = candidate_items[index] if index < len(candidate_items) else original
        fallback = clean_subtitle_text(original.get("text", ""))
        normalized, fix = normalize_item(candidate, fallback_text=fallback, source_index=index + 1)
        if normalized is None and fallback:
            normalized, fix = normalize_item(original, fallback_text=fallback, source_index=index + 1)
            fix = fix or {"action": "restore_missing_item"}
        if normalized is not None:
            repaired.append(normalized)
        if fix:
            fix["index"] = index + 1
            fixes.append(fix)
    return repaired, fixes


def repair_timeline_coverage(original_items: list[dict], export_items: list[dict]) -> tuple[list[dict], dict]:
    normalized_items: list[dict] = []
    fixes: list[dict] = []
    for index, item in enumerate(export_items, start=1):
        normalized, fix = normalize_item(item)
        if normalized is not None:
            normalized_items.append(normalized)
        if fix:
            fix["export_index"] = index
            fixes.append(fix)

    restored = []
    for index, original in enumerate(original_items, start=1):
        original_text = clean_subtitle_text(original.get("text", ""))
        if not original_text:
            continue
        covered = any(
            clean_subtitle_text(item.get("text", ""))
            and (
                item.get("__source_index") == index
                or ("__source_index" not in item and overlap_ms(original, item) >= 200)
            )
            for item in normalized_items
        )
        if covered:
            continue
        fallback = {
            "start_ms": item_start(original),
            "end_ms": item_end(original),
            "text": original_text,
        }
        normalized, fix = normalize_item(fallback, fallback_text=original_text, source_index=index)
        if normalized is not None:
            normalized_items.append(normalized)
            restored.append({"original_index": index, "start_ms": normalized["start_ms"], "end_ms": normalized["end_ms"], "text": original_text})
        if fix:
            fix["original_index"] = index
            fixes.append(fix)

    normalized_items.sort(key=lambda item: (item_start(item), item_end(item)))
    report = {
        "input_original_items": len(original_items),
        "input_export_items": len(export_items),
        "output_export_items": len(normalized_items),
        "restored_missing_segments": restored,
        "fixes": fixes,
        "status": "fixed" if restored or fixes else "ok",
    }
    return normalized_items, report
