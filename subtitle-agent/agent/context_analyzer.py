from __future__ import annotations

import json
import re

from llm_client import LlmClient
from rag_store import compact_hits


def parse_json_object(text: str) -> dict:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`").strip()
        cleaned = re.sub(r"^json\s*", "", cleaned, flags=re.IGNORECASE).strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start >= 0 and end > start:
            return json.loads(cleaned[start : end + 1])
        raise


def transcript_sample(items: list[dict], max_chars: int = 18000) -> str:
    parts: list[str] = []
    used = 0
    for index, item in enumerate(items, start=1):
        line = f"{index}. {item.get('text', '')}\n"
        if used + len(line) > max_chars:
            break
        parts.append(line)
        used += len(line)
    return "".join(parts)


def analyze_video_context(llm: LlmClient, items: list[dict], rag_hits: list[dict], goal: str, profile: str) -> dict:
    """Build a full-video subtitle editing brief before segment-level correction."""

    system = (
        "你是专业字幕总审校 Agent。"
        "你要先理解整段视频的主题、口吻、领域词、反复出现的专名和 ASR 易错点。"
        "你的输出会被后续逐段纠错、术语一致性和字幕排版 Agent 使用。"
        "不要写空泛建议，要给当前视频可执行的规则。"
        "输出 JSON："
        "{"
        "\"video_topic\":\"视频主题\","
        "\"tone\":\"口吻风格\","
        "\"audience\":\"受众\","
        "\"must_keep_style\":[\"必须保留的口语/表达风格\"],"
        "\"likely_terms\":[{\"term\":\"正确词\",\"why\":\"依据\"}],"
        "\"asr_risks\":[{\"wrong_pattern\":\"可能错词\",\"preferred\":\"建议正确词\",\"reason\":\"理由\"}],"
        "\"subtitle_policy\":{\"max_chars_per_line\":20,\"max_lines\":2,\"reading_speed_cps\":13},"
        "\"global_rules\":[\"后续审校必须遵守的具体规则\"]"
        "}"
    )
    payload = {
        "goal": goal,
        "profile": profile,
        "rag_context": compact_hits(rag_hits, max_chars=5200),
        "transcript_sample": transcript_sample(items),
    }
    try:
        response = llm.chat(
            [
                {"role": "system", "content": system},
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
            ],
            temperature=0.05,
            timeout=240,
        )
        data = parse_json_object(response.text)
    except Exception as exc:
        data = {
            "video_topic": "",
            "tone": "",
            "audience": "",
            "must_keep_style": [],
            "likely_terms": [],
            "asr_risks": [],
            "subtitle_policy": {"max_chars_per_line": 20, "max_lines": 2, "reading_speed_cps": 13},
            "global_rules": [],
            "error": str(exc),
        }
    data.setdefault("subtitle_policy", {"max_chars_per_line": 20, "max_lines": 2, "reading_speed_cps": 13})
    data.setdefault("global_rules", [])
    return data
