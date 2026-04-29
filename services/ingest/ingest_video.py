import glob
import json
import os
import re
import shutil
import subprocess
import time
import uuid
import wave
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from kafka import KafkaProducer
from kafka.errors import NoBrokersAvailable

SAMPLE_RATE = 16000
CHANNELS = 1
SAMPLE_WIDTH = 2


@dataclass
class AudioFrame:
    """一帧 16k PCM 音频。"""

    data: bytes
    start_ms: int
    voiced: bool


def env(name: str, default: str) -> str:
    """读取环境变量，代码里统一用这个函数，方便初学者查配置来源。"""
    return os.getenv(name, default).strip()


def is_url(source: str) -> bool:
    """判断输入是否为 RTSP/HTTP 这类真实网络视频流。"""
    scheme = urlparse(source).scheme.lower()
    return scheme in {"rtsp", "rtmp", "http", "https"}


def bool_env(name: str, default: str) -> bool:
    return env(name, default).lower() in {"1", "true", "yes", "on"}


def int_env(name: str, default: int) -> int:
    try:
        return int(env(name, str(default)))
    except ValueError:
        return default


def wait_for_local_source(source: str) -> None:
    """本地视频不存在时等待，方便用户先启动系统再复制视频进 videos 目录。"""
    wait_enabled = bool_env("WAIT_FOR_SOURCE", "true")
    if is_url(source) or not wait_enabled:
        return

    while not Path(source).exists():
        print(f"[ingest] 等待真实视频文件出现: {source}", flush=True)
        time.sleep(3)


def wait_for_kafka(bootstrap_servers: str) -> KafkaProducer:
    """等待 Kafka 可用，并返回生产者。"""
    while True:
        try:
            producer = KafkaProducer(
                bootstrap_servers=bootstrap_servers,
                value_serializer=lambda value: json.dumps(value, ensure_ascii=False).encode("utf-8"),
                key_serializer=lambda value: value.encode("utf-8"),
                retries=5,
            )
            print("[ingest] Kafka 已连接", flush=True)
            return producer
        except NoBrokersAvailable:
            print("[ingest] 等待 Kafka 启动...", flush=True)
            time.sleep(3)


def check_ffmpeg() -> None:
    """确认容器中存在 FFmpeg。"""
    if shutil.which("ffmpeg") is None:
        raise RuntimeError("未找到 ffmpeg，视频抽音频无法执行")


def build_ffmpeg_input_command(source: str) -> list[str]:
    """FFmpeg 的输入部分。固定切块和 VAD 切块都会复用这里。"""
    command = ["ffmpeg", "-hide_banner", "-loglevel", "warning"]

    # 本地视频文件可以使用 -re 按视频原始速度读取，更接近真实实时输入。
    if not is_url(source) and bool_env("REALTIME_FILE_INPUT", "true"):
        command.append("-re")

    # RTSP 摄像头常用 TCP 更稳定。
    if source.lower().startswith("rtsp://"):
        command.extend(["-rtsp_transport", "tcp"])

    command.extend(["-i", source, "-vn", "-ac", str(CHANNELS), "-ar", str(SAMPLE_RATE)])
    return command


def start_ffmpeg_fixed_segments(source: str, output_pattern: str, segment_seconds: int) -> subprocess.Popen:
    """启动 FFmpeg，把真实视频输入切成多个 wav 音频片段。"""
    command = build_ffmpeg_input_command(source)
    command.extend(
        ["-f", "segment", "-segment_time", str(segment_seconds), "-reset_timestamps", "1", output_pattern]
    )

    print("[ingest] 启动 FFmpeg:", " ".join(command), flush=True)
    return subprocess.Popen(command)


def start_ffmpeg_pcm_stream(source: str) -> subprocess.Popen:
    """启动 FFmpeg，把真实视频解码成 16k 单声道 PCM，供 VAD 逐帧处理。"""
    command = build_ffmpeg_input_command(source)
    command.extend(["-f", "s16le", "-acodec", "pcm_s16le", "-"])
    print("[ingest] 启动 FFmpeg PCM 流:", " ".join(command), flush=True)
    return subprocess.Popen(command, stdout=subprocess.PIPE)


