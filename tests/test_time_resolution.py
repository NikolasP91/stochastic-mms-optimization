"""Tests for RDAS/DS sub-period time-resolution preprocessing."""

# The comments in this file are intentionally detailed because these tests
# document how the model decides whether a short operating state is represented
# explicitly in the hourly RDAS/DS model or embedded into a direct transition.

import copy  # Provides deepcopy so each test can mutate input data independently.
import unittest  # Provides the test case and assertion framework used below.

# Import the rounding helpers because the bypass decision is coupled to the
# later minute-to-dispatch-period conversion performed by preprocessing.
from mms.model.preprocessing import round_max_time_to_periods, round_min_time_to_periods, time_granularity

# Import the preprocessing function that classifies and embeds transient states.
from mms.model.time_resolution import prepare_operating_state_time_resolution


def _base_unit():
    """Create the smallest thermal-unit topology needed for bypass tests."""
    # Return a new dictionary each time so test cases can safely modify it.
    return {
        # Use the same zero-based generator id convention as the input JSON.
        "gen_id": 0,
        # Mark the unit as thermal/conventional because the feature is meant for conventional operating states.
        "comments": "Thermal Generating Unit",
        # Define three operating states arranged as enabled -> transient candidate -> operational.
        "operating-states": [
            # State 1 is the initial enabled/non-operational state and remains explicit.
            {"id": 1, "isShutdown": False, "isOperational": False, "isEnabled": True},
            # State 2 is the candidate state that may be bypassed if explicitly marked transient.
            {"id": 2, "isShutdown": False, "isOperational": False, "isEnabled": False},
            # State 3 is the destination operational state reached after the transient candidate.
            {"id": 3, "isShutdown": False, "isOperational": True, "isEnabled": False},
        ],
        # Define the directed operating-state arcs used by the bypass logic.
        "operating-state-transitions": [
            {
                # Start from state 1.
                "from": 1,
                # Allow state 1 to enter state 2 with a sub-period destination-side minimum time.
                "transitions": [
                    {"id": 2, "transition-cost": 4, "min-transition-time_b": 25},
                ],
            },
            {
                # Start from the candidate transient state.
                "from": 2,
                # Allow state 2 to continue to state 3 with its own transition cost.
                "transitions": [
                    {"id": 3, "transition-cost": 6},
                ],
            },
            {
                # Start from the operational state.
                "from": 3,
                # Add a return arc so the transition graph remains closed for tests.
                "transitions": [
                    {"id": 1, "transition-cost": 0},
                ],
            },
        ],
        # State-level on/off transitions are irrelevant for these operating-state preprocessing tests.
        "state-transitions": [],
    }


