import json
import os
import subprocess
import tempfile
import time
import wave
from pathlib import Path

from fastapi import FastAPI, File, Form, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from kafka import KafkaProducer

"""
StreamSense Live 的实时音频接入服务。

这个服务是大数据实时链路的第一站：

Electron 麦克风录音
-> POST /live/audio
-> FFmpeg 转成 16k 单声道 wav
-> 过滤静音/太短片段
-> 写 Kafka audio-segment topic
-> Flink 消费 audio-segment 并调用 ASR

注意：
这个服务不直接调用 Whisper/ASR。它只负责“接入”和“写 Kafka”。
这样设计是为了保留 Kafka + Flink 的课程设计价值。
"""


SAMPLE_RATE = 16000
CHANNELS = 1
OUTPUT_DIR = Path(os.getenv("OUTPUT_DIR", "/data/audio"))
BOOTSTRAP_SERVERS = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "kafka:9092")
AUDIO_TOPIC = os.getenv("AUDIO_TOPIC", "audio-segment")
DEFAULT_STREAM_ID = os.getenv("STREAM_ID", "desktop-live")
MIN_DBFS = float(os.getenv("LIVE_INGEST_MIN_DBFS", "-45"))
MIN_WAV_BYTES = int(os.getenv("LIVE_INGEST_MIN_WAV_BYTES", "32000"))
DROP_TEXT_PATTERNS = [
    "Amara.org",
    "中文字幕志愿者",
    "字幕由",
    "字幕组",
]

app = FastAPI(title="StreamSense Live Ingest")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

producer: KafkaProducer | None = None


def now_ms() -> int:
    return int(time.time() * 1000)


def get_producer() -> KafkaProducer:
    """懒加载 KafkaProducer。

    FastAPI 服务启动时 Kafka 可能还没完全 ready。
    所以不在模块加载时立刻连接 Kafka，而是在第一次收到音频时再创建 producer。
    """
    global producer
    if producer is None:
        producer = KafkaProducer(
            bootstrap_servers=BOOTSTRAP_SERVERS,
            value_serializer=lambda value: json.dumps(value, ensure_ascii=False).encode("utf-8"),
            key_serializer=lambda value: value.encode("utf-8"),
            retries=5,
        )
    return producer


def convert_to_wav(source_path: Path, target_path: Path) -> None:
    """把浏览器上传的 webm/ogg 等音频转换为 ASR 能稳定读取的 wav。

    浏览器 MediaRecorder 默认输出 webm/opus。
    ASR 服务更适合处理 16k、单声道 wav，所以这里统一转换。
    """
    command = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-i",
        str(source_path),
        "-vn",
        "-ac",
        str(CHANNELS),
        "-ar",
        str(SAMPLE_RATE),
        str(target_path),
    ]
    subprocess.run(command, check=True)


def wav_dbfs(path: Path) -> float:
    """计算 wav 音量，单位 dBFS。

    直播字幕里最常见的问题是“没人说话时 Whisper 幻觉出字幕”。
    所以写 Kafka 前先做能量过滤：
      - 音量太低：当静音处理，不进入 Kafka。
      - 文件太短：说明录音片段无效，也不进入 Kafka。
    """
    with wave.open(str(path), "rb") as wav_file:
        frames = wav_file.readframes(wav_file.getnframes())
        sample_width = wav_file.getsampwidth()
    if not frames:
        return -100.0

    import audioop
    import math

    rms = audioop.rms(frames, sample_width)
    if rms <= 0:
        return -100.0
    max_amplitude = float(2 ** (8 * sample_width - 1))
    return 20.0 * math.log10(rms / max_amplitude)


@app.get("/health")
def health() -> dict:
    return {
        "status": "ok",
        "topic": AUDIO_TOPIC,
        "bootstrap_servers": BOOTSTRAP_SERVERS,
    }


@app.post("/live/audio")
async def live_audio(
    file: UploadFile = File(...),
    stream_id: str = Form(DEFAULT_STREAM_ID),
    run_id: str = Form(""),
    chunk_index: int = Form(0),
    chunk_ms: int = Form(3000),
    hotwords: str = Form(""),
) -> dict:
    """接收一个实时音频片段，并把它变成 Kafka 消息。

    参数来源：
      file：Electron 前端录到的一小段完整 WebM。
      stream_id：固定为 desktop-live，用来和普通视频流区分。
      run_id：本次实时字幕会话 ID。
      chunk_index/chunk_ms：用来计算片段相对时间轴。
      hotwords：传给 Flink，再由 Flink 传给 ASR，提高短句识别稳定性。
    """
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    run_value = run_id.strip() or time.strftime("%Y%m%d%H%M%S")
    segment_id = f"{stream_id}-{run_value}-{chunk_index:06d}"

    suffix = Path(file.filename or "chunk.webm").suffix or ".webm"
    with tempfile.NamedTemporaryFile(prefix="streamsense_live_", suffix=suffix, delete=False) as handle:
        raw_path = Path(handle.name)
        handle.write(await file.read())

    wav_name = f"{stream_id}_{run_value}_{chunk_index:06d}.wav"
    wav_path = OUTPUT_DIR / wav_name
    try:
        convert_to_wav(raw_path, wav_path)
    finally:
        raw_path.unlink(missing_ok=True)

    file_size = wav_path.stat().st_size if wav_path.exists() else 0
    dbfs = wav_dbfs(wav_path)
    if file_size < MIN_WAV_BYTES or dbfs < MIN_DBFS:
        # 静音片段直接跳过，不写 Kafka。
        # 这是减少“中文字幕志愿者 / Amara.org”这类幻觉的关键。
        wav_path.unlink(missing_ok=True)
        return {
            "status": "skipped",
            "reason": "silent_or_too_short",
            "segment_id": segment_id,
            "audio_dbfs": round(dbfs, 2),
            "file_size": file_size,
        }

    start_ms = max(chunk_index, 0) * max(chunk_ms, 1)
    end_ms = start_ms + max(chunk_ms, 1)
    created_at = now_ms()
    wall_start_at = created_at - max(chunk_ms, 1)
    message = {
        # 下面这份 message 必须和 services/ingest/ingest_video.py 产出的字段保持接近。
        # 这样 flink/transcription_job.py 可以复用同一套处理逻辑。
        "segment_id": segment_id,
        "stream_id": stream_id,
        "run_id": run_value,
        "file_path": f"/data/audio/{wav_name}",
        "start_time": round(start_ms / 1000, 3),
        "end_time": round(end_ms / 1000, 3),
        "duration": round((end_ms - start_ms) / 1000, 3),
        "start_time_ms": start_ms,
        "end_time_ms": end_ms,
        "duration_ms": end_ms - start_ms,
        "sample_rate": SAMPLE_RATE,
        "created_at": created_at,
        "created_at_ms": created_at,
        "wall_start_at_ms": wall_start_at,
        "wall_end_at_ms": created_at,
        "vad_start_at": created_at,
        "vad_end_at": created_at,
        "kafka_sent_at": now_ms(),
        "source_type": "desktop-microphone",
        "hotwords": hotwords,
    }
    get_producer().send(AUDIO_TOPIC, key=stream_id, value=message)
    get_producer().flush()
    return {"status": "ok", "segment_id": segment_id, "file_path": message["file_path"]}