def is_file_stable(path: str) -> bool:
    """判断文件是否写完。FFmpeg 正在写的片段不能提前发给 ASR。"""
    first_size = os.path.getsize(path)
    time.sleep(0.25)
    second_size = os.path.getsize(path)
    age_seconds = time.time() - os.path.getmtime(path)
    return first_size == second_size and age_seconds > 0.5


def parse_index(path: str) -> int:
    """从 demo_000012.wav 这种文件名里取出片段编号。"""
    match = re.search(r"_(\d+)\.wav$", Path(path).name)
    if not match:
        return 0
    return int(match.group(1))


def build_message(
    stream_id: str,
    run_id: str,
    file_path: str,
    start_ms: int,
    end_ms: int,
    source: str,
) -> dict:
    segment_index = parse_index(file_path)
    segment_id = f"{stream_id}-{run_id}-{segment_index:06d}"
    created_at = int(time.time() * 1000)
    duration_ms = max(end_ms - start_ms, 0)
    return {
        "segment_id": segment_id,
        "stream_id": stream_id,
        "run_id": run_id,
        "file_path": file_path,
        "start_time": round(start_ms / 1000, 3),
        "end_time": round(end_ms / 1000, 3),
        "duration": round(duration_ms / 1000, 3),
        "start_time_ms": start_ms,
        "end_time_ms": end_ms,
        "duration_ms": duration_ms,
        "sample_rate": SAMPLE_RATE,
        "created_at": created_at,
        "vad_start_at": created_at,
        "vad_end_at": created_at,
        "kafka_sent_at": 0,
        "created_at_ms": created_at,
        "source_type": "url" if is_url(source) else "file",
    }


def publish_chunk_message(
    producer: KafkaProducer,
    topic: str,
    stream_id: str,
    run_id: str,
    audio_path: Path,
    start_ms: int,
    end_ms: int,
    source: str,
) -> None:
    message = build_message(stream_id, run_id, str(audio_path), start_ms, end_ms, source)
    message["kafka_sent_at"] = int(time.time() * 1000)
    producer.send(topic, key=stream_id, value=message)
    producer.flush()
    print(f"[ingest] 已发送音频片段到 Kafka: {message['segment_id']}", flush=True)


def publish_ready_segments(
    producer: KafkaProducer,
    topic: str,
    stream_id: str,
    run_id: str,
    segment_seconds: int,
    pattern_for_glob: str,
    published: set[str],
    include_latest: bool = False,
) -> None:
    """扫描已经切好的音频文件，并把元数据写入 Kafka。"""
    audio_paths = sorted(glob.glob(pattern_for_glob))
    if not include_latest and len(audio_paths) > 1:
        # FFmpeg 正在写最新的那个 wav。只发布它前面的文件，确保 wav 头和数据已经写完整。
        audio_paths = audio_paths[:-1]
    elif not include_latest:
        audio_paths = []

    for audio_path in audio_paths:
        if audio_path in published:
            continue
        if not is_file_stable(audio_path):
            continue

        index = parse_index(audio_path)
        start_ms = index * segment_seconds * 1000
        end_ms = (index + 1) * segment_seconds * 1000
        publish_chunk_message(
            producer=producer,
            topic=topic,
            stream_id=stream_id,
            run_id=run_id,
            audio_path=Path(audio_path),
            start_ms=start_ms,
            end_ms=end_ms,
            source=env("VIDEO_SOURCE", ""),
        )
        published.add(audio_path)


def write_wav_file(path: Path, frames: list[AudioFrame]) -> None:
    """把若干 PCM 帧写成 wav 文件，供 ASR 直接读取。"""
    with wave.open(str(path), "wb") as wav_file:
        wav_file.setnchannels(CHANNELS)
        wav_file.setsampwidth(SAMPLE_WIDTH)
        wav_file.setframerate(SAMPLE_RATE)
        wav_file.writeframes(b"".join(frame.data for frame in frames))


