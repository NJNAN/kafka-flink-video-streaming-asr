import argparse
import json
import sqlite3
from pathlib import Path


def rows_to_dicts(cursor: sqlite3.Cursor) -> list[dict]:
    columns = [item[0] for item in cursor.description]
    return [dict(zip(columns, row)) for row in cursor.fetchall()]


def table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
        (table_name,),
    ).fetchone()
    return row is not None


def main() -> None:
    parser = argparse.ArgumentParser(description="Query StreamSense SQLite result database.")
    parser.add_argument("--db", default="data/results/streamsense.db")
    parser.add_argument("--summary", action="store_true")
    parser.add_argument("--stream", default="")
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    db_path = Path(args.db)
    if not db_path.exists():
        raise SystemExit(f"数据库不存在: {db_path}")

    with sqlite3.connect(db_path) as conn:
        if not table_exists(conn, "segments"):
            rows = []
            if args.json:
                print(json.dumps(rows, ensure_ascii=False, indent=2))
            else:
                print("数据库存在，但还没有 segments 表或实时字幕记录。")
            return

        if args.summary:
            where = "WHERE stream_id = ?" if args.stream else ""
            params = (args.stream,) if args.stream else ()
            cursor = conn.execute(
                f"""
                SELECT
                  stream_id,
                  COUNT(*) AS segments,
                  ROUND(AVG(end_to_end_time_ms), 2) AS avg_latency_ms,
                  ROUND(AVG(asr_inference_time_ms), 2) AS avg_asr_ms,
                  MAX(retry_count) AS max_retry_count
                FROM segments
                {where}
                GROUP BY stream_id
                ORDER BY segments DESC
                """,
                params,
            )
        else:
            where = "WHERE stream_id = ?" if args.stream else ""
            params = (args.stream, args.limit) if args.stream else (args.limit,)
            cursor = conn.execute(
                f"""
                SELECT stream_id, run_id, segment_id, start_time_ms, end_time_ms,
                       status, retry_count, end_to_end_time_ms, text
                FROM segments
                {where}
                ORDER BY id DESC
                LIMIT ?
                """,
                params,
            )
        rows = rows_to_dicts(cursor)

    if args.json:
        print(json.dumps(rows, ensure_ascii=False, indent=2))
        return

    if not rows:
        print("没有查询到结果。")
        return

    keys = list(rows[0].keys())
    print(" | ".join(keys))
    print(" | ".join("---" for _ in keys))
    for row in rows:
        print(" | ".join(str(row.get(key, ""))[:80] for key in keys))


if __name__ == "__main__":
    main()
