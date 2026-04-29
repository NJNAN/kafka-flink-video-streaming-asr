import json
import os
import time
from typing import Any

import requests
from pyflink.common import SimpleStringSchema, Types, WatermarkStrategy
from pyflink.datastream import StreamExecutionEnvironment
from pyflink.datastream.connectors.kafka import (
    DeliveryGuarantee,
    KafkaOffsetsInitializer,
    KafkaRecordSerializationSchema,
    KafkaSink,
    KafkaSource,
)


BOOTSTRAP_SERVERS = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "kafka:9092")
AUDIO_TOPIC = os.getenv("AUDIO_TOPIC", "audio-segment")
TRANSCRIPT_TOPIC = os.getenv("TRANSCRIPT_TOPIC", "transcription-result")
FAILED_TOPIC = os.getenv("FAILED_TOPIC", "transcription-failed")
ASR_URL = os.getenv("ASR_URL", "http://asr:8000").rstrip("/")
ASR_TIMEOUT_SECONDS = int(os.getenv("ASR_TIMEOUT_SECONDS", "120"))
ASR_RETRY_TIMES = int(os.getenv("ASR_RETRY_TIMES", "2"))
ASR_RETRY_BACKOFF_MS = int(os.getenv("ASR_RETRY_BACKOFF_MS", "800"))


def now_ms() -> int:
    return int(time.time() * 1000)


def safe_get(data: dict[str, Any], key: str, default: Any = "") -> Any:
    """从字典取值的小工具，避免 KeyError 让 Flink 作业直接失败。"""
    return data.get(key, default)


def stream_id_from_raw(raw_message: str) -> str:
    try:
        data = json.loads(raw_message)
        return str(data.get("stream_id", "unknown"))
    except Exception:
        return "unknown"


def call_asr_with_retry(request_body: dict[str, Any]) -> tuple[dict[str, Any], str]:
    """调用 ASR，失败后做短间隔重试，避免偶发网络/模型忙导致片段直接丢失。"""
    last_error = ""
    last_response_text = ""
    for attempt in range(max(ASR_RETRY_TIMES, 0) + 1):
        try:
            response = requests.post(
                f"{ASR_URL}/transcribe",
                json=request_body,
                timeout=ASR_TIMEOUT_SECONDS,
            )
            response.raise_for_status()
            result = response.json()
            result["retry_count"] = attempt
            return result, ""
        except Exception as exc:
            last_error = str(exc)
            if "response" in locals():
                last_response_text = getattr(response, "text", "")[:500]
            if attempt < ASR_RETRY_TIMES:
                time.sleep(max(ASR_RETRY_BACKOFF_MS, 0) / 1000)

    result = {
        **request_body,
        "text": "",
        "language": "",
        "inference_time_ms": 0,
        "retry_count": max(ASR_RETRY_TIMES, 0),
    }
    if last_response_text:
        last_error = f"{last_error}; response={last_response_text}"
    return result, last_error


