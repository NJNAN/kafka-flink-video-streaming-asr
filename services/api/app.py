import asyncio
import json
import os
import re
import time
import uuid
from collections import Counter, deque
from pathlib import Path
from typing import Any

import jieba
import jieba.analyse
import jieba.posseg as pseg
import redis.asyncio as redis
from aiokafka import AIOKafkaConsumer, AIOKafkaProducer
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel


KAFKA_BOOTSTRAP_SERVERS = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "kafka:9092")
TRANSCRIPT_TOPIC = os.getenv("TRANSCRIPT_TOPIC", "transcription-result")
KEYWORD_TOPIC = os.getenv("KEYWORD_TOPIC", "keyword-event")
HOTWORD_UPDATE_TOPIC = os.getenv("HOTWORD_UPDATE_TOPIC", "streamsense.hotword.updates")
REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")
CUSTOM_KEYWORD_FILE = os.getenv("CUSTOM_KEYWORD_FILE", "/config/custom_keywords.txt")
ASR_CORRECTION_FILE = os.getenv("ASR_CORRECTION_FILE", "/config/asr_corrections.txt")
RESULT_DIR = Path(os.getenv("RESULT_DIR", "/data/results"))
HOTWORD_STATE_FILE = RESULT_DIR / "dynamic_hotwords.json"
TOPIC_SHIFT_THRESHOLD = float(os.getenv("TOPIC_SHIFT_THRESHOLD", "0.35"))
SENTENCE_END_RE = re.compile(r"^(.+?[。！？!?；;]+[\"'”’）)\]】]*)")
PUNCT_TRANSLATION = str.maketrans(
    {
        "﹐": "，",
        "﹑": "、",
        "﹒": "。",
        "﹔": "；",
        "﹕": "：",
    }
)

HOTWORD_STOPWORDS = {
    "我们",
    "你们",
    "他们",
    "这个",
    "那个",
    "一种",
    "一个",
    "一些",
    "这些",
    "那些",
    "就是",
    "然后",
    "因为",
    "所以",
    "但是",
    "如果",
    "以及",
    "已经",
    "还是",
    "可以",
    "不会",
    "没有",
    "不是",
    "其实",
    "时候",
    "今天",
    "大家",
    "聪明",
    "小伙伴",
    "自己",
    "东西",
    "一下",
    "一下子",
    "这样",
    "那么",
    "还有",
    "这里",
    "那里",
    "的话",
    "真的",
    "非常",
    "然后呢",
    "视频",
    "字幕",
    "语音",
    "转写",
    "普通话",
    "中文",
    "内容",
    "总结",
    "重复",
    "Amara",
    "MING",
    "PAO",
    "Exclusive",
    "Series",
    "Television",
    "YoYo",
    "优优",
    "独播",
    "剧场",
    "几乎",
    "可能",
    "想到",
    "org",
    "com",
    "www",
    "tv",
}

CORS_ORIGINS = [origin.strip() for origin in os.getenv("STREAMSENSE_CORS_ORIGINS", "*").split(",") if origin.strip()]

app = FastAPI(title="StreamSense API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.mount("/static", StaticFiles(directory="static"), name="static")

recent_transcripts: deque[dict[str, Any]] = deque(maxlen=500)
recent_keywords: deque[dict[str, Any]] = deque(maxlen=500)
status = {
    "transcript_count": 0,
    "keyword_event_count": 0,
    "failed_segment_count": 0,
    "last_message_time_ms": 0,
    "consumer_running": False,
    "recent_errors": [],
}

redis_client: redis.Redis | None = None
kafka_producer: AIOKafkaProducer | None = None
custom_keywords: list[str] = []
asr_corrections: list[tuple[str, str]] = []
last_keyword_sets: dict[str, set[str]] = {}
sentence_buffers: dict[str, dict[str, Any]] = {}
sentence_counters: dict[str, int] = {}
dynamic_hotword_counts: dict[str, Counter[str]] = {}
dynamic_hotword_meta: dict[str, dict[str, dict[str, Any]]] = {}
dynamic_hotword_windows: dict[str, deque[dict[str, Any]]] = {}
confirmed_hotwords: dict[str, set[str]] = {}
ignored_hotwords: dict[str, set[str]] = {}
hotword_corrections: dict[str, dict[str, str]] = {}


class HotwordDiscoverRequest(BaseModel):
    text: str
    stream_id: str = "demo-video"
    run_id: str = ""
    top_k: int = 50
    min_count: int = 1


class HotwordActionRequest(BaseModel):
    word: str
    stream_id: str = "demo-video"
    run_id: str = ""
    action: str
    correction: str = ""


def now_ms() -> int:
    return int(time.time() * 1000)


def build_session_id(stream_id: str, run_id: str = "") -> str:
    stream_id = stream_id.strip() or "unknown"
    run_id = run_id.strip()
    return f"{stream_id}:{run_id}" if run_id else stream_id


def session_id_from_payload(data: dict[str, Any]) -> str:
    return build_session_id(
        str(data.get("stream_id", "unknown")),
        str(data.get("run_id", "")),
    )


def session_id_to_segment_prefix(session_id: str) -> str:
    return session_id.replace(":", "-")


def bool_env(name: str, default: str) -> bool:
    return os.getenv(name, default).strip().lower() in {"1", "true", "yes", "on"}


def int_env(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)).strip())
    except ValueError:
        return default


def load_custom_keywords() -> list[str]:
    """加载自定义关键词词表，空行和 # 开头的注释行会被忽略。"""
    path = Path(CUSTOM_KEYWORD_FILE)
    if not path.exists():
        return []

    words = []
    for line in path.read_text(encoding="utf-8").splitlines():
        word = line.strip()
        if word and not word.startswith("#"):
            words.append(word)
            jieba.add_word(word)
    return words


def load_asr_corrections() -> list[tuple[str, str]]:
    """加载领域错词纠正表，格式为：错误词=>正确词。"""
    path = Path(ASR_CORRECTION_FILE)
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
            jieba.add_word(right)
    return corrections


def apply_asr_corrections(text: str) -> str:
    for wrong, right in asr_corrections:
        text = text.replace(wrong, right)
    return text


def fallback_keywords(text: str, top_k: int) -> list[dict[str, Any]]:
    """当 jieba 抽取不到结果时，使用简单词频兜底。"""
    tokens = re.findall(r"[A-Za-z0-9_]+|[\u4e00-\u9fff]{2,}", text)
    counts: dict[str, int] = {}
    for token in tokens:
        if len(token.strip()) < 2:
            continue
        counts[token] = counts.get(token, 0) + 1

    sorted_items = sorted(counts.items(), key=lambda item: item[1], reverse=True)
    return [{"word": word, "score": float(count)} for word, count in sorted_items[:top_k]]


