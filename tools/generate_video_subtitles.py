import argparse
import json
import re
import time
import uuid
from pathlib import Path
from urllib import error, request

from export_subtitles import (
    DEFAULT_DROP_PATTERNS,
    clean_text,
    load_corrections,
    normalize_timing,
    should_drop,
    write_srt,
    write_text,
    write_vtt,
)


def http_json(url: str, payload: dict | None = None, timeout: int = 3600) -> dict:
    """发送 JSON 请求。ASR 跑完整视频可能较久，所以默认超时时间给足。"""
    headers = {"Content-Type": "application/json"}
    data = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = request.Request(url, data=data, headers=headers)
    try:
        with request.urlopen(req, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="ignore")
        raise RuntimeError(f"HTTP {exc.code} {url}: {body}") from exc
    except error.URLError as exc:
        raise RuntimeError(f"请求失败 {url}: {exc}") from exc


def save_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def project_root() -> Path:
    """脚本默认从项目根目录运行。"""
    return Path.cwd().resolve()


def resolve_media_path(raw_path: str) -> tuple[str, Path | None, str]:
    """把本机视频路径转换成 ASR 容器可访问的路径。

    docker-compose 会把项目根目录挂载到 ASR 容器的 /workspace。
    例如根目录下的 input2.mp4 会映射成 /workspace/input2.mp4。
    """
    raw = raw_path.strip()
    local_path = Path(raw)

    if local_path.exists():
        absolute = local_path.resolve()
        try:
            relative = absolute.relative_to(project_root())
        except ValueError:
            raise SystemExit(f"视频必须放在项目目录内: {absolute}")
        container_path = "/workspace/" + relative.as_posix()
        return container_path, absolute, absolute.stem

    if raw.startswith("/"):
        return raw, None, Path(raw).stem

    fallback = project_root() / raw
    if fallback.exists():
        return resolve_media_path(str(fallback))

    raise SystemExit(f"找不到视频文件: {raw_path}")


def load_auxiliary_hotwords(custom_keywords_path: Path, corrections_path: Path) -> list[str]:
    """读取显式指定的领域词。默认泛化模式不会主动使用这些词。"""
    words: list[str] = []
    seen: set[str] = set()

    if custom_keywords_path.exists():
        for line in custom_keywords_path.read_text(encoding="utf-8").splitlines():
            word = line.strip()
            if word and not word.startswith("#") and word not in seen:
                words.append(word)
                seen.add(word)

    if corrections_path.exists():
        for line in corrections_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=>" not in line:
                continue
            _, right = line.split("=>", 1)
            word = right.strip()
            if word and word not in seen:
                words.append(word)
                seen.add(word)

    return words


def profile_paths(profile: str) -> tuple[Path | None, Path | None]:
    profile = profile.strip()
    if not profile:
        return None, None
    safe_name = re.sub(r"[^A-Za-z0-9_-]+", "", profile)
    if not safe_name:
        raise SystemExit(f"profile 名称非法: {profile}")
    folder = Path("config/profiles")
    return folder / f"{safe_name}_keywords.txt", folder / f"{safe_name}_corrections.txt"


def merge_corrections(*paths: Path | None) -> list[tuple[str, str]]:
    """按顺序合并默认纠错表和 profile 纠错表，后者可以补充领域词。"""
    merged: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for path in paths:
        if path is None:
            continue
        for item in load_corrections(path):
            if item not in seen:
                merged.append(item)
                seen.add(item)
    return merged


def merge_hotwords(*paths: Path | None, corrections_paths: list[Path | None] | None = None) -> list[str]:
    """合并多个热词文件，并把纠错表右侧正确词也作为可选热词。"""
    words: list[str] = []
    seen: set[str] = set()
    for path in paths:
        if path is None or not path.exists():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            word = line.strip()
            if word and not word.startswith("#") and word not in seen:
                words.append(word)
                seen.add(word)
    for correction_path in corrections_paths or []:
        if correction_path is None or not correction_path.exists():
            continue
        for _, right in load_corrections(correction_path):
            if right and right not in seen:
                words.append(right)
                seen.add(right)
    return words


def normalize_piece_length(text: str) -> int:
    compact = re.sub(r"[，,。！？!?；;、…\s]", "", text)
    return max(len(compact), 1)


def split_text_units(text: str) -> list[str]:
    units = re.findall(r"[^，,。！？!?；;]+[，,。！？!?；;]?", text)
    return [unit.strip() for unit in units if unit.strip()]