def has_voiced_frame(frames: list[AudioFrame]) -> bool:
    return any(frame.voiced for frame in frames)


def trim_trailing_silence(frames: list[AudioFrame], keep_frames: int) -> list[AudioFrame]:
    trimmed = list(frames)
    trailing_silence = 0
    for frame in reversed(trimmed):
        if frame.voiced:
            break
        trailing_silence += 1

    drop_count = max(trailing_silence - keep_frames, 0)
    if drop_count <= 0:
        return trimmed
    return trimmed[:-drop_count]


def run_fixed_segment_mode(
    producer: KafkaProducer,
    topic: str,
    source: str,
    stream_id: str,
    run_id: str,
    output_dir: Path,
) -> None:
    segment_seconds = int_env("SEGMENT_SECONDS", 6)
    output_pattern = str(output_dir / f"{stream_id}_{run_id}_%06d.wav")
    glob_pattern = str(output_dir / f"{stream_id}_{run_id}_*.wav")
    process = start_ffmpeg_fixed_segments(source, output_pattern, segment_seconds)
    published: set[str] = set()

    try:
        while process.poll() is None:
            publish_ready_segments(
                producer,
                topic,
                stream_id,
                run_id,
                segment_seconds,
                glob_pattern,
                published,
                include_latest=False,
            )
            time.sleep(0.5)

        publish_ready_segments(
            producer,
            topic,
            stream_id,
            run_id,
            segment_seconds,
            glob_pattern,
            published,
            include_latest=True,
        )

        if process.returncode != 0:
            raise RuntimeError(f"FFmpeg 异常退出，退出码: {process.returncode}")
        print("[ingest] 固定切块模式处理完成", flush=True)
    finally:
        producer.flush()


