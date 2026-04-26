import asyncio
import audioop
import json
import math
import os
import re
import subprocess
import tempfile
import time
import wave
from collections import Counter
from pathlib import Path
from threading import Lock
from typing import Any, Optional

from aiokafka import AIOKafkaConsumer
from fastapi import FastAPI, HTTPException
from faster_whisper import WhisperModel
from opencc import OpenCC
from pydantic import BaseModel


class TranscribeRequest(BaseModel):
    """Flink 传给 ASR 服务的请求体。"""

    segment_id: str
    stream_id: str
    run_id: str = ""
    file_path: str
    start_time_ms: int
    end_time_ms: int


class MediaTranscribeRequest(BaseModel):
    """整段视频/音频转写请求，用于最终字幕文件生成。"""

    media_path: str
    stream_id: str = "offline-video"
    run_id: str = ""
    hotwords: str = ""
    aggressive_filtering: bool = False
    clip_start_ms: int = 0
    clip_end_ms: int = 0


class SpeechDetectRequest(BaseModel):
    """检测媒体中的有声区间，用于判断字幕是否漏段。"""

    media_path: str
    noise_db: int = -35
    min_silence_ms: int = 350
    min_speech_ms: int = 300
    padding_ms: int = 120


class ModelHolder:
    """延迟加载模型：服务先启动，第一次请求到来时再真正加载 Whisper。"""

    def __init__(self) -> None:
        self.model: Optional[WhisperModel] = None
        self.lock = Lock()
        self.loaded_model_name = ""
        self.device = ""
        self.compute_type = ""

    def get_model(self) -> WhisperModel:
        if self.model is not None:
            return self.model

        with self.lock:
            if self.model is not None:
                return self.model

            model_path = os.getenv("ASR_MODEL_PATH", "").strip()
            model_name = os.getenv("ASR_MODEL", "small").strip()
            cache_dir = os.getenv("ASR_MODEL_CACHE", "/models").strip()
            device = os.getenv("ASR_DEVICE", "cuda").strip()
            compute_type = os.getenv("ASR_COMPUTE_TYPE", "float16").strip()
            cpu_threads = int(os.getenv("ASR_CPU_THREADS", "4").strip())
            num_workers = int(os.getenv("ASR_NUM_WORKERS", "1").strip())

            selected_model = model_path if model_path and Path(model_path).exists() else model_name
            print(
                f"[asr] 加载本地模型: {selected_model}, device={device}, compute_type={compute_type}",
                flush=True,
            )

            self.model = WhisperModel(
                selected_model,
                device=device,
                compute_type=compute_type,
                download_root=cache_dir,
                cpu_threads=cpu_threads,
                num_workers=num_workers,
            )
            self.loaded_model_name = selected_model
            self.device = device
            self.compute_type = compute_type
            return self.model


app = FastAPI(title="Local Whisper ASR Service")
model_holder = ModelHolder()
converter = OpenCC("t2s")
stream_context: dict[str, str] = {}
dynamic_hotwords_by_stream: dict[str, list[str]] = {}
context_lock = Lock()
dynamic_hotword_lock = Lock()
inference_lock = Lock()


def bool_env(name: str, default: str) -> bool:
    return os.getenv(name, default).strip().lower() in {"1", "true", "yes", "on"}


def build_session_id(stream_id: str, run_id: str = "") -> str:
    stream_id = stream_id.strip() or "unknown"
    run_id = run_id.strip()
    return f"{stream_id}:{run_id}" if run_id else stream_id


def run_command(command: list[str]) -> subprocess.CompletedProcess:
    """执行 FFmpeg/FFprobe 命令。统一封装，错误时能看到 stderr。"""
    return subprocess.run(command, capture_output=True, text=True, check=True)


def media_duration_ms(media_path: Path) -> int:
    """用 ffprobe 获取媒体时长。"""
    result = run_command(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(media_path),
        ]
    )
    seconds = float(result.stdout.strip() or "0")
    return max(int(seconds * 1000), 0)


