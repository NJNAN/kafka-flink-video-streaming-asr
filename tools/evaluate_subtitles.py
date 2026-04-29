import argparse
import json
import re
import sqlite3
import time
from pathlib import Path
from typing import Any


TIME_LINE_RE = re.compile(
    r"^\s*\d{1,2}:\d{2}:\d{2}[,.]\d{3}\s*-->\s*\d{1,2}:\d{2}:\d{2}[,.]\d{3}"
)

PUNCT_TRANSLATION = str.maketrans(
    {
        "﹐": "，",
        "﹑": "、",
        "﹒": "。",
        "﹔": "；",
        "﹕": "：",
        ",": "，",
        "?": "？",
        "!": "！",
    }
)


def read_text_file(path: Path) -> str:
    if not path.exists():
        raise SystemExit(f"文件不存在: {path}")

    text = path.read_text(encoding="utf-8-sig", errors="ignore")
    suffix = path.suffix.lower()
    if suffix in {".srt", ".vtt"}:
        return strip_subtitle_markup(text)
    return text


def strip_subtitle_markup(text: str) -> str:
    rows: list[str] = []
    for line in text.splitlines():
        value = line.strip()
        if not value:
            continue
        if value.upper() == "WEBVTT":
            continue
        if value.isdigit():
            continue
        if TIME_LINE_RE.match(value):
            continue
        if value.startswith("NOTE") or value.startswith("STYLE"):
            continue
        rows.append(value)
    return "\n".join(rows)


def normalize_text(text: str, keep_spaces: bool = False) -> str:
    text = text.translate(PUNCT_TRANSLATION)
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"\[[^\]]+\]", "", text)
    text = re.sub(r"\([^)]{0,12}\)", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"(?<=[\u4e00-\u9fff])\s+(?=[\u4e00-\u9fff])", "", text)
    if not keep_spaces:
        text = re.sub(r"\s+", "", text)
    return text


def tokenize_words(text: str) -> list[str]:
    words = re.findall(r"[A-Za-z0-9_+-]+|[\u4e00-\u9fff]", text)
    return words or list(text)


def edit_distance(left: list[str], right: list[str]) -> int:
    if not left:
        return len(right)
    if not right:
        return len(left)

    previous = list(range(len(right) + 1))
    for i, left_item in enumerate(left, start=1):
        current = [i]
        for j, right_item in enumerate(right, start=1):
            cost = 0 if left_item == right_item else 1
            current.append(
                min(
                    previous[j] + 1,
                    current[j - 1] + 1,
                    previous[j - 1] + cost,
                )
            )
        previous = current
    return previous[-1]


def load_keywords(path: Path | None) -> list[str]:
    if path is None or not path.exists():
        return []

    words: list[str] = []
    seen: set[str] = set()
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        value = line.strip()
        if not value or value.startswith("#"):
            continue
        if "=>" in value:
            _, value = value.split("=>", 1)
            value = value.strip()
        if value and value not in seen:
            words.append(value)
            seen.add(value)
    return words


def load_json(path: Path | None) -> dict[str, Any]:
    if path is None or not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


def save_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def percent(value: float | None) -> str:
    if value is None:
        return "不适用"
    return f"{value * 100:.2f}%"


