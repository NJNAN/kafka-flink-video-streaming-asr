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


def sample_transcript_text(items: list[dict], max_chars: int = 14000) -> str:
    parts: list[str] = []
    used = 0
    for index, item in enumerate(items, start=1):
        text = f"{index}. {item.get('text', '')}\n"
        if used + len(text) > max_chars:
            break
        parts.append(text)
        used += len(text)
    return "".join(parts)


def infer_video_glossary(llm: LlmClient, items: list[dict], rag_hits: list[dict], goal: str) -> dict:
    """让大模型先归纳本视频的动态术语表和可疑错词。

    这一步不是静态词典，而是让 AI 从当前视频全文、RAG 资料和上下文里自己判断：
    哪些词应该统一，哪些 ASR 词看起来像误识别。
    """

    system = (
        "你是离线视频字幕 Agent 的术语归纳器。"
        "你需要从当前视频字幕样本和 RAG 资料中，归纳本视频的动态术语表。"
        "重点识别：网络梗、口语词、专有名词、同音误识别、反复出现但不自然的词。"
        "不要照抄静态词表；必须结合当前视频上下文判断。"
        "输出 JSON："
        "{"
        "\"canonical_terms\":[{\"term\":\"正确词\",\"meaning\":\"含义\",\"evidence\":\"证据\"}],"
        "\"suspect_variants\":[{\"variant\":\"字幕中疑似错词\",\"canonical\":\"建议正确词\",\"reason\":\"理由\",\"confidence\":0.0}],"
        "\"style_notes\":[\"本视频字幕风格注意事项\"]"
        "}"
    )
    payload = {
        "goal": goal,
        "rag_context": compact_hits(rag_hits, max_chars=5000),
        "transcript_sample": sample_transcript_text(items),
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
        return parse_json_object(response.text)
    except Exception as exc:
        return {
            "canonical_terms": [],
            "suspect_variants": [],
            "style_notes": [],
            "error": str(exc),
        }