def detect_speech_intervals(
    media_path: Path,
    noise_db: int,
    min_silence_ms: int,
    min_speech_ms: int,
    padding_ms: int,
) -> list[dict[str, int]]:
    """用 FFmpeg silencedetect 得到有声区间。

    这里不依赖当前视频主题，只看音频能量。它的作用不是判断“内容对不对”，
    而是检查字幕时间轴有没有把明显有声的地方漏掉。
    """
    duration_ms = media_duration_ms(media_path)
    if duration_ms <= 0:
        return []

    command = [
        "ffmpeg",
        "-hide_banner",
        "-nostdin",
        "-i",
        str(media_path),
        "-af",
        f"silencedetect=noise={noise_db}dB:d={max(min_silence_ms / 1000, 0.1):.2f}",
        "-f",
        "null",
        "-",
    ]
    result = subprocess.run(command, capture_output=True, text=True)
    log_text = f"{result.stderr}\n{result.stdout}"

    silence_ranges: list[tuple[int, int]] = []
    silence_start_ms: int | None = None
    for line in log_text.splitlines():
        start_match = re.search(r"silence_start:\s*([0-9.]+)", line)
        if start_match:
            silence_start_ms = int(float(start_match.group(1)) * 1000)
            continue

        end_match = re.search(r"silence_end:\s*([0-9.]+)", line)
        if end_match and silence_start_ms is not None:
            silence_end_ms = int(float(end_match.group(1)) * 1000)
            silence_ranges.append((max(silence_start_ms, 0), min(silence_end_ms, duration_ms)))
            silence_start_ms = None

    if silence_start_ms is not None:
        silence_ranges.append((max(silence_start_ms, 0), duration_ms))

    intervals: list[dict[str, int]] = []
    cursor = 0
    for silence_start, silence_end in sorted(silence_ranges):
        if silence_start > cursor:
            start = max(cursor - padding_ms, 0)
            end = min(silence_start + padding_ms, duration_ms)
            if end - start >= min_speech_ms:
                intervals.append({"start_ms": start, "end_ms": end})
        cursor = max(cursor, silence_end)

    if cursor < duration_ms:
        start = max(cursor - padding_ms, 0)
        end = duration_ms
        if end - start >= min_speech_ms:
            intervals.append({"start_ms": start, "end_ms": end})

    if not intervals and duration_ms >= min_speech_ms:
        intervals.append({"start_ms": 0, "end_ms": duration_ms})

    return intervals


def extract_clip_to_wav(media_path: Path, start_ms: int, end_ms: int) -> Path:
    """把一个时间区间裁成临时 wav，供 Whisper 对漏段补转写。"""
    start_ms = max(start_ms, 0)
    end_ms = max(end_ms, start_ms + 1)
    handle = tempfile.NamedTemporaryFile(prefix="streamsense_clip_", suffix=".wav", delete=False)
    clip_path = Path(handle.name)
    handle.close()

    command = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-nostdin",
        "-ss",
        f"{start_ms / 1000:.3f}",
        "-t",
        f"{(end_ms - start_ms) / 1000:.3f}",
        "-i",
        str(media_path),
        "-vn",
        "-ac",
        "1",
        "-ar",
        "16000",
        "-y",
        str(clip_path),
    ]
    run_command(command)
    return clip_path


def offset_result_timing(result: dict[str, Any], offset_ms: int) -> None:
    """裁剪片段转写后，把时间轴加回原视频时间。"""
    for segment in result.get("segments", []):
        segment["start_time_ms"] = int(segment.get("start_time_ms", 0)) + offset_ms
        segment["end_time_ms"] = int(segment.get("end_time_ms", 0)) + offset_ms
        segment["start"] = float(segment.get("start_time_ms", 0)) / 1000
        segment["end"] = float(segment.get("end_time_ms", 0)) / 1000


def parse_hotword_string(raw_value: str) -> list[str]:
    parts = re.split(r"[,，\s]+", raw_value.strip())
    words: list[str] = []
    seen: set[str] = set()
    for part in parts:
        word = part.strip()
        if not word or word in seen:
            continue
        words.append(word)
        seen.add(word)
    return words


def merge_word_lists(*word_groups: list[str]) -> list[str]:
    merged: list[str] = []
    seen: set[str] = set()
    for group in word_groups:
        for word in group:
            cleaned = word.strip()
            if not cleaned or cleaned in seen:
                continue
            merged.append(cleaned)
            seen.add(cleaned)
    return merged


def build_hotwords(session_id: str, extra_hotwords: str = "") -> str | None:
    seed_words = parse_hotword_string(os.getenv("ASR_HOTWORDS", ""))
    extra_words = parse_hotword_string(extra_hotwords)
    with dynamic_hotword_lock:
        stream_words = list(dynamic_hotwords_by_stream.get(session_id, []))
        global_words = list(dynamic_hotwords_by_stream.get("*", []))

    max_words = int(os.getenv("ASR_MAX_HOTWORDS", "120").strip())
    words = merge_word_lists(seed_words, global_words, stream_words, extra_words)[:max_words]
    return ",".join(words) if words else None


