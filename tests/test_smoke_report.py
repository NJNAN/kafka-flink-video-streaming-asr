import json
import tempfile
import unittest
from pathlib import Path

from tools.smoke_check import add_check, write_markdown


class SmokeReportTests(unittest.TestCase):
    def test_add_check_and_markdown_report_are_teacher_readable(self) -> None:
        rows: list[dict] = []
        add_check(rows, "API health", True, {"status": "ok"})
        add_check(rows, "Kafka topics", False, {"missing": ["keyword-event"]})

        with tempfile.TemporaryDirectory() as tmp:
            report_path = Path(tmp) / "smoke_report.md"
            write_markdown(report_path, rows)
            text = report_path.read_text(encoding="utf-8")

        self.assertIn("# StreamSense 冒烟测试报告", text)
        self.assertIn("| API health | pass |", text)
        self.assertIn("| Kafka topics | fail |", text)
        self.assertIn(json.dumps({"missing": ["keyword-event"]}, ensure_ascii=False), text)


if __name__ == "__main__":
    unittest.main()
