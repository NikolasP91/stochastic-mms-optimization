"""Operating-state variables, transition arcs, and active timing constraints.

This module builds the operating-state part of the unit-commitment model. It
does three different jobs:

1. It creates one binary variable for every unit, interval, and operating
   state. Exactly one operating state must be selected for each unit in each
   modeled dispatch interval.
2. It restricts how units may move between operating states by using the
   transition graph defined in the input JSON.
3. It adds the accepted timing constraints: one unit-level minimum on/off time
   constraint and three operating-state transition timing constraints.

The suffixes used in the input names follow the project convention:

* ``_a`` timing is source-side timing. It protects the state being left.
* ``_b`` timing is destination-side timing. It protects the state being entered.
* ``_left`` timing represents residual time already owed at the beginning of
  the optimization horizon because the unit entered that state before period 1.
"""

import copy

import pulp as pl


def create_operating_states_power_levels_constraints(input_data, prob, objective_terms, power, state, data, intervals, CONV, RES, PV, M):
    """Create operating-state variables and link them to dispatch power.

    For each generating unit, each dispatch interval, and each operating state
    listed in the input JSON, this function creates the binary variable
    ``u_2_dict[(gen_id, t, operating_state_id)]``. A value of 1 means that the
    unit is in that specific operating state during interval ``t``.

    The function also:

    * fixes the initial operating state at ``t = 0`` from the ``isEnabled``
      flags in the input;
    * adds the operating-state enabled cost to the objective for modeled
      dispatch intervals ``intervals[1:]``;
    * enforces exactly one operating state per unit and dispatch interval;
    * links the selected operating state to the unit's minimum and maximum
      power limits for that interval;
    * derives the unit-level online/offline binary ``state`` from all operating
      states marked as ``isShutdown``.

    ``CONV``, ``RES``, ``PV``, and ``M`` are kept in the signature because this
    function is called from the wider model-building pipeline, although the
    operating-state power-linking logic itself only needs ``data``, ``power``,
    ``state``, and ``intervals``.
    """
    u_2_dict = {}
    shutdown_states = {}

    # First pass: create one binary operating-state selector per unit, interval,
    # and operating state. At the same time, keep a list of the operating states
    # that represent shutdown so that the aggregate unit-level state can be
    # computed later.
    for gen in data:
        gen_id = gen['gen_id']
        for operating_state in gen['operating-states']:
            operating_state_id = operating_state['id']
            if operating_state['isShutdown']:
                if gen_id not in shutdown_states:
                    shutdown_states[gen_id] = []
                shutdown_states[gen_id].append(operating_state_id)

            for t in intervals:
                key = (gen_id, t, operating_state_id)
                u_2_dict[key] = pl.LpVariable(
                    name=f'u_2_{key[0] + 1}_{key[1]}_{key[2]}',
                    lowBound=0,
                    upBound=1,
                    cat='Binary',
                )

    # Second pass: fix the initial operating state and account for the cost of
    # being in each operating state during each modeled dispatch interval.
    for gen in data:
        gen_id = gen['gen_id']
        for operating_state in gen['operating-states']:
            operating_state_id = operating_state['id']
            if operating_state['isEnabled']:
                prob += u_2_dict[(gen_id, 0, operating_state_id)] == 1
            else:
                prob += u_2_dict[(gen_id, 0, operating_state_id)] == 0

            for t in intervals[1:]:
                objective_terms += (
                        operating_state['enabled-cost']
                        * u_2_dict[(gen_id, t, operating_state_id)]
                        * input_data["Time_granularity"]
                )

    # Third pass: enforce the core operating-state physics. The selected
    # operating state determines the feasible power range, exactly one state is
    # active, and the unit-level online/offline binary follows from whether the
    # selected operating state is a shutdown state.
    for gen in data:
        gen_id = gen['gen_id']
        for t in intervals[1:]:
            prob += power[gen_id][t] <= pl.lpSum(
                u_2_dict[(gen_id, t, operating_state['id'])] * operating_state['max-power'][t - 1]
                for operating_state in gen['operating-states']
            )
            prob += power[gen_id][t] >= pl.lpSum(
                u_2_dict[(gen_id, t, operating_state['id'])] * operating_state['min-power'][t - 1]
                for operating_state in gen['operating-states']
            )
            prob += pl.lpSum(
                u_2_dict[(gen_id, t, operating_state['id'])]
                for operating_state in gen['operating-states']
            ) == 1
            prob += state[gen_id][t] == 1 - pl.lpSum(
                u_2_dict[(gen_id, t, oper_id)]
                for oper_id in shutdown_states[gen_id]
            )

    return prob, objective_terms, u_2_dict, shutdown_states


