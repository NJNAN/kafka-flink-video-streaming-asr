from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def find_project_root(start: Path | None = None) -> Path:
    current = (start or Path(__file__).resolve()).resolve()
    if current.is_file():
        current = current.parent
    for candidate in [current, *current.parents]:
        if (candidate / "docker-compose.yml").exists() and (candidate / "tools" / "generate_video_subtitles.py").exists():
            return candidate
    return Path.cwd().resolve()


def load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


@dataclass
class AgentConfig:
    project_root: Path
    agent_root: Path
    llm_api_base: str
    llm_api_key: str
    llm_model: str
    default_profile: str
    default_passes: int
    history_limit: int
    ai_batch_size: int

    @property
    def result_root(self) -> Path:
        return self.project_root / "data" / "results" / "agent_tasks"


def load_config() -> AgentConfig:
    agent_root = Path(__file__).resolve().parent
    project_root = find_project_root(agent_root)
    load_dotenv(agent_root / ".env")
    load_dotenv(project_root / ".env")

    try:
        passes = int(os.getenv("SUBTITLE_AGENT_PASSES", "1"))
    except ValueError:
        passes = 1
    try:
        history_limit = int(os.getenv("SUBTITLE_AGENT_HISTORY_LIMIT", "80"))
    except ValueError:
        history_limit = 80
    try:
        ai_batch_size = int(os.getenv("SUBTITLE_AGENT_AI_BATCH_SIZE", "18"))
    except ValueError:
        ai_batch_size = 18

    return AgentConfig(
        project_root=project_root,
        agent_root=agent_root,
        llm_api_base=os.getenv("LLM_API_BASE", "https://api.deepseek.com").rstrip("/"),
        llm_api_key=os.getenv("LLM_API_KEY", ""),
        llm_model=os.getenv("LLM_MODEL", "deepseek-v4-flash"),
        default_profile=os.getenv("SUBTITLE_AGENT_PROFILE", "bigdata"),
        default_passes=max(1, min(passes, 2)),
        history_limit=max(10, history_limit),
        ai_batch_size=max(6, min(ai_batch_size, 30)),
    )