class TimeResolutionPreprocessingTests(unittest.TestCase):
    """Checks sub-period transient-state preprocessing and timing rounding rules."""

    def test_explicit_subperiod_transient_state_is_embedded_into_transition_arc(self):
        # Build a minimal RDAS/DS input with a 60-minute dispatch period.
        input_data = {
            "Time_granularity": 60,
            "optimization_parameters": {},
            "Generating_Units": [_base_unit()],
        }
        # Explicitly label state 2 as a synchronization state, which the default policy treats as transient.
        input_data["Generating_Units"][0]["operating-states"][1]["state_role"] = "synchronization"

        # Run preprocessing on a deepcopy so the original fixture is not changed by the test action.
        prepared = prepare_operating_state_time_resolution(copy.deepcopy(input_data))
        # Read the modified first unit after preprocessing.
        unit = prepared["Generating_Units"][0]
        # Read the structured audit report produced by the preprocessing stage.
        report = prepared["Time_Resolution_Report"]

        # Exactly one operating state should have been embedded.
        self.assertEqual(1, report["embedded_state_count"])
        # Only informational issues should be present, so the report status remains passed.
        self.assertEqual("passed", report["status"])
        # State 2 should no longer appear in the explicit operating-state list.
        self.assertNotIn(2, {state["id"] for state in unit["operating-states"]})
        # State 2 should no longer be used as a source group in the transition list.
        self.assertNotIn(2, {transition["from"] for transition in unit["operating-state-transitions"]})

        # Select the remaining transitions that start at state 1.
        transitions_from_1 = next(
            transition_group["transitions"]
            for transition_group in unit["operating-state-transitions"]
            if transition_group["from"] == 1
        )
        # Find the new direct 1 -> 3 arc that replaced the explicit 1 -> 2 -> 3 path.
        embedded_arc = next(transition for transition in transitions_from_1 if transition["id"] == 3)

        # The direct arc cost should equal the sum of 1 -> 2 and 2 -> 3 transition costs.
        self.assertEqual(10.0, embedded_arc["transition-cost"])
        # The embedded metadata should identify state 2 as the state that was bypassed.
        self.assertEqual(2, embedded_arc["embedded_transient_states"][0]["id"])
        # The metadata should preserve the sub-period timing field that justified embedding.
        self.assertEqual(
            "min-transition-time_b",
            embedded_arc["embedded_transient_states"][0]["timing_minutes"][0]["field"],
        )
        # The mathematical arc should not retain the minute-level field because the state is no longer period-level.
        self.assertNotIn("min-transition-time_b", embedded_arc)

    def test_endpoint_timing_fields_are_attributed_to_correct_state_when_embedding(self):
        # Build a minimal RDAS/DS input with a 60-minute dispatch period.
        input_data = {
            "Time_granularity": 60,
            "optimization_parameters": {},
            "Generating_Units": [_base_unit()],
        }
        # Mark state 2 as transient so the path 1 -> 2 -> 3 can be considered for embedding.
        input_data["Generating_Units"][0]["operating-states"][1]["isTransient"] = True
        # Add a long A-side rule on 1 -> 2. This belongs to source state 1, not candidate state 2.
        input_data["Generating_Units"][0]["operating-state-transitions"][0]["transitions"][0][
            "min-transition-time_a"
        ] = 120
        # Add a long B-side rule on 2 -> 3. This belongs to destination state 3, not candidate state 2.
        input_data["Generating_Units"][0]["operating-state-transitions"][1]["transitions"][0][
            "max-transition-time_b"
        ] = 300

        # Run time-resolution preprocessing.
        prepared = prepare_operating_state_time_resolution(copy.deepcopy(input_data))
        # Read the rewritten first unit.
        unit = prepared["Generating_Units"][0]
        # Select the new direct 1 -> 3 arc created by bypassing state 2.
        transitions_from_1 = next(
            transition_group["transitions"]
            for transition_group in unit["operating-state-transitions"]
            if transition_group["from"] == 1
        )
        embedded_arc = next(transition for transition in transitions_from_1 if transition["id"] == 3)

        # State 2 should still be embedded because only its own timing is tested for sub-period eligibility.
        self.assertEqual(1, prepared["Time_Resolution_Report"]["embedded_state_count"])
        # The predecessor's A-side rule should remain on the direct arc.
        self.assertEqual(120, embedded_arc["min-transition-time_a"])
        # The successor's B-side maximum rule should remain on the direct arc.
        self.assertEqual(300, embedded_arc["max-transition-time_b"])
        # The skipped-state metadata should only include the B-side rule that actually belongs to state 2.
        self.assertEqual(
            ["min-transition-time_b"],
            [item["field"] for item in embedded_arc["embedded_transient_states"][0]["timing_minutes"]],
        )

    def test_duplicate_direct_arc_keeps_transient_state_explicit_with_warning(self):
        # Build a topology that already has a direct 1 -> 3 arc in parallel with 1 -> 2 -> 3.
        input_data = {
            "Time_granularity": 60,
            "optimization_parameters": {},
            "Generating_Units": [_base_unit()],
        }
        input_data["Generating_Units"][0]["operating-states"][1]["isTransient"] = True
        input_data["Generating_Units"][0]["operating-state-transitions"][0]["transitions"].append(
            {"id": 3, "transition-cost": 99}
        )

        # Run preprocessing. The transient state should not be embedded because
        # the direct arc would make it ambiguous which path cost/timing to keep.
        prepared = prepare_operating_state_time_resolution(copy.deepcopy(input_data))
        unit = prepared["Generating_Units"][0]
        report = prepared["Time_Resolution_Report"]

        # State 2 remains explicit, and its transition group remains available to the MIP.
        self.assertIn(2, {state["id"] for state in unit["operating-states"]})
        self.assertIn(2, {transition["from"] for transition in unit["operating-state-transitions"]})
        # No state is embedded, and the audit explains the duplicate direct-arc blocker.
        self.assertEqual(0, report["embedded_state_count"])
        self.assertEqual("warning", report["status"])
        self.assertTrue(
            any(issue["code"] == "transient_state_duplicate_direct_arc" for issue in report["issues"])
        )

    def test_consecutive_transient_states_preserve_full_embedded_metadata_chain(self):
        # Build an input with two consecutive transient states in the path 1 -> 2 -> 3 -> 4.
        input_data = {
            "Time_granularity": 60,
            "optimization_parameters": {},
            "Generating_Units": [
                {
                    "gen_id": 0,
                    "comments": "Thermal Generating Unit",
                    "operating-states": [
                        {"id": 1, "isShutdown": False, "isOperational": False, "isEnabled": True},
                        {
                            "id": 2,
                            "state_role": "synchronization",
                            "isShutdown": False,
                            "isOperational": False,
                            "isEnabled": False,
                        },
                        {
                            "id": 3,
                            "state_role": "startup",
                            "isShutdown": False,
                            "isOperational": False,
                            "isEnabled": False,
                        },
                        {"id": 4, "isShutdown": False, "isOperational": True, "isEnabled": False},
                    ],
                    "operating-state-transitions": [
                        {"from": 1, "transitions": [{"id": 2, "transition-cost": 4, "min-transition-time_b": 10}]},
                        {"from": 2, "transitions": [{"id": 3, "transition-cost": 6, "min-transition-time_b": 20}]},
                        {"from": 3, "transitions": [{"id": 4, "transition-cost": 8, "min-transition-time_b": 30}]},
                        {"from": 4, "transitions": [{"id": 1, "transition-cost": 0}]},
                    ],
                    "state-transitions": [],
                }
            ],
        }

        # Run preprocessing so both transient states can be embedded sequentially.
        prepared = prepare_operating_state_time_resolution(copy.deepcopy(input_data))
        # Read the rewritten unit topology.
        unit = prepared["Generating_Units"][0]
        # Select the final direct 1 -> 4 arc produced after both transient states are bypassed.
        transitions_from_1 = next(
            transition_group["transitions"]
            for transition_group in unit["operating-state-transitions"]
            if transition_group["from"] == 1
        )
        direct_arc = next(transition for transition in transitions_from_1 if transition["id"] == 4)

        # Both transient states should be removed from the explicit operating-state set.
        self.assertEqual({1, 4}, {state["id"] for state in unit["operating-states"]})
        # The direct arc should preserve the total transition cost: 4 + 6 + 8.
        self.assertEqual(18.0, direct_arc["transition-cost"])
        # The final destination-side timing rule should remain on the direct arc for state 4.
        self.assertEqual(30, direct_arc["min-transition-time_b"])
        # The final arc metadata should preserve both skipped states, in path order.
        self.assertEqual(
            [2, 3],
            [state["id"] for state in direct_arc["embedded_transient_states"]],
        )
        # The report should still record that two states were embedded.
        self.assertEqual(2, prepared["Time_Resolution_Report"]["embedded_state_count"])

    def test_unmarked_subperiod_timer_is_reported_but_not_embedded(self):
        # Build the same unit with a 25-minute timer but no explicit transient-state marker.
        input_data = {
            "Time_granularity": 60,
            "optimization_parameters": {},
            "Generating_Units": [_base_unit()],
        }

        # Run preprocessing with the default embed_transient policy.
        prepared = prepare_operating_state_time_resolution(copy.deepcopy(input_data))
        # Read the first generating unit after preprocessing.
        unit = prepared["Generating_Units"][0]
        # Read the audit report that records the treatment of sub-period timing data.
        report = prepared["Time_Resolution_Report"]

        # No state should be embedded because the candidate was not explicitly marked transient.
        self.assertEqual(0, report["embedded_state_count"])
        # The presence of a short minimum timer is informational, not a blocking warning/error.
        self.assertEqual("passed", report["status"])
        # State 2 should remain in the period-level model.
        self.assertIn(2, {state["id"] for state in unit["operating-states"]})
        # The report should still document that a sub-period transition minimum time exists.
        self.assertTrue(
            any(
                issue["code"] == "subperiod_transition_min_time"
                and issue["severity"] == "info"
                and issue["operating_state_id"] == 2
                for issue in report["issues"]
            )
        )

        # Convert remaining minute-based timing values into dispatch-period counts.
        converted = time_granularity(prepared, 60)
        # Select the original 1 -> 2 transition after rounding.
        transition_to_2 = converted["Generating_Units"][0]["operating-state-transitions"][0]["transitions"][0]
        # A 25-minute minimum time rounds up to one 60-minute dispatch period.
        self.assertEqual(1, transition_to_2["min-transition-time_b"])

    def test_is_transient_false_overrides_role_based_transient_default(self):
        # Build a unit where state 2 has a role that would normally be treated as transient.
        input_data = {
            "Time_granularity": 60,
            "optimization_parameters": {},
            "Generating_Units": [_base_unit()],
        }
        # Explicitly choosing false must keep the state period-level even though the role is transient.
        input_data["Generating_Units"][0]["operating-states"][1]["state_role"] = "synchronization"
        input_data["Generating_Units"][0]["operating-states"][1]["isTransient"] = False

        # Run the time-resolution preprocessing.
        prepared = prepare_operating_state_time_resolution(copy.deepcopy(input_data))
        # Read the rewritten unit topology.
        unit = prepared["Generating_Units"][0]

        # No state should be embedded because isTransient is the authoritative user switch.
        self.assertEqual(0, prepared["Time_Resolution_Report"]["embedded_state_count"])
        # The synchronization state should remain available as an explicit operating state.
        self.assertIn(2, {state["id"] for state in unit["operating-states"]})

    def test_ramp_roles_are_not_transient_by_default(self):
        # Build a unit where state 2 has a ramp role but no explicit transient flag.
        input_data = {
            "Time_granularity": 60,
            "optimization_parameters": {},
            "Generating_Units": [_base_unit()],
        }
        # Ramp-up/ramp-down labels describe movement between output levels, not automatic bypass states.
        input_data["Generating_Units"][0]["operating-states"][1]["state_role"] = "rampup"

        # Run preprocessing with the default embed_transient policy.
        prepared = prepare_operating_state_time_resolution(copy.deepcopy(input_data))
        # Read the rewritten unit topology.
        unit = prepared["Generating_Units"][0]

        # The ramp state should remain explicit because rampup is not a transient role.
        self.assertEqual(0, prepared["Time_Resolution_Report"]["embedded_state_count"])
        # State 2 should still be represented in the period-level operating-state list.
        self.assertIn(2, {state["id"] for state in unit["operating-states"]})

    def test_maximum_times_round_down_to_dispatch_periods(self):
        # Minimum-time constraints must round up, so a 25-minute minimum becomes one hourly period.
        self.assertEqual(1, round_min_time_to_periods(25, 60))
        # Maximum-time constraints must round down, so a 25-minute maximum cannot be represented in an hourly model.
        self.assertEqual(0, round_max_time_to_periods(25, 60))
        # An exact 60-minute maximum is represented as one hourly period.
        self.assertEqual(1, round_max_time_to_periods(60, 60))
        # A 119-minute maximum still permits only one complete hourly period.
        self.assertEqual(1, round_max_time_to_periods(119, 60))

        # Build a minimal nested input that covers state, operating-state transition, and on/off transition timers.
        data = {
            "Generating_Units": [
                {
                    # State-level timers exercise min/max and remaining-time conversion.
                    "operating-states": [
                        {
                            "min-time-enabled": 25,
                            "max-time-enabled": 25,
                            "min-time-enabled-left": 25,
                            "max-time-enabled-left": 25,
                        }
                    ],
                    # Operating-state transition timers exercise transition-side conversion.
                    "operating-state-transitions": [
                        {
                            "from": 1,
                            "transitions": [
                                {
                                    "id": 2,
                                    "min-transition-time_b": 25,
                                    "max-transition-time_b": 25,
                                }
                            ],
                        }
                    ],
                    # Unit on/off transition timers exercise the legacy state-transition conversion path.
                    "state-transitions": [
                        {"transitions": {"min-transition-time-left": 25, "min-transition-time": 25}}
                    ],
                }
            ]
        }

        # Apply the same conversion used by the normal optimization pipeline.
        converted = time_granularity(data, 60)
        # Read the converted operating-state fields.
        state = converted["Generating_Units"][0]["operating-states"][0]
        # Read the converted operating-state transition fields.
        transition = converted["Generating_Units"][0]["operating-state-transitions"][0]["transitions"][0]

        # Confirm minimum state dwell time rounds up.
        self.assertEqual(1, state["min-time-enabled"])
        # Confirm maximum state dwell time rounds down.
        self.assertEqual(0, state["max-time-enabled"])
        # Confirm remaining minimum dwell time rounds up.
        self.assertEqual(1, state["min-time-enabled-left"])
        # Confirm remaining maximum dwell time rounds down.
        self.assertEqual(0, state["max-time-enabled-left"])
        # Confirm transition minimum time rounds up.
        self.assertEqual(1, transition["min-transition-time_b"])
        # Confirm transition maximum time rounds down.
        self.assertEqual(0, transition["max-transition-time_b"])

    def test_explicit_transient_state_with_period_level_duration_is_not_embedded(self):
        # Build a base input where state 2 will be explicitly marked as transient.
        input_data = {
            "Time_granularity": 60,
            "optimization_parameters": {},
            "Generating_Units": [_base_unit()],
        }
        # Keep a local reference to the first unit to make the test setup readable.
        unit = input_data["Generating_Units"][0]
        # Mark state 2 as a transient synchronization state.
        unit["operating-states"][1]["state_role"] = "synchronization"
        # Make the relevant duration 90 minutes, which is longer than the 60-minute dispatch period.
        unit["operating-state-transitions"][0]["transitions"][0]["min-transition-time_b"] = 90

        # Run preprocessing.
        prepared = prepare_operating_state_time_resolution(copy.deepcopy(input_data))
        # Read the generated time-resolution report.
        report = prepared["Time_Resolution_Report"]

        # No state should be embedded because the duration is not sub-period.
        self.assertEqual(0, report["embedded_state_count"])
        # State 2 must remain explicit in the model.
        self.assertIn(2, {state["id"] for state in prepared["Generating_Units"][0]["operating-states"]})
        # The report should explain that an explicit transient state was retained because its timing is period-level.
        self.assertTrue(
            any(issue["code"] == "transient_state_not_subperiod" for issue in report["issues"])
        )


if __name__ == "__main__":
    # Allow the file to be executed directly during local debugging.
    unittest.main()