def create_allowed_operating_states_transition_constraints(prob, obj, data, intervals, u_2_dict, M):
    """Enforce the allowed operating-state transition graph.

    The input JSON provides, for each source operating state, the list of
    destination operating states that may be reached in the next dispatch
    interval. This function translates that graph into transition-arc variables.

    For a transition from state ``A`` at interval ``t - 1`` to state ``B`` at
    interval ``t``, the variable
    ``transition_arc[(gen_id, t, A, B)]`` becomes 1 only when both endpoint
    operating-state variables are active. The three inequalities around each
    arc are the standard linearization of a binary AND relation:

    * arc <= source-state binary;
    * arc <= destination-state binary;
    * arc >= source + destination - 1.

    The final equality for each source state forces every active source state
    to choose exactly one outgoing arc. A self-transition is always added with
    zero cost so that a unit may remain in the same operating state when the
    input graph does not explicitly list a self-loop.

    This function does not impose minimum or maximum dwell times. It only
    controls which one-period transitions are allowed and charges transition
    costs. The timing restrictions are added by the separate functions below.
    ``M`` remains in the signature for compatibility with the model pipeline.
    """
    transition_arc = {}
    for gen in data:
        gen_id = gen['gen_id']
        for allowed_transition in gen['operating-state-transitions']:
            from_oper_state_id = allowed_transition['from']
            to_oper_states = {
                to_oper_state_data['id']: to_oper_state_data.get('transition-cost', 0)
                for to_oper_state_data in allowed_transition['transitions']
            }
            to_oper_states.setdefault(from_oper_state_id, 0)

            for t in intervals[1:]:
                arcs_from_state = []
                for to_oper_state_id, transition_cost in to_oper_states.items():
                    key = (gen_id, t, from_oper_state_id, to_oper_state_id)
                    # Transition arc for the movement from the source state at
                    # t - 1 to the destination state at t.
                    transition_arc[key] = pl.LpVariable(
                        name=f'transition_arc_{gen_id + 1}_{t}_{from_oper_state_id}_{to_oper_state_id}',
                        lowBound=0,
                        upBound=1,
                    )
                    arcs_from_state.append(transition_arc[key])
                    # Binary AND linearization: the arc can be 1 only if both
                    # endpoint operating-state binaries are selected.
                    prob += transition_arc[key] <= u_2_dict[(gen_id, t - 1, from_oper_state_id)]
                    prob += transition_arc[key] <= u_2_dict[(gen_id, t, to_oper_state_id)]
                    prob += transition_arc[key] >= (
                            u_2_dict[(gen_id, t - 1, from_oper_state_id)]
                            + u_2_dict[(gen_id, t, to_oper_state_id)]
                            - 1
                    )
                    obj += transition_cost * transition_arc[key]

                # If the unit is in the source state at t - 1, exactly one
                # outgoing transition from that source must be selected.
                prob += pl.lpSum(arcs_from_state) == u_2_dict[(gen_id, t - 1, from_oper_state_id)]

    return prob, obj


