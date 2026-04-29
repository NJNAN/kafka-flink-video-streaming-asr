import argparse
import json
import subprocess
import time
from pathlib import Path
from urllib import error, request


def http_json(url: str, timeout: int = 5) -> tuple[bool, dict | list | str]:
    try:
        with request.urlopen(url, timeout=timeout) as response:
            text = response.read().decode("utf-8", errors="replace")
            try:
                return True, json.loads(text)
            except json.JSONDecodeError:
                return True, text
    except (error.URLError, error.HTTPError, TimeoutError, OSError) as exc:
        return False, str(exc)


def run_command(command: list[str], timeout: int = 20) -> tuple[bool, str]:
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
        output = (completed.stdout or completed.stderr or "").strip()
        return completed.returncode == 0, output
    except Exception as exc:
        return False, str(exc)


def add_check(rows: list[dict], name: str, ok: bool, detail: object) -> None:
    rows.append({"name": name, "status": "pass" if ok else "fail", "detail": detail})


def write_markdown(path: Path, rows: list[dict]) -> None:
    lines = [
        "# StreamSense 冒烟测试报告",
        "",
        f"- 生成时间戳：{int(time.time() * 1000)}",
        "",
        "| 检查项 | 状态 | 说明 |",
        "| --- | --- | --- |",
    ]
    for row in rows:
        detail = row["detail"]
        if isinstance(detail, (dict, list)):
            detail_text = json.dumps(detail, ensure_ascii=False)
        else:
            detail_text = str(detail)
        detail_text = detail_text.replace("|", "\\|").replace("\n", " ")[:500]
        lines.append(f"| {row['name']} | {row['status']} | {detail_text} |")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run lightweight StreamSense smoke checks.")
    parser.add_argument("--api-url", default="http://localhost:8000")
    parser.add_argument("--asr-url", default="http://localhost:8001")
    parser.add_argument("--flink-url", default="http://localhost:8081")
    parser.add_argument("--output-dir", default="data/results/smoke")
    args = parser.parse_args()

    rows: list[dict] = []
    ok, payload = http_json(f"{args.api_url.rstrip('/')}/health")
    add_check(rows, "API health", ok and isinstance(payload, dict) and payload.get("status") == "ok", payload)

    ok, payload = http_json(f"{args.asr_url.rstrip('/')}/health")
    add_check(rows, "ASR health", ok and isinstance(payload, dict) and payload.get("status") == "ok", payload)

    ok, payload = http_json(f"{args.flink_url.rstrip('/')}/jobs/overview")
    flink_running = False
    if isinstance(payload, dict):
        flink_running = any(job.get("state") == "RUNNING" for job in payload.get("jobs", []))
    add_check(rows, "Flink running job", ok and flink_running, payload)

    ok, output = run_command(["docker", "compose", "ps", "--format", "json"], timeout=30)
    required = {"kafka", "redis", "api", "asr", "flink-jobmanager", "flink-taskmanager"}
    services_seen: set[str] = set()
    if ok:
        for line in output.splitlines():
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            service = str(item.get("Service", item.get("service", "")))
            state = f"{item.get('State', '')} {item.get('Status', '')}".lower()
            if service and ("running" in state or "up" in state):
                services_seen.add(service)
    add_check(rows, "Docker compose services", ok and required.issubset(services_seen), {"seen": sorted(services_seen), "required": sorted(required)})

    ok, output = run_command(
        ["docker", "exec", "streamsense-kafka", "kafka-topics", "--bootstrap-server", "localhost:9092", "--list"],
        timeout=30,
    )
    topics = set(output.split()) if ok else set()
    required_topics = {"audio-segment", "transcription-result", "keyword-event", "streamsense.hotword.updates", "transcription-failed"}
    add_check(rows, "Kafka topics", ok and required_topics.issubset(topics), {"topics": sorted(topics), "required": sorted(required_topics)})

    ok, payload = http_json(f"{args.api_url.rstrip('/')}/api/metrics")
    add_check(rows, "API metrics", ok and isinstance(payload, dict) and payload.get("status") == "ok", payload)

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "smoke_report.json").write_text(json.dumps({"checks": rows}, ensure_ascii=False, indent=2), encoding="utf-8")
    write_markdown(output_dir / "smoke_report.md", rows)

    failed = [row for row in rows if row["status"] != "pass"]
    print(f"checks: {len(rows)}")
    print(f"passed: {len(rows) - len(failed)}")
    print(f"failed: {len(failed)}")
    print(f"report: {output_dir / 'smoke_report.md'}")
    raise SystemExit(1 if failed else 0)


if __name__ == "__main__":
    main()
