from __future__ import annotations

from pathlib import Path
from typing import Callable

from agent.ai_corrector import correct_segments_with_llm
from agent.consistency_agent import enforce_term_consistency
from agent.context_analyzer import analyze_video_context
from agent.glossary import infer_video_glossary
from agent.planner import make_plan
from agent.reporter import write_report
from agent.reviewer import review_subtitles
from agent.semantic_editor import semantic_polish_subtitles
from config import AgentConfig
from llm_client import LlmClient
from rag_store import RagStore
from tools.export_tool import write_items_ass, write_items_srt, write_items_text
from tools.file_tool import copy_if_exists, load_json, make_task_id, save_json
from tools.integrity_tool import repair_index_aligned_items, repair_timeline_coverage
from tools.quality_tool import local_quality_scan
from tools.readability_tool import improve_subtitle_readability
from tools.rhythm_tool import optimize_subtitle_rhythm
from tools.subtitle_tool import ensure_backend_ready, prepare_video, run_subtitle_generation


LogFn = Callable[[str], None]


def policy_value(context_brief: dict, key: str, default):
    policy = context_brief.get("subtitle_policy", {}) if isinstance(context_brief, dict) else {}
    try:
        return type(default)(policy.get(key, default))
    except (TypeError, ValueError):
        return default