def _finite_max_time(value, dispatch_period_count):
    """Normalize max-time input values before constraints are created.

    Maximum-time constraints are meaningful only when the limit is finite,
    positive, and short enough to bind inside the current optimization horizon.
    This helper converts the input value to an integer dispatch-period count and
    returns ``None`` when the value should be ignored.

    A value is ignored when:

    * it is ``float('inf')``;
    * it is zero or negative;
    * it is greater than or equal to the number of modeled dispatch periods,
      because such a limit cannot be violated inside the solved horizon.
    """
    if value == float('inf'):
        return None
    limit = int(value)
    if limit <= 0 or limit >= dispatch_period_count:
        return None
    return limit


def create_operating_state_max_transition_time_between_states_constraints_b(
    prob, objective_terms, input_data, data, u_2_dict, IntervalCount, intervals
):
    """Add soft destination-side maximum-time limits for operating-state B.

    This function implements the operating-state transition constraint driven by
    the input fields ``max-transition-time_b`` and
    ``max-transition-time-left_b``. It is called "B-side" because the timing
    limit applies to the destination operating state of an allowed transition:
    after a unit enters destination state ``B`` from source state ``A``, it must
    not remain in ``B`` longer than the allowed number of dispatch periods.

    Two cases are modeled:

    * ``max-transition-time-left_b`` covers the beginning of the horizon. It is
      used when the unit was already in the destination state before the
      optimization horizon started and some maximum-time obligation remains. An
      overstay is charged for every excess period in the initial continuous
      destination-state stretch.
    * ``max-transition-time_b`` covers transitions that occur inside the
      optimization horizon. Whenever the model moves from ``A`` at ``t - 1`` to
      ``B`` at ``t``, the unit may remain in ``B`` only for the specified number
      of periods. If the continuous stay in ``B`` exceeds that maximum, slack is
      charged for every excess period.

    The constraints are soft. If the input data and other requirements make the
    timing rule impossible to satisfy, binary slack variables can relax the rule
    and the corresponding penalty terms are added to the objective:

    * ``s_max_oper_state_time_b_left`` for residual left-time violations;
    * ``s_max_oper_state_time_b_1`` for in-horizon maximum-time violations.

    ``IntervalCount`` remains in the signature for compatibility with the
    historical model interface; this implementation uses ``intervals`` directly.
    """
    s_max_oper_state_time_b_left = {}
    s_max_oper_state_time_b_1 = {}
    dispatch_period_count = len(intervals) - 1

    # Create only the slack variables that can actually be needed. Infinite,
    # zero, negative, or horizon-long max-time values are filtered out by
    # _finite_max_time and therefore produce no constraints or slack variables.
    for gen in data:
        gen_id = gen['gen_id']
        for allowed_transition in gen['operating-state-transitions']:
            from_oper_state_id = allowed_transition['from']
            for next_state in allowed_transition['transitions']:
                next_state_id = next_state['id']
                if from_oper_state_id == next_state_id:
                    continue

                max_time_left = _finite_max_time(
                    next_state.get('max-transition-time-left_b', 100000000000),
                    dispatch_period_count,
                )
                max_time = _finite_max_time(
                    next_state.get('max-transition-time_b', 100000000000),
                    dispatch_period_count,
                )
                if max_time_left is None and max_time is None:
                    continue

                for t in intervals:
                    key = (gen_id, from_oper_state_id, next_state_id, t)
                    if max_time_left is not None:
                        s_max_oper_state_time_b_left[key] = pl.LpVariable(
                            name=f's_max_oper_state_time_b_left_{gen_id + 1}_{from_oper_state_id}_{next_state_id}_{t}',
                            lowBound=0,
                            upBound=1,
                            cat='Binary',
                        )
                    if max_time is not None:
                        s_max_oper_state_time_b_1[key] = pl.LpVariable(
                            name=f's_max_oper_state_time_b_1_{gen_id + 1}_{from_oper_state_id}_{next_state_id}_{t}',
                            lowBound=0,
                            upBound=1,
                            cat='Binary',
                        )

    last_period = intervals[-1]
    for gen in data:
        gen_id = gen['gen_id']
        state_by_id = {
            operating_state['id']: operating_state
            for operating_state in gen['operating-states']
        }
        for allowed_transition in gen['operating-state-transitions']:
            from_oper_state_id = allowed_transition['from']
            for next_state in allowed_transition['transitions']:
                next_state_id = next_state['id']
                if from_oper_state_id == next_state_id:
                    continue

                max_time_left = _finite_max_time(
                    next_state.get('max-transition-time-left_b', 100000000000),
                    dispatch_period_count,
                )
                max_time = _finite_max_time(
                    next_state.get('max-transition-time_b', 100000000000),
                    dispatch_period_count,
                )

                # Residual maximum-time obligation at the horizon start. If B
                # is initially enabled, every excess period in the initial
                # continuous B stretch receives its own slack. If B is left
                # before an excess period, the prefix sum is no longer full and
                # later re-entry is not charged against this inherited timer.
                if max_time_left is not None and state_by_id[next_state_id]["isEnabled"]:
                    for violation_period in intervals[max_time_left + 1:]:
                        prefix_periods = intervals[1:violation_period + 1]
                        prob += (
                                pl.lpSum(
                                    u_2_dict[(gen_id, t, next_state_id)]
                                    for t in prefix_periods
                                )
                                <= len(prefix_periods) - 1
                                + s_max_oper_state_time_b_left[
                                    (gen_id, from_oper_state_id, next_state_id, violation_period)
                                ]
                        )

                # In-horizon maximum stay after an A -> B transition. For each
                # potential entry period tt, every later excess period checks
                # whether B has remained selected continuously since tt. If so,
                # that excess period needs its own slack.
                if max_time is not None:
                    for tt in intervals[1:]:
                        for violation_period in intervals[tt + max_time:]:
                            checked_periods = intervals[tt:violation_period + 1]
                            prob += (
                                    pl.lpSum(
                                        u_2_dict[(gen_id, t, next_state_id)]
                                        for t in checked_periods
                                    )
                                    <= len(checked_periods) - 1
                                    + (1 - u_2_dict[(gen_id, tt - 1, from_oper_state_id)])
                                    + s_max_oper_state_time_b_1[
                                        (gen_id, from_oper_state_id, next_state_id, violation_period)
                                    ]
                            )

                # Penalize every max-time slack variable so violations are used
                # only when they are cheaper than infeasibility or other larger
                # relaxation penalties.
                for t in intervals[1:]:
                    key = (gen_id, from_oper_state_id, next_state_id, t)
                    if key in s_max_oper_state_time_b_left:
                        objective_terms += (
                                s_max_oper_state_time_b_left[key]
                                * input_data["Cost_parameters"]["x_max_oper_state_time_b_left"]
                        )
                    if key in s_max_oper_state_time_b_1:
                        objective_terms += (
                                s_max_oper_state_time_b_1[key]
                                * input_data["Cost_parameters"]["x_max_oper_state_time_b"]
                        )

    return prob, objective_terms


