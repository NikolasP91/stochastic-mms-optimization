"""Boundary and algebra-unit tests for modular model-building helpers."""

import unittest
from contextlib import redirect_stdout
from io import StringIO

import pulp as pl

from RV_genericMmsOptimization import define_problem_and_solve_problem as public_problem_entry
from mms.model.bounds import (
    forbidden_zone_big_m,
    res_pv_dispatch_bounds,
    res_pv_unit_dispatch_bounds,
    reserve_activation_bound,
)
from mms.model.operating_states import (
    create_operating_state_max_transition_time_between_states_constraints_b,
)
from mms.model.preprocessing import (
    filter_generating_units,
    round_max_time_to_periods,
    round_min_time_to_periods,
    round_to_best,
    time_granularity,
    unit_categories,
)
from mms.model.problem import define_problem_and_solve_problem


class ModelModuleBoundaryTests(unittest.TestCase):
    """Exercises model-module helpers and protects modular algebra boundaries."""
    def test_main_script_uses_modular_problem_entry_point(self):
        self.assertIs(public_problem_entry, define_problem_and_solve_problem)

    def test_filter_generating_units_keeps_all_units_to_preserve_gen_id_positions(self):
        units = [
            {"availability": [0, 0, 0]},
            {"availability": [0, 1, 0]},
            {"availability": 0},
            {"availability": 5},
        ]

        self.assertEqual(units, filter_generating_units(units))

    def test_unit_categories_preserve_current_set_construction(self):
        input_data = {
            "Generating_Units": [
                {"Accepts_SP": 0},
                {"Accepts_SP": 1},
                {"Accepts_SP": 1},
                {"Accepts_SP": 0},
            ],
            "Other_coefficients": {"include_PV": True},
        }
        data = [
            {"comments": "Thermal Generating Unit"},
            {"comments": "PV Aggregated Unit"},
            {"comments": "Wind Turbine Generating Unit"},
            {"comments": "Partially Controllable Unit"},
        ]

        with redirect_stdout(StringIO()):
            UNITS, CONV, RES, PV, RES_SP, RES_no_SP, PV_SP, PV_no_SP, on_AGC, partially = unit_categories(
                input_data, data
            )

        self.assertEqual([0, 2, 1], UNITS)
        self.assertEqual([0], CONV)
        self.assertEqual([2], RES)
        self.assertEqual([1], PV)
        self.assertEqual([2], RES_SP)
        self.assertEqual([], RES_no_SP)
        self.assertEqual([1], PV_SP)
        self.assertEqual([], PV_no_SP)
        self.assertEqual([], on_AGC)
        self.assertEqual([3], partially)

    def test_time_granularity_converts_minutes_to_period_counts(self):
        data = {
            "Generating_Units": [
                {
                    "operating-states": [
                        {
                            "min-time-enabled": 30,
                            "max-time-enabled": 45,
                            "min-time-enabled-left": 15,
                            "max-time-enabled-left": 60,
                        }
                    ],
                    "operating-state-transitions": [
                        {
                            "from": 1,
                            "transitions": [
                                {
                                    "id": 2,
                                    "min-transition-time_a": 30,
                                    "min-transition-time-left_b": 15,
                                    "max-transition-time_b": 45,
                                    "max-transition-time-left_b": 60,
                                }
                            ],
                        }
                    ],
                    "state-transitions": [
                        {"transitions": {"min-transition-time-left": 15, "min-transition-time": 30}}
                    ],
                }
            ]
        }

        converted = time_granularity(data, 15)
        state = converted["Generating_Units"][0]["operating-states"][0]
        transition = converted["Generating_Units"][0]["operating-state-transitions"][0]["transitions"][0]
        unit_transition = converted["Generating_Units"][0]["state-transitions"][0]["transitions"]

        self.assertEqual(2, state["min-time-enabled"])
        self.assertEqual(3, state["max-time-enabled"])
        self.assertEqual(1, state["min-time-enabled-left"])
        self.assertEqual(4, state["max-time-enabled-left"])
        self.assertEqual(2, transition["min-transition-time_a"])
        self.assertEqual(1, transition["min-transition-time-left_b"])
        self.assertEqual(3, transition["max-transition-time_b"])
        self.assertEqual(4, transition["max-transition-time-left_b"])
        self.assertEqual(1, unit_transition["min-transition-time-left"])
        self.assertEqual(2, unit_transition["min-transition-time"])

    def test_round_to_best_matches_existing_ceiling_behavior(self):
        self.assertEqual(3, round_to_best(45, 15))
        self.assertEqual(4, round_to_best(46, 15))
        self.assertEqual(100000000000, round_to_best(float("inf"), 15))

    def test_min_and_max_time_rounding_use_conservative_direction(self):
        self.assertEqual(1, round_min_time_to_periods(25, 60))
        self.assertEqual(0, round_max_time_to_periods(25, 60))
        self.assertEqual(2, round_min_time_to_periods(61, 60))
        self.assertEqual(1, round_max_time_to_periods(61, 60))

    def test_operating_state_max_transition_b_slacks_follow_project_naming(self):
        intervals = [0, 1, 2, 3]
        data = [
            {
                "gen_id": 0,
                "operating-states": [
                    {"id": 4, "isEnabled": True},
                    {"id": 5, "isEnabled": False},
                ],
                "operating-state-transitions": [
                    {
                        "from": 4,
                        "transitions": [
                            {
                                "id": 5,
                                "max-transition-time-left_b": 100000000000,
                                "max-transition-time_b": 2,
                            }
                        ],
                    }
                ],
            }
        ]
        u_2_dict = {
            (0, t, state_id): pl.LpVariable(
                f"u_2_1_{t}_{state_id}", lowBound=0, upBound=1, cat="Binary"
            )
            for t in intervals
            for state_id in (4, 5)
        }
        prob = pl.LpProblem("state_max_time_slack_naming")
        input_data = {
            "Cost_parameters": {
                "x_max_oper_state_time_b_left": 10000,
                "x_max_oper_state_time_b": 10000,
            }
        }

        prob, objective_terms = create_operating_state_max_transition_time_between_states_constraints_b(
            prob, 0, input_data, data, u_2_dict, len(intervals), intervals
        )
        prob += objective_terms
        variable_names = {variable.name for variable in prob.variables()}

        self.assertNotIn("s_max_oper_state_time_b_left_1_4_5_1", variable_names)
        self.assertIn("s_max_oper_state_time_b_1_1_4_5_2", variable_names)

    def test_reserve_activation_bound_uses_unit_and_state_limits(self):
        unit = {
            "availability": [12],
            "Primary_Active_Power_Reserves(MW)": [20, 20],
        }
        operating_state = {
            "max-power": [9],
            "min-power": [3],
            "user_max_power": 8,
            "user_min_power": 4,
        }

        self.assertEqual(
            8.0,
            reserve_activation_bound(
                unit, "Primary_Active_Power_Reserves(MW)", 0, 0, operating_state
            ),
        )
        self.assertEqual(
            8.0,
            reserve_activation_bound(
                unit, "Primary_Active_Power_Reserves(MW)", 1, 0, operating_state
            ),
        )

    def test_forbidden_zone_big_m_is_local_and_never_larger_than_fallback(self):
        unit = {"availability": [20]}
        local_m = forbidden_zone_big_m(unit, [8, 12], 0, 1000)

        self.assertGreaterEqual(local_m, 10)
        self.assertLess(local_m, 1000)
        self.assertEqual(5.0, forbidden_zone_big_m(unit, [8, 12], 0, 5))

    def test_res_pv_dispatch_bounds_are_period_specific(self):
        input_data = {
            "Other_coefficients": {
                "x_res_pv_dynamic": 1,
                "PV_Participation_coefficient": 50,
                "include_PV": 1,
            }
        }
        data = [
            {"min_power(MW)": [5], "availability": [30]},
            {"availability": [20]},
            {"availability": [10]},
            {"availability": [4]},
        ]

        bounds = res_pv_dispatch_bounds(
            input_data,
            data,
            CONV=[0],
            RES_SP=[1],
            PV_SP=[2],
            RES_no_SP=[3],
            PV_no_SP=[],
            Load_forecast=[0, 10],
            period=1,
        )

        self.assertEqual(15.0, bounds["grid_capacity2_slack_upper"])
        self.assertEqual(25.0, bounds["grid_capacity2_big_m"])
        self.assertGreaterEqual(bounds["grid_capacity1_big_m"], 25.0)

    def test_res_pv_unit_dispatch_bounds_limit_forecast_slack_and_power_m(self):
        unit = {"availability": [20], "min_power(MW)": [3]}

        bounds = res_pv_unit_dispatch_bounds(unit, forecast=5, period_index=0, fallback_m=1000)

        self.assertEqual(15.0, bounds["s_power_minus_upper"])
        self.assertEqual(20.0, bounds["setpoint_forecast_big_m"])
        self.assertEqual(20.0, bounds["power_big_m"])


if __name__ == "__main__":
    unittest.main()
