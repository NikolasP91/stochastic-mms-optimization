"""Tests for post-solve objective reconstruction."""

import unittest

from mms.objective import build_objective_breakdown_report


class ObjectiveBreakdownTests(unittest.TestCase):
    """Checks objective-component reconstruction from solved outputs."""
    def test_objective_breakdown_reconstructs_observable_components(self):
        input_data = {
            "Time_granularity": 1,
            "Cost_parameters": {
                "x_load": 1000,
                "x_primary_APR_up": 100,
                "x_primary_APR_down": 100,
                "x_secondary_APR_up": 100,
                "x_secondary_APR_down": 100,
                "x_tertiary_APR_up": 100,
                "x_tertiary_APR_down": 100,
                "x_RES_PV_power_plus": 100,
                "x_RES_PV_power_minus": 100,
            },
            "optimization_parameters": {"cost_curve_time_unit": "euro_per_dispatch_period"},
            "Generating_Units": [
                {
                    "gen_id": 0,
                    "comments": "Thermo test unit",
                    "availability": [20],
                    "Production_Forecast": [0],
                    "min_power(MW)": 10,
                    "max_power(MW)": 20,
                    "start_up_cost(euro)": 50,
                    "shut_down_cost(euro)": 10,
                    "Primary_APR_Cost(euro/MW)": [2, 3],
                    "Secondary_APR_Cost(euro/MW)": [0, 0],
                    "Tertiary_APR_Cost(euro/MW)": [0, 0],
                    "var_gen_cost(euro/MW)": [[10, 20], [100, 5]],
                    "operating-states": [
                        {"id": 0, "isEnabled": False, "enabled-cost": 0},
                        {"id": 1, "isEnabled": True, "enabled-cost": 7},
                    ],
                    "operating-state-transitions": [],
                }
            ],
        }
        output_data = {
            "Solve_Metadata": {"objective_value": 321},
            "Generating_Units": [
                {
                    "gen_id": 0,
                    "Power": [15],
                    "State": [1],
                    "Startup": [1],
                    "Shutdown": [0],
                    "Operating-states": [[0, 1]],
                    "Primary_Active_Power_Reserves(MW)": [[2], [1]],
                    "Secondary_Active_Power_Reserves(MW)": [[0], [0]],
                    "Tertiary_Active_Power_Reserves(MW)": [[0], [0]],
                }
            ],
            "Load_Cutrailment": [0],
            "primary_upwards_APRV": [0],
            "primary_downwards_APRV": [0],
            "secondary_upwards_APRV": [0],
            "secondary_downwards_APRV": [0],
            "tertiary_upwards_APRV": [0],
            "tertiary_downwards_APRV": [0],
        }

        report = build_objective_breakdown_report(input_data, output_data)
        components = {item["name"]: item["amount"] for item in report["components"]}

        self.assertEqual(125.0, components["thermal_variable_cost"])
        self.assertEqual(50.0, components["startup_cost"])
        self.assertEqual(100.0, components["thermal_online_commitment_cost"])
        self.assertEqual(7.0, components["operating_state_enabled_cost"])
        self.assertEqual(7.0, components["reserve_capacity_cost"])
        self.assertEqual(321.0, report["solver_objective"])
        self.assertEqual(32.0, report["residual"])


if __name__ == "__main__":
    unittest.main()
