from __future__ import annotations

import json

from llm_client import LlmClient
from rag_store import compact_hits


def review_subtitles(
    llm: LlmClient,
    items: list[dict],
    quality_scan: dict,
    rag_hits: list[dict],
    goal: str,
    ai_revisions: list[dict] | None = None,
) -> dict:
    sample = items[:160]
    system = (
        "你是一个字幕审校 Agent。你必须基于 RAG 证据和字幕质量报告给出建议。"
        "重点检查中文 ASR 同音错词、网络流行语、口语词、专有名词。"
        "字幕已经经过一次 AI 逐段动态改写。"
        "你现在要评估这些修改是否合理，并补充仍需人工复查的问题。"
        "不要重复机械列出已经应用的修改；重点指出仍不确定的地方。"
        "请只返回 JSON，不要写 Markdown。JSON 字段必须包含 summary、topic_keywords、"
        "term_replacements、segments_to_review、hotwords_to_add、timeline_warnings、final_advice。"
        "term_replacements 每项包含 wrong、right、reason、confidence。"
        "segments_to_review 每项包含 index、start_ms、end_ms、text、reason。"
    )
    user = {
        "goal": goal,
        "quality_scan": quality_scan,
        "ai_revisions": ai_revisions or [],
        "rag_context": compact_hits(rag_hits),
        "subtitle_sample": sample,
    }
    try:
        response = llm.chat(
            [
                {"role": "system", "content": system},
                {"role": "user", "content": json.dumps(user, ensure_ascii=False)},
            ],
            temperature=0.2,
        )
        text = response.text.strip()
        if text.startswith("```"):
            text = text.strip("`")
            text = text.replace("json\n", "", 1).strip()
        return json.loads(text)
    except Exception as exc:
        return {
            "summary": "大模型审校失败，已保留本地质量扫描结果。",
            "topic_keywords": quality_scan.get("hotwords", []),
            "term_replacements": [],
            "segments_to_review": [],
            "hotwords_to_add": [],
            "timeline_warnings": quality_scan.get("blocking_gaps", []),
            "final_advice": str(exc),
        }
