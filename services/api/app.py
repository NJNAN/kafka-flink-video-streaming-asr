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
from fastapi import FastAPI, Query
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

app = FastAPI(title="StreamSense API")
app.mount("/static", StaticFiles(directory="static"), name="static")

recent_transcripts: deque[dict[str, Any]] = deque(maxlen=500)
recent_keywords: deque[dict[str, Any]] = deque(maxlen=500)
status = {
    "transcript_count": 0,
    "keyword_event_count": 0,
    "last_message_time_ms": 0,
    "consumer_running": False,
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


class HotwordDiscoverRequest(BaseModel):
    text: str
    stream_id: str = "demo-video"
    run_id: str = ""
    top_k: int = 50
    min_count: int = 1


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


def write_dynamic_hotword_state(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


async def save_to_file(transcript: dict[str, Any], keyword_event: dict[str, Any]) -> None:
    await asyncio.to_thread(append_jsonl, RESULT_DIR / "transcripts.jsonl", transcript)
    await asyncio.to_thread(append_jsonl, RESULT_DIR / "keyword_events.jsonl", keyword_event)


async def save_to_redis(transcript: dict[str, Any], keyword_event: dict[str, Any]) -> None:
    """把结果存到 Redis，Dashboard 查询会更稳定。"""
    if redis_client is None:
        return

    session_id = session_id_from_payload(transcript)
    transcript_key = f"stream:{session_id}:transcripts"
    keyword_key = f"stream:{session_id}:keyword_events"

    await redis_client.lpush(transcript_key, json.dumps(transcript, ensure_ascii=False))
    await redis_client.ltrim(transcript_key, 0, 199)
    await redis_client.zadd(
        keyword_key,
        {json.dumps(keyword_event, ensure_ascii=False): keyword_event.get("created_at_ms", now_ms())},
    )
    await redis_client.zremrangebyrank(keyword_key, 0, -501)


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
    details = [dict(item) for item in details if int(item.get("count", 0)) >= min_count]
    details.sort(key=lambda item: (-int(item.get("count", 0)), item.get("word", "")))
    return details[:max_words]


def build_dynamic_hotword_state() -> dict[str, Any]:
    sessions: dict[str, list[dict[str, Any]]] = {}
    for session_id in sorted(dynamic_hotword_meta.keys()):
        sessions[session_id] = active_hotwords_for_session(session_id)
    return {"updated_at_ms": now_ms(), "sessions": sessions}


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
                "first_seen_ms": int(item.get("first_seen_ms", now_ms())),
                "last_seen_ms": int(item.get("last_seen_ms", now_ms())),
                "source": str(item.get("source", "auto_discovery")),
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
    candidate_limit = int_env("HOTWORD_DISCOVERY_TOP_K", 30)
    candidates = discover_hotword_candidates(text, top_k=candidate_limit, min_count=1)

    if not candidates:
        return

    for candidate in candidates:
        word = candidate["word"]
        counter[word] += int(candidate.get("count", 1))
        existing = meta.get(word, {})
        meta[word] = {
            "word": word,
            "count": int(counter[word]),
            "first_seen_ms": int(existing.get("first_seen_ms", now_ms())),
            "last_seen_ms": now_ms(),
            "source": "auto_discovery",
        }
        jieba.add_word(word)

    after_items = active_hotwords_for_session(session_id)
    added_terms = [item for item in after_items if item["word"] not in before_active]
    if added_terms:
        await publish_hotword_update(stream_id, run_id, session_id, added_terms)
        await persist_dynamic_hotwords()


async def handle_ready_transcript(transcript: dict[str, Any]) -> None:
    keyword_event = build_keyword_event(transcript)
    recent_transcripts.appendleft(transcript)
    recent_keywords.appendleft(keyword_event)

    status["transcript_count"] += 1
    status["keyword_event_count"] += 1
    status["last_message_time_ms"] = now_ms()

    await save_to_redis(transcript, keyword_event)
    await save_to_file(transcript, keyword_event)
    await publish_keyword_event(keyword_event)
    await maybe_learn_hotwords(transcript)


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
                if transcript.get("status") != "ok":
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


@app.get("/api/transcripts")
async def transcripts(stream_id: str | None = None, limit: int = Query(default=50, ge=1, le=200)) -> list[dict[str, Any]]:
    data = list(recent_transcripts)
    if stream_id:
        data = [item for item in data if item.get("stream_id") == stream_id]
    return data[:limit]


@app.get("/api/keywords")
async def keywords(stream_id: str | None = None, limit: int = Query(default=50, ge=1, le=200)) -> list[dict[str, Any]]:
    data = list(recent_keywords)
    if stream_id:
        data = [item for item in data if item.get("stream_id") == stream_id]
    return data[:limit]


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