def audio_dbfs(audio_path: Path) -> Optional[float]:
    """计算 wav 音频响度。静音片段可以直接跳过，减少 Whisper 幻觉。"""
    try:
        with wave.open(str(audio_path), "rb") as wav_file:
            sample_width = wav_file.getsampwidth()
            frames = wav_file.readframes(wav_file.getnframes())
        if not frames:
            return None

        rms = audioop.rms(frames, sample_width)
        if rms <= 0:
            return -100.0

        max_amplitude = float(2 ** (8 * sample_width - 1))
        return 20.0 * math.log10(rms / max_amplitude)
    except Exception as exc:
        print(f"[asr] 音频能量计算失败 {audio_path}: {exc}", flush=True)
        return None


def should_skip_by_energy(audio_path: Path) -> tuple[bool, Optional[float]]:
    """按能量阈值过滤静音/近静音片段。"""
    if not bool_env("ASR_ENABLE_ENERGY_FILTER", "true"):
        return False, None

    dbfs = audio_dbfs(audio_path)
    if dbfs is None:
        return False, None

    threshold = float(os.getenv("ASR_ENERGY_THRESHOLD_DBFS", "-42").strip())
    return dbfs < threshold, dbfs


def build_prompt(session_id: str, include_context: bool = True) -> str | None:
    """提示词只保留语言和场景信息，避免把指令文本回声成字幕。"""
    base_prompt = os.getenv(
        "ASR_INITIAL_PROMPT",
        "普通话中文音频，输出简体中文字幕。",
    ).strip()
    if not base_prompt:
        return None

    previous_text = ""
    if include_context and bool_env("ASR_USE_CONTEXT", "true"):
        with context_lock:
            previous_text = stream_context.get(session_id, "")

    if previous_text:
        return f"{base_prompt}\n上一段字幕仅用于理解上下文：{previous_text}"
    return base_prompt


def update_context(session_id: str, text: str) -> None:
    """保存每路视频最近字幕，供下一段短音频使用。"""
    if not text:
        return
    max_chars = int(os.getenv("ASR_CONTEXT_CHARS", "120").strip())
    with context_lock:
        old_text = stream_context.get(session_id, "")
        merged = f"{old_text} {text}".strip()
        stream_context[session_id] = merged[-max_chars:]


def looks_like_text(text: str) -> bool:
    """过滤只有标点、空白或模型幻觉的片段。"""
    return re.search(r"[A-Za-z0-9\u4e00-\u9fff]", text) is not None


def normalize_text(text: str) -> str:
    if bool_env("ASR_SIMPLIFIED_CHINESE", "true"):
        text = converter.convert(text)
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"(?<=[\u4e00-\u9fff])\s+(?=[\u4e00-\u9fff])", "", text)
    text = re.sub(r"([。！？!?；;])\1+", r"\1", text)
    text = re.sub(r"([，,、])\1+", r"\1", text)
    return text


def is_repetitive_text(text: str) -> bool:
    """过滤短音频上常见的重复字幻觉，例如“鸟、鸟、鸟、鸟”。"""
    if not bool_env("ASR_FILTER_REPETITION", "true"):
        return False

    compact = re.sub(r"\s+", "", text)
    chinese_chars = re.findall(r"[\u4e00-\u9fff]", compact)
    if len(chinese_chars) < 6:
        return False

    char_counts = Counter(chinese_chars)
    most_common_count = char_counts.most_common(1)[0][1]
    if most_common_count >= 6 and most_common_count / len(chinese_chars) >= 0.45:
        return True

    if re.search(r"((?:[\u4e00-\u9fff]{1,3}[、，,。.!！？?])+)\1{2,}", compact):
        return True
    return False


def is_boilerplate_hallucination(text: str) -> bool:
    """过滤片尾模板、提示词回声和常见无声幻觉。"""
    patterns = os.getenv(
        "ASR_HALLUCINATION_PATTERNS",
        (
            "请不吝点赞|点赞订阅|订阅转发|打赏支持|感谢观看|"
            "请逐字准确转写真实语音|不要总结|不要重复无声内容"
        ),
    ).split("|")
    compact = re.sub(r"\s+", "", text)
    return any(pattern and pattern in compact for pattern in patterns)