def create_min_transition_time_between_states_constraints_a(prob, objective_terms, input_data, data, u_2_dict, intervals):
    """Add soft source-side minimum-time rules for operating-state transitions.

    This function implements the ``A`` part of the operating-state timing
    formulation. In a transition notation ``A -> B``, state ``A`` is the source
    operating state. The ``min-transition-time_a`` fields therefore protect the
    source side: once the model has entered or is still obligated to remain in
    source state ``A``, it should not leave ``A`` too early.

    Two related inputs are handled:

    * ``min-transition-time-left_a`` represents residual time that was already
      owed at the start of the horizon. It protects the source state at the
      beginning of the horizon and counts the remaining protected periods if the
      unit leaves that source state too early.
    * ``min-transition-time_a`` is the normal in-horizon minimum source-side
      time. If the unit enters source state ``A`` and then leaves ``A`` too
      early, the model charges slack for every remaining protected period after
      that early departure.

    The constraints are soft and use binary slack variables:

    * ``s_min_a_left`` relaxes residual source-side minimum-time obligations;
    * ``s_min_a_1`` relaxes in-horizon source-side minimum-time obligations.

    The function also appends a self-transition entry to each transition list so
    that "remaining in A" is treated consistently with moving from A to another
    listed destination.
    """
    s_min_a_left = [
        [pl.LpVariable(name=f's_min_a_left_{i + 1}_{t}', lowBound=0, upBound=1, cat='Binary') for t in intervals]
        for i, _ in enumerate(data)
    ]
    s_min_a_1 = [
        [pl.LpVariable(name=f's_min_a_1_{i + 1}_{t}', lowBound=0, upBound=1, cat='Binary') for t in intervals]
        for i, _ in enumerate(data)
    ]

    for gen in data:
        gen_id = gen['gen_id']
        for allowed_transition in gen['operating-state-transitions']:
            from_oper_state_id = allowed_transition['from']
            to_oper_states = copy.deepcopy(allowed_transition['transitions'])
            to_oper_states.append({'id': from_oper_state_id})

            # Residual left-time rule. A-side timing protects the source state,
            # so inherited time is enforced as a source-state stay requirement:
            # if the unit starts the horizon in source state A, then A should
            # remain selected throughout the protected window. The slack at
            # protected period tau is forced to 1 when the unit has already
            # left A at any earlier protected period k <= tau. Therefore, an
            # immediate departure with five periods left creates five slack
            # periods, not merely one transition-event slack.
            min_time_left = max(
                int(next_state.get('min-transition-time-left_a', 0))
                for next_state in to_oper_states
            )
            protected_periods = intervals[1:min_time_left + 1]
            for protected_index, protected_t in enumerate(protected_periods):
                for earlier_t in protected_periods[:protected_index + 1]:
                    prob += (
                            u_2_dict[(gen_id, earlier_t, from_oper_state_id)]
                            >= u_2_dict[(gen_id, 0, from_oper_state_id)] - s_min_a_left[gen_id][protected_t]
                    )

            # In-horizon source-side minimum-time rule. entered_state_now is 1
            # only when the model switches into source state A at interval t.
            # If an A -> B departure occurs before the A-side minimum time is
            # completed, every remaining protected period after that departure
            # receives its own slack. This keeps the penalty proportional to the
            # missing protected duration rather than to a single early-departure
            # event.
            for t in intervals[1:]:
                entered_state_now = (
                        u_2_dict[(gen_id, t, from_oper_state_id)]
                        - u_2_dict[(gen_id, t - 1, from_oper_state_id)]
                )
                for next_state in to_oper_states:
                    next_state_id = next_state['id']
                    if next_state_id == from_oper_state_id:
                        continue
                    min_time = int(next_state.get('min-transition-time_a', 0))
                    protected_periods = intervals[t:t + min_time]
                    for departure_index, departure_t in enumerate(protected_periods):
                        if (gen_id, departure_t, next_state_id) in u_2_dict:
                            for protected_t in protected_periods[departure_index:]:
                                prob += (
                                        u_2_dict[(gen_id, departure_t - 1, from_oper_state_id)]
                                        + u_2_dict[(gen_id, departure_t, next_state_id)]
                                        <= 2 - entered_state_now + s_min_a_1[gen_id][protected_t]
                                )

        # Add source-side slack penalties to the objective for all modeled
        # dispatch intervals. The left and normal penalties are separated so
        # input data can price inherited violations differently from new ones.
        for t in intervals[1:]:
            objective_terms += (
                    s_min_a_left[gen_id][t] * input_data["Cost_parameters"]["x_min_transition_oper_states_a_left"]
                    + s_min_a_1[gen_id][t] * input_data["Cost_parameters"]["x_min_transition_oper_states_a"]
            )

    return prob, objective_terms