def split_text_by_chars(text: str, max_chars: int) -> list[str]:
    chunks = []
    current = ""
    for char in text:
        current += char
        if len(current) >= max_chars:
            chunks.append(current.strip())
            current = ""
    if current.strip():
        chunks.append(current.strip())
    return chunks or [text]


def smart_join(left: str, right: str) -> str:
    """中文片段直接拼接，中英文混排时保留空格。"""
    if not left:
        return right
    if not right:
        return left
    if re.search(r"[\u4e00-\u9fff]$", left) and re.search(r"^[\u4e00-\u9fff]", right):
        return f"{left}{right}"
    return f"{left} {right}"


def parse_chunk_index(path: Path) -> int:
    match = re.search(r"_(\d+)\.wav$", path.name)
    if not match:
        raise ValueError(f"无法从文件名解析切片编号: {path.name}")
    return int(match.group(1))


def collect_chunk_files(chunk_dir: Path) -> list[Path]:
    files = sorted(chunk_dir.glob("*.wav"))
    return sorted(files, key=parse_chunk_index)


def host_chunk_to_container_path(path: Path) -> str:
    return f"/data/audio/{path.name}"


def transcribe_media(
    asr_url: str,
    media_path: str,
    stream_id: str,
    run_id: str,
    hotwords: list[str],
    clip_start_ms: int = 0,
    clip_end_ms: int = 0,
) -> dict:
    """调用 ASR 服务转写完整媒体或某个时间片段。"""
    return http_json(
        f"{asr_url.rstrip('/')}/transcribe-media",
        {
            "media_path": media_path,
            "stream_id": stream_id,
            "run_id": run_id,
            "hotwords": ",".join(hotwords),
            "aggressive_filtering": False,
            "clip_start_ms": clip_start_ms,
            "clip_end_ms": clip_end_ms,
        },
    )


def detect_speech(asr_url: str, media_path: str, noise_db: int, min_silence_ms: int) -> dict:
    """让 ASR 容器用 FFmpeg 检测有声区间。"""
    return http_json(
        f"{asr_url.rstrip('/')}/detect-speech",
        {
            "media_path": media_path,
            "noise_db": noise_db,
            "min_silence_ms": min_silence_ms,
            "min_speech_ms": 300,
            "padding_ms": 120,
        },
    )


def transcribe_chunk_batch(
    asr_url: str,
    chunk_paths: list[Path],
    stream_id: str,
    run_id: str,
    segment_seconds: int,
    hotwords: list[str],
) -> dict:
    """保留旧的切片模式，但最终字幕推荐使用 full 模式。"""
    all_segments = []
    full_text_parts = []
    chunk_results = []

    for chunk_path in chunk_paths:
        index = parse_chunk_index(chunk_path)
        chunk_start_ms = index * segment_seconds * 1000
        response = transcribe_media(
            asr_url=asr_url,
            media_path=host_chunk_to_container_path(chunk_path),
            stream_id=stream_id,
            run_id=run_id,
            hotwords=hotwords,
        )
        chunk_results.append({"chunk": chunk_path.name, "response": response})
        if response.get("text"):
            full_text_parts.append(str(response["text"]))

        for segment in response.get("segments", []):
            start_ms = chunk_start_ms + int(segment.get("start_time_ms", 0))
            end_ms = chunk_start_ms + int(segment.get("end_time_ms", start_ms + 2500))
            all_segments.append(
                {
                    "start_time_ms": start_ms,
                    "end_time_ms": end_ms,
                    "text": str(segment.get("text", "")),
                }
            )

    all_segments.sort(key=lambda item: (int(item["start_time_ms"]), int(item["end_time_ms"])))
    return {
        "mode": "chunks",
        "stream_id": stream_id,
        "run_id": run_id,
        "segments": all_segments,
        "text": " ".join(full_text_parts).strip(),
        "chunk_count": len(chunk_paths),
        "chunks": chunk_results,
    }


