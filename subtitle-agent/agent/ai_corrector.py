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


def chunk_items(items: list[dict], batch_size: int) -> list[list[tuple[int, dict]]]:
    indexed = list(enumerate(items, start=1))
    return [indexed[index : index + batch_size] for index in range(0, len(indexed), batch_size)]


def normalize_confidence(value: object) -> float:
    if isinstance(value, (int, float)):
        return max(0.0, min(float(value), 1.0))
    text = str(value).strip().lower()
    if text in {"高", "high", "sure"}:
        return 0.9
    if text in {"中", "medium"}:
        return 0.7
    if text in {"低", "low"}:
        return 0.45
    try:
        return max(0.0, min(float(text), 1.0))
    except ValueError:
        return 0.6


def segment_window(items: list[dict], center_index: int, radius: int = 2) -> list[dict]:
    start = max(0, center_index - radius - 1)
    end = min(len(items), center_index + radius)
    window = []
    for index, item in enumerate(items[start:end], start=start + 1):
        window.append({"index": index, "text": str(item.get("text", ""))})
    return window


def correct_segments_with_llm(
    llm: LlmClient,
    items: list[dict],
    rag_hits: list[dict],
    goal: str,
    glossary: dict | None = None,
    context_brief: dict | None = None,
    batch_size: int = 18,
    log=None,
) -> tuple[list[dict], list[dict]]:
    """让大模型逐段动态修正字幕文本。

    这一步是 Agent 的主要智能纠错能力：模型必须看上下文和 RAG 资料，自行判断 ASR 错词。
    它不依赖静态替换表直接改字幕。
    """

    corrected_items = [dict(item) for item in items]
    revisions: list[dict] = []
    rag_context = compact_hits(rag_hits, max_chars=3800)
    glossary = glossary or {}
    context_brief = context_brief or {}
    system = (
        "你是离线视频字幕 Agent 的动态审校器。"
        "你的任务是基于上下文和 RAG 资料，修正中文 ASR 字幕中的错词、同音误识别、网络流行语误识别、专有名词误识别。"
        "你必须保留原句意思和说话风格，不能润色成书面语，不能删减观点，不能凭空添加原音频没有的内容。"
        "只改明显的识别错误、错别字、专名和网络词。"
        "优先处理 ASR 常见问题：同音字、近音词、断句导致的词组错拆、口语词被识别成生僻搭配。"
        "遇到不自然词组时，要结合前后语义恢复成自然中文搭配，不能简单删掉可疑字来规避判断。"
        "例如疑似网络词、群体标签、梗名，应优先恢复为语义完整的常见说法。"
        "每条字幕都有邻近上下文，你必须先看前后句再决定是否修正。"
        "你还会收到全片 context_brief 和本视频由 AI 动态归纳出的 glossary。它们不是硬规则，但应作为当前视频语境的重要参考。"
        "如果字幕中出现 glossary.suspect_variants 里的 variant，且上下文吻合，应改成 canonical。"
        "时间戳不可更改。"
        "如果不确定，就保持原文不变，并在 reason 中说明 uncertain。"
        "输出必须是 JSON，格式为："
        "{\"revisions\":[{\"index\":1,\"text\":\"修正后的完整字幕文本\",\"reason\":\"为什么改\",\"confidence\":0.0}]}"
    )

    for batch_number, batch in enumerate(chunk_items(items, batch_size), start=1):
        if log:
            log(f"AI 动态审校批次 {batch_number}: {batch[0][0]}-{batch[-1][0]}")
        payload = {
            "goal": goal,
            "rag_context": rag_context,
            "context_brief": context_brief,
            "video_glossary": glossary,
            "rules": [
                "index 必须使用输入里的全局 index",
                "text 必须是该条字幕修正后的完整文本",
                "不要返回没有变化且没有疑点的条目",
                "不要只给替换词，要直接给整条修正后的字幕",
                "置信度 confidence 使用 0 到 1",
                "不要把口语改成书面语",
                "不要为了降低风险而删除关键词",
                "如果前后句证明某个词是口语、梗或专名，请大胆恢复为自然说法",
            ],
            "segments": [
                {
                    "index": index,
                    "start_ms": int(item.get("start_ms", item.get("start_time_ms", 0))),
                    "end_ms": int(item.get("end_ms", item.get("end_time_ms", 0))),
                    "text": str(item.get("text", "")),
                    "neighbor_context": segment_window(items, index, radius=2),
                }
                for index, item in batch
            ],
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
            revisions.append(
                {
                    "batch": batch_number,
                    "error": str(exc),
                    "source": "ai_segment_corrector",
                }
            )
            continue

        for revision in data.get("revisions", []):
            try:
                index = int(revision.get("index", 0))
            except (TypeError, ValueError):
                continue
            if index < 1 or index > len(corrected_items):
                continue
            original_text = str(corrected_items[index - 1].get("text", ""))
            revised_text = str(revision.get("text", "")).strip()
            if not revised_text or revised_text == original_text:
                continue
            confidence = normalize_confidence(revision.get("confidence", 0.6))
            if confidence < 0.45:
                revisions.append(
                    {
                        "index": index,
                        "original_text": original_text,
                        "revised_text": revised_text,
                        "reason": revision.get("reason", "low confidence"),
                        "confidence": confidence,
                        "applied": False,
                    }
                )
                continue
            corrected_items[index - 1]["text"] = revised_text
            revisions.append(
                {
                    "index": index,
                    "start_ms": int(corrected_items[index - 1].get("start_ms", 0)),
                    "end_ms": int(corrected_items[index - 1].get("end_ms", 0)),
                    "original_text": original_text,
                    "revised_text": revised_text,
                    "reason": revision.get("reason", ""),
                    "confidence": confidence,
                    "applied": True,
                    "source": "llm_dynamic_segment_revision",
                }
            )

    return corrected_items, revisions