def should_drop_segment_text(
    text: str,
    avg_logprob: float | None,
    no_speech_prob: float | None,
    aggressive_filtering: bool,
) -> bool:
    normalized = normalize_text(text)
    if not normalized:
        return True
    if not looks_like_text(normalized):
        return True
    if is_repetitive_text(normalized):
        return True
    if is_boilerplate_hallucination(normalized):
        return True

    if aggressive_filtering:
        skip_no_speech_prob = float(os.getenv("ASR_SKIP_NO_SPEECH_PROB", "0.65").strip())
        skip_avg_logprob_below = float(os.getenv("ASR_SKIP_AVG_LOGPROB_BELOW", "-0.85").strip())
        if no_speech_prob is not None and no_speech_prob > skip_no_speech_prob:
            return True
        if avg_logprob is not None and avg_logprob < skip_avg_logprob_below:
            return True
    else:
        subtitle_no_speech = float(os.getenv("ASR_SUBTITLE_SKIP_NO_SPEECH_PROB", "0.88").strip())
        subtitle_avg_logprob = float(os.getenv("ASR_SUBTITLE_SKIP_AVG_LOGPROB_BELOW", "-1.20").strip())
        if no_speech_prob is not None and avg_logprob is not None:
            if no_speech_prob > subtitle_no_speech and avg_logprob < subtitle_avg_logprob:
                return True
    return False


def transcribe_with_model(
    media_path: Path,
    session_id: str,
    extra_hotwords: str = "",
    aggressive_filtering: bool = True,
    include_context: bool = True,
) -> dict[str, Any]:
    model = model_holder.get_model()
    started_at = time.time()
    hotwords = build_hotwords(session_id, extra_hotwords)

    with inference_lock:
        segments_iter, info = model.transcribe(
            str(media_path),
            language=os.getenv("ASR_LANGUAGE", "zh").strip() or None,
            task="transcribe",
            initial_prompt=build_prompt(session_id, include_context=include_context),
            hotwords=hotwords,
            vad_filter=bool_env("ASR_ENABLE_VAD", "true"),
            vad_parameters={
                "min_silence_duration_ms": int(
                    os.getenv(
                        "ASR_VAD_MIN_SILENCE_MS",
                        "300" if aggressive_filtering else "450",
                    ).strip()
                )
            },
            beam_size=int(os.getenv("ASR_BEAM_SIZE", "5").strip()),
            best_of=int(os.getenv("ASR_BEST_OF", "5").strip()),
            repetition_penalty=float(os.getenv("ASR_REPETITION_PENALTY", "1.05").strip()),
            no_repeat_ngram_size=int(os.getenv("ASR_NO_REPEAT_NGRAM_SIZE", "3").strip()),
            temperature=0.0,
            condition_on_previous_text=bool_env(
                "ASR_CONDITION_ON_PREVIOUS_TEXT",
                "false" if aggressive_filtering else "true",
            ),
            compression_ratio_threshold=float(
                os.getenv("ASR_COMPRESSION_RATIO_THRESHOLD", "2.2").strip()
            ),
            log_prob_threshold=float(os.getenv("ASR_LOG_PROB_THRESHOLD", "-1.0").strip()),
            no_speech_threshold=float(os.getenv("ASR_NO_SPEECH_THRESHOLD", "0.6").strip()),
            hallucination_silence_threshold=float(
                os.getenv("ASR_HALLUCINATION_SILENCE_THRESHOLD", "1.0").strip()
            ),
        )
        raw_segments = list(segments_iter)

    segments: list[dict[str, Any]] = []
    text_parts: list[str] = []
    for raw_segment in raw_segments:
        raw_text = raw_segment.text.strip()
        avg_logprob = getattr(raw_segment, "avg_logprob", None)
        no_speech_prob = getattr(raw_segment, "no_speech_prob", None)
        if should_drop_segment_text(
            raw_text,
            avg_logprob=avg_logprob,
            no_speech_prob=no_speech_prob,
            aggressive_filtering=aggressive_filtering,
        ):
            cleaned_text = ""
        else:
            cleaned_text = normalize_text(raw_text)

        if cleaned_text:
            text_parts.append(cleaned_text)

        segments.append(
            {
                "start": raw_segment.start,
                "end": raw_segment.end,
                "start_time_ms": int(max(raw_segment.start, 0.0) * 1000),
                "end_time_ms": int(max(raw_segment.end, raw_segment.start) * 1000),
                "text": cleaned_text,
                "avg_logprob": avg_logprob,
                "no_speech_prob": no_speech_prob,
            }
        )

    finished_at = time.time()
    final_text = normalize_text(" ".join(text_parts))
    return {
        "text": final_text,
        "segments": segments,
        "language": info.language,
        "language_probability": info.language_probability,
        "hotwords_used": parse_hotword_string(hotwords or ""),
        "inference_time_ms": int((finished_at - started_at) * 1000),
        "model": model_holder.loaded_model_name,
        "device": model_holder.device,
        "compute_type": model_holder.compute_type,
    }


