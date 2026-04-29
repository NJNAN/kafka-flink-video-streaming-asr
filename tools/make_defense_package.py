import argparse
import json
import shutil
import time
from pathlib import Path


CORE_DOCS = [
    ("README.md", "01_README.md"),
    ("docs/原理解说.md", "02_系统原理解说.md"),
    ("docs/傻瓜式实现文档.md", "03_运行步骤.md"),
    ("docs/本次性能压测实验报告.md", "04_性能压测报告.md"),
    ("docs/system_metrics.md", "06_指标接口说明.md"),
    ("docs/benchmark.md", "07_压测说明.md"),
    ("docs/求精v1.md", "08_求精方案.md"),
]


def copy_if_exists(source: Path, target: Path, copied: list[dict]) -> None:
    if not source.exists() or not source.is_file():
        copied.append({"source": str(source), "target": str(target), "status": "missing"})
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)
    copied.append({"source": str(source), "target": str(target), "status": "copied"})


def copy_matching(source_dir: Path, target_dir: Path, patterns: list[str], copied: list[dict]) -> None:
    if not source_dir.exists():
        copied.append({"source": str(source_dir), "target": str(target_dir), "status": "missing_dir"})
        return
    for pattern in patterns:
        for source in sorted(source_dir.rglob(pattern)):
            if source.is_file():
                copy_if_exists(source, target_dir / source.name, copied)


def write_manifest(path: Path, copied: list[dict], args: argparse.Namespace) -> None:
    ready = [item for item in copied if item["status"] == "copied"]
    missing = [item for item in copied if item["status"] != "copied"]
    lines = [
        "# StreamSense 答辩材料清单",
        "",
        f"- 生成时间戳：{int(time.time() * 1000)}",
        f"- 输出目录：`{args.output_dir}`",
        f"- 已复制文件：{len(ready)}",
        f"- 缺失或跳过：{len(missing)}",
        "",
        "## 1. 建议答辩阅读顺序",
        "",
        "1. `01_README.md`：项目总览和启动方式。",
        "2. `02_系统原理解说.md`：Kafka、Flink、ASR、Redis 的分工。",
        "3. `03_运行步骤.md`：复现项目的操作步骤。",
        "4. `04_性能压测报告.md`：1/2/4 路实验结果和性能结论。",
        "5. `05_字幕质量评测报告.md`：字幕准确率、关键词命中率和覆盖缺口。",
        "6. `sample_subtitles/`：可直接打开的字幕样例。",
        "7. `benchmark/`：压测脚本原始输出。",
        "",
        "## 2. 已复制文件",
        "",
    ]
    for item in ready:
        target = Path(item["target"]).as_posix()
        lines.append(f"- `{target}`")

    if missing:
        lines.extend(["", "## 3. 缺失项提示", ""])
        for item in missing:
            lines.append(f"- `{item['source']}`：{item['status']}")

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Collect StreamSense defense-ready documents and outputs.")
    parser.add_argument("--subtitle-dir", default="data/results/single_test")
    parser.add_argument("--benchmark-dir", default="data/results/benchmark")
    parser.add_argument("--evaluation-dir", default="data/results/evaluation")
    parser.add_argument("--output-dir", default="data/results/defense_package")
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    copied: list[dict] = []

    for source, target_name in CORE_DOCS:
        copy_if_exists(Path(source), output_dir / target_name, copied)

    copy_matching(
        Path(args.evaluation_dir),
        output_dir,
        ["*_eval.md"],
        copied,
    )
    eval_reports = [Path(item["target"]) for item in copied if item["status"] == "copied" and item["target"].endswith("_eval.md")]
    if eval_reports:
        shutil.copy2(eval_reports[0], output_dir / "05_字幕质量评测报告.md")

    copy_matching(
        Path(args.subtitle_dir),
        output_dir / "sample_subtitles",
        ["*.srt", "*.vtt", "*_subtitle.txt", "*_final_segments.json", "*_report.json"],
        copied,
    )
    copy_matching(
        Path(args.benchmark_dir),
        output_dir / "benchmark",
        ["benchmark_report*.md", "benchmark_report*.json"],
        copied,
    )
    copy_matching(
        Path(args.evaluation_dir),
        output_dir / "evaluation",
        ["*_eval.md", "*_eval.json", "evaluation_summary.md"],
        copied,
    )

    write_manifest(output_dir / "00_答辩材料清单.md", copied, args)
    (output_dir / "manifest.json").write_text(json.dumps({"files": copied}, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"defense_package: {output_dir}")
    print(f"copied: {sum(1 for item in copied if item['status'] == 'copied')}")
    print(f"missing_or_skipped: {sum(1 for item in copied if item['status'] != 'copied')}")


if __name__ == "__main__":
    main()
