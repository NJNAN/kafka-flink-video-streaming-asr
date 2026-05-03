from __future__ import annotations

import json
from pathlib import Path

from llm_client import LlmClient


def build_fallback_plan(video_path: Path, profile: str, goal: str) -> dict:
    return {
        "goal": goal,
        "video_path": str(video_path),
        "profile": profile,
        "steps": [
            "检查视频路径并复制到项目 videos 目录",
            "调用离线字幕生成脚本生成基础字幕",
            "读取字幕 JSON 和质量 report",
            "建立 RAG 索引并检索领域词、纠错词和历史字幕",
            "调用大模型审校字幕并生成建议",
            "导出修正版字幕和 Agent 报告",
        ],
        "risk_points": ["ASR/API 后端未启动时字幕生成会失败", "大模型 API key 缺失时只能生成本地质检报告"],
    }


def make_plan(llm: LlmClient, video_path: Path, profile: str, goal: str) -> dict:
    prompt = (
        "你是离线视频字幕生成 Agent 的规划器。"
        "请只返回 JSON，不要写 Markdown。字段包含 goal、profile、steps、risk_points、rag_sources。"
    )
    user = f"视频路径: {video_path}\n领域 profile: {profile}\n用户目标: {goal}"
    try:
        response = llm.chat(
            [
                {"role": "system", "content": prompt},
                {"role": "user", "content": user},
            ],
            temperature=0.1,
        )
        text = response.text.strip()
        if text.startswith("```"):
            text = text.strip("`")
            text = text.replace("json\n", "", 1).strip()
        return json.loads(text)
    except Exception as exc:
        plan = build_fallback_plan(video_path, profile, goal)
        plan["planner_warning"] = str(exc)
        return plan