def split_long_item(item: dict, max_chars: int, max_duration_ms: int) -> list[dict]:
    """把过长字幕拆短，避免播放器里一行太长。"""
    text = item["text"]
    duration_ms = int(item["end_ms"]) - int(item["start_ms"])
    units = split_text_units(text)
    if len(text) <= max_chars * 2 and duration_ms <= max_duration_ms:
        return [item]

    chunks: list[str] = []
    if len(units) <= 1:
        chunks = split_text_by_chars(text, max_chars=max_chars)
    else:
        current = ""
        for unit in units:
            candidate = smart_join(current, unit) if current else unit
            if current and len(candidate) > max_chars * 2:
                chunks.append(current)
                current = unit
                continue
            current = candidate
            if re.search(r"[。！？!?；;]$", current) and len(current) >= max_chars:
                chunks.append(current)
                current = ""
        if current:
            chunks.append(current)

    if len(chunks) <= 1:
        return [item]

    total_weight = sum(normalize_piece_length(chunk) for chunk in chunks)
    start_ms = int(item["start_ms"])
    end_ms = int(item["end_ms"])
    cursor = start_ms
    results = []
    for index, chunk in enumerate(chunks):
        if index == len(chunks) - 1:
            chunk_end = end_ms
        else:
            proportion = normalize_piece_length(chunk) / total_weight
            chunk_end = cursor + max(700, int((end_ms - start_ms) * proportion))
        results.append({"start_ms": cursor, "end_ms": chunk_end, "text": chunk})
        cursor = chunk_end + 1
    return results


def merge_adjacent_items(items: list[dict], max_gap_ms: int, max_chars: int) -> list[dict]:
    """合并很近的短字幕，但不跨越已经自然结束的句子。"""
    merged: list[dict] = []
    for item in items:
        if not merged:
            merged.append(dict(item))
            continue

        previous = merged[-1]
        gap_ms = int(item["start_ms"]) - int(previous["end_ms"])
        candidate_text = smart_join(previous["text"], item["text"])
        if (
            gap_ms <= max_gap_ms
            and len(candidate_text) <= max_chars * 2
            and not re.search(r"[。！？!?；;]$", previous["text"])
        ):
            previous["text"] = candidate_text
            previous["end_ms"] = item["end_ms"]
        else:
            merged.append(dict(item))
    return merged


def build_subtitle_items(
    segments: list[dict],
    corrections: list[tuple[str, str]],
    drop_patterns: list[str],
    max_chars: int,
    max_duration_ms: int,
) -> list[dict]:
    """把 ASR segment 转成最终字幕 item。"""
    items = []
    for segment in segments:
        raw_text = str(segment.get("text", "")).strip()
        text = clean_text(raw_text, corrections)
        if not text or should_drop(text, drop_patterns):
            continue

        start_ms = int(segment.get("start_time_ms", 0))
        end_ms = int(segment.get("end_time_ms", start_ms + 2500))
        if end_ms <= start_ms:
            end_ms = start_ms + 2500

        items.extend(
            split_long_item(
                {"start_ms": start_ms, "end_ms": end_ms, "text": text},
                max_chars=max_chars,
                max_duration_ms=max_duration_ms,
            )
        )

    items = normalize_timing(items)
    items = merge_adjacent_items(items, max_gap_ms=250, max_chars=max_chars)
    return normalize_timing(items)


