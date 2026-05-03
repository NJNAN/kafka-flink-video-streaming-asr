from __future__ import annotations

import json
import re

from llm_client import LlmClient


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


def safe_float(value: object, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def apply_semantic_edits(items: list[dict], edits: list[dict]) -> tuple[list[dict], list[dict]]:
    updated = [dict(item) for item in items]
    applied: list[dict] = []
    for edit in edits:
        try:
            index = int(edit.get("index", 0))
        except (TypeError, ValueError):
            continue
        if index < 1 or index > len(updated):
            continue
        text = str(edit.get("text", "")).strip()
        confidence = safe_float(edit.get("confidence"), 0.0)
        if not text or confidence < 0.62:
            continue
        original = str(updated[index - 1].get("text", ""))
        if text == original:
            continue
        if len(text) > max(80, len(original) * 2 + 20):
            continue
        updated[index - 1]["text"] = text
        applied.append(
            {
                "index": index,
                "original_text": original,
                "revised_text": text,
                "reason": edit.get("reason", "semantic subtitle edit"),
                "confidence": confidence,
            }
        )
    return updated, applied


def semantic_polish_subtitles(
    llm: LlmClient,
    items: list[dict],
    context_brief: dict,
    goal: str,
    batch_size: int = 14,
    log=None,
) -> tuple[list[dict], dict]:
    """Conservative subtitle-editor wording pass inside existing segments."""

    updated = [dict(item) for item in items]
    all_applied: list[dict] = []
    errors: list[dict] = []
    system = (
        "你是专业字幕编辑 Agent。"
        "你可以轻度优化字幕的语义断句和可读性，但不能改变含义、不能新增内容、不能删除关键信息。"
        "优先处理：ASR 断句导致的不自然表达、明显重复卡顿、太口水但影响阅读的重复词。"
        "保留原视频口语风格，不要改成书面稿。"
        "时间戳不可改。不要合并或删除条目，只返回需要改写的条目的完整文本。"
        "输出 JSON："
        "{\"edits\":[{\"index\":1,\"text\":\"优化后的完整字幕\",\"reason\":\"理由\",\"confidence\":0.0}]}"
    )
    for batch_number, batch in enumerate(chunk_items(updated, batch_size), start=1):
        if log:
            log(f"AI 语义排版批次 {batch_number}: {batch[0][0]}-{batch[-1][0]}")
        payload = {
            "goal": goal,
            "context_brief": context_brief,
            "rules": [
                "不要合并条目，不要删除条目",
                "只返回确实需要优化的条目",
                "text 必须是该条字幕的完整文本",
                "保留口语，不要扩写",
            ],
            "segments": [
                {
                    "index": index,
                    "start_ms": int(item.get("start_ms", item.get("start_time_ms", 0))),
                    "end_ms": int(item.get("end_ms", item.get("end_time_ms", 0))),
                    "text": str(item.get("text", "")),
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
                temperature=0.04,
                timeout=240,
            )
            data = parse_json_object(response.text)
            updated, applied = apply_semantic_edits(updated, data.get("edits", []))
            all_applied.extend(applied)
        except Exception as exc:
            errors.append({"batch": batch_number, "error": str(exc)})
    return updated, {"applied_edits": all_applied, "applied_count": len(all_applied), "errors": errors}
