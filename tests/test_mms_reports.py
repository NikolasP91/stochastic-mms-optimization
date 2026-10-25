"""Tests for MMS dispatch, reserve, and RES-curtailment reports."""

import unittest

from mms.reports import (
    build_dispatch_instructions,
    build_res_curtailment_report,
    build_reserve_monitoring_report,
)


def _sample_input():
    return {
        "Time_granularity": 1,
        "Other_coefficients": {
            "primary_upwards": [[10, 0], [0, 0], 0, 0],
            "primary_downwards": [[5, 0], [0, 0], 0, 0],
            "secondary_upwards": [[0, 0], [0, 0], 0, 0],
            "secondary_downwards": [[0, 0], [0, 0], 0, 0],
            "tertiary_upwards": [[0, 0], [0, 0], 0, 0],
            "tertiary_downwards": [[0, 0], [0, 0], 0, 0],
        },
        "constraints": {
            "APRR_calculations": {
                "calculation-method_upwards": [[1, 0], [0, 0], 0, 0],
                "calculation-method_downwards": [[1, 0], [0, 0], 0, 0],
            }
        },
        "Generating_Units": [
            {
                "gen_id": 0,
                "comments": "Thermo test unit",
                "availability": [20, 20],
                "Production_Forecast": [0, 0],
                "operating-states": [{"id": 0}, {"id": 1}],
            },
            {
                "gen_id": 1,
                "comments": "Wind test unit",
                "availability": [8, 10],
                "Production_Forecast": [8, 10],
                "Accepts_SP": 1,
                "operating-states": [{"id": 0}, {"id": 1}],
            },
        ],
    }


def _sample_output():
    zero_pair = [[0, 0], [0, 0]]
    return {
        "Solution_Status": "Optimal",
        "Generating_Units": [
            {
                "gen_id": 0,
                "Power": [10, 12],
                "State": [1, 1],
                "Startup": [1, 0],
                "Shutdown": [0, 0],
                "Operating-states": [[0, 1], [0, 1]],
                "Primary_Active_Power_Reserves(MW)": [[2, 3], [1, 2]],
                "Secondary_Active_Power_Reserves(MW)": zero_pair,
                "Tertiary_Active_Power_Reserves(MW)": zero_pair,
            },
            {
                "gen_id": 1,
                "Power": [6, 10],
                "State": [1, 1],
                "Startup": [1, 0],
                "Shutdown": [0, 0],
                "Setpoints": [0.75, 1.0],
                "Primary_Active_Power_Reserves(MW)": zero_pair,
                "Secondary_Active_Power_Reserves(MW)": zero_pair,
                "Tertiary_Active_Power_Reserves(MW)": zero_pair,
            },
        ],
        "primary_upwards_APRV": [0, 0],
        "primary_downwards_APRV": [0, 0],
        "secondary_upwards_APRV": [0, 0],
        "secondary_downwards_APRV": [0, 0],
        "tertiary_upwards_APRV": [0, 0],
        "tertiary_downwards_APRV": [0, 0],
    }


class MmsReportTests(unittest.TestCase):
    """Covers dispatch instructions, reserve monitoring, and RES curtailment reports."""
    def test_dispatch_instructions_are_created_per_unit_period(self):
        report = build_dispatch_instructions(_sample_input(), _sample_output())
        self.assertEqual(report["scope"], "DS")
        self.assertEqual(report["rtd_scope"], "excluded")
        self.assertEqual(len(report["instructions"]), 4)
        self.assertEqual(report["instructions"][0]["commitment_action"], "synchronize")
        self.assertEqual(report["instructions"][0]["operating_state_id"], 1)

    def test_reserve_monitoring_reproduces_requirement_formula(self):
        report = build_reserve_monitoring_report(_sample_input(), _sample_output())
        primary_up = report["periods"][0]["reserves"]["primary"]["upwards"]
        self.assertEqual(primary_up["required_mw"], 1.6)
        self.assertEqual(primary_up["provided_mw"], 2.0)
        self.assertEqual(primary_up["status"], "ok")
        self.assertEqual(primary_up["active_method"], "total_generation_percent")

    def test_res_curtailment_report_summarizes_unabsorbed_res(self):
        report = build_res_curtailment_report(_sample_input(), _sample_output())
        first_res_entry = report["entries"][0]
        self.assertEqual(first_res_entry["curtailed_mw"], 2.0)
        self.assertEqual(first_res_entry["setpoint"], 0.75)
        self.assertEqual(report["summary"]["curtailed_mwh"], 2.0)


if __name__ == "__main__":
    unittest.main()
