import argparse
import tempfile
import unittest
from pathlib import Path

from tools import evaluate_subtitles as evaluator


class SubtitleQualityTests(unittest.TestCase):
    def test_strip_subtitle_markup_keeps_only_spoken_text(self) -> None:
        raw = """WEBVTT

00:00:00.000 --> 00:00:02.000
本节课介绍 Kafka。

2
00:00:02,000 --> 00:00:04,000
Flink 负责流式调度。
"""
        text = evaluator.strip_subtitle_markup(raw)

        self.assertEqual(text, "本节课介绍 Kafka。\nFlink 负责流式调度。")

    def test_normalize_text_unifies_punctuation_and_chinese_spaces(self) -> None:
        text = evaluator.normalize_text("Kafka ， Flink  实时 数据 <b>处理</b>")

        self.assertEqual(text, "Kafka，Flink实时数据处理")

    def test_evaluate_reports_cer_and_keyword_recall(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            candidate = root / "candidate.vtt"
            reference = root / "reference.txt"
            keywords = root / "keywords.txt"
            candidate.write_text(
                "WEBVTT\n\n00:00:00.000 --> 00:00:03.000\n本节课介绍 Kafka 和 Flink 实时数据处理。\n",
                encoding="utf-8",
            )
            reference.write_text("本节课介绍 Kafka 和 Flink 实时数据处理。", encoding="utf-8")
            keywords.write_text("Kafka\nFlink\n实时数据\n", encoding="utf-8")

            result = evaluator.evaluate(
                argparse.Namespace(
                    candidate=str(candidate),
                    reference=str(reference),
                    keywords=str(keywords),
                    report="",
                    basename="unit-demo",
                )
            )

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["cer"], 0)
        self.assertEqual(result["keyword_recall"], 1)
        self.assertEqual(result["keyword_hits"], ["Kafka", "Flink", "实时数据"])


if __name__ == "__main__":
    unittest.main()
