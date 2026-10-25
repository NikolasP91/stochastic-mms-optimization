"""Behavioral tests for operating-state and unit time-constraint families."""

# The comments in this file are intentionally analytical because each test is a
# small proof-by-example for one mathematical timing constraint family.

import unittest  # Supplies the TestCase base class and assertion methods.

import pulp as pl  # Supplies the PuLP variables, problems, and HiGHS solver wrapper used in the tests.

# Import the exact constraint builders under test so these scenarios exercise
# the same algebra used by the production optimization model.
from mms.model.operating_states import (
    create_min_transition_time_between_states_constraints_a,
    create_min_transition_time_between_states_constraints_b,
    create_operating_state_max_transition_time_between_states_constraints_b,
    create_state_min_time_constraints,
)


def _cost_parameters():
    """Return large but finite penalties for every timing-slack family used here."""
    # Each key mirrors a slack-variable family created by the timing constraints.
    return {
        # Penalty for remaining on/off state-transition time at the beginning of the horizon.
        "x_min_transition_states_left": 1000,
        # Penalty for new on/off state-transition minimum-time violations inside the horizon.
        "x_min_transition_states": 1000,
        # Penalty for remaining source-side operating-state transition minimum time.
        "x_min_transition_oper_states_a_left": 1000,
        # Penalty for new source-side operating-state transition minimum-time violations.
        "x_min_transition_oper_states_a": 1000,
        # Penalty for remaining destination-side operating-state transition minimum time.
        "x_min_transition_oper_states_b_left": 1000,
        # Penalty for new destination-side operating-state transition minimum-time violations.
        "x_min_transition_oper_states_b": 1000,
        # Penalty for remaining transition-specific maximum destination dwell-time violations.
        "x_max_oper_state_time_b_left": 1000,
        # Penalty for new transition-specific maximum destination dwell-time violations.
        "x_max_oper_state_time_b": 1000,
    }


def _input_data():
    """Wrap timing-penalty coefficients in the same structure used by production code."""
    # Return only the Cost_parameters branch because these isolated tests need no other input sections.
    return {"Cost_parameters": _cost_parameters()}


def _fixed_binary(prob, name, value):
    """Create a binary variable and immediately fix it to the requested value."""
    # Create a binary decision variable with the supplied test-readable name.
    variable = pl.LpVariable(name, lowBound=0, upBound=1, cat="Binary")
    # Add an equality constraint that forces the variable to the desired schedule value.
    prob += variable == int(value)
    # Return the fixed variable so the constraint builder can use it exactly as it would use a model variable.
    return variable


def _fixed_binary_matrix(prob, prefix, unit_count, intervals, values_by_unit):
    """Create a unit-by-time matrix of fixed binary variables."""
    # Return one list per unit and one fixed variable per interval.
    return [
        [
            # Use zero as the default so omitted time steps are explicitly fixed off.
            _fixed_binary(prob, f"{prefix}_{unit_index + 1}_{t}", values_by_unit[unit_index].get(t, 0))
            for t in intervals
        ]
        for unit_index in range(unit_count)
    ]


def _fixed_operating_state_variables(prob, intervals, schedule_by_state):
    """Create the operating-state binary dictionary expected by constraint builders."""
    # The production model keys operating-state variables by unit index, time, and operating-state id.
    return {
        # Use unit index 0 and the production-style variable name u_2_1_t_state.
        (0, t, state_id): _fixed_binary(prob, f"u_2_1_{t}_{state_id}", schedule_by_state[state_id].get(t, 0))
        for state_id in schedule_by_state
        for t in intervals
    }


def _solve(prob, objective_terms):
    """Solve the small test problem and fail fast if the forced schedule is infeasible."""
    # Attach the slack-penalty objective returned by the constraint builder.
    prob += objective_terms
    # Solve with HiGHS and no console messages so the unit-test output stays focused.
    prob.solve(pl.HiGHS(msg=False))
    # Convert the PuLP numeric status into text and require a clean optimum.
    if pl.LpStatus[prob.status] != "Optimal":
        # Raise an assertion that reports the solver status if any fixture is malformed.
        raise AssertionError(f"Expected Optimal, got {pl.LpStatus[prob.status]}")


def _value(prob, variable_name):
    """Read one solved variable by name."""
    # PuLP stores variables in a dictionary keyed by the exact string name used at creation.
    return prob.variablesDict()[variable_name].value()


def _sum_values(prob, prefix):
    """Sum all solved variable values whose names start with a common prefix."""
    # This helper checks all slacks in one family when the exact indexed members are not individually important.
    return sum(
        variable.value() or 0
        for variable_name, variable in prob.variablesDict().items()
        if variable_name.startswith(prefix)
    )


