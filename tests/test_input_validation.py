"""Tests for input validation errors and warnings."""

import copy
import json
import unittest
from pathlib import Path

from input_validation import validate_input_data


ROOT = Path(__file__).resolve().parents[1]
INPUT_PATH = ROOT / "v2.1_last_real_values_RDAS_60_FAT---test-case_BIOMASS.json"


class InputValidationTests(unittest.TestCase):
    """Checks input validation failures, warnings, and accepted project data."""
    def test_project_input_passes_validation(self):
        with INPUT_PATH.open(encoding="utf-8") as f:
            data = json.load(f)
        report = validate_input_data(data)
        self.assertEqual(report["errors"], [])

    def test_bad_load_length_fails_validation(self):
        with INPUT_PATH.open(encoding="utf-8") as f:
            data = json.load(f)
        bad_data = copy.deepcopy(data)
        bad_data["Generating_Units"][0]["availability"] = [1, 2, 3]
        report = validate_input_data(bad_data)
        self.assertEqual(report["status"], "failed")
        self.assertTrue(any("availability" in error for error in report["errors"]))

    def test_noncontiguous_ids_are_warned(self):
        with INPUT_PATH.open(encoding="utf-8") as f:
            data = json.load(f)
        warned_data = copy.deepcopy(data)
        warned_data["Generating_Units"][0]["gen_id"] = 99
        report = validate_input_data(warned_data)
        self.assertTrue(report["warnings"])

    def test_rtd_run_mode_is_rejected(self):
        with INPUT_PATH.open(encoding="utf-8") as f:
            data = json.load(f)
        rtd_data = copy.deepcopy(data)
        rtd_data["run_mode"] = "RTD"
        report = validate_input_data(rtd_data)
        self.assertEqual(report["status"], "failed")
        self.assertTrue(any("RTD" in error for error in report["errors"]))

    def test_bad_time_resolution_policy_fails_validation(self):
        with INPUT_PATH.open(encoding="utf-8") as f:
            data = json.load(f)
        bad_data = copy.deepcopy(data)
        bad_data.setdefault("optimization_parameters", {}).setdefault("time_resolution", {})[
            "subperiod_operating_state_policy"
        ] = "unknown"

        report = validate_input_data(bad_data)

        self.assertEqual(report["status"], "failed")
        self.assertTrue(any("subperiod_operating_state_policy" in error for error in report["errors"]))

    def test_operating_state_is_transient_must_be_boolean(self):
        with INPUT_PATH.open(encoding="utf-8") as f:
            data = json.load(f)
        bad_data = copy.deepcopy(data)
        bad_data["Generating_Units"][0]["operating-states"][0]["isTransient"] = "false"

        report = validate_input_data(bad_data)

        self.assertEqual(report["status"], "failed")
        self.assertTrue(any("isTransient" in error for error in report["errors"]))

    def test_thermal_desynchronization_state_is_connected_nonoperational(self):
        with INPUT_PATH.open(encoding="utf-8") as f:
            data = json.load(f)

        thermal_units = [
            unit for unit in data["Generating_Units"]
            if unit["comments"].startswith("Thermo:")
        ]
        self.assertGreaterEqual(len(thermal_units), 1)

        for unit in thermal_units:
            states = {state["id"]: state for state in unit["operating-states"]}
            desync_state = next(
                state for state in unit["operating-states"]
                if state.get("state_role") == "desynchronization"
            )
            reference_state = states[3]

            self.assertFalse(desync_state["isShutdown"])
            self.assertFalse(desync_state["isOperational"])
            self.assertEqual(reference_state["min-power"], desync_state["min-power"])
            self.assertEqual(reference_state["max-power"], desync_state["max-power"])

            operational_state = next(
                state for state in unit["operating-states"] if state["isOperational"]
            )
            transitions = {
                transition["from"]: transition["transitions"]
                for transition in unit["operating-state-transitions"]
            }
            self.assertTrue(
                any(target["id"] == desync_state["id"] for target in transitions[operational_state["id"]])
            )
            self.assertTrue(
                any(states[target["id"]]["isShutdown"] for target in transitions[desync_state["id"]])
            )

    def test_multiple_operational_states_fail_validation(self):
        with INPUT_PATH.open(encoding="utf-8") as f:
            data = json.load(f)
        bad_data = copy.deepcopy(data)
        bad_data["Generating_Units"][0]["operating-states"][0]["isOperational"] = True

        report = validate_input_data(bad_data)

        self.assertEqual(report["status"], "failed")
        self.assertTrue(any("multiple isOperational=true" in error for error in report["errors"]))


if __name__ == "__main__":
    unittest.main()