def extract_keywords(text: str, top_k: int = 5) -> list[dict[str, Any]]:
    """关键词提取：自定义词优先，然后使用 TextRank，最后用词频兜底。"""
    if not text.strip():
        return []

    results: list[dict[str, Any]] = []
    seen: set[str] = set()

    for word in custom_keywords:
        if word in text and word not in seen:
            results.append({"word": word, "score": 1.0, "source": "custom"})
            seen.add(word)

    try:
        for word, weight in jieba.analyse.textrank(text, topK=top_k * 2, withWeight=True):
            if word not in seen:
                results.append({"word": word, "score": float(weight), "source": "textrank"})
                seen.add(word)
            if len(results) >= top_k:
                break
    except Exception:
        pass

    if not results:
        results = fallback_keywords(text, top_k)

    return results[:top_k]


def clean_transcript_text(text: str) -> str:
    """整理 ASR 文本，去掉中文之间多余空格和连续重复标点。"""
    text = text.translate(PUNCT_TRANSLATION)
    text = apply_asr_corrections(text)
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"(?<=[\u4e00-\u9fff])\s+(?=[\u4e00-\u9fff])", "", text)
    text = re.sub(r"([。！？!?；;])\1+", r"\1", text)
    text = re.sub(r"([，,、])\1+", r"\1", text)
    return text


def is_incomplete_fragment(text: str) -> bool:
    endings = os.getenv(
        "SENTENCE_INCOMPLETE_ENDINGS",
        "因为|所以|但是|然而|并且|以及|如果|虽然|或者|并不是|换句话说|比如|例如|首先|其次",
    ).split("|")
    compact = text.rstrip("，,、；;:： ")
    return any(ending and compact.endswith(ending) for ending in endings)


def smart_join(left: str, right: str) -> str:
    """中文片段直接拼接，中英混合片段保留必要空格。"""
    if not left:
        return right
    if not right:
        return left
    if re.search(r"[\u4e00-\u9fff]$", left) and re.search(r"^[\u4e00-\u9fff]", right):
        return f"{left}{right}"
    return f"{left} {right}"


def next_sentence_id(session_id: str) -> str:
    sentence_counters[session_id] = sentence_counters.get(session_id, 0) + 1
    prefix = session_id_to_segment_prefix(session_id)
    return f"{prefix}-sentence-{sentence_counters[session_id]:06d}"


def make_sentence_transcript(session_id: str, sentence: str, buffer: dict[str, Any]) -> dict[str, Any]:
    """把若干 ASR 小切片合并成一句自然字幕。"""
    template = dict(buffer.get("template", {}))
    audio_created_at_ms = int(buffer.get("audio_created_at_ms", now_ms()))
    template.update(
        {
            "segment_id": next_sentence_id(session_id),
            "session_id": session_id,
            "raw_segment_ids": list(buffer.get("raw_segment_ids", [])),
            "text": sentence,
            "start_time_ms": int(buffer.get("start_time_ms", 0)),
            "end_time_ms": int(buffer.get("end_time_ms", 0)),
            "audio_created_at_ms": audio_created_at_ms,
            "end_to_end_time_ms": now_ms() - audio_created_at_ms,
            "sentence_level": True,
            "asr_inference_time_ms": int(buffer.get("asr_inference_time_ms", 0)),
        }
    )
    return template


def finalize_buffer_text(text: str, add_period: bool) -> str:
    text = clean_transcript_text(text)
    if not text:
        return ""

    incomplete = is_incomplete_fragment(text)
    if incomplete and bool_env("SENTENCE_DROP_INCOMPLETE_ON_FLUSH", "false"):
        return ""

    if incomplete and bool_env("SENTENCE_MARK_INCOMPLETE_ON_FLUSH", "true"):
        if not re.search(r"[。！？!?；;…]$", text):
            return f"{text}……"

    if add_period and not re.search(r"[。！？!?；;…]$", text):
        return f"{text}。"
    return text


def flush_sentence_buffer(session_id: str, add_period: bool = True) -> dict[str, Any] | None:
    """把当前未输出的半句刷成一句，通常用于长静音或视频结束前后的残留文本。"""
    buffer = sentence_buffers.pop(session_id, None)
    if not buffer:
        return None

    text = finalize_buffer_text(str(buffer.get("text", "")), add_period=add_period)
    if not text:
        return None
    return make_sentence_transcript(session_id, text, buffer)


def split_to_sentence_transcripts(transcript: dict[str, Any]) -> list[dict[str, Any]]:
    """把 Flink 输出的 ASR 小片段转换为更自然的句子级字幕。"""
    if not bool_env("SENTENCE_BUFFER_ENABLED", "true"):
        transcript["text"] = clean_transcript_text(str(transcript.get("text", "")))
        return [transcript] if transcript["text"] else []

    text = clean_transcript_text(str(transcript.get("text", "")))
    if not text:
        return []

    session_id = session_id_from_payload(transcript)
    outputs: list[dict[str, Any]] = []
    gap_ms = int_env("SENTENCE_FLUSH_GAP_MS", 1500)
    max_chars = int_env("SENTENCE_MAX_CHARS", 90)
    start_time_ms = int(transcript.get("start_time_ms", 0))
    end_time_ms = int(transcript.get("end_time_ms", start_time_ms))

    existing = sentence_buffers.get(session_id)
    if existing and start_time_ms - int(existing.get("end_time_ms", start_time_ms)) > gap_ms:
        flushed = flush_sentence_buffer(
            session_id,
            add_period=bool_env("SENTENCE_ADD_PERIOD_ON_FLUSH", "true"),
        )
        if flushed:
            outputs.append(flushed)

    buffer = sentence_buffers.setdefault(
        session_id,
        {
            "text": "",
            "start_time_ms": start_time_ms,
            "end_time_ms": end_time_ms,
            "audio_created_at_ms": int(transcript.get("audio_created_at_ms", now_ms())),
            "raw_segment_ids": [],
            "template": transcript,
            "asr_inference_time_ms": 0,
            "last_update_wall_ms": now_ms(),
        },
    )

    buffer["text"] = smart_join(str(buffer.get("text", "")), text)
    buffer["end_time_ms"] = end_time_ms
    buffer["template"] = transcript
    buffer["last_update_wall_ms"] = now_ms()
    buffer["asr_inference_time_ms"] = int(buffer.get("asr_inference_time_ms", 0)) + int(
        transcript.get("inference_time_ms", 0)
    )
    segment_id = transcript.get("segment_id")
    if segment_id:
        buffer["raw_segment_ids"].append(segment_id)

    while True:
        current_text = clean_transcript_text(str(buffer.get("text", "")))
        match = SENTENCE_END_RE.match(current_text)
        if not match:
            break

        sentence = match.group(1).strip()
        if sentence:
            outputs.append(make_sentence_transcript(session_id, sentence, buffer))

        remaining = current_text[len(match.group(1)) :].strip()
        if not remaining:
            sentence_buffers.pop(session_id, None)
            break

        buffer["text"] = remaining
        buffer["start_time_ms"] = start_time_ms
        buffer["audio_created_at_ms"] = int(transcript.get("audio_created_at_ms", now_ms()))
        buffer["raw_segment_ids"] = [segment_id] if segment_id else []
        buffer["asr_inference_time_ms"] = int(transcript.get("inference_time_ms", 0))

    buffer = sentence_buffers.get(session_id)
    if buffer and len(str(buffer.get("text", ""))) >= max_chars:
        flushed = flush_sentence_buffer(
            session_id,
            add_period=bool_env("SENTENCE_ADD_PERIOD_ON_FLUSH", "true"),
        )
        if flushed:
            outputs.append(flushed)

    return outputs