def write_markdown(path: Path, result: dict[str, Any]) -> None:
    keyword_hits = result.get("keyword_hits", [])
    keyword_misses = result.get("keyword_misses", [])
    lines = [
        f"# {result['basename']} 字幕质量评测报告",
        "",
        "## 1. 总览",
        "",
        "| 指标 | 数值 | 解释 |",
        "| --- | ---: | --- |",
        f"| CER | {percent(result.get('cer'))} | 中文字符级错误率，越低越好 |",
        f"| WER | {percent(result.get('wer'))} | 混合文本词级错误率，中文场景只作辅助参考 |",
        f"| 关键词命中率 | {percent(result.get('keyword_recall'))} | 领域关键词在候选字幕中的命中比例 |",
        f"| 字符编辑距离 | {result.get('char_edit_distance', 0)} | 候选字幕到参考文本的字符修改量 |",
        f"| 参考字符数 | {result.get('reference_chars', 0)} | 标准答案清洗后的字符数 |",
        f"| 候选字符数 | {result.get('candidate_chars', 0)} | 系统字幕清洗后的字符数 |",
        f"| 字幕条数 | {result.get('subtitle_items', 0)} | 字幕生成报告中的最终字幕块数量 |",
        f"| 补漏后阻塞缺口 | {result.get('coverage_blocking_gaps', 0)} | 明显有声但仍无有效字幕的时间段数量 |",
        f"| 耗时/视频时长 | {result.get('speed_ratio_elapsed_over_media', '不适用')} | 小于 1 表示快于视频实时播放 |",
        "",
        "## 2. 关键词命中情况",
        "",
        f"- 命中数量：{len(keyword_hits)}",
        f"- 未命中数量：{len(keyword_misses)}",
        f"- 命中关键词：{', '.join(keyword_hits) if keyword_hits else '无'}",
        f"- 未命中关键词：{', '.join(keyword_misses) if keyword_misses else '无'}",
        "",
        "## 3. 结论",
        "",
    ]

    cer = result.get("cer")
    blocking_gaps = int(result.get("coverage_blocking_gaps", 0))
    keyword_recall = result.get("keyword_recall")
    if cer is not None and cer <= 0.15 and blocking_gaps == 0:
        lines.append("本次字幕在字符错误率和覆盖完整性上表现较好，可作为答辩展示样例。")
    elif blocking_gaps > 0:
        lines.append("本次字幕仍存在补漏后阻塞缺口，建议优先复查这些时间段。")
    else:
        lines.append("本次字幕可以用于演示，但建议继续扩充热词和纠错表来降低错误率。")

    if keyword_recall is not None and keyword_recall < 0.8:
        lines.append("领域关键词命中率偏低，建议补充 profile 热词或纠错词。")

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def maybe_store_sqlite(db_path: Path | None, result: dict[str, Any]) -> None:
    if db_path is None:
        return
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS evaluations (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              basename TEXT,
              candidate_path TEXT,
              reference_path TEXT,
              cer REAL,
              wer REAL,
              keyword_recall REAL,
              subtitle_items INTEGER,
              created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.execute(
            """
            INSERT INTO evaluations (
              basename, candidate_path, reference_path, cer, wer,
              keyword_recall, subtitle_items
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                result.get("basename", ""),
                result.get("candidate", ""),
                result.get("reference", ""),
                result.get("cer"),
                result.get("wer"),
                result.get("keyword_recall"),
                int(result.get("subtitle_items", 0)),
            ),
        )


def evaluate(args: argparse.Namespace) -> dict[str, Any]:
    candidate_path = Path(args.candidate)
    reference_path = Path(args.reference)
    candidate_raw = read_text_file(candidate_path)
    reference_raw = read_text_file(reference_path)

    candidate_chars_text = normalize_text(candidate_raw)
    reference_chars_text = normalize_text(reference_raw)
    candidate_word_text = normalize_text(candidate_raw, keep_spaces=True)
    reference_word_text = normalize_text(reference_raw, keep_spaces=True)

    char_distance = edit_distance(list(candidate_chars_text), list(reference_chars_text))
    candidate_words = tokenize_words(candidate_word_text)
    reference_words = tokenize_words(reference_word_text)
    word_distance = edit_distance(candidate_words, reference_words)

    keywords = load_keywords(Path(args.keywords) if args.keywords else None)
    keyword_hits = [word for word in keywords if normalize_text(word) in candidate_chars_text]
    keyword_misses = [word for word in keywords if normalize_text(word) not in candidate_chars_text]
    report = load_json(Path(args.report) if args.report else None)
    blocking_gaps = report.get(
        "blocking_uncovered_gaps_after_recovery",
        report.get("uncovered_gaps_after_recovery", []),
    )
    if not isinstance(blocking_gaps, list):
        blocking_gaps = []

    return {
        "status": "ok",
        "basename": args.basename or candidate_path.stem,
        "candidate": str(candidate_path),
        "reference": str(reference_path),
        "evaluated_at_ms": int(time.time() * 1000),
        "candidate_chars": len(candidate_chars_text),
        "reference_chars": len(reference_chars_text),
        "char_edit_distance": char_distance,
        "word_edit_distance": word_distance,
        "cer": round(char_distance / max(len(reference_chars_text), 1), 6),
        "wer": round(word_distance / max(len(reference_words), 1), 6),
        "keyword_recall": round(len(keyword_hits) / max(len(keywords), 1), 6) if keywords else None,
        "keyword_total": len(keywords),
        "keyword_hits": keyword_hits,
        "keyword_misses": keyword_misses,
        "subtitle_items": int(report.get("subtitle_items", 0) or 0),
        "coverage_blocking_gaps": len(blocking_gaps),
        "speed_ratio_elapsed_over_media": report.get("speed_ratio_elapsed_over_media"),
        "source_report": str(args.report or ""),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate StreamSense subtitle quality with reference text.")
    parser.add_argument("--candidate", required=True, help="系统生成的 srt/vtt/txt 字幕文件。")
    parser.add_argument("--reference", required=True, help="人工整理的参考字幕或纯文本。")
    parser.add_argument("--keywords", default="config/custom_keywords.txt", help="领域关键词文件。")
    parser.add_argument("--report", default="", help="generate_video_subtitles.py 生成的 report.json。")
    parser.add_argument("--output-dir", default="data/results/evaluation")
    parser.add_argument("--basename", default="")
    parser.add_argument("--db", default="", help="可选：把评测结果写入 SQLite。")
    args = parser.parse_args()

    result = evaluate(args)
    output_dir = Path(args.output_dir)
    basename = result["basename"]
    json_path = output_dir / f"{basename}_eval.json"
    md_path = output_dir / f"{basename}_eval.md"

    save_json(json_path, result)
    write_markdown(md_path, result)
    maybe_store_sqlite(Path(args.db) if args.db else None, result)

    print(f"cer: {percent(result['cer'])}")
    print(f"wer: {percent(result['wer'])}")
    print(f"keyword_recall: {percent(result['keyword_recall'])}")
    print(f"json: {json_path}")
    print(f"markdown: {md_path}")


if __name__ == "__main__":
    main()
