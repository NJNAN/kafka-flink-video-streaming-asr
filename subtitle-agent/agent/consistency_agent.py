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


def compact_items(items: list[dict], max_chars: int = 22000) -> str:
    parts: list[str] = []
    used = 0
    for index, item in enumerate(items, start=1):
        line = f"{index}. {item.get('text', '')}\n"
        if used + len(line) > max_chars:
            break
        parts.append(line)
        used += len(line)
    return "".join(parts)


def safe_float(value: object, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def apply_consistency_rules(items: list[dict], rules: list[dict]) -> tuple[list[dict], list[dict]]:
    updated = [dict(item) for item in items]
    applied: list[dict] = []
    for rule in rules:
        canonical = str(rule.get("canonical", "")).strip()
        variants = [str(item).strip() for item in rule.get("variants", []) if str(item).strip()]
        confidence = safe_float(rule.get("confidence"), 0.0)
        if not canonical or not variants or confidence < 0.68:
            continue
        for index, item in enumerate(updated, start=1):
            text = str(item.get("text", ""))
            revised = text
            changed_variants = []
            for variant in variants:
                if variant == canonical:
                    continue
                if variant in revised:
                    revised = revised.replace(variant, canonical)
                    changed_variants.append(variant)
            if revised != text:
                updated[index - 1]["text"] = revised
                applied.append(
                    {
                        "index": index,
                        "original_text": text,
                        "revised_text": revised,
                        "canonical": canonical,
                        "variants": changed_variants,
                        "reason": rule.get("reason", "term consistency"),
                        "confidence": confidence,
                    }
                )
    return updated, applied


def enforce_term_consistency(
    llm: LlmClient,
    items: list[dict],
    context_brief: dict,
    glossary: dict,
    goal: str,
) -> tuple[list[dict], dict]:
    """Ask the LLM for global term consistency rules, then apply high-confidence rules."""

    system = (
        "你是字幕术语一致性 Agent。"
        "你要找出同一视频里同一个词的不同写法、ASR 同音误识别、专有名词不一致。"
        "只输出高置信度、可全局统一的规则；不要为了显得有工作量而乱改。"
        "输出 JSON："
        "{\"rules\":[{\"canonical\":\"统一正确词\",\"variants\":[\"错写1\"],\"reason\":\"理由\",\"confidence\":0.0}],"
        "\"notes\":[\"说明\"]}"
    )
    payload = {
        "goal": goal,
        "context_brief": context_brief,
        "ai_glossary": glossary,
        "transcript": compact_items(items),
    }
    try:
        response = llm.chat(
            [
                {"role": "system", "content": system},
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
            ],
            temperature=0.03,
            timeout=240,
        )
        report = parse_json_object(response.text)
    except Exception as exc:
        report = {"rules": [], "notes": [], "error": str(exc)}
    rules = report.get("rules", []) if isinstance(report.get("rules", []), list) else []
    updated, applied = apply_consistency_rules(items, rules)
    report["applied_revisions"] = applied
    report["applied_count"] = len(applied)
    return updated, report