def apply_hotword_update(session_id: str, terms: list[str]) -> int:
    cleaned_terms = merge_word_lists(terms)
    if not cleaned_terms:
        return 0

    with dynamic_hotword_lock:
        current = list(dynamic_hotwords_by_stream.get(session_id, []))
        merged = merge_word_lists(current, cleaned_terms)
        dynamic_hotwords_by_stream[session_id] = merged
        return max(len(merged) - len(current), 0)


async def consume_hotword_updates() -> None:
    """消费 API 广播的动态热词更新，避免 ASR 只能依赖静态词表。"""
    bootstrap_servers = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "kafka:9092").strip()
    topic = os.getenv("HOTWORD_UPDATE_TOPIC", "streamsense.hotword.updates").strip()
    if not topic:
        return

    while True:
        consumer: AIOKafkaConsumer | None = None
        try:
            consumer = AIOKafkaConsumer(
                topic,
                bootstrap_servers=bootstrap_servers,
                group_id="streamsense-asr-hotwords",
                auto_offset_reset="latest",
                enable_auto_commit=True,
            )
            await consumer.start()
            print(f"[asr] 动态热词消费者已启动, topic={topic}", flush=True)
            async for message in consumer:
                payload = json.loads(message.value.decode("utf-8"))
                session_id = str(payload.get("session_id", "")).strip()
                if not session_id:
                    session_id = build_session_id(
                        str(payload.get("stream_id", "*")),
                        str(payload.get("run_id", "")),
                    )
                incoming_terms = payload.get("terms", [])
                terms: list[str] = []
                for item in incoming_terms:
                    if isinstance(item, dict):
                        word = str(item.get("word", "")).strip()
                    else:
                        word = str(item).strip()
                    if word:
                        terms.append(word)

                added = apply_hotword_update(session_id, terms)
                if added:
                    print(
                        f"[asr] 已更新动态热词 session_id={session_id}, 新增={added}, 当前总数={len(dynamic_hotwords_by_stream.get(session_id, []))}",
                        flush=True,
                    )
        except Exception as exc:
            print(f"[asr] 动态热词消费异常，3 秒后重试: {exc}", flush=True)
            await asyncio.sleep(3)
        finally:
            if consumer is not None:
                await consumer.stop()


@app.get("/health")
def health() -> dict[str, Any]:
    with dynamic_hotword_lock:
        hotword_streams = {stream_id: len(words) for stream_id, words in dynamic_hotwords_by_stream.items()}
    return {
        "status": "ok",
        "model_loaded": model_holder.model is not None,
        "model": model_holder.loaded_model_name,
        "device": model_holder.device,
        "compute_type": model_holder.compute_type,
        "dynamic_hotword_streams": hotword_streams,
    }


@app.get("/hotwords")
def hotwords(stream_id: str | None = None) -> dict[str, Any]:
    with dynamic_hotword_lock:
        if stream_id:
            data = {stream_id: list(dynamic_hotwords_by_stream.get(stream_id, []))}
        else:
            data = {key: list(value) for key, value in dynamic_hotwords_by_stream.items()}
    return {"status": "ok", "hotwords": data}


@app.post("/detect-speech")
def detect_speech(request: SpeechDetectRequest) -> dict[str, Any]:
    media_path = Path(request.media_path)
    if not media_path.exists():
        raise HTTPException(status_code=404, detail=f"媒体文件不存在: {media_path}")

    try:
        duration_ms = media_duration_ms(media_path)
        intervals = detect_speech_intervals(
            media_path=media_path,
            noise_db=request.noise_db,
            min_silence_ms=request.min_silence_ms,
            min_speech_ms=request.min_speech_ms,
            padding_ms=request.padding_ms,
        )
        return {
            "status": "ok",
            "media_path": str(media_path),
            "duration_ms": duration_ms,
            "speech_intervals": intervals,
        }
    except Exception as exc:
        print(f"[asr] 语音区间检测失败 media_path={media_path}: {exc}", flush=True)
        raise HTTPException(status_code=500, detail=f"语音区间检测失败: {exc}") from exc


