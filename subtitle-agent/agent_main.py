from __future__ import annotations

import argparse
from pathlib import Path

from agent.executor import run_agent
from config import load_config


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the StreamSense offline subtitle Agent.")
    parser.add_argument("--video", required=True, help="本地视频路径。")
    parser.add_argument("--profile", default="", help="领域 Profile，例如 bigdata/course/meeting/dino。")
    parser.add_argument("--goal", default="生成高质量字幕，检查专业词、漏字幕、错词和时间轴问题。")
    args = parser.parse_args()

    config = load_config()
    result = run_agent(
        config=config,
        video_path=Path(args.video),
        profile=args.profile or config.default_profile,
        goal=args.goal,
        log=lambda message: print(message, flush=True),
    )
    print("agent_task_id:", result["task_id"])
    print("task_dir:", result["task_dir"])
    print("report:", result["report"])


if __name__ == "__main__":
    main()
