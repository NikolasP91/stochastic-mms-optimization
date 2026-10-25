"""Tests for warning and diagnostics report assembly."""

import unittest

from mms.diagnostics import build_diagnostics_report, build_warning_report


class DiagnosticsTests(unittest.TestCase):
    """Covers warning and diagnostics payload behavior for degraded runs."""
    def test_warning_report_collects_slacks_shortfalls_and_validation_failures(self):
        output_data = {
            "Solution_Status": "Optimal",
            "Load_Cutrailment": [0.0, 1.5],
            "primary_upwards_APRV": [2.0, 0.0],
            "primary_downwards_APRV": [0.0, 0.0],
            "secondary_upwards_APRV": [0.0, 0.0],
            "secondary_downwards_APRV": [0.0, 0.0],
            "tertiary_upwards_APRV": [0.0, 0.0],
            "tertiary_downwards_APRV": [0.0, 0.0],
            "Reserve_Monitoring_Report": {
                "periods": [
                    {
                        "period": 1,
                        "reserves": {
                            "primary": {
                                "upwards": {
                                    "status": "shortfall",
                                    "required_mw": 5.0,
                                    "provided_mw": 3.0,
                                    "shortfall_mw": 2.0,
                                }
                            }
                        },
                    }
                ]
            },
        }
        validation_report = {
            "status": "warning",
            "checks": [
                {
                    "name": "reported_apr_violations",
                    "status": "failed",
                    "severity": "warning",
                    "detail": "APR violation is nonzero.",
                }
            ],
        }

        report = build_warning_report({}, output_data, validation_report, tolerance=1e-3)

        warning_codes = {warning["code"] for warning in report["warnings"]}
        self.assertEqual("warning", report["status"])
        self.assertIn("load_curtailment", warning_codes)
        self.assertIn("reserve_requirement_violation", warning_codes)
        self.assertIn("reserve_shortfall", warning_codes)
        self.assertIn("validation_reported_apr_violations", warning_codes)

    def test_diagnostics_report_marks_nonoptimal_solver_status_as_failed(self):
        report = build_diagnostics_report({}, {"Solution_Status": "Infeasible"})

        self.assertEqual("failed", report["status"])
        self.assertEqual(1, report["issue_count"])
        self.assertEqual("solve", report["issues"][0]["stage"])
        self.assertIn("Infeasible", report["issues"][0]["message"])

    def test_diagnostics_report_preserves_input_validation_errors(self):
        report = build_diagnostics_report(
            {},
            error_report={
                "stage": "input_validation",
                "errors": ["Generating_Units must not be empty.", "RTD mode is out of scope."],
            },
        )

        self.assertEqual("failed", report["status"])
        self.assertEqual("input_validation", report["issues"][0]["stage"])
        self.assertIn("Generating_Units", report["issues"][0]["message"])

    def test_warning_report_includes_thermal_cost_curve_audit_issues(self):
        report = build_warning_report(
            {},
            {
                "Thermal_Cost_Curve_Audit": {
                    "issues": [
                        {
                            "severity": "warning",
                            "code": "nonconvex_marginal_costs",
                            "message": "PWL marginal costs decrease.",
                            "unit_index": 0,
                            "gen_id": 7,
                        }
                    ]
                }
            },
        )

        self.assertEqual("warning", report["status"])
        self.assertEqual("thermal_cost_curve_nonconvex_marginal_costs", report["warnings"][0]["code"])
        self.assertEqual(7, report["warnings"][0]["gen_id"])


if __name__ == "__main__":
    unittest.main()