def create_min_transition_time_between_states_constraints_b(prob, objective_terms, input_data, data, u_2_dict, intervals):
    """Add soft destination-side minimum-time rules for operating-state B.

    This function implements the ``B`` part of the operating-state timing
    formulation. In a transition notation ``A -> B``, state ``B`` is the
    destination operating state. The ``min-transition-time_b`` fields therefore
    protect the destination side: after the model enters ``B``, it should remain
    in ``B`` for the required minimum number of dispatch periods.

    Two related inputs are handled:

    * ``min-transition-time-left_b`` represents residual destination-side time
      owed at the beginning of the horizon because the unit had already entered
      that destination state before period 1.
    * ``min-transition-time_b`` is the normal in-horizon minimum stay in the
      destination state after a transition from ``A`` to ``B``.

    The constraints are soft and use binary slack variables:

    * ``s_min_b_left`` relaxes residual destination-side obligations;
    * ``s_min_b_1`` relaxes in-horizon destination-side obligations.

    This function is intentionally different from the source-side ``A``
    function. Here the selected destination state must remain active; in the
    ``A`` function, the model is prevented from leaving the source state too
    early.
    """
    s_min_b_left = [
        [pl.LpVariable(name=f's_min_b_left_{i + 1}_{t}', lowBound=0, upBound=1, cat='Binary') for t in intervals]
        for i, _ in enumerate(data)
    ]
    s_min_b_1 = [
        [pl.LpVariable(name=f's_min_b_1_{i + 1}_{t}', lowBound=0, upBound=1, cat='Binary') for t in intervals]
        for i, _ in enumerate(data)
    ]

    for gen in data:
        gen_id = gen['gen_id']
        for allowed_transition in gen['operating-state-transitions']:
            from_oper_state_id = allowed_transition['from']
            to_oper_states = copy.deepcopy(allowed_transition['transitions'])
            to_oper_states.append({'id': from_oper_state_id})

            # Residual destination-side obligation. If time is still owed at
            # the start of the horizon, the destination state must be selected
            # in those initial periods unless the model pays the slack penalty.
            for next_state in to_oper_states:
                next_state_id = next_state['id']
                min_time_left = next_state.get('min-transition-time-left_b', 0)
                for t in intervals[1:min_time_left + 1]:
                    if (gen_id, t, next_state_id) in u_2_dict:
                        prob += u_2_dict[(gen_id, t, next_state_id)] + s_min_b_left[gen_id][t] >= 1

            # In-horizon destination-side minimum stay. entered_state_now
            # becomes 2 only when the model was in A at t - 1 and is in B at t.
            # In that case, the right-hand side below becomes 1 and forces B to
            # remain selected over the protected window, unless slack is used.
            for t in intervals[1:]:
                for next_state in to_oper_states:
                    next_state_id = next_state['id']
                    entered_state_now = (
                            u_2_dict[(gen_id, t, next_state_id)]
                            + u_2_dict[(gen_id, t - 1, from_oper_state_id)]
                    )
                    min_time = int(next_state.get('min-transition-time_b', 0))
                    for t_prime in intervals[t:t + min_time]:
                        if (gen_id, t_prime, next_state_id) in u_2_dict:
                            prob += (
                                    u_2_dict[(gen_id, t_prime, next_state_id)]
                                    + s_min_b_1[gen_id][t_prime]
                                    >= entered_state_now - 1
                            )

        # Add destination-side slack penalties to the objective. Separate
        # penalties allow inherited and in-horizon violations to be weighted
        # differently.
        for t in intervals[1:]:
            objective_terms += (
                    s_min_b_left[gen_id][t] * input_data["Cost_parameters"]["x_min_transition_oper_states_b_left"]
                    + s_min_b_1[gen_id][t] * input_data["Cost_parameters"]["x_min_transition_oper_states_b"]
            )

    return prob, objective_terms


