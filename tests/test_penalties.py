"""Tests for soft-constraint penalty hierarchy auditing."""

import unittest

from mms.penalties import audit_penalty_hierarchy


def _valid_penalties():
    return {
        "Cost_parameters": {
            "x_load": 20000,
            "x_primary_APR_up": 10000,
            "x_primary_APR_down": 10000,
            "x_secondary_APR_up": 5000,
            "x_secondary_APR_down": 5000,
            "x_tertiary_APR_up": 3000,
            "x_tertiary_APR_down": 300,
            "x_forbidden_zones": 10000,
            "x_ramp": 10000,
            "x_must_run": 100000,
            "x_min_transition_oper_states_a": 10000,
            "x_min_transition_oper_states_a_left": 10000,
            "x_min_transition_oper_states_b": 10000,
            "x_min_transition_oper_states_b_left": 10000,
            "x_max_oper_state_time_b": 10000,
            "x_max_oper_state_time_b_left": 10000,
            "x_min_transition_states": 10000,
            "x_min_transition_states_left": 10000,
            "x_Grid_Capacity": 10000,
            "x_testing_mode": 10000,
            "x_RES_PV_power_plus": 100000,
            "x_RES_PV_power_minus": 100000,
            "x_OOS_more_than": 10000,
            "x_OOS_less_than": 10000,
        }
    }


class PenaltyHierarchyTests(unittest.TestCase):
    """Covers penalty coefficient validation and priority-order warnings."""
    def test_valid_penalty_hierarchy_passes(self):
        report = audit_penalty_hierarchy(_valid_penalties())

        self.assertEqual("passed", report["status"])
        self.assertEqual(0, report["warning_count"])
        self.assertEqual(0, report["error_count"])

    def test_priority_inversion_is_warned(self):
        data = _valid_penalties()
        data["Cost_parameters"]["x_load"] = 100

        report = audit_penalty_hierarchy(data)

        self.assertEqual("warning", report["status"])
        self.assertTrue(
            any(issue["code"] == "penalty_priority_inversion" for issue in report["issues"])
        )

    def test_non_numeric_penalty_is_error(self):
        data = _valid_penalties()
        data["Cost_parameters"]["x_load"] = "high"

        report = audit_penalty_hierarchy(data)

        self.assertEqual("failed", report["status"])
        self.assertTrue(any(issue["code"] == "non_numeric_penalty" for issue in report["issues"]))


if __name__ == "__main__":
    unittest.main()
