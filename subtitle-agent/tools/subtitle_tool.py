from __future__ import annotations

import shutil
import subprocess
import sys
import time
from pathlib import Path
from urllib import request


VIDEO_SUFFIXES = {".mp4", ".mkv", ".avi", ".mov", ".flv", ".webm"}


def prepare_video(project_root: Path, video_path: Path, task_id: str) -> Path:
    video_path = video_path.resolve()
    if not video_path.exists():
        raise FileNotFoundError(f"视频文件不存在: {video_path}")
    try:
        video_path.relative_to(project_root)
        return video_path
    except ValueError:
        pass

    if video_path.suffix.lower() not in VIDEO_SUFFIXES:
        raise ValueError(f"不支持的视频格式: {video_path.suffix}")
    target = project_root / "videos" / f"{task_id}{video_path.suffix.lower()}"
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(video_path, target)
    return target


def http_ok(url: str, timeout: float = 2.0) -> bool:
    try:
        with request.urlopen(url, timeout=timeout) as response:
            return 200 <= response.status < 300
    except Exception:
        return False


def ensure_backend_ready(project_root: Path, log=None, wait_seconds: int = 240) -> None:
    """确保原 StreamSense API/ASR 后端可用。

    离线字幕脚本实际调用 localhost:8001 的 ASR 服务和 localhost:8000 的 API。
    如果用户直接运行 Agent 而没有先启动后端，这里会自动尝试 docker compose up。
    """

    def emit(message: str) -> None:
        if log:
            log(message)

    api_health = "http://localhost:8000/health"
    asr_health = "http://localhost:8001/health"
    if http_ok(api_health) and http_ok(asr_health):
        emit("后端预检通过：API/ASR 已在线")
        return

    emit("后端预检：API/ASR 未就绪，尝试启动 docker compose 服务")
    startup = subprocess.run(
        ["docker", "compose", "up", "-d", "--build"],
        cwd=project_root,
        capture_output=True,
        text=True,
    )
    if startup.returncode != 0:
        detail = (startup.stderr or startup.stdout or "").strip()
        raise RuntimeError(
            "无法自动启动 StreamSense 后端。请确认 Docker Desktop 已启动。\n"
            f"docker compose 输出:\n{detail[-2000:]}"
        )

    deadline = time.time() + wait_seconds
    last_state = ""
    while time.time() < deadline:
        api_ok = http_ok(api_health)
        asr_ok = http_ok(asr_health)
        state = f"API={'ok' if api_ok else 'wait'} ASR={'ok' if asr_ok else 'wait'}"
        if state != last_state:
            emit(f"等待后端就绪：{state}")
            last_state = state
        if api_ok and asr_ok:
            emit("后端启动完成：API/ASR 已在线")
            return
        time.sleep(4)

    raise RuntimeError(
        "等待 StreamSense 后端超时。请检查：\n"
        "1. Docker Desktop 是否正常运行；\n"
        "2. docker compose ps 里 asr/api 是否为 Up；\n"
        "3. http://localhost:8001/health 是否可访问。"
    )


def run_subtitle_generation(
    project_root: Path,
    video_path: Path,
    task_dir: Path,
    task_id: str,
    profile: str,
    passes: int,
) -> subprocess.CompletedProcess[str]:
    media_path = str(video_path.relative_to(project_root))
    command = [
        sys.executable,
        "tools/generate_video_subtitles.py",
        "--mode",
        "full",
        "--media-path",
        media_path,
        "--output-dir",
        str(task_dir),
        "--basename",
        task_id,
        "--passes",
        str(max(1, min(passes, 2))),
    ]
    if profile:
        command.extend(["--profile", profile, "--use-static-hints"])
    return subprocess.run(command, cwd=project_root, capture_output=True, text=True)
