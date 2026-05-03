from __future__ import annotations

import json
from pathlib import Path


def write_report(path: Path, task: dict, plan: dict, quality: dict, suggestions: dict, rag_hits: list[dict]) -> None:
    lines = [
        "# Subtitle Agent 审校报告",
        "",
        "## 1. 任务信息",
        "",
        f"- Agent 任务 ID：`{task['task_id']}`",
        f"- 视频：`{task['video_path']}`",
        f"- Profile：`{task['profile']}`",
        f"- 输出目录：`{task['task_dir']}`",
        "",
        "## 2. Agent 计划",
        "",
    ]
    for index, step in enumerate(plan.get("steps", []), start=1):
        lines.append(f"{index}. {step}")

    lines.extend(
        [
            "",
            "## 3. 本地质量扫描",
            "",
            f"- 字幕条数：{quality.get('subtitle_count', 0)}",
            f"- 任务状态：{quality.get('status', 'unknown')}",
            f"- 疑似过长字幕：{len(quality.get('too_long', []))}",
            f"- 疑似过短字幕：{len(quality.get('too_short', []))}",
            f"- 需复查漏字幕区间：{len(quality.get('blocking_gaps', []))}",
            "",
            "## 4. RAG 命中来源",
            "",
        ]
    )
    for index, hit in enumerate(rag_hits[:10], start=1):
        lines.append(f"{index}. `{hit['title']}` score={hit['score']} source=`{hit['source']}`")

    lines.extend(
        [
            "",
            "## 5. 大模型审校结论",
            "",
            suggestions.get("summary", ""),
            "",
            "### 5.1 建议替换词",
            "",
        ]
    )
    replacements = suggestions.get("term_replacements", [])
    if replacements:
        for item in replacements:
            lines.append(
                f"- `{item.get('wrong', '')}` -> `{item.get('right', '')}`：{item.get('reason', '')} "
                f"(confidence={item.get('confidence', '')})"
            )
    else:
        lines.append("- 暂无明确替换建议。")

    lines.extend(["", "### 5.2 需要人工复查的字幕", ""])
    review_items = suggestions.get("segments_to_review", [])
    if review_items:
        for item in review_items[:30]:
            lines.append(
                f"- #{item.get('index', '')} {item.get('start_ms', '')}-{item.get('end_ms', '')}ms："
                f"{item.get('reason', '')}；原文：{item.get('text', '')}"
            )
    else:
        lines.append("- 暂无高优先级人工复查项。")

    lines.extend(
        [
            "",
            "### 5.3 建议新增热词",
            "",
            ", ".join(str(item) for item in suggestions.get("hotwords_to_add", [])) or "暂无",
            "",
            "## 6. 原始结构化建议",
            "",
            "```json",
            json.dumps(suggestions, ensure_ascii=False, indent=2),
            "```",
        ]
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
