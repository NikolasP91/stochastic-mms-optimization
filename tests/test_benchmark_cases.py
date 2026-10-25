"""Regression tests for small known-answer benchmark cases."""

import json
import unittest
from pathlib import Path

from mms.diagnostics import build_diagnostics_report, build_warning_report
from mms.reports import (
    build_dispatch_instructions,
    build_mms_reports,
    build_res_curtailment_report,
)
from solution_validation import validate_solution


ROOT = Path(__file__).resolve().parents[1]
BENCHMARK_PATH = ROOT / "benchmarks" / "known_answer_cases.json"


class KnownAnswerBenchmarkTests(unittest.TestCase):
    """Checks small benchmark fixtures against hand-checkable expected behavior."""
    def test_known_answer_cases_validate_as_expected(self):
        with BENCHMARK_PATH.open(encoding="utf-8") as f:
            cases = json.load(f)
        self.assertGreater(len(cases), 0)
        for case in cases:
            with self.subTest(case=case["name"]):
                report = validate_solution(case["input"], case["output"])
                self.assertEqual(report["status"], case["expected_validation_status"])

    def test_known_answer_cases_match_expected_reports(self):
        with BENCHMARK_PATH.open(encoding="utf-8") as f:
            cases = json.load(f)
        for case in cases:
            with self.subTest(case=case["name"]):
                validation = validate_solution(case["input"], case["output"])
                output_with_reports = dict(case["output"])
                output_with_reports.update(build_mms_reports(case["input"], output_with_reports))
                warning_report = build_warning_report(case["input"], output_with_reports, validation)
                diagnostics_report = build_diagnostics_report(
                    case["input"], output_with_reports, validation
                )

                if "expected_output_unit_count" in case:
                    self.assertEqual(
                        case["expected_output_unit_count"],
                        len(output_with_reports.get("Generating_Units", [])),
                    )

                if "expected_dispatch_actions" in case:
                    dispatch_report = build_dispatch_instructions(case["input"], output_with_reports)
                    actions = [row["commitment_action"] for row in dispatch_report["instructions"]]
                    self.assertEqual(case["expected_dispatch_actions"], actions)

                if "expected_res_curtailment_mwh" in case:
                    curtailment_report = build_res_curtailment_report(
                        case["input"], output_with_reports
                    )
                    self.assertAlmostEqual(
                        case["expected_res_curtailment_mwh"],
                        curtailment_report["summary"]["curtailed_mwh"],
                    )

                if "expected_warning_codes" in case:
                    warning_codes = {warning["code"] for warning in warning_report["warnings"]}
                    self.assertTrue(set(case["expected_warning_codes"]).issubset(warning_codes))

                if "expected_diagnostics_status" in case:
                    self.assertEqual(
                        case["expected_diagnostics_status"], diagnostics_report["status"]
                    )


if __name__ == "__main__":
    unittest.main()
