from __future__ import annotations

import json
import math
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9_-]{1,30}|[\u4e00-\u9fff]{2,}")


@dataclass
class RagDocument:
    doc_id: str
    source: str
    title: str
    text: str


def tokenize(text: str) -> list[str]:
    return [item.lower() for item in TOKEN_RE.findall(text)]


def chunks(text: str, size: int = 700, overlap: int = 120) -> list[str]:
    cleaned = re.sub(r"\s+", " ", text).strip()
    if not cleaned:
        return []
    results = []
    cursor = 0
    while cursor < len(cleaned):
        piece = cleaned[cursor : cursor + size].strip()
        if piece:
            results.append(piece)
        cursor += max(1, size - overlap)
    return results


class RagStore:
    def __init__(self) -> None:
        self.documents: list[RagDocument] = []

    def add_text(self, source: str, title: str, text: str) -> None:
        for index, chunk in enumerate(chunks(text)):
            self.documents.append(
                RagDocument(
                    doc_id=f"doc-{len(self.documents) + 1:05d}",
                    source=source,
                    title=f"{title} #{index + 1}",
                    text=chunk,
                )
            )

    def add_file(self, path: Path, title_prefix: str = "") -> None:
        if not path.exists() or not path.is_file():
            return
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            return
        title = f"{title_prefix}{path.name}" if title_prefix else path.name
        self.add_text(str(path), title, text)

    def add_json_file(self, path: Path, title_prefix: str = "") -> None:
        if not path.exists():
            return
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        self.add_text(str(path), f"{title_prefix}{path.name}", json.dumps(data, ensure_ascii=False, indent=2))

    def build_default_corpus(self, project_root: Path, task_dir: Path, history_limit: int = 80) -> None:
        for path in sorted((project_root / "config" / "profiles").glob("*.txt")):
            self.add_file(path, "profile:")

        for path in sorted((project_root / "subtitle-agent" / "knowledge").glob("*.txt")):
            self.add_file(path, "agent-knowledge:")

        for path in sorted((project_root / "docs").glob("*.md")):
            if path.name in {"领域Profile说明.md", "字幕质量评测说明.md", "原理解说.md", "文档导航.md"}:
                self.add_file(path, "docs:")

        for path in [project_root / "README.md", task_dir / "subtitle.txt", task_dir / "source_report.json", task_dir / "final_segments.json"]:
            if path.suffix == ".json":
                self.add_json_file(path, "current:")
            else:
                self.add_file(path, "current:")

        result_root = project_root / "data" / "results"
        history_files = []
        for pattern in ["**/*_final_segments.json", "**/*_subtitle.txt", "**/*.srt"]:
            history_files.extend(result_root.glob(pattern))
        for path in sorted(history_files, key=lambda item: item.stat().st_mtime if item.exists() else 0, reverse=True)[:history_limit]:
            if task_dir in path.parents:
                continue
            if path.suffix == ".json":
                self.add_json_file(path, "history:")
            else:
                self.add_file(path, "history:")

    def search(self, query: str, top_k: int = 8) -> list[dict]:
        query_tokens = tokenize(query)
        if not query_tokens:
            return []
        query_counts = Counter(query_tokens)
        scores = []
        for doc in self.documents:
            doc_tokens = tokenize(doc.text)
            if not doc_tokens:
                continue
            doc_counts = Counter(doc_tokens)
            overlap = sum(min(query_counts[token], doc_counts[token]) for token in query_counts)
            if overlap <= 0:
                continue
            length_penalty = math.sqrt(len(doc_tokens))
            score = overlap / max(length_penalty, 1.0)
            scores.append((score, doc))
        scores.sort(key=lambda item: item[0], reverse=True)
        return [
            {
                "score": round(score, 4),
                "doc_id": doc.doc_id,
                "source": doc.source,
                "title": doc.title,
                "text": doc.text,
            }
            for score, doc in scores[:top_k]
        ]

    def save_jsonl(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as handle:
            for doc in self.documents:
                handle.write(json.dumps(doc.__dict__, ensure_ascii=False) + "\n")


def compact_hits(hits: Iterable[dict], max_chars: int = 4500) -> str:
    parts = []
    used = 0
    for index, hit in enumerate(hits, start=1):
        text = f"[{index}] {hit['title']} | {hit['source']}\n{hit['text']}\n"
        if used + len(text) > max_chars:
            break
        parts.append(text)
        used += len(text)
    return "\n".join(parts)
