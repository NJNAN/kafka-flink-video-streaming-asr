import sqlite3
from pathlib import Path
from typing import Any


SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  stream_id TEXT NOT NULL,
  run_id TEXT NOT NULL,
  source_type TEXT,
  started_at_ms INTEGER,
  finished_at_ms INTEGER,
  status TEXT,
  model TEXT,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS segments (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  stream_id TEXT NOT NULL,
  run_id TEXT,
  segment_id TEXT,
  start_time_ms INTEGER,
  end_time_ms INTEGER,
  text TEXT,
  status TEXT,
  retry_count INTEGER DEFAULT 0,
  end_to_end_time_ms INTEGER,
  asr_inference_time_ms INTEGER,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_segments_stream_time
ON segments(stream_id, run_id, start_time_ms);

CREATE UNIQUE INDEX IF NOT EXISTS idx_segments_unique
ON segments(stream_id, run_id, segment_id, start_time_ms, end_time_ms, text);

CREATE TABLE IF NOT EXISTS failed_segments (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  stream_id TEXT,
  run_id TEXT,
  segment_id TEXT,
  error TEXT,
  retry_count INTEGER DEFAULT 0,
  created_at_ms INTEGER,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_failed_segments_unique
ON failed_segments(stream_id, run_id, segment_id, created_at_ms);

CREATE TABLE IF NOT EXISTS metrics_samples (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  sampled_at_ms INTEGER,
  stream_id TEXT,
  total_segments INTEGER,
  success_segments INTEGER,
  failed_segments INTEGER,
  average_end_to_end_latency_ms REAL,
  p95_latency_ms REAL,
  p99_latency_ms REAL,
  throughput_segments_per_second REAL
);

CREATE TABLE IF NOT EXISTS evaluations (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  basename TEXT,
  candidate_path TEXT,
  reference_path TEXT,
  cer REAL,
  wer REAL,
  keyword_recall REAL,
  subtitle_items INTEGER,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
"""


def connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(db_path: Path) -> None:
    with connect(db_path) as conn:
        conn.executescript(SCHEMA)


def to_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def to_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def insert_segment(db_path: Path, transcript: dict[str, Any]) -> None:
    with connect(db_path) as conn:
        conn.execute(
            """
            INSERT OR IGNORE INTO segments (
              stream_id, run_id, segment_id, start_time_ms, end_time_ms,
              text, status, retry_count, end_to_end_time_ms, asr_inference_time_ms
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(transcript.get("stream_id", "unknown")),
                str(transcript.get("run_id", "")),
                str(transcript.get("segment_id", "")),
                to_int(transcript.get("start_time_ms")),
                to_int(transcript.get("end_time_ms")),
                str(transcript.get("text", "")),
                str(transcript.get("status", "ok")),
                to_int(transcript.get("retry_count")),
                to_int(transcript.get("end_to_end_time_ms")),
                to_int(transcript.get("asr_inference_time_ms", transcript.get("inference_time_ms"))),
            ),
        )


def segment_values(transcript: dict[str, Any]) -> tuple[Any, ...]:
    return (
        str(transcript.get("stream_id", "unknown")),
        str(transcript.get("run_id", "")),
        str(transcript.get("segment_id", "")),
        to_int(transcript.get("start_time_ms")),
        to_int(transcript.get("end_time_ms")),
        str(transcript.get("text", "")),
        str(transcript.get("status", "ok")),
        to_int(transcript.get("retry_count")),
        to_int(transcript.get("end_to_end_time_ms")),
        to_int(transcript.get("asr_inference_time_ms", transcript.get("inference_time_ms"))),
    )


def insert_segments_many(db_path: Path, transcripts: list[dict[str, Any]]) -> None:
    if not transcripts:
        return
    with connect(db_path) as conn:
        conn.executemany(
            """
            INSERT OR IGNORE INTO segments (
              stream_id, run_id, segment_id, start_time_ms, end_time_ms,
              text, status, retry_count, end_to_end_time_ms, asr_inference_time_ms
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [segment_values(item) for item in transcripts],
        )


def insert_failed_segment(db_path: Path, item: dict[str, Any]) -> None:
    with connect(db_path) as conn:
        conn.execute(
            """
            INSERT OR IGNORE INTO failed_segments (
              stream_id, run_id, segment_id, error, retry_count, created_at_ms
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                str(item.get("stream_id", "")),
                str(item.get("run_id", "")),
                str(item.get("segment_id", "")),
                str(item.get("error", ""))[:1000],
                to_int(item.get("retry_count")),
                to_int(item.get("created_at_ms")),
            ),
        )


def failed_segment_values(item: dict[str, Any]) -> tuple[Any, ...]:
    return (
        str(item.get("stream_id", "")),
        str(item.get("run_id", "")),
        str(item.get("segment_id", "")),
        str(item.get("error", ""))[:1000],
        to_int(item.get("retry_count")),
        to_int(item.get("created_at_ms")),
    )


def insert_failed_segments_many(db_path: Path, items: list[dict[str, Any]]) -> None:
    if not items:
        return
    with connect(db_path) as conn:
        conn.executemany(
            """
            INSERT OR IGNORE INTO failed_segments (
              stream_id, run_id, segment_id, error, retry_count, created_at_ms
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            [failed_segment_values(item) for item in items],
        )


def insert_metrics_sample(db_path: Path, metrics: dict[str, Any]) -> None:
    with connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO metrics_samples (
              sampled_at_ms, stream_id, total_segments, success_segments,
              failed_segments, average_end_to_end_latency_ms, p95_latency_ms,
              p99_latency_ms, throughput_segments_per_second
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                to_int(metrics.get("sampled_at_ms")),
                str(metrics.get("stream_id", "")),
                to_int(metrics.get("total_segments")),
                to_int(metrics.get("success_segments")),
                to_int(metrics.get("failed_segments")),
                to_float(metrics.get("average_end_to_end_latency_ms")),
                to_float(metrics.get("p95_latency_ms")),
                to_float(metrics.get("p99_latency_ms")),
                to_float(metrics.get("throughput_segments_per_second")),
            ),
        )


def summary(db_path: Path, stream_id: str = "") -> list[dict[str, Any]]:
    if not db_path.exists():
        return []
    where = "WHERE stream_id = ?" if stream_id else ""
    params = (stream_id,) if stream_id else ()
    query = f"""
      SELECT
        stream_id,
        COUNT(*) AS segments,
        AVG(end_to_end_time_ms) AS avg_latency_ms,
        AVG(asr_inference_time_ms) AS avg_asr_ms,
        MAX(retry_count) AS max_retry_count
      FROM segments
      {where}
      GROUP BY stream_id
      ORDER BY segments DESC
    """
    with connect(db_path) as conn:
        return [dict(row) for row in conn.execute(query, params).fetchall()]
