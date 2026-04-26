import argparse
import json
import re
from pathlib import Path
from typing import Any


PUNCT_TRANSLATION = str.maketrans(
    {
        "﹐": "，",
        "﹑": "、",
        "﹒": "。",
        "﹔": "；",
        "﹕": "：",
    }
)


DEFAULT_DROP_PATTERNS = [
    "请不吝点赞",
    "点赞订阅",
    "订阅转发",
    "打赏支持",
    "感谢观看",
    "MING PAO",
    "Amara.org",
    "字幕组",
    "Subtitles by",
    "Caption by",
]


def load_corrections(path: Path) -> list[tuple[str, str]]:
    if not path.exists():
        return []

    corrections = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=>" not in line:
            continue
        wrong, right = line.split("=>", 1)
        wrong = wrong.strip()
        right = right.strip()
        if wrong and right:
            corrections.append((wrong, right))
    return corrections


def clean_text(text: str, corrections: list[tuple[str, str]]) -> str:
    text = text.translate(PUNCT_TRANSLATION)
    for wrong, right in corrections:
        text = text.replace(wrong, right)
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"(?<=[\u4e00-\u9fff])\s+(?=[\u4e00-\u9fff])", "", text)
    text = re.sub(r"(?<=[\u4e00-\u9fff]),\s*(?=[\u4e00-\u9fff])", "，", text)
    text = re.sub(r"([，,、。！？!?；;])\s+", r"\1", text)
    text = re.sub(r"([。！？!?；;])\1+", r"\1", text)
    text = re.sub(r"([，,、])\1+", r"\1", text)
    return text


def should_drop(text: str, drop_patterns: list[str]) -> bool:
    compact = re.sub(r"\s+", "", text)
    compact_lower = compact.lower()
    text_lower = text.lower()
    for pattern in drop_patterns:
        if not pattern:
            continue
        pattern_lower = pattern.lower()
        compact_pattern = re.sub(r"\s+", "", pattern_lower)
        if pattern_lower in text_lower or compact_pattern in compact_lower:
            return True
    return False


def load_transcripts(path: Path, corrections: list[tuple[str, str]], drop_patterns: list[str]) -> list[dict[str, Any]]:
    seen_ids = set()
    items = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        item = json.loads(line)
        segment_id = item.get("segment_id", "")
        if segment_id in seen_ids:
            continue
        seen_ids.add(segment_id)

        text = clean_text(str(item.get("text", "")), corrections)
        if not text or should_drop(text, drop_patterns):
            continue

        start_ms = int(item.get("start_time_ms", 0))
        end_ms = int(item.get("end_time_ms", start_ms + 2500))
        if end_ms <= start_ms:
            end_ms = start_ms + 2500

        items.append({"start_ms": start_ms, "end_ms": end_ms, "text": text})

    items.sort(key=lambda value: (value["start_ms"], value["end_ms"]))
    return normalize_timing(items)


def normalize_timing(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized = []
    previous_end = -1
    for item in items:
        start_ms = max(int(item["start_ms"]), previous_end + 1)
        end_ms = int(item["end_ms"])
        if end_ms <= start_ms:
            end_ms = start_ms + 2500
        previous_end = end_ms
        normalized.append({"start_ms": start_ms, "end_ms": end_ms, "text": item["text"]})
    return normalized


def format_srt_time(ms: int) -> str:
    hours = ms // 3_600_000
    ms %= 3_600_000
    minutes = ms // 60_000
    ms %= 60_000
    seconds = ms // 1000
    millis = ms % 1000
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{millis:03d}"


def format_vtt_time(ms: int) -> str:
    return format_srt_time(ms).replace(",", ".")


def wrap_text(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text

    pieces = re.split(r"([，,。！？!?；;、])", text)
    units = []
    for index in range(0, len(pieces), 2):
        unit = pieces[index].strip()
        if index + 1 < len(pieces):
            unit += pieces[index + 1]
        if unit:
            units.append(unit)

    lines = []
    current = ""
    for unit in units or [text]:
        unit = unit.strip()
        if current and len(current) + len(unit) > max_chars:
            lines.append(current.strip())
            current = unit
        else:
            current += unit
    if current:
        lines.append(current.strip())

    return "\n".join(lines)


def write_srt(items: list[dict[str, Any]], path: Path, max_chars: int) -> None:
    blocks = []
    for index, item in enumerate(items, start=1):
        blocks.append(
            "\n".join(
                [
                    str(index),
                    f"{format_srt_time(item['start_ms'])} --> {format_srt_time(item['end_ms'])}",
                    wrap_text(item["text"], max_chars),
                ]
            )
        )
    path.write_text("\n\n".join(blocks) + "\n", encoding="utf-8-sig")


def write_vtt(items: list[dict[str, Any]], path: Path, max_chars: int) -> None:
    blocks = ["WEBVTT\n"]
    for item in items:
        blocks.append(
            "\n".join(
                [
                    f"{format_vtt_time(item['start_ms'])} --> {format_vtt_time(item['end_ms'])}",
                    wrap_text(item["text"], max_chars),
                ]
            )
        )
    path.write_text("\n\n".join(blocks) + "\n", encoding="utf-8")


def write_text(items: list[dict[str, Any]], path: Path) -> None:
    path.write_text("\n".join(item["text"] for item in items) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Export StreamSense JSONL transcripts to SRT/VTT subtitles.")
    parser.add_argument("--input", default="data/results/transcripts.jsonl")
    parser.add_argument("--output-dir", default="data/results")
    parser.add_argument("--corrections", default="config/asr_corrections.txt")
    parser.add_argument("--basename", default="input")
    parser.add_argument("--max-chars", type=int, default=24)
    parser.add_argument("--keep-boilerplate", action="store_true")
    args = parser.parse_args()

    input_path = Path(args.input)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    corrections = load_corrections(Path(args.corrections))
    drop_patterns = [] if args.keep_boilerplate else DEFAULT_DROP_PATTERNS
    items = load_transcripts(input_path, corrections, drop_patterns)

    if not items:
        raise SystemExit(f"No usable subtitle items found in {input_path}")

    srt_path = output_dir / f"{args.basename}.srt"
    vtt_path = output_dir / f"{args.basename}.vtt"
    text_path = output_dir / f"{args.basename}_subtitle.txt"

    write_srt(items, srt_path, args.max_chars)
    write_vtt(items, vtt_path, args.max_chars)
    write_text(items, text_path)

    print(f"exported {len(items)} subtitle items")
    print(f"srt: {srt_path}")
    print(f"vtt: {vtt_path}")
    print(f"text: {text_path}")


if __name__ == "__main__":
    main()
