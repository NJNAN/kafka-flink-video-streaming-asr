from __future__ import annotations

import re


PUNCT_RE = re.compile(r"([，,。！？!?；;、])")


def text_weight(text: str) -> int:
    compact = re.sub(r"\s+", "", text)
    return max(len(compact), 1)


def split_text_for_subtitle(text: str, max_chars: int = 24) -> list[str]:
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= max_chars:
        return [text] if text else []

    pieces = PUNCT_RE.split(text)
    units: list[str] = []
    for index in range(0, len(pieces), 2):
        unit = pieces[index].strip()
        if index + 1 < len(pieces):
            unit += pieces[index + 1]
        if unit:
            units.append(unit)
    if not units:
        units = [text]

    lines: list[str] = []
    current = ""
    for unit in units:
        candidate = current + unit if current else unit
        if current and len(candidate) > max_chars:
            lines.append(current.strip())
            current = unit
        else:
            current = candidate
        if len(current) >= max_chars and re.search(r"[。！？!?；;]$", current):
            lines.append(current.strip())
            current = ""
    if current.strip():
        lines.append(current.strip())

    final: list[str] = []
    for line in lines:
        if len(line) <= max_chars + 8:
            final.append(line)
            continue
        cursor = 0
        while cursor < len(line):
            final.append(line[cursor : cursor + max_chars])
            cursor += max_chars
    return [item for item in final if item.strip()]


def improve_subtitle_readability(items: list[dict], max_chars: int = 24, max_duration_ms: int = 5200) -> tuple[list[dict], list[dict]]:
    improved: list[dict] = []
    changes: list[dict] = []
    for index, item in enumerate(items, start=1):
        text = str(item.get("text", "")).strip()
        start_ms = int(item.get("start_ms", item.get("start_time_ms", 0)))
        end_ms = int(item.get("end_ms", item.get("end_time_ms", start_ms + 2500)))
        duration = max(end_ms - start_ms, 700)
        parts = split_text_for_subtitle(text, max_chars=max_chars)
        needs_split = len(parts) > 1 or duration > max_duration_ms
        if not needs_split:
            improved.append(dict(item))
            continue

        total_weight = sum(text_weight(part) for part in parts)
        cursor = start_ms
        new_items: list[dict] = []
        for part_index, part in enumerate(parts):
            if part_index == len(parts) - 1:
                part_end = end_ms
            else:
                ratio = text_weight(part) / max(total_weight, 1)
                part_end = cursor + max(800, int(duration * ratio))
                part_end = min(part_end, end_ms - (len(parts) - part_index - 1) * 500)
            next_item = dict(item)
            next_item["start_ms"] = cursor
            next_item["end_ms"] = max(part_end, cursor + 500)
            next_item["text"] = part
            new_items.append(next_item)
            cursor = next_item["end_ms"] + 1
        improved.extend(new_items)
        changes.append(
            {
                "index": index,
                "original_text": text,
                "parts": parts,
                "reason": "split_for_readability",
            }
        )
    return improved, changes
