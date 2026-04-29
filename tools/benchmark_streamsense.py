import argparse
import json
import re
import statistics
import subprocess
import time
from pathlib import Path
from urllib import error, request


def now_ms() -> int:
    return int(time.time() * 1000)


def http_json(url: str, timeout: int = 10) -> dict:
    req = request.Request(url)
    try:
        with request.urlopen(req, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except (error.URLError, error.HTTPError, TimeoutError) as exc:
        return {"status": "error", "error": str(exc)}


def percentile(values: list[float], percent: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = int(round((len(ordered) - 1) * percent))
    return float(ordered[max(0, min(index, len(ordered) - 1))])


def number(value: object, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def run_command(command: list[str], timeout: int = 30) -> subprocess.CompletedProcess:
    return subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )


def wait_for_api(api_url: str, timeout_seconds: int) -> None:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        data = http_json(f"{api_url.rstrip('/')}/health", timeout=5)
        if data.get("status") == "ok":
            return
        time.sleep(2)
    raise SystemExit(f"API not ready: {api_url}")


def stream_ids(prefix: str, count: int) -> list[str]:
    stamp = time.strftime("%Y%m%d%H%M%S")
    return [f"{prefix}-{stamp}-{index + 1}" for index in range(count)]


def container_name_for_stream(stream_id: str) -> str:
    safe = re.sub(r"[^a-zA-Z0-9_.-]+", "-", stream_id).strip("-").lower()
    return f"streamsense-benchmark-{safe[:80]}"


def start_ingest(stream_id: str, video_source: str) -> subprocess.Popen:
    container_name = container_name_for_stream(stream_id)
    run_command(["docker", "rm", "-f", container_name], timeout=20)
    command = [
        "docker",
        "compose",
        "run",
        "--rm",
        "--no-deps",
        "--name",
        container_name,
        "-e",
        f"STREAM_ID={stream_id}",
        "-e",
        f"VIDEO_SOURCE={video_source}",
        "ingest",
    ]
    process = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, text=True)
    setattr(process, "container_name", container_name)
    return process


def wait_for_processes(processes: list[subprocess.Popen], timeout_seconds: int) -> dict[str, object]:
    deadline = time.time() + timeout_seconds
    logs: dict[str, str] = {}
    while time.time() < deadline:
        if all(process.poll() is not None for process in processes):
            break
        time.sleep(2)

    for index, process in enumerate(processes):
        container_name = getattr(process, "container_name", "")
        if process.poll() is None:
            if container_name:
                run_command(["docker", "logs", "--tail", "200", container_name], timeout=20)
                run_command(["docker", "stop", container_name], timeout=30)
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
        output = ""
        if container_name:
            log_result = run_command(["docker", "logs", "--tail", "200", container_name], timeout=20)
            output = (log_result.stdout or log_result.stderr or "")[-4000:]
            run_command(["docker", "rm", "-f", container_name], timeout=20)
        logs[f"ingest_{index + 1}"] = output[-4000:]

    return {
        "return_codes": [process.returncode for process in processes],
        "logs": logs,
    }


def wait_until_segments_stable(api_url: str, streams: list[str], min_segments: int, timeout_seconds: int) -> None:
    deadline = time.time() + timeout_seconds
    last_total = -1
    stable_rounds = 0
    while time.time() < deadline:
        total = 0
        for stream_id in streams:
            data = http_json(f"{api_url.rstrip('/')}/api/streams/{stream_id}/segments?limit=2000", timeout=10)
            if isinstance(data, list):
                total += len(data)
        if total >= min_segments and total == last_total:
            stable_rounds += 1
            if stable_rounds >= 3:
                return
        else:
            stable_rounds = 0
        last_total = total
        time.sleep(3)


def kafka_lag() -> dict[str, object]:
    command = [
        "docker",
        "exec",
        "streamsense-kafka",
        "kafka-consumer-groups",
        "--bootstrap-server",
        "localhost:9092",
        "--describe",
        "--all-groups",
    ]
    result = run_command(command, timeout=30)
    lags: list[int] = []
    for line in result.stdout.splitlines():
        parts = line.split()
        if len(parts) >= 6 and parts[5].isdigit():
            lags.append(int(parts[5]))
    return {
        "status": "ok" if result.returncode == 0 else "error",
        "total_lag": sum(lags),
        "max_lag": max(lags) if lags else 0,
        "raw_tail": result.stdout[-4000:] if result.stdout else result.stderr[-4000:],
    }


def collect_stream_segments(api_url: str, streams: list[str]) -> list[dict]:
    rows: list[dict] = []
    for stream_id in streams:
        data = http_json(f"{api_url.rstrip('/')}/api/streams/{stream_id}/segments?limit=2000", timeout=20)
        if isinstance(data, list):
            rows.extend(data)
    return rows


def build_report(api_url: str, streams: list[str], started_at: int, finished_at: int, process_info: dict) -> dict:
    segments = collect_stream_segments(api_url, streams)
    metrics = http_json(f"{api_url.rstrip('/')}/api/metrics", timeout=20)
    stream_metrics = {
        stream_id: http_json(f"{api_url.rstrip('/')}/api/metrics?stream_id={stream_id}", timeout=20)
        for stream_id in streams
    }
    fallback_success = sum(int(number(item.get("success_segments", 0))) for item in stream_metrics.values())
    end_to_end = [number(item.get("end_to_end_time_ms")) for item in segments if number(item.get("end_to_end_time_ms")) > 0]
    asr = [
        number(item.get("asr_inference_time_ms", item.get("inference_time_ms")))
        for item in segments
        if number(item.get("asr_inference_time_ms", item.get("inference_time_ms"))) > 0
    ]
    dispatch = [number(item.get("kafka_flink_dispatch_time_ms")) for item in segments if number(item.get("kafka_flink_dispatch_time_ms")) > 0]
    api_cost = [number(item.get("api_aggregation_time_ms")) for item in segments if number(item.get("api_aggregation_time_ms")) > 0]
    redis_cost = [number(item.get("redis_write_time_ms")) for item in segments if number(item.get("redis_write_time_ms")) > 0]
    wall_seconds = max((finished_at - started_at) / 1000, 0.001)
    failed = number(metrics.get("failed_segments", 0))
    success_segments = len(segments) if segments else fallback_success
    return {
        "status": "ok",
        "started_at": started_at,
        "finished_at": finished_at,
        "stream_count": len(streams),
        "stream_ids": streams,
        "success_segments": success_segments,
        "failed_segments": int(failed),
        "throughput_segments_per_second": round(success_segments / wall_seconds, 3),
        "latency_ms": {
            "average": round(statistics.mean(end_to_end), 2) if end_to_end else 0,
            "p50": round(percentile(end_to_end, 0.50), 2),
            "p95": round(percentile(end_to_end, 0.95), 2),
            "p99": round(percentile(end_to_end, 0.99), 2),
        },
        "asr_inference_ms": {
            "average": round(statistics.mean(asr), 2) if asr else 0,
            "p95": round(percentile(asr, 0.95), 2),
        },
        "kafka_flink_dispatch_ms": {
            "average": round(statistics.mean(dispatch), 2) if dispatch else 0,
            "p95": round(percentile(dispatch, 0.95), 2),
        },
        "api_aggregation_ms": {
            "average": round(statistics.mean(api_cost), 2) if api_cost else 0,
            "p95": round(percentile(api_cost, 0.95), 2),
        },
        "redis_write_ms": {
            "average": round(statistics.mean(redis_cost), 2) if redis_cost else 0,
            "p95": round(percentile(redis_cost, 0.95), 2),
        },
        "kafka_lag": kafka_lag(),
        "api_metrics": metrics,
        "stream_metrics": stream_metrics,
        "ingest_processes": process_info,
    }


def write_markdown(path: Path, report: dict) -> None:
    latency = report["latency_ms"]
    lines = [
        "# StreamSense Benchmark Report",
        "",
        f"- streams: {report['stream_count']}",
        f"- stream_ids: {', '.join(report['stream_ids'])}",
        f"- success_segments: {report['success_segments']}",
        f"- failed_segments: {report['failed_segments']}",
        f"- throughput_segments_per_second: {report['throughput_segments_per_second']}",
        "",
        "## Latency",
        "",
        f"- end_to_end_average_ms: {latency['average']}",
        f"- end_to_end_p50_ms: {latency['p50']}",
        f"- end_to_end_p95_ms: {latency['p95']}",
        f"- end_to_end_p99_ms: {latency['p99']}",
        f"- asr_average_ms: {report['asr_inference_ms']['average']}",
        f"- kafka_flink_average_dispatch_ms: {report['kafka_flink_dispatch_ms']['average']}",
        f"- api_average_aggregation_ms: {report['api_aggregation_ms']['average']}",
        f"- redis_average_write_ms: {report['redis_write_ms']['average']}",
        "",
        "## Kafka Lag",
        "",
        f"- total_lag: {report['kafka_lag'].get('total_lag', 0)}",
        f"- max_lag: {report['kafka_lag'].get('max_lag', 0)}",
        "",
        "## Streams",
        "",
    ]
    for stream_id, metrics in report["stream_metrics"].items():
        lines.extend(
            [
                f"### {stream_id}",
                "",
                f"- total_segments: {metrics.get('total_segments', 0)}",
                f"- average_end_to_end_latency_ms: {metrics.get('average_end_to_end_latency_ms', 0)}",
                f"- p95_latency_ms: {metrics.get('p95_latency_ms', 0)}",
                f"- p99_latency_ms: {metrics.get('p99_latency_ms', 0)}",
                "",
            ]
        )
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run StreamSense single/multi-stream benchmark.")
    parser.add_argument("--streams", type=int, nargs="+", default=[1], help="Run stream counts, for example: --streams 1 2 4")
    parser.add_argument("--video-source", default="/videos/input.mp4", help="Container-visible source, default reuses videos/input.mp4.")
    parser.add_argument("--api-url", default="http://localhost:8000")
    parser.add_argument("--stream-prefix", default="bench")
    parser.add_argument("--output-dir", default="data/results/benchmark")
    parser.add_argument("--api-timeout-seconds", type=int, default=180)
    parser.add_argument("--ingest-timeout-seconds", type=int, default=900)
    parser.add_argument("--settle-timeout-seconds", type=int, default=180)
    args = parser.parse_args()

    wait_for_api(args.api_url, args.api_timeout_seconds)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    all_reports = []

    for count in args.streams:
        streams = stream_ids(args.stream_prefix, count)
        print(f"[benchmark] starting {count} stream(s): {', '.join(streams)}")
        started_at = now_ms()
        processes = [start_ingest(stream_id, args.video_source) for stream_id in streams]
        process_info = wait_for_processes(processes, args.ingest_timeout_seconds)
        wait_until_segments_stable(args.api_url, streams, min_segments=count, timeout_seconds=args.settle_timeout_seconds)
        finished_at = now_ms()
        report = build_report(args.api_url, streams, started_at, finished_at, process_info)
        report["benchmark_name"] = f"{count}_streams"
        all_reports.append(report)

        json_path = output_dir / f"benchmark_report_{count}streams.json"
        md_path = output_dir / f"benchmark_report_{count}streams.md"
        json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        write_markdown(md_path, report)
        print(f"[benchmark] wrote {json_path}")
        print(f"[benchmark] wrote {md_path}")

    if len(all_reports) == 1:
        final_report = all_reports[0]
    else:
        final_report = {"status": "ok", "runs": all_reports}
    (output_dir / "benchmark_report.json").write_text(json.dumps(final_report, ensure_ascii=False, indent=2), encoding="utf-8")
    if all_reports:
        write_markdown(output_dir / "benchmark_report.md", all_reports[-1])
    print(f"[benchmark] final json: {output_dir / 'benchmark_report.json'}")
    print(f"[benchmark] final md: {output_dir / 'benchmark_report.md'}")


if __name__ == "__main__":
    main()