def run_vad_segment_mode(
    producer: KafkaProducer,
    topic: str,
    source: str,
    stream_id: str,
    run_id: str,
    output_dir: Path,
) -> None:
    """用 WebRTC VAD 做动态切块。静音足够长才切句，避免把词切断。"""
    try:
        import webrtcvad
    except ImportError as exc:
        raise RuntimeError("VAD 模式依赖 webrtcvad-wheels，请重新构建 ingest 镜像") from exc

    frame_ms = int_env("INGEST_VAD_FRAME_MS", 30)
    if frame_ms not in {10, 20, 30}:
        raise RuntimeError("INGEST_VAD_FRAME_MS 只能是 10、20 或 30")

    aggressiveness = int_env("INGEST_VAD_AGGRESSIVENESS", 2)
    min_chunk_ms = int_env("INGEST_VAD_MIN_CHUNK_MS", 500)
    target_chunk_ms = int_env("INGEST_VAD_TARGET_CHUNK_MS", int_env("INGEST_VAD_MAX_CHUNK_MS", 3000))
    hard_max_chunk_ms = int_env("INGEST_VAD_HARD_MAX_CHUNK_MS", 4500)
    max_silence_ms = int_env("INGEST_VAD_MAX_SILENCE_MS", 1400)
    short_boundary_ms = int_env("INGEST_VAD_SHORT_BOUNDARY_MS", 240)
    padding_ms = int_env("INGEST_VAD_PADDING_MS", 300)

    min_chunk_frames = max(1, min_chunk_ms // frame_ms)
    target_chunk_frames = max(min_chunk_frames, target_chunk_ms // frame_ms)
    hard_max_chunk_frames = max(target_chunk_frames, hard_max_chunk_ms // frame_ms)
    silence_flush_frames = max(1, max_silence_ms // frame_ms)
    short_boundary_frames = max(1, short_boundary_ms // frame_ms)
    padding_frames = max(0, padding_ms // frame_ms)
    bytes_per_frame = SAMPLE_RATE * SAMPLE_WIDTH * frame_ms // 1000

    vad = webrtcvad.Vad(max(0, min(aggressiveness, 3)))
    process = start_ffmpeg_pcm_stream(source)
    if process.stdout is None:
        raise RuntimeError("FFmpeg PCM 流未成功创建 stdout 管道")

    prefix_buffer: deque[AudioFrame] = deque(maxlen=max(padding_frames, 1))
    active_frames: list[AudioFrame] = []
    emitted_chunks = 0
    frame_index = 0
    silence_frames = 0

    def flush_current_chunk(reason: str) -> None:
        nonlocal active_frames, silence_frames, emitted_chunks
        if not active_frames or not has_voiced_frame(active_frames):
            active_frames = []
            silence_frames = 0
            return

        frames_to_write = list(active_frames)
        if reason in {"pause", "eof"}:
            frames_to_write = trim_trailing_silence(frames_to_write, padding_frames)

        if len(frames_to_write) < min_chunk_frames and reason != "eof":
            return

        audio_path = output_dir / f"{stream_id}_{run_id}_{emitted_chunks:06d}.wav"
        write_wav_file(audio_path, frames_to_write)
        start_ms = frames_to_write[0].start_ms
        end_ms = frames_to_write[-1].start_ms + frame_ms
        publish_chunk_message(
            producer=producer,
            topic=topic,
            stream_id=stream_id,
            run_id=run_id,
            audio_path=audio_path,
            start_ms=start_ms,
            end_ms=end_ms,
            source=source,
        )
        emitted_chunks += 1
        active_frames = []
        silence_frames = 0

    try:
        while True:
            frame_bytes = process.stdout.read(bytes_per_frame)
            if not frame_bytes:
                break
            if len(frame_bytes) < bytes_per_frame:
                print("[ingest] 遇到末尾残缺 PCM 帧，停止读取", flush=True)
                break

            start_ms = frame_index * frame_ms
            frame_index += 1
            voiced = vad.is_speech(frame_bytes, SAMPLE_RATE)
            frame = AudioFrame(data=frame_bytes, start_ms=start_ms, voiced=voiced)

            if not active_frames:
                prefix_buffer.append(frame)
                if voiced:
                    active_frames = list(prefix_buffer)
                    prefix_buffer.clear()
                    silence_frames = 0
                continue

            active_frames.append(frame)
            if voiced:
                silence_frames = 0
            else:
                silence_frames += 1

            if silence_frames >= silence_flush_frames:
                if len(active_frames) >= min_chunk_frames:
                    flush_current_chunk("pause")
                else:
                    active_frames = []
                    silence_frames = 0
                continue

            if len(active_frames) >= target_chunk_frames and silence_frames >= short_boundary_frames:
                flush_current_chunk("target")
                continue

            if len(active_frames) >= hard_max_chunk_frames:
                flush_current_chunk("max")

        if active_frames:
            flush_current_chunk("eof")

        exit_code = process.wait()
        if exit_code != 0:
            raise RuntimeError(f"FFmpeg 异常退出，退出码: {exit_code}")
        print("[ingest] VAD 动态切块模式处理完成", flush=True)
    finally:
        producer.flush()


def main() -> None:
    bootstrap_servers = env("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")
    topic = env("AUDIO_TOPIC", "audio-segment")
    source = env("VIDEO_SOURCE", "/videos/input.mp4")
    stream_id = env("STREAM_ID", "demo-video")
    segment_mode = env("INGEST_SEGMENT_MODE", "vad").lower()
    output_dir = Path(env("OUTPUT_DIR", "/data/audio"))

    check_ffmpeg()
    wait_for_local_source(source)
    output_dir.mkdir(parents=True, exist_ok=True)

    run_id = uuid.uuid4().hex[:8]
    producer = wait_for_kafka(bootstrap_servers)
    try:
        if segment_mode == "vad":
            run_vad_segment_mode(producer, topic, source, stream_id, run_id, output_dir)
        elif segment_mode == "fixed":
            run_fixed_segment_mode(producer, topic, source, stream_id, run_id, output_dir)
        else:
            raise RuntimeError(f"不支持的 INGEST_SEGMENT_MODE: {segment_mode}")

        print(f"[ingest] 视频处理完成, mode={segment_mode}", flush=True)
    finally:
        producer.flush()
        producer.close()


if __name__ == "__main__":
    main()
