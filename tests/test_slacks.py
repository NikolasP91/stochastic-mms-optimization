"""Tests for normalized soft-constraint slack penalty reporting."""

import unittest

import pandas as pd

from mms.slacks import build_slack_penalty_report


class SlackPenaltyReportTests(unittest.TestCase):
    """Checks normalized reporting of priced slack variables."""
    def test_slack_penalty_report_combines_variable_and_matrix_sources(self):
        input_data = {
            "Cost_parameters": {
                "x_ramp": 10,
                "x_Grid_Capacity": 20,
                "x_primary_APR_up": 30,
                "x_min_oper_state_time_b": 40,
                "x_max_oper_state_time_b": 50,
            }
        }
        slack_frames = {
            "ramp_relax": pd.DataFrame([[0.0, 2.0]], index=[1], columns=[1, 2]),
            "s_Grid_Capacity_2": pd.DataFrame(
                [("s_Grid_Capacity_2_2", 3.5)], columns=["Variable", "Value"]
            ),
            "s_primary_APR_upwards": pd.DataFrame(
                [("s_primary_APR_upwards_1", 1.0)], columns=["Variable", "Value"]
            ),
            "s_min_oper_state_time_b_1": pd.DataFrame(
                [("s_min_oper_state_time_b_1_2_7_3", 1.0)], columns=["Variable", "Value"]
            ),
            "s_max_oper_state_time_b_1": pd.DataFrame(
                [("s_max_oper_state_time_b_1_2_4_7_3", 1.0)], columns=["Variable", "Value"]
            ),
        }

        report = build_slack_penalty_report(input_data, slack_frames)
        entries = {entry["family"]: entry for entry in report["entries"]}

        self.assertEqual("warning", report["status"])
        self.assertEqual(5, report["nonzero_slack_count"])
        self.assertAlmostEqual(210.0, report["total_penalty_eur"])
        self.assertEqual(0, entries["ramp_relaxation"]["unit_index"])
        self.assertEqual(2, entries["ramp_relaxation"]["period"])
        self.assertEqual(70.0, entries["grid_capacity_2"]["cost_eur"])
        self.assertEqual(1, entries["operating_state_min_time_b"]["unit_index"])
        self.assertEqual(7, entries["operating_state_min_time_b"]["operating_state_id"])
        self.assertEqual(3, entries["operating_state_min_time_b"]["period"])
        self.assertEqual(1, entries["operating_state_max_time_b"]["unit_index"])
        self.assertEqual(4, entries["operating_state_max_time_b"]["from_operating_state_id"])
        self.assertEqual(7, entries["operating_state_max_time_b"]["operating_state_id"])
        self.assertEqual(3, entries["operating_state_max_time_b"]["period"])

    def test_slack_penalty_report_passes_when_all_slacks_are_zero(self):
        input_data = {"Cost_parameters": {"x_ramp": 10}}
        slack_frames = {"ramp_relax": pd.DataFrame([[0.0]], index=[1], columns=[1])}

        report = build_slack_penalty_report(input_data, slack_frames)

        self.assertEqual("passed", report["status"])
        self.assertEqual(0, report["nonzero_slack_count"])
        self.assertEqual([], report["entries"])


if __name__ == "__main__":
    unittest.main()