def build_keyword_event(transcript: dict[str, Any]) -> dict[str, Any]:
    text = transcript.get("text", "")
    keywords = extract_keywords(text, top_k=5)
    stream_id = transcript.get("stream_id", "")
    run_id = str(transcript.get("run_id", ""))
    session_id = session_id_from_payload(transcript)
    current_words = {item["word"] for item in keywords if item.get("word")}
    previous_words = last_keyword_sets.get(session_id, set())

    event_type = "custom_hit" if any(item.get("source") == "custom" for item in keywords) else "keyword"
    if previous_words and current_words:
        union = previous_words | current_words
        overlap_ratio = len(previous_words & current_words) / len(union)
        if overlap_ratio < TOPIC_SHIFT_THRESHOLD:
            event_type = "topic_shift"

    if current_words:
        last_keyword_sets[session_id] = current_words

    return {
        "event_id": uuid.uuid4().hex,
        "stream_id": stream_id,
        "run_id": run_id,
        "session_id": session_id,
        "segment_id": transcript.get("segment_id", ""),
        "event_type": event_type,
        "keywords": keywords,
        "source_text": text,
        "start_time_ms": transcript.get("start_time_ms", 0),
        "end_time_ms": transcript.get("end_time_ms", 0),
        "created_at_ms": now_ms(),
        "end_to_end_time_ms": transcript.get("end_to_end_time_ms", 0),
    }


