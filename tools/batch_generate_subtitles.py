import argparse
import json
import subprocess
import sys
import time
from pathlib import Path


VIDEO_EXTENSIONS = {".mp4", ".mkv", ".avi", ".mov", ".flv", ".webm"}


def find_video_files() -> list[Path]:
    """查找项目根目录和 videos 目录下的视频样本。"""
    candidates: list[Path] = []
    root = Path.cwd()
    search_dirs = [root, root / "videos"]

    for folder in search_dirs:
        if not folder.exists():
            continue
        for path in folder.iterdir():
            if path.is_file() and path.suffix.lower() in VIDEO_EXTENSIONS:
                candidates.append(path.resolve())

    seen: set[Path] = set()
    unique = []
    for path in sorted(candidates, key=lambda item: item.name.lower()):
        if path in seen:
            continue
        seen.add(path)
        unique.append(path)
    return unique


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def save_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def write_markdown(path: Path, rows: list[dict]) -> None:
    lines = [
        "# StreamSense 批量字幕验收报告",
        "",
        "| 视频 | 状态 | 时长(s) | 耗时(s) | 耗时/视频 | 字幕条数 | 补漏前缺口 | 补漏后缺口 |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in rows:
        lines.append(
            "| {video} | {status} | {duration:.1f} | {elapsed:.1f} | {ratio} | {items} | {before} | {after} |".format(
                video=row["video"],
                status=row["status"],
                duration=row.get("duration_ms", 0) / 1000,
                elapsed=row.get("elapsed_ms", 0) / 1000,
                ratio=row.get("speed_ratio_elapsed_over_media", ""),
                items=row.get("subtitle_items", 0),
                before=row.get("gaps_before", 0),
                after=row.get("gaps_after", 0),
            )
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run_one_video(video_path: Path, args: argparse.Namespace) -> dict:
    """运行单个视频字幕生成，并读取对应 report。"""
    output_dir = Path(args.output_dir) / video_path.stem
    output_dir.mkdir(parents=True, exist_ok=True)

    command = [
        sys.executable,
        "tools/generate_video_subtitles.py",
        "--mode",
        "full",
        "--media-path",
        str(video_path),
        "--output-dir",
        str(output_dir),
        "--basename",
        video_path.stem,
        "--passes",
        str(args.passes),
        "--coverage-max-gap-ms",
        str(args.coverage_max_gap_ms),
        "--recovery-limit",
        str(args.recovery_limit),
    ]
    if args.use_static_hints:
        command.append("--use-static-hints")

    started_at = time.time()
    completed = subprocess.run(command, capture_output=True, text=True)
    finished_at = time.time()

    report_path = output_dir / f"{video_path.stem}_report.json"
    row = {
        "video": video_path.name,
        "video_path": str(video_path),
        "output_dir": str(output_dir),
        "command": command,
        "process_returncode": completed.returncode,
        "process_elapsed_ms": int((finished_at - started_at) * 1000),
        "stdout": completed.stdout,
        "stderr": completed.stderr,
    }

    if completed.returncode != 0:
        row.update(
            {
                "status": "failed",
                "duration_ms": 0,
                "elapsed_ms": row["process_elapsed_ms"],
                "speed_ratio_elapsed_over_media": None,
                "subtitle_items": 0,
                "gaps_before": 0,
                "gaps_after": 0,
            }
        )
        return row

    report = load_json(report_path)
    gaps_before = len(report.get("uncovered_gaps_before_recovery", []))
    gaps_after = len(report.get("blocking_uncovered_gaps_after_recovery", report.get("uncovered_gaps_after_recovery", [])))
    speed_ratio = report.get("speed_ratio_elapsed_over_media")
    speed_ok = speed_ratio is not None and float(speed_ratio) <= args.max_speed_ratio
    coverage_ok = gaps_after == 0

    row.update(
        {
            "status": "ok" if speed_ok and coverage_ok else "needs_review",
            "duration_ms": int(report.get("duration_ms", 0)),
            "elapsed_ms": int(report.get("elapsed_ms", row["process_elapsed_ms"])),
            "speed_ratio_elapsed_over_media": speed_ratio,
            "subtitle_items": int(report.get("subtitle_items", 0)),
            "gaps_before": gaps_before,
            "gaps_after": gaps_after,
            "ignored_gaps_after": len(report.get("ignored_uncovered_gaps_after_recovery", [])),
            "srt": str(output_dir / f"{video_path.stem}.srt"),
            "vtt": str(output_dir / f"{video_path.stem}.vtt"),
            "text": str(output_dir / f"{video_path.stem}_subtitle.txt"),
            "report": str(report_path),
        }
    )
    return row


def main() -> None:
    parser = argparse.ArgumentParser(description="Batch-generate subtitles and validation reports for all project videos.")
    parser.add_argument("--output-dir", default="data/results/batch")
    parser.add_argument("--passes", type=int, choices=[1, 2], default=1)
    parser.add_argument("--coverage-max-gap-ms", type=int, default=1200)
    parser.add_argument("--recovery-limit", type=int, default=60)
    parser.add_argument("--max-speed-ratio", type=float, default=0.5, help="0.5 表示 10 分钟视频最多 5 分钟跑完。")
    parser.add_argument("--use-static-hints", action="store_true")
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()

    videos = find_video_files()
    if args.limit > 0:
        videos = videos[: args.limit]
    if not videos:
        raise SystemExit("没有找到可测试的视频文件。")

    rows = []
    for index, video in enumerate(videos, start=1):
        print(f"[{index}/{len(videos)}] generating subtitles for {video.name}", flush=True)
        rows.append(run_one_video(video, args))

    output_dir = Path(args.output_dir)
    save_json(output_dir / "batch_report.json", {"videos": rows})
    write_markdown(output_dir / "batch_report.md", rows)

    failed = [row for row in rows if row["status"] != "ok"]
    print(f"videos: {len(rows)}")
    print(f"ok: {len(rows) - len(failed)}")
    print(f"needs_review_or_failed: {len(failed)}")
    print(f"report_json: {output_dir / 'batch_report.json'}")
    print(f"report_md: {output_dir / 'batch_report.md'}")

    if failed:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