def subtract_interval(base: tuple[int, int], cutters: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """从一个有声区间里减去已有字幕覆盖的区间。"""
    remaining = [base]
    for cutter_start, cutter_end in cutters:
        next_remaining = []
        for start, end in remaining:
            if cutter_end <= start or cutter_start >= end:
                next_remaining.append((start, end))
                continue
            if cutter_start > start:
                next_remaining.append((start, cutter_start))
            if cutter_end < end:
                next_remaining.append((cutter_end, end))
        remaining = next_remaining
        if not remaining:
            break
    return remaining


def find_uncovered_speech(
    speech_intervals: list[dict],
    subtitle_items: list[dict],
    max_gap_ms: int,
    subtitle_padding_ms: int,
) -> list[dict]:
    """找出明显有声音但没有字幕覆盖的时间段。"""
    subtitle_ranges = [
        (
            max(int(item["start_ms"]) - subtitle_padding_ms, 0),
            int(item["end_ms"]) + subtitle_padding_ms,
        )
        for item in subtitle_items
    ]

    gaps: list[dict] = []
    for interval in speech_intervals:
        start = int(interval["start_ms"])
        end = int(interval["end_ms"])
        for gap_start, gap_end in subtract_interval((start, end), subtitle_ranges):
            if gap_end - gap_start >= max_gap_ms:
                gaps.append({"start_ms": gap_start, "end_ms": gap_end, "duration_ms": gap_end - gap_start})
    return gaps


def merge_items_by_time(items: list[dict]) -> list[dict]:
    """合并主转写和补漏转写结果，去掉完全重复的字幕。"""
    seen: set[tuple[int, int, str]] = set()
    merged = []
    for item in sorted(items, key=lambda value: (int(value["start_ms"]), int(value["end_ms"]))):
        key = (int(item["start_ms"]), int(item["end_ms"]), str(item["text"]))
        if key in seen:
            continue
        seen.add(key)
        merged.append(dict(item))
    return normalize_timing(merged)


def recover_uncovered_gaps(
    asr_url: str,
    media_path: str,
    stream_id: str,
    run_id: str,
    hotwords: list[str],
    gaps: list[dict],
    corrections: list[tuple[str, str]],
    drop_patterns: list[str],
    max_chars: int,
    max_duration_ms: int,
    pad_ms: int,
    limit: int,
) -> tuple[list[dict], list[dict]]:
    """只对漏掉的小时间段重新识别，不重复跑完整视频。"""
    recovered_items: list[dict] = []
    attempts: list[dict] = []

    for gap in gaps[:limit]:
        clip_start_ms = max(int(gap["start_ms"]) - pad_ms, 0)
        clip_end_ms = int(gap["end_ms"]) + pad_ms
        response = transcribe_media(
            asr_url=asr_url,
            media_path=media_path,
            stream_id=stream_id,
            run_id=run_id,
            hotwords=hotwords,
            clip_start_ms=clip_start_ms,
            clip_end_ms=clip_end_ms,
        )
        items = build_subtitle_items(
            response.get("segments", []),
            corrections=corrections,
            drop_patterns=drop_patterns,
            max_chars=max_chars,
            max_duration_ms=max_duration_ms,
        )
        recovered_items.extend(items)
        attempts.append(
            {
                "gap": gap,
                "clip_start_ms": clip_start_ms,
                "clip_end_ms": clip_end_ms,
                "text": response.get("text", ""),
                "items": len(items),
            }
        )

    return recovered_items, attempts


def overlaps(left: dict, right_start_ms: int, right_end_ms: int) -> bool:
    return int(left["start_ms"]) < right_end_ms and int(left["end_ms"]) > right_start_ms


def recovery_explains_gap(gap: dict, attempts: list[dict], drop_patterns: list[str]) -> bool:
    """判断残留缺口是否已被补漏步骤解释。

    补漏后仍然没有正文字幕，通常有三种情况：
    1. 这段其实是背景音乐、音效或片头片尾台标；
    2. ASR 只识别出水印/字幕组模板，已被过滤；
    3. ASR 在该段识别到很短文本，剩余部分不是人声。
    这些不应该算作“正文语音漏字幕”。
    """
    for attempt in attempts:
        clip_start = int(attempt.get("clip_start_ms", 0))
        clip_end = int(attempt.get("clip_end_ms", 0))
        if not overlaps(gap, clip_start, clip_end):
            continue

        text = clean_text(str(attempt.get("text", "")), [])
        if not text:
            return True
        if should_drop(text, drop_patterns):
            return True
        if int(attempt.get("items", 0)) > 0:
            return True

    return False


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate complete final subtitles from a real video with local ASR.")
    parser.add_argument("--mode", choices=["auto", "chunks", "full"], default="full")
    parser.add_argument("--media-path", default="videos/input.mp4", help="本机项目内视频路径，或容器内 /videos 路径。")
    parser.add_argument("--chunk-dir", default="data/audio", help="真实视频切出来的音频片段目录。")
    parser.add_argument("--segment-seconds", type=int, default=6)
    parser.add_argument("--stream-id", default="demo-video")
    parser.add_argument("--run-id", default="")
    parser.add_argument("--asr-url", default="http://localhost:8001")
    parser.add_argument("--api-url", default="http://localhost:8000")
    parser.add_argument("--corrections", default="config/asr_corrections.txt")
    parser.add_argument("--output-dir", default="data/results")
    parser.add_argument("--basename", default="")
    parser.add_argument("--max-chars", type=int, default=24)
    parser.add_argument("--max-duration-ms", type=int, default=6500)
    parser.add_argument("--hotword-top-k", type=int, default=40)
    parser.add_argument("--custom-keywords", default="config/custom_keywords.txt")
    parser.add_argument("--profile", default="", help="领域 Profile 名称，例如 bigdata / meeting / dino。")
    parser.add_argument("--passes", type=int, choices=[1, 2], default=1)
    parser.add_argument("--use-static-hints", action="store_true")
    parser.add_argument("--keep-boilerplate", action="store_true")
    parser.add_argument("--no-recover-gaps", action="store_true")
    parser.add_argument("--coverage-noise-db", type=int, default=-35)
    parser.add_argument("--coverage-min-silence-ms", type=int, default=350)
    parser.add_argument("--coverage-max-gap-ms", type=int, default=1200)
    parser.add_argument("--recovery-pad-ms", type=int, default=350)
    parser.add_argument("--recovery-limit", type=int, default=60)
    args = parser.parse_args()

    started_at = time.time()
    media_path, local_media_path, default_basename = resolve_media_path(args.media_path)
    basename = args.basename.strip() or default_basename
    run_id = args.run_id.strip() or uuid.uuid4().hex[:8]

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    corrections_path = Path(args.corrections)
    profile_keyword_path, profile_correction_path = profile_paths(args.profile)
    corrections = merge_corrections(corrections_path, profile_correction_path)
    drop_patterns = [] if args.keep_boilerplate else DEFAULT_DROP_PATTERNS

    auxiliary_hotwords = []
    if args.use_static_hints:
        auxiliary_hotwords = merge_hotwords(
            Path(args.custom_keywords),
            profile_keyword_path,
            corrections_paths=[corrections_path, profile_correction_path],
        )

    chunk_dir = Path(args.chunk_dir)
    chunk_files = collect_chunk_files(chunk_dir) if chunk_dir.exists() else []
    use_chunks = args.mode == "chunks" or (args.mode == "auto" and len(chunk_files) > 0)
    if use_chunks and not chunk_files:
        raise SystemExit(f"No audio chunks found in {chunk_dir}")

    if use_chunks:
        primary = transcribe_chunk_batch(
            asr_url=args.asr_url,
            chunk_paths=chunk_files,
            stream_id=args.stream_id,
            run_id=run_id,
            segment_seconds=args.segment_seconds,
            hotwords=[],
        )
    else:
        primary = transcribe_media(
            asr_url=args.asr_url,
            media_path=media_path,
            stream_id=args.stream_id,
            run_id=run_id,
            hotwords=auxiliary_hotwords if args.passes == 1 else [],
        )
    save_json(output_dir / f"{basename}_pass1.json", primary)

    hotword_response = http_json(
        f"{args.api_url.rstrip('/')}/api/discover-hotwords",
        {
            "text": primary.get("text", ""),
            "stream_id": args.stream_id,
            "run_id": run_id,
            "top_k": args.hotword_top_k,
            "min_count": 2,
        },
    )
    save_json(output_dir / f"{basename}_hotwords.json", hotword_response)
    hotwords = [item["word"] for item in hotword_response.get("hotwords", []) if item.get("word")]
    for word in auxiliary_hotwords:
        if word not in hotwords and len(hotwords) < args.hotword_top_k:
            hotwords.append(word)

    if args.passes == 2:
        if use_chunks:
            final_pass = transcribe_chunk_batch(
                asr_url=args.asr_url,
                chunk_paths=chunk_files,
                stream_id=args.stream_id,
                run_id=run_id,
                segment_seconds=args.segment_seconds,
                hotwords=hotwords,
            )
        else:
            final_pass = transcribe_media(
                asr_url=args.asr_url,
                media_path=media_path,
                stream_id=args.stream_id,
                run_id=run_id,
                hotwords=hotwords,
            )
    else:
        final_pass = primary
    save_json(output_dir / f"{basename}_pass2.json", final_pass)

    items = build_subtitle_items(
        final_pass.get("segments", []),
        corrections=corrections,
        drop_patterns=drop_patterns,
        max_chars=args.max_chars,
        max_duration_ms=args.max_duration_ms,
    )

    speech_response = {"status": "skipped", "speech_intervals": [], "duration_ms": 0}
    gaps_before: list[dict] = []
    gaps_after: list[dict] = []
    ignored_gaps_after: list[dict] = []
    blocking_gaps_after: list[dict] = []
    recovery_attempts: list[dict] = []
    if not use_chunks:
        speech_response = detect_speech(
            args.asr_url,
            media_path=media_path,
            noise_db=args.coverage_noise_db,
            min_silence_ms=args.coverage_min_silence_ms,
        )
        speech_intervals = speech_response.get("speech_intervals", [])
        gaps_before = find_uncovered_speech(
            speech_intervals,
            items,
            max_gap_ms=args.coverage_max_gap_ms,
            subtitle_padding_ms=250,
        )
        if gaps_before and not args.no_recover_gaps:
            recovered_items, recovery_attempts = recover_uncovered_gaps(
                asr_url=args.asr_url,
                media_path=media_path,
                stream_id=args.stream_id,
                run_id=run_id,
                hotwords=hotwords,
                gaps=gaps_before,
                corrections=corrections,
                drop_patterns=drop_patterns,
                max_chars=args.max_chars,
                max_duration_ms=args.max_duration_ms,
                pad_ms=args.recovery_pad_ms,
                limit=args.recovery_limit,
            )
            if recovered_items:
                items = merge_items_by_time(items + recovered_items)

        gaps_after = find_uncovered_speech(
            speech_response.get("speech_intervals", []),
            items,
            max_gap_ms=args.coverage_max_gap_ms,
            subtitle_padding_ms=250,
        )
        ignored_gaps_after = [
            gap for gap in gaps_after if recovery_explains_gap(gap, recovery_attempts, drop_patterns)
        ]
        blocking_gaps_after = [
            gap for gap in gaps_after if not recovery_explains_gap(gap, recovery_attempts, drop_patterns)
        ]

    elapsed_ms = int((time.time() - started_at) * 1000)
    duration_ms = int(speech_response.get("duration_ms", 0))
    speed_ratio = round(elapsed_ms / duration_ms, 3) if duration_ms > 0 else None

    srt_path = output_dir / f"{basename}.srt"
    vtt_path = output_dir / f"{basename}.vtt"
    text_path = output_dir / f"{basename}_subtitle.txt"
    final_json_path = output_dir / f"{basename}_final_segments.json"
    report_path = output_dir / f"{basename}_report.json"

    write_srt(items, srt_path, args.max_chars)
    write_vtt(items, vtt_path, args.max_chars)
    write_text(items, text_path)
    save_json(
        final_json_path,
        {
            "items": items,
            "hotwords": hotwords,
            "media_path": media_path,
            "local_media_path": str(local_media_path) if local_media_path else "",
            "run_id": run_id,
            "profile": args.profile,
            "profile_keyword_file": str(profile_keyword_path or ""),
            "profile_correction_file": str(profile_correction_path or ""),
        },
    )
    save_json(
        report_path,
        {
            "status": "ok" if not blocking_gaps_after else "needs_review",
            "media_path": media_path,
            "local_media_path": str(local_media_path) if local_media_path else "",
            "run_id": run_id,
            "profile": args.profile,
            "profile_keyword_file": str(profile_keyword_path or ""),
            "profile_correction_file": str(profile_correction_path or ""),
            "passes": args.passes,
            "duration_ms": duration_ms,
            "elapsed_ms": elapsed_ms,
            "speed_ratio_elapsed_over_media": speed_ratio,
            "subtitle_items": len(items),
            "speech_intervals": speech_response.get("speech_intervals", []),
            "uncovered_gaps_before_recovery": gaps_before,
            "uncovered_gaps_after_recovery": gaps_after,
            "ignored_uncovered_gaps_after_recovery": ignored_gaps_after,
            "blocking_uncovered_gaps_after_recovery": blocking_gaps_after,
            "recovery_attempts": recovery_attempts,
            "hotwords": hotwords,
        },
    )

    print(f"mode: {'chunks' if use_chunks else 'full'}")
    print(f"run_id: {run_id}")
    print(f"profile: {args.profile or 'default'}")
    print(f"passes: {args.passes}")
    print(f"pass1 segments: {len(primary.get('segments', []))}")
    print(f"final pass segments: {len(final_pass.get('segments', []))}")
    print(f"discovered hotwords: {len(hotwords)}")
    print(f"final subtitle items: {len(items)}")
    print(f"coverage gaps before recovery: {len(gaps_before)}")
    print(f"coverage gaps after recovery: {len(gaps_after)}")
    print(f"blocking coverage gaps after recovery: {len(blocking_gaps_after)}")
    print(f"elapsed ms: {elapsed_ms}")
    print(f"speed ratio elapsed/media: {speed_ratio}")
    print(f"srt: {srt_path}")
    print(f"vtt: {vtt_path}")
    print(f"text: {text_path}")
    print(f"segments_json: {final_json_path}")
    print(f"report: {report_path}")


if __name__ == "__main__":
    main()