def create_state_min_time_constraints(prob, objective_terms, input_data, data, state, intervals, startup, shutdown):
    """Add soft unit-level minimum on/off-time constraints.

    This is the only active state-level time constraint. It works on the
    aggregate unit commitment binary ``state[gen_id][t]`` rather than on the
    detailed operating-state binary ``u_2_dict``. A unit-level ``state`` value
    of 1 means the unit is online; a value of 0 means the unit is offline.

    The input section ``state-transitions`` defines minimum time requirements
    between the two aggregate states:

    * a transition from 0 to 1 corresponds to startup and creates minimum
      online-time obligations;
    * a transition from 1 to 0 corresponds to shutdown and creates minimum
      offline-time obligations.

    Two forms are handled:

    * ``min-transition-time-left`` for residual obligations inherited at the
      beginning of the horizon;
    * ``min-transition-time`` for obligations created by startups or shutdowns
      inside the horizon.

    The constraints are soft. ``s_min_state_b_left`` relaxes inherited
    obligations and ``s_min_state_b_1`` relaxes obligations created inside the
    horizon. These slacks are penalized in the objective using the
    state-transition penalty parameters.
    """
    s_min_state_b_left = [
        [pl.LpVariable(name=f's_min_state_b_left_{i + 1}_{t}', lowBound=0, upBound=1, cat='Binary') for t in intervals]
        for i, _ in enumerate(data)
    ]
    s_min_state_b_1 = [
        [pl.LpVariable(name=f's_min_state_b_1_{i + 1}_{t}', lowBound=0, upBound=1, cat='Binary') for t in intervals]
        for i, _ in enumerate(data)
    ]

    for gen in data:
        gen_id = gen['gen_id']
        for allowed_transition in gen['state-transitions']:
            from_state_value = allowed_transition['from']
            to_state_value = copy.deepcopy(allowed_transition['transitions'])
            min_time_left = int(to_state_value.get('min-transition-time-left', 0))
            min_time = int(to_state_value.get('min-transition-time', 0))

            # Residual minimum-time obligation at the start of the horizon. For
            # a previous offline-to-online transition, the unit must stay online
            # during the remaining protected periods. For a previous
            # online-to-offline transition, it must stay offline.
            for t in intervals[1:min_time_left + 1]:
                if from_state_value == 0:
                    prob += state[gen_id][t] + s_min_state_b_left[gen_id][t] >= 1
                else:
                    prob += state[gen_id][t] - s_min_state_b_left[gen_id][t] <= 0

            # In-horizon minimum online time after startup. If startup is 1 at
            # interval t, the unit-level state must remain online throughout the
            # protected window unless slack is activated.
            if from_state_value == 0:
                for t in intervals[1:]:
                    for t_prime in intervals[t:t + min_time]:
                        prob += startup[gen_id][t] <= state[gen_id][t_prime] + s_min_state_b_1[gen_id][t_prime]
            else:
                # In-horizon minimum offline time after shutdown. If shutdown is
                # 1 at interval t, the unit-level state must remain offline
                # throughout the protected window unless slack is activated.
                for t in intervals[1:]:
                    for t_prime in intervals[t:t + min_time]:
                        prob += shutdown[gen_id][t] <= 1 - state[gen_id][t_prime] + s_min_state_b_1[gen_id][t_prime]

        # Penalize state-level timing slacks in the objective so the solver can
        # keep the model feasible while still preferring schedules that respect
        # the minimum on/off-time rules.
        for t in intervals[1:]:
            objective_terms += (
                    s_min_state_b_left[gen_id][t] * input_data["Cost_parameters"]["x_min_transition_states_left"]
                    + s_min_state_b_1[gen_id][t] * input_data["Cost_parameters"]["x_min_transition_states"]
            )

    return prob, objective_terms
