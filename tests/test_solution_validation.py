"""Tests for post-solve solution validation checks."""

import unittest

from solution_validation import validate_solution


def _base_input():
    return {
        "constraints": {"load_production_balance_constraint": True},
        "Load_forecast": [0, 10, 12],
        "Generating_Units": [
            {
                "gen_id": 0,
                "state": 0,
                "availability": [10, 12],
                "Primary_Active_Power_Reserves(MW)": [5, 5],
                "Secondary_Active_Power_Reserves(MW)": [4, 4],
                "Tertiary_Active_Power_Reserves(MW)": [3, 3],
            }
        ],
    }


def _base_output():
    return {
        "Solution_Status": "Optimal",
        "Load_Cutrailment": [0, 0],
        "Generating_Units": [
            {
                "gen_id": 0,
                "Power": [10, 12],
                "State": [1, 1],
                "Startup": [1, 0],
                "Shutdown": [0, 0],
                "Primary_Active_Power_Reserves(MW)": [[1, 1], [1, 1]],
                "Secondary_Active_Power_Reserves(MW)": [[1, 1], [1, 1]],
                "Tertiary_Active_Power_Reserves(MW)": [[1, 1], [1, 1]],
            }
        ],
        "primary_upwards_APRV": [0, 0],
        "primary_downwards_APRV": [0, 0],
        "secondary_upwards_APRV": [0, 0],
        "secondary_downwards_APRV": [0, 0],
        "tertiary_upwards_APRV": [0, 0],
        "tertiary_downwards_APRV": [0, 0],
    }


class SolutionValidationTests(unittest.TestCase):
    """Exercises post-solve feasibility and consistency validation checks."""
    def test_valid_solution_passes(self):
        report = validate_solution(_base_input(), _base_output())
        self.assertEqual(report["status"], "passed")

    def test_load_balance_failure_is_reported(self):
        output = _base_output()
        output["Generating_Units"][0]["Power"][1] = 11
        report = validate_solution(_base_input(), output)
        self.assertEqual(report["status"], "failed")
        checks = {check["name"]: check for check in report["checks"]}
        self.assertEqual(checks["load_balance"]["status"], "failed")

    def test_startup_shutdown_failure_is_reported(self):
        output = _base_output()
        output["Generating_Units"][0]["Startup"][0] = 0
        report = validate_solution(_base_input(), output)
        self.assertEqual(report["status"], "failed")
        checks = {check["name"]: check for check in report["checks"]}
        self.assertEqual(checks["startup_shutdown_consistency"]["status"], "failed")

    def test_reserve_limit_failure_is_reported(self):
        output = _base_output()
        output["Generating_Units"][0]["Primary_Active_Power_Reserves(MW)"][0][0] = 6
        report = validate_solution(_base_input(), output)
        self.assertEqual(report["status"], "failed")
        checks = {check["name"]: check for check in report["checks"]}
        self.assertEqual(checks["reserve_outputs"]["status"], "failed")


if __name__ == "__main__":
    unittest.main()