class TimeConstraintScenarioTests(unittest.TestCase):
    """Uses small forced schedules to verify timing-constraint families."""

    def test_state_minimum_time_slacks_cover_initial_startup_and_shutdown_windows(self):
        # Use six hourly periods so both startup and shutdown windows fit in the miniature horizon.
        intervals = [0, 1, 2, 3, 4, 5]
        # Create a minimization problem whose objective will be the timing slack penalties.
        prob = pl.LpProblem("state_minimum_time_scenario", pl.LpMinimize)
        # Define one unit with on/off state-transition minimum-time metadata.
        data = [
            {
                "gen_id": 0,
                "state-transitions": [
                    # The first transition includes one remaining period at the start plus a two-period rule.
                    {"from": 0, "transitions": {"min-transition-time-left": 1, "min-transition-time": 2}},
                    # The second transition has no remaining time but still has a two-period rule.
                    {"from": 1, "transitions": {"min-transition-time-left": 0, "min-transition-time": 2}},
                ],
            }
        ]
        # Force the unit on/off state sequence: off, off, on, off, off, on.
        state = _fixed_binary_matrix(prob, "state", 1, intervals, [{1: 0, 2: 1, 3: 0, 4: 0, 5: 1}])
        # Force a startup at interval 2.
        startup = _fixed_binary_matrix(prob, "startup", 1, intervals, [{2: 1}])
        # Force a shutdown at interval 4.
        shutdown = _fixed_binary_matrix(prob, "shutdown", 1, intervals, [{4: 1}])

        # Add the on/off state minimum-time constraints to the test problem.
        prob, objective_terms = create_state_min_time_constraints(
            prob, 0, _input_data(), data, state, intervals, startup, shutdown
        )

        # Solve the forced schedule to let the constraint slacks take their required values.
        _solve(prob, objective_terms)

        # The initial remaining-time rule should require one left-side slack unit.
        self.assertEqual(1, _value(prob, "s_min_state_b_left_1_1"))
        # The forced startup/shutdown pattern should require two in-horizon slack units.
        self.assertEqual(2, _sum_values(prob, "s_min_state_b_1_1_"))

    def test_min_transition_time_a_blocks_departure_from_source_state_too_soon(self):
        # Use five periods so the source state can be entered and exited twice.
        intervals = [0, 1, 2, 3, 4]
        # Create a minimization problem for source-side transition minimum time.
        prob = pl.LpProblem("transition_minimum_time_a_scenario", pl.LpMinimize)
        # Define one allowed transition 1 -> 2 with A-side timing requirements.
        data = [
            {
                "gen_id": 0,
                "operating-state-transitions": [
                    {
                        "from": 1,
                        "transitions": [
                            {
                                "id": 2,
                                "min-transition-time-left_a": 1,
                                "min-transition-time_a": 2,
                            }
                        ],
                    }
                ],
            }
        ]
        # Force state 1 to be left too early at the beginning and after a later entry.
        u_2_dict = _fixed_operating_state_variables(
            prob,
            intervals,
            {
                1: {0: 1, 1: 0, 2: 1, 3: 0, 4: 0},
                2: {0: 0, 1: 1, 2: 0, 3: 1, 4: 1},
            },
        )

        # Add constraints requiring the source state to persist long enough before departure.
        prob, objective_terms = create_min_transition_time_between_states_constraints_a(
            prob, 0, _input_data(), data, u_2_dict, intervals
        )

        # Solve the forced schedule.
        _solve(prob, objective_terms)

        # One left-side slack is needed because state 1 is not held at interval 1.
        self.assertEqual(1, _value(prob, "s_min_a_left_1_1"))
        # One in-horizon A-side slack is needed after entering state 1 at interval 2.
        self.assertEqual(1, _value(prob, "s_min_a_1_1_3"))

    def test_min_transition_time_a_left_counts_remaining_protected_periods(self):
        # Use six periods so a three-period residual source-side obligation can be observed completely.
        intervals = [0, 1, 2, 3, 4, 5]
        # Create a minimization problem for inherited source-side transition minimum time.
        prob = pl.LpProblem("transition_minimum_time_a_left_duration_scenario", pl.LpMinimize)
        # Define one allowed transition 1 -> 2 with three dispatch periods still owed at the horizon start.
        data = [
            {
                "gen_id": 0,
                "operating-state-transitions": [
                    {
                        "from": 1,
                        "transitions": [
                            {
                                "id": 2,
                                "min-transition-time-left_a": 3,
                                "min-transition-time_a": 0,
                            }
                        ],
                    }
                ],
            }
        ]
        # Force an immediate departure from source state 1 into state 2 at period 1.
        u_2_dict = _fixed_operating_state_variables(
            prob,
            intervals,
            {
                1: {0: 1, 1: 0, 2: 0, 3: 0, 4: 0, 5: 0},
                2: {0: 0, 1: 1, 2: 1, 3: 1, 4: 1, 5: 1},
            },
        )

        # Add the A-side timing constraints.
        prob, objective_terms = create_min_transition_time_between_states_constraints_a(
            prob, 0, _input_data(), data, u_2_dict, intervals
        )

        # Solve the forced schedule.
        _solve(prob, objective_terms)

        # Leaving immediately with three periods left should create three protected-period violations.
        self.assertEqual(3, _sum_values(prob, "s_min_a_left_1_"))
        # The violation should be charged for every protected period and stop after the residual window ends.
        self.assertEqual(1, _value(prob, "s_min_a_left_1_1"))
        self.assertEqual(1, _value(prob, "s_min_a_left_1_2"))
        self.assertEqual(1, _value(prob, "s_min_a_left_1_3"))
        self.assertEqual(0, _value(prob, "s_min_a_left_1_4"))

    def test_min_transition_time_a_counts_remaining_periods_after_early_departure(self):
        # Use six periods so a four-period source-side minimum time can be violated for three periods.
        intervals = [0, 1, 2, 3, 4, 5]
        # Create a minimization problem for in-horizon source-side transition minimum time.
        prob = pl.LpProblem("transition_minimum_time_a_duration_scenario", pl.LpMinimize)
        # Define one allowed transition 1 -> 2 with four periods of A-side protection after entering state 1.
        data = [
            {
                "gen_id": 0,
                "operating-state-transitions": [
                    {
                        "from": 1,
                        "transitions": [
                            {
                                "id": 2,
                                "min-transition-time_a": 4,
                            }
                        ],
                    }
                ],
            }
        ]
        # Force entry into source state 1 at period 1, then force departure to state 2 at period 2.
        u_2_dict = _fixed_operating_state_variables(
            prob,
            intervals,
            {
                1: {0: 0, 1: 1, 2: 0, 3: 0, 4: 0, 5: 0},
                2: {0: 1, 1: 0, 2: 1, 3: 1, 4: 1, 5: 1},
            },
        )

        # Add the A-side timing constraints.
        prob, objective_terms = create_min_transition_time_between_states_constraints_a(
            prob, 0, _input_data(), data, u_2_dict, intervals
        )

        # Solve the forced schedule.
        _solve(prob, objective_terms)

        # Leaving at period 2 with protection owed through period 4 creates three missing-period slacks.
        self.assertEqual(3, _sum_values(prob, "s_min_a_1_1_"))
        self.assertEqual(1, _value(prob, "s_min_a_1_1_2"))
        self.assertEqual(1, _value(prob, "s_min_a_1_1_3"))
        self.assertEqual(1, _value(prob, "s_min_a_1_1_4"))
        self.assertEqual(0, _value(prob, "s_min_a_1_1_5"))

    def test_min_transition_time_b_requires_destination_state_to_persist(self):
        # Use five periods to test destination-side persistence after arrival.
        intervals = [0, 1, 2, 3, 4]
        # Create a minimization problem for destination-side transition minimum time.
        prob = pl.LpProblem("transition_minimum_time_b_scenario", pl.LpMinimize)
        # Define one allowed transition 1 -> 2 with B-side timing requirements.
        data = [
            {
                "gen_id": 0,
                "operating-state-transitions": [
                    {
                        "from": 1,
                        "transitions": [
                            {
                                "id": 2,
                                "min-transition-time-left_b": 1,
                                "min-transition-time_b": 3,
                            }
                        ],
                    }
                ],
            }
        ]
        # Force state 2 to appear briefly at interval 2 and then disappear, violating B-side persistence.
        u_2_dict = _fixed_operating_state_variables(
            prob,
            intervals,
            {
                1: {0: 0, 1: 1, 2: 0, 3: 1, 4: 1},
                2: {0: 0, 1: 0, 2: 1, 3: 0, 4: 0},
            },
        )

        # Add constraints requiring the destination state to remain active after a transition.
        prob, objective_terms = create_min_transition_time_between_states_constraints_b(
            prob, 0, _input_data(), data, u_2_dict, intervals
        )

        # Solve the forced schedule.
        _solve(prob, objective_terms)

        # One left-side slack is needed because the destination state is not active in the first remaining window.
        self.assertEqual(1, _value(prob, "s_min_b_left_1_1"))
        # Two in-horizon B-side slack units are needed because a three-period stay is violated.
        self.assertEqual(2, _sum_values(prob, "s_min_b_1_1_"))

    def test_max_transition_time_b_detects_destination_state_overstay(self):
        # Use five periods so a destination state can exceed a two-period transition-specific limit.
        intervals = [0, 1, 2, 3, 4]
        # Create a problem for transition-specific B-side maximum timing constraints.
        transition_prob = pl.LpProblem("transition_max_operating_time_b_scenario", pl.LpMinimize)
        # Define a transition into state 5 with transition-specific maximum B-side timing metadata.
        transition_data = [
            {
                "gen_id": 0,
                "operating-states": [
                    # State 4 is the source state for the tested transition.
                    {"id": 4, "isEnabled": False},
                    # State 5 is the destination state whose stay is capped.
                    {"id": 5, "isEnabled": True},
                ],
                "operating-state-transitions": [
                    {
                        "from": 4,
                        "transitions": [
                            {
                                "id": 5,
                                "max-transition-time-left_b": 1,
                                "max-transition-time_b": 2,
                            }
                        ],
                    }
                ],
            }
        ]
        # Force state 5 to remain active three periods after entering from state 4.
        transition_u_2 = _fixed_operating_state_variables(
            transition_prob,
            intervals,
            {
                4: {0: 1, 1: 0, 2: 0, 3: 0, 4: 0},
                5: {0: 0, 1: 1, 2: 1, 3: 1, 4: 0},
            },
        )

        # Add transition-specific maximum B-side dwell constraints.
        transition_prob, transition_objective = create_operating_state_max_transition_time_between_states_constraints_b(
            transition_prob, 0, _input_data(), transition_data, transition_u_2, len(intervals), intervals
        )
        # Solve the transition-specific maximum-time scenario.
        _solve(transition_prob, transition_objective)

        # Two left-side B-family slacks are needed because state 5 exceeds a one-period inherited limit.
        self.assertEqual(2, _sum_values(transition_prob, "s_max_oper_state_time_b_left_"))
        self.assertEqual(1, _value(transition_prob, "s_max_oper_state_time_b_left_1_4_5_2"))
        self.assertEqual(1, _value(transition_prob, "s_max_oper_state_time_b_left_1_4_5_3"))
        # One in-horizon B-family slack is needed when state 5 overstays after transition.
        self.assertEqual(1, _value(transition_prob, "s_max_oper_state_time_b_1_1_4_5_3"))

    def test_max_transition_time_b_counts_every_excess_period(self):
        # Use six periods so a two-period maximum stay can be exceeded by three periods.
        intervals = [0, 1, 2, 3, 4, 5]
        # Create a problem for transition-specific B-side maximum timing constraints.
        prob = pl.LpProblem("transition_max_operating_time_b_duration_scenario", pl.LpMinimize)
        # Define a transition 4 -> 5 with a two-period maximum stay in destination state 5.
        data = [
            {
                "gen_id": 0,
                "operating-states": [
                    {"id": 4, "isEnabled": False},
                    {"id": 5, "isEnabled": False},
                ],
                "operating-state-transitions": [
                    {
                        "from": 4,
                        "transitions": [
                            {
                                "id": 5,
                                "max-transition-time_b": 2,
                            }
                        ],
                    }
                ],
            }
        ]
        # Force a transition from state 4 into state 5 at period 1 and keep state 5 active through period 5.
        u_2_dict = _fixed_operating_state_variables(
            prob,
            intervals,
            {
                4: {0: 1, 1: 0, 2: 0, 3: 0, 4: 0, 5: 0},
                5: {0: 0, 1: 1, 2: 1, 3: 1, 4: 1, 5: 1},
            },
        )

        # Add transition-specific maximum B-side dwell constraints.
        prob, objective_terms = create_operating_state_max_transition_time_between_states_constraints_b(
            prob, 0, _input_data(), data, u_2_dict, len(intervals), intervals
        )

        # Solve the forced schedule.
        _solve(prob, objective_terms)

        # Periods 3, 4, and 5 exceed the two-period maximum stay and each receives one slack.
        self.assertEqual(3, _sum_values(prob, "s_max_oper_state_time_b_1_"))
        self.assertEqual(1, _value(prob, "s_max_oper_state_time_b_1_1_4_5_3"))
        self.assertEqual(1, _value(prob, "s_max_oper_state_time_b_1_1_4_5_4"))
        self.assertEqual(1, _value(prob, "s_max_oper_state_time_b_1_1_4_5_5"))


if __name__ == "__main__":
    # Allow this test module to run directly from the command line.
    unittest.main()
