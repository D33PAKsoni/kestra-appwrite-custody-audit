"""Check report completeness and safe CSV output, using local temporary files."""

import csv
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from build_report import build_report, write_reports


def fixture():
    return json.loads((ROOT / "fixtures" / "clean-ready.json").read_text(encoding="utf-8"))


class ReportOutputTests(unittest.TestCase):
    def emit(self, report):
        # Temporary output stays in the sibling project and is removed after inspection.
        with tempfile.TemporaryDirectory(prefix="report-test-", dir=ROOT) as temporary:
            target = Path(temporary).resolve()
            self.assertTrue(target.is_relative_to(ROOT.resolve()))
            previous = Path.cwd()
            try:
                os.chdir(target)
                write_reports(report)
                result = json.loads(Path("audit.json").read_text(encoding="utf-8"))
                with Path("audit.csv").open(newline="", encoding="utf-8") as stream:
                    rows = list(csv.DictReader(stream))
            finally:
                os.chdir(previous)
        return result, rows

    def report(self, data=None):
        return build_report(fixture() if data is None else data,
                            {"findings": [], "checkedSamples": 1},
                            {"findings": [], "checkedReceipts": 0, "resolvedMissing": 0, "unresolvedMissing": 0})

    def test_incomplete_no_findings_still_emits_inconclusive_summary(self):
        data = fixture()
        data.update(complete=False, issues=[{"code": "EXPORT_LIMIT_REACHED", "message": "Fictional limit."}])
        expected = self.report(data)
        result, rows = self.emit(expected)
        self.assertEqual(result["status"], "inconclusive")
        self.assertFalse(result["complete"])
        self.assertEqual(result["coverage"], data["coverage"])
        self.assertEqual(result["issues"], data["issues"])
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["status"], "inconclusive")
        self.assertEqual(rows[0]["complete"], "False")
        self.assertTrue(rows[0]["message"])

    def test_export_issues_override_a_claim_of_completeness(self):
        data = fixture()
        data["issues"] = [{"code": "CONCURRENT_CHANGE", "message": "Fictional concurrent write."}]
        self.assertEqual(self.report(data)["status"], "inconclusive")

    def test_formula_prefixes_are_escaped_in_csv_but_json_retains_evidence(self):
        for prefix in ("=", "+", "-", "@", "   =", "\t@"):
            with self.subTest(prefix=prefix):
                report = self.report()
                finding = {"code": "fictional", "severity": "error", "sampleId": prefix + "sample",
                           "receiptId": prefix + "receipt", "message": prefix + "text"}
                report.update(status="findings", findings=[finding])
                result, rows = self.emit(report)
                self.assertEqual(result["findings"], [finding])
                self.assertEqual(rows[0]["status"], "findings")
                for field in ("sampleId", "receiptId", "message"):
                    self.assertEqual(rows[0][field], "'" + finding[field])

    def test_plain_text_with_commas_and_newlines_round_trips(self):
        report = self.report()
        finding = {"code": "fictional", "severity": "warning", "sampleId": "water-001",
                   "receiptId": "receipt-001", "message": "One, two\nthree"}
        report.update(status="findings", findings=[finding])
        _, rows = self.emit(report)
        self.assertEqual(rows[0]["message"], finding["message"])
        self.assertEqual(rows[0]["sampleId"], "water-001")


if __name__ == "__main__":
    unittest.main()