def append_jsonl(path: Path, data: dict[str, Any]) -> None:
    """追加写 JSONL 文件，方便论文中做历史回放和实验统计。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as file:
        file.write(json.dumps(data, ensure_ascii=False) + "\n")


def result_dir_root() -> Path:
    return RESULT_DIR.resolve()


def safe_result_path(path_value: str) -> Path:
    """只允许读取 RESULT_DIR 内部文件，避免任意路径读取。"""
    if not path_value:
        raise HTTPException(status_code=400, detail="path is required")

    raw = Path(path_value)
    if raw.is_absolute():
        candidate = raw.resolve()
    else:
        parts = list(raw.parts)
        if len(parts) >= 2 and parts[0] == "data" and parts[1] == "results":
            parts = parts[2:]
        candidate = (RESULT_DIR / Path(*parts)).resolve()

    root = result_dir_root()
    if candidate != root and root not in candidate.parents:
        raise HTTPException(status_code=403, detail="path must stay inside RESULT_DIR")
    if not candidate.exists():
        raise HTTPException(status_code=404, detail="result file not found")
    return candidate


def relative_result_path(path_value: Path) -> str:
    try:
        return str(path_value.resolve().relative_to(result_dir_root())).replace("\\", "/")
    except ValueError:
        return path_value.name


def read_json_file(path_value: Path) -> dict[str, Any] | list[Any] | None:
    try:
        return json.loads(path_value.read_text(encoding="utf-8"))
    except Exception:
        return None


def human_size(size: int) -> str:
    value = float(size)
    units = ["B", "KB", "MB", "GB"]
    unit = 0
    while value >= 1024 and unit < len(units) - 1:
        value /= 1024
        unit += 1
    return f"{value:.1f} {units[unit]}" if unit else f"{int(value)} B"


def tail_jsonl(path_value: Path, limit: int) -> list[dict[str, Any]]:
    if not path_value.exists():
        return []
    try:
        lines = path_value.read_text(encoding="utf-8").splitlines()[-limit:]
    except Exception:
        return []
    items = []
    for line in lines:
        try:
            items.append(json.loads(line))
        except Exception:
            continue
    return items


def percentile(values: list[float], percent: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = int(round((len(ordered) - 1) * percent))
    return float(ordered[max(0, min(index, len(ordered) - 1))])


def numeric_ms(item: dict[str, Any], *keys: str) -> int:
    for key in keys:
        value = item.get(key)
        if isinstance(value, (int, float)):
            return int(value)
        if isinstance(value, str) and value.strip().isdigit():
            return int(value)
    return 0


def sorted_segments(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        items,
        key=lambda item: (
            str(item.get("stream_id", "")),
            numeric_ms(item, "start_time_ms"),
            str(item.get("segment_id", "")),
        ),
    )


def load_transcript_history(limit: int = 5000, stream_id: str | None = None) -> list[dict[str, Any]]:
    file_items = tail_jsonl(RESULT_DIR / "transcripts.jsonl", limit)
    memory_items = list(recent_transcripts)
    seen: set[str] = set()
    merged: list[dict[str, Any]] = []
    for item in file_items + memory_items:
        if stream_id and item.get("stream_id") != stream_id:
            continue
        key = str(item.get("segment_id", "")) or json.dumps(item, ensure_ascii=False, sort_keys=True)
        if key in seen:
            continue
        seen.add(key)
        merged.append(item)
    return sorted_segments(merged)[-limit:]


def stream_ids_from_history() -> list[str]:
    ids = {str(item.get("stream_id", "unknown")) for item in load_transcript_history() if item.get("stream_id")}
    ids.update(str(key).split(":", 1)[0] for key in dynamic_hotword_meta.keys() if key)
    return sorted(ids)


def stream_hotwords(stream_id: str) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    for session_id in sorted(dynamic_hotword_meta.keys()):
        if session_id != stream_id and not session_id.startswith(f"{stream_id}:"):
            continue
        for item in active_hotwords_for_session(session_id):
            word = str(item.get("word", ""))
            if word and word not in seen:
                seen.add(word)
                items.append(item)
    items.sort(key=lambda item: (-float(item.get("score", item.get("count", 0))), item.get("word", "")))
    return items


def build_metrics_payload(stream_id: str | None = None) -> dict[str, Any]:
    items = load_transcript_history(stream_id=stream_id)
    end_to_end = [float(numeric_ms(item, "end_to_end_time_ms")) for item in items if numeric_ms(item, "end_to_end_time_ms")]
    asr_times = [
        float(numeric_ms(item, "asr_inference_time_ms", "inference_time_ms", "asr_total_time_ms"))
        for item in items
        if numeric_ms(item, "asr_inference_time_ms", "inference_time_ms", "asr_total_time_ms")
    ]
    kafka_flink = [
        float(numeric_ms(item, "kafka_flink_dispatch_time_ms"))
        for item in items
        if numeric_ms(item, "kafka_flink_dispatch_time_ms")
    ]
    api_times = [
        float(numeric_ms(item, "api_aggregation_time_ms"))
        for item in items
        if numeric_ms(item, "api_aggregation_time_ms")
    ]
    redis_times = [
        float(numeric_ms(item, "redis_write_time_ms"))
        for item in items
        if numeric_ms(item, "redis_write_time_ms")
    ]
    created = [numeric_ms(item, "created_at", "audio_created_at_ms") for item in items]
    written = [numeric_ms(item, "result_written_at") for item in items]
    wall_ms = max(written) - min(created) if created and written else 0
    throughput = round(len(items) / (wall_ms / 1000), 3) if wall_ms > 0 else 0.0
    pending = sum(1 for buffer in sentence_buffers.values() if (not stream_id) or str(buffer.get("template", {}).get("stream_id", "")) == stream_id)
    all_hotwords = []
    for sid in (stream_ids_from_history() if stream_id is None else [stream_id]):
        all_hotwords.extend(stream_hotwords(sid))
    all_hotwords.sort(key=lambda item: (-float(item.get("score", item.get("count", 0))), item.get("word", "")))
    return {
        "status": "ok",
        "stream_id": stream_id or "",
        "active_stream_count": len(stream_ids_from_history()),
        "total_segments": len(items),
        "success_segments": len(items),
        "failed_segments": int(status.get("failed_segment_count", 0)),
        "average_end_to_end_latency_ms": round(sum(end_to_end) / len(end_to_end), 2) if end_to_end else 0,
        "p50_latency_ms": round(percentile(end_to_end, 0.50), 2),
        "p95_latency_ms": round(percentile(end_to_end, 0.95), 2),
        "p99_latency_ms": round(percentile(end_to_end, 0.99), 2),
        "asr_average_time_ms": round(sum(asr_times) / len(asr_times), 2) if asr_times else 0,
        "kafka_flink_average_dispatch_ms": round(sum(kafka_flink) / len(kafka_flink), 2) if kafka_flink else 0,
        "api_average_aggregation_ms": round(sum(api_times) / len(api_times), 2) if api_times else 0,
        "redis_average_write_ms": round(sum(redis_times) / len(redis_times), 2) if redis_times else 0,
        "pending_segments": pending,
        "throughput_segments_per_second": throughput,
        "recent_errors": list(status.get("recent_errors", []))[-10:],
        "hotwords_top10": all_hotwords[:10],
    }


def format_srt_time(ms: int) -> str:
    hours = ms // 3_600_000
    ms %= 3_600_000
    minutes = ms // 60_000
    ms %= 60_000
    seconds = ms // 1000
    millis = ms % 1000
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{millis:03d}"


def write_stream_export(stream_id: str, fmt: str, items: list[dict[str, Any]]) -> Path:
    export_dir = RESULT_DIR / "stream-exports" / stream_id
    export_dir.mkdir(parents=True, exist_ok=True)
    fmt = fmt.lower()
    if fmt not in {"json", "srt", "vtt", "txt"}:
        raise HTTPException(status_code=400, detail="format must be json, srt, vtt, or txt")
    path_value = export_dir / f"{stream_id}.{fmt}"
    if fmt == "json":
        path_value.write_text(json.dumps({"stream_id": stream_id, "segments": items}, ensure_ascii=False, indent=2), encoding="utf-8")
        return path_value
    if fmt == "txt":
        path_value.write_text("\n".join(str(item.get("text", "")) for item in items) + "\n", encoding="utf-8")
        return path_value
    blocks = []
    if fmt == "vtt":
        blocks.append("WEBVTT\n")
    for index, item in enumerate(items, start=1):
        start_ms = numeric_ms(item, "start_time_ms")
        end_ms = numeric_ms(item, "end_time_ms") or start_ms + 2500
        start = format_srt_time(start_ms)
        end = format_srt_time(end_ms)
        if fmt == "vtt":
            start = start.replace(",", ".")
            end = end.replace(",", ".")
            blocks.append(f"{start} --> {end}\n{item.get('text', '')}")
        else:
            blocks.append(f"{index}\n{start} --> {end}\n{item.get('text', '')}")
    path_value.write_text("\n\n".join(blocks) + "\n", encoding="utf-8-sig" if fmt == "srt" else "utf-8")
    return path_value


def write_dynamic_hotword_state(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


async def save_to_file(transcript: dict[str, Any], keyword_event: dict[str, Any]) -> None:
    await asyncio.to_thread(append_jsonl, RESULT_DIR / "transcripts.jsonl", transcript)
    await asyncio.to_thread(append_jsonl, RESULT_DIR / "keyword_events.jsonl", keyword_event)


async def save_to_redis(transcript: dict[str, Any], keyword_event: dict[str, Any]) -> int:
    """把结果存到 Redis，Dashboard 查询会更稳定。"""
    if redis_client is None:
        return 0

    started_at = now_ms()
    session_id = session_id_from_payload(transcript)
    transcript_key = f"stream:{session_id}:transcripts"
    stream_transcript_key = f"stream_id:{transcript.get('stream_id', 'unknown')}:transcripts"
    keyword_key = f"stream:{session_id}:keyword_events"

    await redis_client.lpush(transcript_key, json.dumps(transcript, ensure_ascii=False))
    await redis_client.ltrim(transcript_key, 0, 199)
    await redis_client.lpush(stream_transcript_key, json.dumps(transcript, ensure_ascii=False))
    await redis_client.ltrim(stream_transcript_key, 0, 499)
    await redis_client.zadd(
        keyword_key,
        {json.dumps(keyword_event, ensure_ascii=False): keyword_event.get("created_at_ms", now_ms())},
    )
    await redis_client.zremrangebyrank(keyword_key, 0, -501)
    return now_ms() - started_at


async def publish_keyword_event(keyword_event: dict[str, Any]) -> None:
    """关键词事件也写回 Kafka，方便后续扩展下游系统。"""
    if kafka_producer is None:
        return

    key = str(keyword_event.get("session_id", keyword_event.get("stream_id", "unknown"))).encode("utf-8")
    value = json.dumps(keyword_event, ensure_ascii=False).encode("utf-8")
    await kafka_producer.send_and_wait(KEYWORD_TOPIC, value=value, key=key)


def average_segment_logprob(transcript: dict[str, Any]) -> float | None:
    values = []
    for item in transcript.get("segments", []):
        avg_logprob = item.get("avg_logprob")
        text = str(item.get("text", "")).strip()
        if avg_logprob is not None and text:
            values.append(float(avg_logprob))
    if not values:
        return None
    return sum(values) / len(values)


def is_valid_hotword_candidate(word: str) -> bool:
    word = word.strip()
    if not word:
        return False
    if word.lower() in {item.lower() for item in HOTWORD_STOPWORDS}:
        return False
    if len(word) < 2 or len(word) > 16:
        return False
    if re.fullmatch(r"\d+", word):
        return False
    if re.search(r"[，,。！？!?；;：:\"“”'（）()\[\]【】/\\|]", word):
        return False
    if not re.search(r"[A-Za-z\u4e00-\u9fff]", word):
        return False
    return True


def discover_hotword_candidates(text: str, top_k: int = 30, min_count: int = 1) -> list[dict[str, Any]]:
    cleaned = clean_transcript_text(text)
    counts: Counter[str] = Counter()
    boosted_words: set[str] = set()
    if bool_env("HOTWORD_USE_STATIC_HINTS", "false"):
        boosted_words = set(custom_keywords) | {right for _, right in asr_corrections}
    allowed_pos_prefixes = ("n", "nz", "vn", "eng")

    for token in pseg.cut(cleaned):
        word = token.word.strip()
        flag = token.flag or ""
        if not is_valid_hotword_candidate(word):
            continue
        if word in boosted_words or flag.startswith(allowed_pos_prefixes):
            counts[word] += 1

    for token in re.findall(r"[A-Za-z][A-Za-z0-9_-]{1,20}", cleaned):
        if is_valid_hotword_candidate(token):
            counts[token] += 1

    for word in boosted_words:
        if word and word in cleaned and is_valid_hotword_candidate(word):
            counts[word] += 2

    items = []
    for word, count in counts.items():
        if count < min_count:
            continue
        items.append({"word": word, "count": int(count), "score": float(count)})

    items.sort(key=lambda item: (-item["count"], -len(item["word"]), item["word"]))
    return items[:top_k]


def active_hotwords_for_session(session_id: str) -> list[dict[str, Any]]:
    min_count = int_env("HOTWORD_AUTO_ADD_MIN_COUNT", 5)
    max_words = int_env("HOTWORD_MAX_WORDS", 120)
    details = list(dynamic_hotword_meta.get(session_id, {}).values())
    ignored = ignored_hotwords.get(session_id, set())
    confirmed = confirmed_hotwords.get(session_id, set())
    filtered = []
    for item in details:
        word = str(item.get("word", ""))
        if word in ignored:
            continue
        copy_item = dict(item)
        if word in confirmed:
            copy_item["confirmed"] = True
        if int(copy_item.get("count", 0)) >= min_count or copy_item.get("confirmed"):
            filtered.append(copy_item)
    details = filtered
    details.sort(key=lambda item: (-float(item.get("score", item.get("count", 0))), item.get("word", "")))
    return details[:max_words]


def build_dynamic_hotword_state() -> dict[str, Any]:
    sessions: dict[str, list[dict[str, Any]]] = {}
    for session_id in sorted(dynamic_hotword_meta.keys()):
        sessions[session_id] = active_hotwords_for_session(session_id)
    return {
        "updated_at_ms": now_ms(),
        "sessions": sessions,
        "confirmed": {key: sorted(value) for key, value in confirmed_hotwords.items()},
        "blocklist": {key: sorted(value) for key, value in ignored_hotwords.items()},
        "corrections": hotword_corrections,
    }


async def persist_dynamic_hotwords() -> None:
    payload = build_dynamic_hotword_state()
    await asyncio.to_thread(write_dynamic_hotword_state, HOTWORD_STATE_FILE, payload)


def load_dynamic_hotwords() -> None:
    if not HOTWORD_STATE_FILE.exists():
        return

    try:
        payload = json.loads(HOTWORD_STATE_FILE.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"[api] 读取动态热词状态失败: {exc}", flush=True)
        return

    sessions = payload.get("sessions", {}) or payload.get("streams", {})
    for session_id, words in (payload.get("confirmed", {}) or {}).items():
        confirmed_hotwords[session_id] = {str(word) for word in words if str(word).strip()}
    for session_id, words in (payload.get("blocklist", {}) or {}).items():
        ignored_hotwords[session_id] = {str(word) for word in words if str(word).strip()}
    for session_id, mapping in (payload.get("corrections", {}) or {}).items():
        if isinstance(mapping, dict):
            hotword_corrections[session_id] = {str(k): str(v) for k, v in mapping.items()}
    for session_id, items in sessions.items():
        counter = Counter()
        meta: dict[str, dict[str, Any]] = {}
        for item in items:
            word = str(item.get("word", "")).strip()
            count = int(item.get("count", 0))
            if not word or count <= 0:
                continue
            counter[word] = count
            meta[word] = {
                "word": word,
                "count": count,
                "score": float(item.get("score", count)),
                "first_seen_ms": int(item.get("first_seen_ms", now_ms())),
                "last_seen_ms": int(item.get("last_seen_ms", now_ms())),
                "source": str(item.get("source", "auto_discovery")),
                "confirmed": bool(item.get("confirmed", word in confirmed_hotwords.get(session_id, set()))),
            }
            jieba.add_word(word)
        if counter:
            dynamic_hotword_counts[session_id] = counter
            dynamic_hotword_meta[session_id] = meta


async def publish_hotword_update(stream_id: str, run_id: str, session_id: str, terms: list[dict[str, Any]]) -> None:
    if kafka_producer is None or not terms:
        return

    payload = {
        "stream_id": stream_id,
        "run_id": run_id,
        "session_id": session_id,
        "terms": terms,
        "created_at_ms": now_ms(),
    }
    await kafka_producer.send_and_wait(
        HOTWORD_UPDATE_TOPIC,
        value=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        key=session_id.encode("utf-8"),
    )


async def rebroadcast_hotwords() -> None:
    for session_id in sorted(dynamic_hotword_meta.keys()):
        items = active_hotwords_for_session(session_id)
        if items:
            stream_id, _, run_id = session_id.partition(":")
            await publish_hotword_update(stream_id, run_id, session_id, items)


async def maybe_learn_hotwords(transcript: dict[str, Any]) -> None:
    if not bool_env("HOTWORD_AUTO_DISCOVERY_ENABLED", "true"):
        return

    stream_id = str(transcript.get("stream_id", "unknown"))
    run_id = str(transcript.get("run_id", ""))
    session_id = session_id_from_payload(transcript)
    text = clean_transcript_text(str(transcript.get("text", "")))
    if not text:
        return

    avg_logprob = average_segment_logprob(transcript)
    threshold = float(os.getenv("HOTWORD_MIN_TRANSCRIPT_LOGPROB", "-0.55").strip())
    if avg_logprob is not None and avg_logprob < threshold:
        return

    before_active = {item["word"] for item in active_hotwords_for_session(session_id)}
    counter = dynamic_hotword_counts.setdefault(session_id, Counter())
    meta = dynamic_hotword_meta.setdefault(session_id, {})
    window = dynamic_hotword_windows.setdefault(session_id, deque(maxlen=int_env("HOTWORD_RECENT_WINDOW_SEGMENTS", 120)))
    candidate_limit = int_env("HOTWORD_DISCOVERY_TOP_K", 30)
    candidates = discover_hotword_candidates(text, top_k=candidate_limit, min_count=1)

    if not candidates:
        return

    current_ms = now_ms()
    window.append({"created_at_ms": current_ms, "text": text, "avg_logprob": avg_logprob})
    recent_text = "\n".join(
        str(item.get("text", ""))
        for item in window
        if current_ms - int(item.get("created_at_ms", current_ms)) <= int_env("HOTWORD_RECENT_WINDOW_MS", 300000)
    )
    recent_counts = Counter()
    for item in discover_hotword_candidates(recent_text, top_k=candidate_limit * 2, min_count=1):
        recent_counts[str(item["word"])] = int(item.get("count", 1))

    for candidate in candidates:
        word = candidate["word"]
        if word in ignored_hotwords.get(session_id, set()):
            continue
        counter[word] += int(candidate.get("count", 1))
        existing = meta.get(word, {})
        recency_bonus = 1.0
        confidence_bonus = 1.0
        if avg_logprob is not None:
            confidence_bonus = max(0.2, min(1.5, 1.0 + float(avg_logprob)))
        confirmed_bonus = 2.0 if word in confirmed_hotwords.get(session_id, set()) else 1.0
        score = (
            float(counter[word])
            + float(recent_counts.get(word, 0)) * 0.7
            + recency_bonus
        ) * confidence_bonus * confirmed_bonus
        meta[word] = {
            "word": word,
            "count": int(counter[word]),
            "recent_count": int(recent_counts.get(word, 0)),
            "score": round(score, 4),
            "first_seen_ms": int(existing.get("first_seen_ms", now_ms())),
            "last_seen_ms": current_ms,
            "avg_logprob": avg_logprob,
            "source": "auto_discovery",
            "confirmed": word in confirmed_hotwords.get(session_id, set()),
        }
        jieba.add_word(word)

    after_items = active_hotwords_for_session(session_id)
    added_terms = [item for item in after_items if item["word"] not in before_active]
    if added_terms:
        await publish_hotword_update(stream_id, run_id, session_id, added_terms)
        await persist_dynamic_hotwords()


async def handle_ready_transcript(transcript: dict[str, Any]) -> None:
    api_received_at = int(transcript.get("api_received_at", now_ms()))
    transcript["api_received_at"] = api_received_at
    keyword_event = build_keyword_event(transcript)
    recent_transcripts.appendleft(transcript)
    recent_keywords.appendleft(keyword_event)

    status["transcript_count"] += 1
    status["keyword_event_count"] += 1
    status["last_message_time_ms"] = now_ms()

    redis_write_time_ms = await save_to_redis(transcript, keyword_event)
    transcript["redis_write_time_ms"] = redis_write_time_ms
    keyword_event["redis_write_time_ms"] = redis_write_time_ms
    transcript["api_aggregation_time_ms"] = now_ms() - api_received_at
    transcript["result_written_at"] = now_ms()
    created_at = numeric_ms(transcript, "created_at", "audio_created_at_ms")
    if created_at:
        transcript["end_to_end_time_ms"] = transcript["result_written_at"] - created_at
    await save_to_file(transcript, keyword_event)
    await publish_keyword_event(keyword_event)
    await maybe_learn_hotwords(transcript)


async def handle_failed_transcript(transcript: dict[str, Any]) -> None:
    status["failed_segment_count"] = int(status.get("failed_segment_count", 0)) + 1
    error_item = {
        "segment_id": transcript.get("segment_id", ""),
        "stream_id": transcript.get("stream_id", ""),
        "error": str(transcript.get("error", ""))[:500],
        "created_at_ms": now_ms(),
    }
    recent_errors = list(status.get("recent_errors", []))
    recent_errors.append(error_item)
    status["recent_errors"] = recent_errors[-20:]
    await asyncio.to_thread(append_jsonl, RESULT_DIR / "failed_segments.jsonl", {**transcript, **error_item})


async def flush_stale_sentence_buffers() -> None:
    """长时间没有新音频时，把最后一句残留字幕输出，避免视频末尾丢句。"""
    stale_ms = int_env("SENTENCE_STALE_FLUSH_MS", 3000)
    while True:
        await asyncio.sleep(1)
        if not bool_env("SENTENCE_BUFFER_ENABLED", "true"):
            continue

        current_ms = now_ms()
        ready_streams = [
            stream_id
            for stream_id, buffer in list(sentence_buffers.items())
            if current_ms - int(buffer.get("last_update_wall_ms", current_ms)) >= stale_ms
        ]
        for stream_id in ready_streams:
            transcript = flush_sentence_buffer(
                stream_id,
                add_period=bool_env("SENTENCE_ADD_PERIOD_ON_FLUSH", "true"),
            )
            if transcript:
                await handle_ready_transcript(transcript)


async def consume_transcripts() -> None:
    """后台任务：持续消费 Flink 输出的字幕结果。"""
    global kafka_producer
    status["consumer_running"] = False

    while True:
        consumer = None
        try:
            consumer = AIOKafkaConsumer(
                TRANSCRIPT_TOPIC,
                bootstrap_servers=KAFKA_BOOTSTRAP_SERVERS,
                group_id="dashboard-keyword-service",
                auto_offset_reset="latest",
                enable_auto_commit=True,
            )
            kafka_producer = AIOKafkaProducer(bootstrap_servers=KAFKA_BOOTSTRAP_SERVERS)

            await consumer.start()
            await kafka_producer.start()
            await rebroadcast_hotwords()
            status["consumer_running"] = True
            print("[api] Kafka 字幕消费者已启动", flush=True)

            async for message in consumer:
                transcript = json.loads(message.value.decode("utf-8"))
                transcript["api_received_at"] = now_ms()
                if transcript.get("status") != "ok":
                    await handle_failed_transcript(transcript)
                    continue
                if not transcript.get("text", "").strip():
                    continue

                for sentence_transcript in split_to_sentence_transcripts(transcript):
                    await handle_ready_transcript(sentence_transcript)

        except Exception as exc:
            status["consumer_running"] = False
            print(f"[api] Kafka 消费异常，3 秒后重试: {exc}", flush=True)
            await asyncio.sleep(3)
        finally:
            if consumer is not None:
                await consumer.stop()
            if kafka_producer is not None:
                await kafka_producer.stop()


@app.on_event("startup")
async def startup() -> None:
    global redis_client, custom_keywords, asr_corrections

    custom_keywords = load_custom_keywords()
    asr_corrections = load_asr_corrections()
    load_dynamic_hotwords()
    redis_client = redis.from_url(REDIS_URL, decode_responses=True)
    asyncio.create_task(consume_transcripts())
    asyncio.create_task(flush_stale_sentence_buffers())


@app.get("/")
async def index() -> FileResponse:
    return FileResponse("static/index.html")


@app.get("/health")
async def health() -> dict[str, Any]:
    return {"status": "ok", **status}


@app.get("/api/status")
async def api_status() -> dict[str, Any]:
    return status


@app.get("/api/results")
async def results() -> dict[str, Any]:
    RESULT_DIR.mkdir(parents=True, exist_ok=True)
    allowed_suffixes = {".srt", ".vtt", ".txt", ".json", ".jsonl", ".md"}
    files: list[dict[str, Any]] = []
    reports: list[tuple[float, Path, Any]] = []

    for path_value in RESULT_DIR.rglob("*"):
        if not path_value.is_file() or path_value.suffix.lower() not in allowed_suffixes:
            continue
        try:
            item_stat = path_value.stat()
        except OSError:
            continue
        rel_path = relative_result_path(path_value)
        files.append(
            {
                "name": path_value.name,
                "path": rel_path,
                "size": human_size(item_stat.st_size),
                "size_bytes": item_stat.st_size,
                "modified_at_ms": int(item_stat.st_mtime * 1000),
            }
        )
        if path_value.name.endswith("_report.json") or path_value.name == "report.json":
            report = read_json_file(path_value)
            if report is not None:
                reports.append((item_stat.st_mtime, path_value, report))

    latest_report = None
    latest_report_path = ""
    if reports:
        _, report_path, latest_report = sorted(reports, key=lambda item: item[0], reverse=True)[0]
        latest_report_path = relative_result_path(report_path)

    tasks_path = RESULT_DIR / "tasks.json"
    tasks = read_json_file(tasks_path)
    if not isinstance(tasks, list):
        tasks = []

    files.sort(key=lambda item: int(item["modified_at_ms"]), reverse=True)
    return {
        "status": "ok",
        "result_dir": str(RESULT_DIR),
        "files": files[:500],
        "latest_report": latest_report,
        "latest_report_path": latest_report_path,
        "tasks": tasks,
    }


@app.get("/api/results/report")
async def result_report(path: str) -> dict[str, Any] | list[Any]:
    path_value = safe_result_path(path)
    if path_value.suffix.lower() != ".json":
        raise HTTPException(status_code=400, detail="report path must be a json file")
    data = read_json_file(path_value)
    if data is None:
        raise HTTPException(status_code=400, detail="report json parse failed")
    return data


@app.get("/api/results/file")
async def result_file(path: str) -> FileResponse:
    path_value = safe_result_path(path)
    if not path_value.is_file():
        raise HTTPException(status_code=400, detail="path is not a file")
    return FileResponse(path_value)


@app.get("/api/logs")
async def logs(limit: int = Query(default=300, ge=1, le=1000)) -> list[dict[str, Any]]:
    transcript_tail = tail_jsonl(RESULT_DIR / "transcripts.jsonl", limit)
    keyword_tail = tail_jsonl(RESULT_DIR / "keyword_events.jsonl", limit)
    rows: list[dict[str, Any]] = []

    for item in transcript_tail[-limit:]:
        rows.append(
            {
                "id": str(item.get("segment_id", uuid.uuid4().hex)),
                "time": time.strftime("%H:%M:%S", time.localtime(int(item.get("audio_created_at_ms", now_ms())) / 1000)),
                "level": "OK",
                "source": "transcript",
                "message": str(item.get("text", ""))[:220],
            }
        )

    for item in keyword_tail[-limit:]:
        keywords = item.get("keywords", [])
        words = [str(keyword.get("word", "")) for keyword in keywords if isinstance(keyword, dict)]
        rows.append(
            {
                "id": str(item.get("event_id", uuid.uuid4().hex)),
                "time": time.strftime("%H:%M:%S", time.localtime(int(item.get("created_at_ms", now_ms())) / 1000)),
                "level": "INFO",
                "source": "keyword",
                "message": "关键词：" + " / ".join([word for word in words if word]),
            }
        )

    rows.sort(key=lambda item: item["time"], reverse=True)
    return rows[:limit]


@app.get("/api/transcripts")
async def transcripts(stream_id: str | None = None, limit: int = Query(default=50, ge=1, le=200)) -> list[dict[str, Any]]:
    data = list(recent_transcripts)
    if stream_id:
        data = [item for item in data if item.get("stream_id") == stream_id]
    return sorted_segments(data)[:limit]


@app.get("/api/keywords")
async def keywords(stream_id: str | None = None, limit: int = Query(default=50, ge=1, le=200)) -> list[dict[str, Any]]:
    data = list(recent_keywords)
    if stream_id:
        data = [item for item in data if item.get("stream_id") == stream_id]
    return data[:limit]


@app.get("/api/metrics")
async def metrics(stream_id: str | None = None) -> dict[str, Any]:
    return build_metrics_payload(stream_id=stream_id)


@app.get("/api/streams")
async def streams() -> dict[str, Any]:
    stream_items = []
    for stream_id in stream_ids_from_history():
        stream_items.append(
            {
                "stream_id": stream_id,
                "metrics": build_metrics_payload(stream_id=stream_id),
                "hotwords": stream_hotwords(stream_id)[:10],
            }
        )
    return {"status": "ok", "streams": stream_items}


@app.get("/api/streams/{stream_id}")
async def stream_detail(stream_id: str) -> dict[str, Any]:
    segments = load_transcript_history(stream_id=stream_id, limit=1000)
    return {
        "status": "ok",
        "stream_id": stream_id,
        "metrics": build_metrics_payload(stream_id=stream_id),
        "latest_segment": segments[-1] if segments else None,
        "segment_count": len(segments),
    }


@app.get("/api/streams/{stream_id}/segments")
async def stream_segments(stream_id: str, limit: int = Query(default=200, ge=1, le=2000)) -> list[dict[str, Any]]:
    return load_transcript_history(stream_id=stream_id, limit=limit)


@app.get("/api/streams/{stream_id}/hotwords")
async def stream_hotword_endpoint(stream_id: str) -> dict[str, Any]:
    return {"status": "ok", "stream_id": stream_id, "hotwords": stream_hotwords(stream_id)}


@app.get("/api/streams/{stream_id}/export")
async def stream_export(stream_id: str, format: str = Query(default="json")) -> FileResponse:
    segments = load_transcript_history(stream_id=stream_id, limit=5000)
    if not segments:
        raise HTTPException(status_code=404, detail="stream has no segments")
    path_value = write_stream_export(stream_id, format, segments)
    return FileResponse(path_value)


@app.delete("/api/streams/{stream_id}/segments")
async def clear_stream_segments(stream_id: str) -> dict[str, Any]:
    """清理某一路实时字幕的内存、Redis 和 JSONL 历史，供直播演示重新开始。"""
    global recent_transcripts, recent_keywords

    before_transcripts = len(recent_transcripts)
    before_keywords = len(recent_keywords)
    recent_transcripts = deque(
        [item for item in recent_transcripts if item.get("stream_id") != stream_id],
        maxlen=recent_transcripts.maxlen,
    )
    recent_keywords = deque(
        [item for item in recent_keywords if item.get("stream_id") != stream_id],
        maxlen=recent_keywords.maxlen,
    )

    deleted_redis_keys = 0
    if redis_client is not None:
        keys = await redis_client.keys(f"stream_id:{stream_id}:*")
        for key in keys:
            deleted_redis_keys += int(await redis_client.delete(key))

    def filter_jsonl(path_value: Path) -> int:
        if not path_value.exists():
            return 0
        kept = []
        removed = 0
        for line in path_value.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                kept.append(line)
                continue
            if item.get("stream_id") == stream_id:
                removed += 1
            else:
                kept.append(line)
        path_value.write_text("\n".join(kept) + ("\n" if kept else ""), encoding="utf-8")
        return removed

    removed_transcript_file = await asyncio.to_thread(filter_jsonl, RESULT_DIR / "transcripts.jsonl")
    removed_keyword_file = await asyncio.to_thread(filter_jsonl, RESULT_DIR / "keyword_events.jsonl")
    return {
        "status": "ok",
        "stream_id": stream_id,
        "removed_memory_transcripts": before_transcripts - len(recent_transcripts),
        "removed_memory_keywords": before_keywords - len(recent_keywords),
        "deleted_redis_keys": deleted_redis_keys,
        "removed_transcript_file_rows": removed_transcript_file,
        "removed_keyword_file_rows": removed_keyword_file,
    }


@app.get("/api/hotwords")
async def hotwords(stream_id: str | None = None, run_id: str | None = None, session_id: str | None = None) -> dict[str, Any]:
    if session_id:
        return {
            "status": "ok",
            "session_id": session_id,
            "hotwords": active_hotwords_for_session(session_id),
        }

    if stream_id and run_id is not None:
        session_id = build_session_id(stream_id, run_id)
        return {
            "status": "ok",
            "stream_id": stream_id,
            "run_id": run_id,
            "session_id": session_id,
            "hotwords": active_hotwords_for_session(session_id),
        }

    if stream_id:
        matching = {
            key: active_hotwords_for_session(key)
            for key in sorted(dynamic_hotword_meta.keys())
            if key == stream_id or key.startswith(f"{stream_id}:")
        }
        return {"status": "ok", "stream_id": stream_id, "sessions": matching}

    return {
        "status": "ok",
        "sessions": {key: active_hotwords_for_session(key) for key in sorted(dynamic_hotword_meta.keys())},
    }


@app.post("/api/discover-hotwords")
async def discover_hotwords(request: HotwordDiscoverRequest) -> dict[str, Any]:
    items = discover_hotword_candidates(
        request.text,
        top_k=max(1, min(int(request.top_k), 100)),
        min_count=max(1, int(request.min_count)),
    )
    session_id = build_session_id(request.stream_id, request.run_id)
    dynamic_items = active_hotwords_for_session(session_id)
    existing_words = {item["word"] for item in items}
    for item in dynamic_items:
        if item["word"] not in existing_words and len(items) < request.top_k:
            items.append({"word": item["word"], "count": int(item.get("count", 1)), "score": float(item.get("count", 1))})

    items.sort(key=lambda item: (-int(item.get("count", 0)), item["word"]))
    return {
        "status": "ok",
        "stream_id": request.stream_id,
        "run_id": request.run_id,
        "session_id": session_id,
        "hotwords": items[: request.top_k],
    }


@app.post("/api/hotwords/action")
async def hotword_action(request: HotwordActionRequest) -> dict[str, Any]:
    word = request.word.strip()
    if not word:
        raise HTTPException(status_code=400, detail="word is required")
    session_id = build_session_id(request.stream_id, request.run_id)
    action = request.action.strip().lower()
    meta = dynamic_hotword_meta.setdefault(session_id, {})
    counter = dynamic_hotword_counts.setdefault(session_id, Counter())

    if action == "confirm":
        confirmed_hotwords.setdefault(session_id, set()).add(word)
        ignored_hotwords.setdefault(session_id, set()).discard(word)
        counter[word] = max(counter[word], int_env("HOTWORD_AUTO_ADD_MIN_COUNT", 5))
        existing = meta.get(word, {})
        meta[word] = {
            "word": word,
            "count": int(counter[word]),
            "recent_count": int(existing.get("recent_count", 0)),
            "score": float(existing.get("score", counter[word])) + 5.0,
            "first_seen_ms": int(existing.get("first_seen_ms", now_ms())),
            "last_seen_ms": now_ms(),
            "source": "user_confirmed",
            "confirmed": True,
        }
        jieba.add_word(word)
    elif action == "ignore":
        ignored_hotwords.setdefault(session_id, set()).add(word)
        confirmed_hotwords.setdefault(session_id, set()).discard(word)
    elif action == "correct":
        correction = request.correction.strip()
        if not correction:
            raise HTTPException(status_code=400, detail="correction is required for correct action")
        ignored_hotwords.setdefault(session_id, set()).add(word)
        confirmed_hotwords.setdefault(session_id, set()).add(correction)
        hotword_corrections.setdefault(session_id, {})[word] = correction
        counter[correction] = max(counter[correction], int_env("HOTWORD_AUTO_ADD_MIN_COUNT", 5))
        meta[correction] = {
            "word": correction,
            "count": int(counter[correction]),
            "recent_count": 0,
            "score": float(counter[correction]) + 5.0,
            "first_seen_ms": now_ms(),
            "last_seen_ms": now_ms(),
            "source": "user_corrected",
            "confirmed": True,
            "corrected_from": word,
        }
        jieba.add_word(correction)
    else:
        raise HTTPException(status_code=400, detail="action must be confirm, ignore, or correct")

    await persist_dynamic_hotwords()
    await publish_hotword_update(request.stream_id, request.run_id, session_id, active_hotwords_for_session(session_id))
    return {
        "status": "ok",
        "stream_id": request.stream_id,
        "run_id": request.run_id,
        "session_id": session_id,
        "hotwords": active_hotwords_for_session(session_id),
        "blocklist": sorted(ignored_hotwords.get(session_id, set())),
        "corrections": hotword_corrections.get(session_id, {}),
    }