def run_agent(config: AgentConfig, video_path: Path, profile: str, goal: str, log: LogFn | None = None) -> dict:
    def emit(message: str) -> None:
        if log:
            log(message)

    task_id = make_task_id()
    task_dir = config.result_root / task_id
    task_dir.mkdir(parents=True, exist_ok=True)
    run_log: list[str] = []

    def log_and_store(message: str) -> None:
        run_log.append(message)
        emit(message)

    llm = LlmClient(config.llm_api_base, config.llm_api_key, config.llm_model)
    profile = profile or config.default_profile
    task = {
        "task_id": task_id,
        "video_path": str(video_path),
        "profile": profile,
        "goal": goal,
        "task_dir": str(task_dir),
    }
    save_json(task_dir / "task.json", task)

    log_and_store("Step 1/12: Agent 正在规划任务")
    plan = make_plan(llm, video_path, profile, goal)
    save_json(task_dir / "agent_plan.json", plan)

    log_and_store("Step 2/12: 准备视频并调用离线字幕生成工具")
    prepared_video = prepare_video(config.project_root, video_path, task_id)
    ensure_backend_ready(config.project_root, log=log_and_store)
    completed = run_subtitle_generation(
        project_root=config.project_root,
        video_path=prepared_video,
        task_dir=task_dir,
        task_id=task_id,
        profile=profile,
        passes=config.default_passes,
    )
    (task_dir / "subtitle_generation_stdout.txt").write_text(completed.stdout, encoding="utf-8")
    (task_dir / "subtitle_generation_stderr.txt").write_text(completed.stderr, encoding="utf-8")
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "").strip()
        raise RuntimeError(
            f"字幕生成失败，returncode={completed.returncode}，详见 {task_dir}\n"
            f"脚本输出:\n{detail[-2000:]}"
        )

    original_srt = task_dir / f"{task_id}.srt"
    subtitle_txt = task_dir / f"{task_id}_subtitle.txt"
    final_segments = task_dir / f"{task_id}_final_segments.json"
    source_report = task_dir / f"{task_id}_report.json"
    copy_if_exists(original_srt, task_dir / "original.srt")
    copy_if_exists(subtitle_txt, task_dir / "subtitle.txt")
    copy_if_exists(final_segments, task_dir / "final_segments.json")
    copy_if_exists(source_report, task_dir / "source_report.json")

    log_and_store("Step 3/12: 读取字幕和质量报告")
    segments_payload = load_json(task_dir / "final_segments.json")
    report = load_json(task_dir / "source_report.json")
    items = segments_payload.get("items", [])
    original_quality = local_quality_scan(items, report)
    save_json(task_dir / "local_quality_scan.json", original_quality)

    log_and_store("Step 4/12: 建立 RAG 索引并检索上下文")
    rag = RagStore()
    rag.build_default_corpus(config.project_root, task_dir, history_limit=config.history_limit)
    rag.save_jsonl(task_dir / "rag_index.jsonl")
    query = " ".join(
        [
            goal,
            profile,
            " ".join(str(item) for item in original_quality.get("hotwords", [])),
            " ".join(item.get("text", "") for item in items[:100]),
        ]
    )
    rag_hits = rag.search(query, top_k=12)
    save_json(task_dir / "rag_hits.json", rag_hits)

    log_and_store("Step 5/12: 调用大模型建立全片上下文审校规则")
    context_brief = analyze_video_context(llm, items, rag_hits, goal, profile)
    save_json(task_dir / "ai_context_brief.json", context_brief)

    log_and_store("Step 6/12: 调用大模型归纳本视频动态术语表")
    ai_glossary = infer_video_glossary(llm, items, rag_hits, goal)
    save_json(task_dir / "ai_glossary.json", ai_glossary)

    log_and_store("Step 7/12: 调用大模型进行逐段动态字幕修正")
    corrected_items, ai_revisions = correct_segments_with_llm(
        llm=llm,
        items=items,
        rag_hits=rag_hits,
        goal=goal,
        glossary=ai_glossary,
        context_brief=context_brief,
        batch_size=config.ai_batch_size,
        log=log_and_store,
    )
    corrected_items, correction_integrity = repair_index_aligned_items(items, corrected_items)
    save_json(task_dir / "correction_integrity_report.json", correction_integrity)
    save_json(task_dir / "ai_segment_revisions.json", ai_revisions)
    save_json(task_dir / "agent_corrected_segments.json", {"items": corrected_items, "ai_revisions": ai_revisions})

    log_and_store("Step 8/12: 调用大模型做全局术语一致性检查")
    consistent_items, consistency_report = enforce_term_consistency(llm, corrected_items, context_brief, ai_glossary, goal)
    consistent_items, consistency_integrity = repair_index_aligned_items(corrected_items, consistent_items)
    save_json(task_dir / "term_consistency_report.json", consistency_report)
    save_json(task_dir / "consistency_integrity_report.json", consistency_integrity)

    log_and_store("Step 9/12: 调用大模型做字幕语义排版优化")
    semantic_items, semantic_report = semantic_polish_subtitles(
        llm=llm,
        items=consistent_items,
        context_brief=context_brief,
        goal=goal,
        batch_size=max(6, min(config.ai_batch_size, 14)),
        log=log_and_store,
    )
    semantic_items, semantic_integrity = repair_index_aligned_items(consistent_items, semantic_items)
    save_json(task_dir / "semantic_edit_report.json", semantic_report)
    save_json(task_dir / "semantic_integrity_report.json", semantic_integrity)

    log_and_store("Step 10/12: 优化字幕阅读节奏和行宽")
    max_chars = max(16, min(policy_value(context_brief, "max_chars_per_line", 22), 28))
    readable_items, readability_changes = improve_subtitle_readability(semantic_items, max_chars=max_chars)
    target_cps = max(10.0, min(policy_value(context_brief, "reading_speed_cps", 13.0), 16.0))
    rhythm_items, rhythm_report = optimize_subtitle_rhythm(readable_items, target_cps=target_cps)
    final_items, subtitle_integrity = repair_timeline_coverage(items, rhythm_items)
    save_json(task_dir / "readability_changes.json", readability_changes)
    save_json(task_dir / "rhythm_report.json", rhythm_report)
    save_json(task_dir / "subtitle_integrity_report.json", subtitle_integrity)
    corrected_quality = local_quality_scan(final_items, report)
    save_json(task_dir / "corrected_quality_scan.json", corrected_quality)

    log_and_store("Step 11/12: 调用大模型生成整体审校报告")
    suggestions = review_subtitles(llm, final_items, corrected_quality, rag_hits, goal, ai_revisions)
    suggestions["experience_agent"] = {
        "context_brief_file": "ai_context_brief.json",
        "term_consistency_file": "term_consistency_report.json",
        "semantic_edit_file": "semantic_edit_report.json",
        "rhythm_file": "rhythm_report.json",
        "styled_outputs": ["revised.ass", "revised.clean.ass", "revised.creator.ass"],
    }
    save_json(task_dir / "agent_suggestions.json", suggestions)

    log_and_store("Step 12/12: 导出多版本字幕和 Agent 报告")
    write_items_srt(final_items, task_dir / "revised.srt")
    write_items_ass(final_items, task_dir / "revised.ass", title=f"StreamSense {task_id}", variant="clean")
    write_items_ass(final_items, task_dir / "revised.clean.ass", title=f"StreamSense {task_id}", variant="clean")
    write_items_ass(final_items, task_dir / "revised.creator.ass", title=f"StreamSense {task_id}", variant="creator")
    write_items_text(final_items, task_dir / "agent_revised_subtitle.txt")
    write_report(task_dir / "agent_report.md", task, plan, corrected_quality, suggestions, rag_hits)
    (task_dir / "run_log.txt").write_text("\n".join(run_log) + "\n", encoding="utf-8")
    log_and_store(f"完成：{task_dir}")
    return {
        "task_id": task_id,
        "task_dir": str(task_dir),
        "report": str(task_dir / "agent_report.md"),
        "suggestions": str(task_dir / "agent_suggestions.json"),
        "revised_srt": str(task_dir / "revised.srt"),
        "revised_ass": str(task_dir / "revised.ass"),
        "creator_ass": str(task_dir / "revised.creator.ass"),
    }
