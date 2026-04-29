import argparse
import json
import os
import subprocess
import time
from pathlib import Path


def run_command(command: list[str], env: dict[str, str] | None = None, timeout: int = 3600) -> subprocess.CompletedProcess:
    return subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env={**os.environ, **(env or {})},
        timeout=timeout,
    )


def load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


def write_markdown(path: Path, rows: list[dict]) -> None:
    lines = [
        "# StreamSense 模型与并发对比实验",
        "",
        "| 模型 | 计算类型 | 并发路数 | 状态 | 成功片段 | 失败片段 | 平均延迟(ms) | P95(ms) | 吞吐(片段/s) | 结论 |",
        "| --- | --- | ---: | --- | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for row in rows:
        report = row.get("report", {})
        latency = report.get("latency_ms", {}) if isinstance(report, dict) else {}
        conclusion = "质量优先" if row["model"] == "large-v3" else "实时演示优先" if row["model"] in {"small", "base"} else "平衡方案"
        lines.append(
            "| {model} | {compute_type} | {streams} | {status} | {success} | {failed} | {avg} | {p95} | {throughput} | {conclusion} |".format(
                model=row["model"],
                compute_type=row["compute_type"],
                streams=row["streams"],
                status=row["status"],
                success=report.get("success_segments", 0) if isinstance(report, dict) else 0,
                failed=report.get("failed_segments", 0) if isinstance(report, dict) else 0,
                avg=latency.get("average", 0),
                p95=latency.get("p95", 0),
                throughput=report.get("throughput_segments_per_second", 0) if isinstance(report, dict) else 0,
                conclusion=conclusion,
            )
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run StreamSense model/concurrency ablation experiments.")
    parser.add_argument("--models", nargs="+", default=["small", "medium", "large-v3"])
    parser.add_argument("--compute-types", nargs="+", default=["int8_float16", "float16"])
    parser.add_argument("--streams", nargs="+", type=int, default=[1, 2])
    parser.add_argument("--video-source", default="/videos/input.mp4")
    parser.add_argument("--output-dir", default="data/results/model_ablation")
    parser.add_argument("--timeout", type=int, default=3600)
    parser.add_argument("--dry-run", action="store_true", help="只生成计划，不真正重启服务或压测。")
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    rows: list[dict] = []

    for model in args.models:
        for compute_type in args.compute_types:
            for stream_count in args.streams:
                row = {
                    "model": model,
                    "compute_type": compute_type,
                    "streams": stream_count,
                    "video_source": args.video_source,
                    "status": "planned" if args.dry_run else "running",
                    "started_at_ms": int(time.time() * 1000),
                }
                rows.append(row)
                print(f"[ablation] model={model}, compute={compute_type}, streams={stream_count}", flush=True)

                if args.dry_run:
                    continue

                env = {
                    "ASR_MODEL": model,
                    "ASR_COMPUTE_TYPE": compute_type,
                }
                restart = run_command(["docker", "compose", "up", "-d", "--build", "asr", "flink-job-submitter"], env=env, timeout=args.timeout)
                row["restart_returncode"] = restart.returncode
                row["restart_tail"] = (restart.stdout + restart.stderr)[-4000:]
                if restart.returncode != 0:
                    row["status"] = "restart_failed"
                    continue

                time.sleep(8)
                bench = run_command(
                    [
                        "python",
                        "tools/benchmark_streamsense.py",
                        "--streams",
                        str(stream_count),
                        "--video-source",
                        args.video_source,
                        "--output-dir",
                        str(output_dir / f"{model}_{compute_type}_{stream_count}streams"),
                    ],
                    env=env,
                    timeout=args.timeout,
                )
                row["benchmark_returncode"] = bench.returncode
                row["benchmark_stdout_tail"] = bench.stdout[-4000:]
                row["benchmark_stderr_tail"] = bench.stderr[-4000:]
                report_path = output_dir / f"{model}_{compute_type}_{stream_count}streams" / f"benchmark_report_{stream_count}streams.json"
                if not report_path.exists():
                    report_path = output_dir / f"{model}_{compute_type}_{stream_count}streams" / "benchmark_report.json"
                row["report_path"] = str(report_path)
                row["report"] = load_json(report_path)
                row["status"] = "ok" if bench.returncode == 0 and row["report"] else "needs_review"
                row["finished_at_ms"] = int(time.time() * 1000)

    summary = {"status": "ok", "dry_run": args.dry_run, "experiments": rows}
    (output_dir / "model_ablation_report.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    write_markdown(output_dir / "model_ablation_report.md", rows)
    print(f"report_json: {output_dir / 'model_ablation_report.json'}")
    print(f"report_md: {output_dir / 'model_ablation_report.md'}")


if __name__ == "__main__":
    main()