@app.post("/transcribe")
def transcribe(request: TranscribeRequest) -> dict[str, Any]:
    audio_path = Path(request.file_path)
    if not audio_path.exists():
        raise HTTPException(status_code=404, detail=f"音频片段不存在: {audio_path}")

    session_id = build_session_id(request.stream_id, request.run_id)
    started_at = time.time()
    skip_by_energy, dbfs = should_skip_by_energy(audio_path)
    if skip_by_energy:
        finished_at = time.time()
        return {
            "segment_id": request.segment_id,
            "stream_id": request.stream_id,
            "run_id": request.run_id,
            "session_id": session_id,
            "text": "",
            "language": os.getenv("ASR_LANGUAGE", "zh").strip() or "zh",
            "language_probability": 1.0,
            "start_time_ms": request.start_time_ms,
            "end_time_ms": request.end_time_ms,
            "model": model_holder.loaded_model_name or os.getenv("ASR_MODEL", ""),
            "device": model_holder.device or os.getenv("ASR_DEVICE", ""),
            "compute_type": model_holder.compute_type or os.getenv("ASR_COMPUTE_TYPE", ""),
            "inference_time_ms": int((finished_at - started_at) * 1000),
            "audio_dbfs": dbfs,
            "segments": [],
            "hotwords_used": parse_hotword_string(build_hotwords(session_id) or ""),
            "status": "ok",
        }

    try:
        result = transcribe_with_model(
            audio_path,
            session_id=session_id,
            aggressive_filtering=True,
            include_context=True,
        )
        update_context(session_id, result["text"])
        result.update(
            {
                "segment_id": request.segment_id,
                "stream_id": request.stream_id,
                "run_id": request.run_id,
                "session_id": session_id,
                "start_time_ms": request.start_time_ms,
                "end_time_ms": request.end_time_ms,
                "audio_dbfs": dbfs,
                "status": "ok",
            }
        )
        return result
    except Exception as exc:
        print(f"[asr] 推理失败 segment_id={request.segment_id}: {exc}", flush=True)
        raise HTTPException(status_code=500, detail=f"ASR 推理失败: {exc}") from exc


@app.post("/transcribe-media")
def transcribe_media(request: MediaTranscribeRequest) -> dict[str, Any]:
    media_path = Path(request.media_path)
    if not media_path.exists():
        raise HTTPException(status_code=404, detail=f"媒体文件不存在: {media_path}")

    session_id = build_session_id(request.stream_id, request.run_id)
    transcribe_path = media_path
    clip_path: Path | None = None
    clip_offset_ms = 0
    try:
        if request.clip_end_ms > request.clip_start_ms:
            clip_offset_ms = max(int(request.clip_start_ms), 0)
            clip_path = extract_clip_to_wav(
                media_path,
                start_ms=clip_offset_ms,
                end_ms=int(request.clip_end_ms),
            )
            transcribe_path = clip_path

        result = transcribe_with_model(
            transcribe_path,
            session_id=session_id,
            extra_hotwords=request.hotwords,
            aggressive_filtering=request.aggressive_filtering,
            include_context=False,
        )
        if clip_offset_ms:
            offset_result_timing(result, clip_offset_ms)

        result.update(
            {
                "media_path": str(media_path),
                "stream_id": request.stream_id,
                "run_id": request.run_id,
                "session_id": session_id,
                "clip_start_ms": request.clip_start_ms,
                "clip_end_ms": request.clip_end_ms,
                "status": "ok",
            }
        )
        return result
    except Exception as exc:
        print(f"[asr] 整段媒体转写失败 media_path={media_path}: {exc}", flush=True)
        raise HTTPException(status_code=500, detail=f"整段媒体转写失败: {exc}") from exc
    finally:
        if clip_path is not None:
            try:
                clip_path.unlink(missing_ok=True)
            except Exception:
                pass


@app.on_event("startup")
async def startup() -> None:
    if bool_env("ASR_PRELOAD", "true"):
        await asyncio.to_thread(model_holder.get_model)
    asyncio.create_task(consume_hotword_updates())
