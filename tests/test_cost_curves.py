"""Tests for thermal cost-curve generation, audit, formulation, and reporting."""

import copy
import unittest

import pulp as pl

from input_validation import validate_input_data
from mms.cost_curves import (
    audit_thermal_cost_curves,
    build_thermal_cost_report,
    generate_pwl_from_quadratic,
    prepare_thermal_cost_curves,
)
from mms.model.thermal_constraints import create_variable_cost_curve_calculation_constraints


def _base_input():
    return {
        "Cost_parameters": {},
        "Other_coefficients": {},
        "constraints": {},
        "optimization_parameters": {"solver": "highs", "big_m": "auto"},
        "Time_granularity": 1,
        "Load_forecast": [0, 10],
        "Generating_Units": [
            {
                "gen_id": 0,
                "comments": "Thermo cost benchmark unit",
                "state": 1,
                "current_Power(MW)": 10,
                "availability": [30],
                "Production_Forecast": [0],
                "max_power(MW)": 30,
                "min_power(MW)": 10,
                "Primary_Active_Power_Reserves(MW)": [0, 0],
                "Secondary_Active_Power_Reserves(MW)": [0, 0],
                "Tertiary_Active_Power_Reserves(MW)": [0, 0],
                "operating-states": [
                    {
                        "id": 0,
                        "isShutdown": False,
                        "isEnabled": True,
                        "isOperational": True,
                        "max-power": 30,
                        "min-power": 10,
                    }
                ],
                "operating-state-transitions": [],
                "state-transitions": [],
                "var_gen_cost(euro/MW)": [[10, 20, 30], [100, 5, 7]],
            }
        ],
    }


class ThermalCostCurveAuditTests(unittest.TestCase):
    """Exercises thermal cost-curve generation, validation, formulation, and reporting paths."""
    def test_convex_incremental_curve_passes_and_reports_segments(self):
        report = audit_thermal_cost_curves(_base_input())

        self.assertEqual("passed", report["status"])
        self.assertEqual(1, report["thermal_unit_count"])
        unit = report["units"][0]
        self.assertEqual("incremental_piecewise_linear", unit["formulation"])
        self.assertEqual([10.0, 20.0, 30.0], unit["breakpoints_mw"])
        self.assertEqual([5.0, 7.0], unit["segment_slopes"])
        self.assertEqual([100.0, 150.0, 220.0], unit["cost_at_breakpoints"])

    def test_nonconvex_and_undercovered_curve_is_warned(self):
        data = _base_input()
        data["Generating_Units"][0]["availability"] = [35]
        data["Generating_Units"][0]["max_power(MW)"] = 35
        data["Generating_Units"][0]["var_gen_cost(euro/MW)"] = [[10, 20, 30], [100, 8, 6]]

        report = audit_thermal_cost_curves(data)

        codes = {issue["code"] for issue in report["issues"]}
        self.assertEqual("warning", report["status"])
        self.assertIn("nonconvex_marginal_costs", codes)
        self.assertIn("cost_curve_does_not_cover_max_power", codes)
        self.assertIn("cost_curve_does_not_cover_availability", codes)

    def test_malformed_curve_fails_input_validation_early(self):
        data = copy.deepcopy(_base_input())
        data["Generating_Units"][0]["var_gen_cost(euro/MW)"] = [[10, 20, 30], [5, 7]]

        report = validate_input_data(data)

        self.assertEqual("failed", report["status"])
        self.assertTrue(any("cost_curve_length_mismatch" in error for error in report["errors"]))

    def test_thermal_cost_report_reconstructs_segment_costs(self):
        output = {
            "Generating_Units": [
                {
                    "gen_id": 0,
                    "Power": [25],
                    "State": [1],
                }
            ]
        }

        report = build_thermal_cost_report(_base_input(), output)

        entry = report["entries"][0]
        self.assertEqual("convex_incremental_pwl", entry["formulation"])
        self.assertEqual(100.0, entry["base_cost"])
        self.assertEqual([10.0, 5.0], [segment["dispatch_mw"] for segment in entry["segments"]])
        self.assertEqual(185.0, entry["total_cost"])
        self.assertEqual(185.0, report["summary"]["thermal_cost"])

    def test_cost_report_supports_hourly_cost_scaling(self):
        data = _base_input()
        data["Time_granularity"] = 30
        data["optimization_parameters"]["cost_curve_time_unit"] = "euro_per_mwh"
        output = {"Generating_Units": [{"Power": [25], "State": [1]}]}

        report = build_thermal_cost_report(data, output)

        self.assertEqual(0.5, report["cost_time_multiplier"])
        self.assertEqual(92.5, report["summary"]["thermal_cost"])

    def test_convex_curve_uses_continuous_incremental_formulation(self):
        prob = pl.LpProblem("convex_cost", pl.LpMinimize)
        power = [[pl.LpVariable("power_0"), pl.LpVariable("power_1")]]
        state = [[pl.LpVariable("state_0"), pl.LpVariable("state_1", 0, 1, cat="Binary")]]

        prob, objective, u_1 = create_variable_cost_curve_calculation_constraints(
            _base_input(),
            prob,
            0,
            power,
            _base_input()["Generating_Units"],
            [0, 1],
            1000,
            state,
            [0],
        )

        prob += objective
        variable_names = {variable.name for variable in prob.variables()}
        self.assertFalse(any(name.startswith("u_1") for name in variable_names))
        self.assertEqual([], u_1[0][1])

    def test_nonconvex_curve_uses_ordered_fill_binaries(self):
        data = _base_input()
        data["Generating_Units"][0]["var_gen_cost(euro/MW)"] = [[10, 20, 30], [100, 8, 6]]
        prob = pl.LpProblem("nonconvex_cost", pl.LpMinimize)
        power = [[pl.LpVariable("power_0"), pl.LpVariable("power_1")]]
        state = [[pl.LpVariable("state_0"), pl.LpVariable("state_1", 0, 1, cat="Binary")]]

        prob, objective, u_1 = create_variable_cost_curve_calculation_constraints(
            data,
            prob,
            0,
            power,
            data["Generating_Units"],
            [0, 1],
            1000,
            state,
            [0],
        )

        prob += objective
        variable_names = {variable.name for variable in prob.variables()}
        self.assertTrue(any(name.startswith("u_1") for name in variable_names))
        self.assertEqual(1, len(u_1[0][1]))

    def test_quadratic_coefficients_generate_secant_pwl_curve(self):
        data = _base_input()
        unit = data["Generating_Units"][0]
        unit.pop("var_gen_cost(euro/MW)")
        unit["quadratic_cost_coefficients"] = {"a": 1.0, "b": 2.0, "c": 3.0}
        unit["cost_curve_generation"] = {"segments": 2}

        generated = generate_pwl_from_quadratic(unit, data)

        self.assertEqual([[10.0, 20.0, 30.0], [123.0, 32.0, 52.0]], generated)

    def test_prepare_thermal_cost_curves_populates_missing_curve(self):
        data = _base_input()
        unit = data["Generating_Units"][0]
        unit.pop("var_gen_cost(euro/MW)")
        unit["quadratic_cost_coefficients"] = {"a": 0.1, "b": 1.0, "c": 0.0}

        report = prepare_thermal_cost_curves(data)

        self.assertEqual("passed", report["status"])
        self.assertEqual(1, report["generated_count"])
        self.assertIn("var_gen_cost(euro/MW)", unit)
        self.assertEqual("generated_from_quadratic", unit["cost_curve_source"]["type"])


if __name__ == "__main__":
    unittest.main()