def transcribe_segment(raw_message: str) -> str:
    """Flink 的核心处理函数：收到音频片段消息，调用本地 ASR 服务。"""
    flink_received_at = now_ms()

    try:
        audio_message = json.loads(raw_message)
    except json.JSONDecodeError as exc:
        return json.dumps(
            {
                "status": "error",
                "error": f"非法 JSON: {exc}",
                "raw_message": raw_message,
                "flink_received_at": flink_received_at,
                "flink_receive_time_ms": flink_received_at,
                "flink_finish_time_ms": now_ms(),
            },
            ensure_ascii=False,
        )

    request_body = {
        "segment_id": safe_get(audio_message, "segment_id"),
        "stream_id": safe_get(audio_message, "stream_id"),
        "run_id": safe_get(audio_message, "run_id"),
        "file_path": safe_get(audio_message, "file_path"),
        "start_time_ms": safe_get(audio_message, "start_time_ms", 0),
        "end_time_ms": safe_get(audio_message, "end_time_ms", 0),
    }
    hotwords = safe_get(audio_message, "hotwords", "")
    if hotwords:
        request_body["hotwords"] = hotwords

    asr_start_at = now_ms()
    try:
        result, error = call_asr_with_retry(request_body)
        status = result.get("status", "ok")
    except Exception as exc:
        result = {
            **request_body,
            "text": "",
            "language": "",
            "inference_time_ms": 0,
            "retry_count": max(ASR_RETRY_TIMES, 0),
        }
        status = "error"
        error = str(exc)

    asr_end_at = now_ms()
    finish_time = asr_end_at
    created_at_ms = safe_get(audio_message, "created_at_ms", safe_get(audio_message, "created_at", flink_received_at))
    kafka_sent_at = safe_get(audio_message, "kafka_sent_at", 0)

    # 保留每个阶段的时间，后续论文可以用这些字段做延迟分析。
    result.update(
        {
            "status": status,
            "error": error,
            "created_at": int(created_at_ms),
            "vad_start_at": safe_get(audio_message, "vad_start_at", int(created_at_ms)),
            "vad_end_at": safe_get(audio_message, "vad_end_at", int(created_at_ms)),
            "kafka_sent_at": kafka_sent_at,
            "flink_received_at": flink_received_at,
            "asr_start_at": asr_start_at,
            "asr_end_at": asr_end_at,
            "audio_created_at_ms": created_at_ms,
            "wall_start_at_ms": safe_get(audio_message, "wall_start_at_ms", 0),
            "wall_end_at_ms": safe_get(audio_message, "wall_end_at_ms", 0),
            "flink_receive_time_ms": flink_received_at,
            "flink_finish_time_ms": finish_time,
            "flink_process_time_ms": finish_time - flink_received_at,
            "kafka_flink_dispatch_time_ms": flink_received_at - int(kafka_sent_at) if kafka_sent_at else 0,
            "asr_total_time_ms": asr_end_at - asr_start_at,
            "end_to_end_time_ms": finish_time - int(created_at_ms),
        }
    )
    return json.dumps(result, ensure_ascii=False)


def is_failed_result(raw_message: str) -> bool:
    try:
        data = json.loads(raw_message)
        return data.get("status") != "ok"
    except Exception:
        return True


def build_kafka_source() -> KafkaSource:
    return (
        KafkaSource.builder()
        .set_bootstrap_servers(BOOTSTRAP_SERVERS)
        .set_topics(AUDIO_TOPIC)
        .set_group_id("flink-asr-transcription")
        # 使用 earliest 可以避免 ASR 首次下载/加载模型较慢时，漏掉已经进入 Kafka 的真实视频片段。
        .set_starting_offsets(KafkaOffsetsInitializer.earliest())
        .set_value_only_deserializer(SimpleStringSchema())
        .build()
    )


def build_kafka_sink(topic: str) -> KafkaSink:
    serializer = (
        KafkaRecordSerializationSchema.builder()
        .set_topic(topic)
        .set_value_serialization_schema(SimpleStringSchema())
        .build()
    )
    return (
        KafkaSink.builder()
        .set_bootstrap_servers(BOOTSTRAP_SERVERS)
        .set_record_serializer(serializer)
        .set_delivery_guarantee(DeliveryGuarantee.AT_LEAST_ONCE)
        .build()
    )


def main() -> None:
    env = StreamExecutionEnvironment.get_execution_environment()
    env.set_parallelism(int(os.getenv("FLINK_JOB_PARALLELISM", "1")))
    env.enable_checkpointing(30_000)

    source = build_kafka_source()
    sink = build_kafka_sink(TRANSCRIPT_TOPIC)
    failed_sink = build_kafka_sink(FAILED_TOPIC)

    stream = env.from_source(source, WatermarkStrategy.no_watermarks(), "audio-segment-source")
    result_stream = stream.key_by(stream_id_from_raw, key_type=Types.STRING()).map(
        transcribe_segment,
        output_type=Types.STRING(),
    )
    result_stream.sink_to(sink)
    result_stream.filter(is_failed_result).sink_to(failed_sink)

    env.execute("video-audio-transcription-job")


if __name__ == "__main__":
    main()
