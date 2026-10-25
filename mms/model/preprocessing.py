"""Pre-solve data preparation for unit filtering, categories, and time discretization."""

# Extracted from RV_genericMmsOptimization.py. Keep behavior-compatible with the original scheduling data preparation.

def unit_categories(input_data, data):
    """Classify units into conventional, RES, PV, setpoint, and controllable groups."""
    CONV = []
    RES = []
    PV = []
    Partially_Controllable = []
    on_AGC = []
    for i, _ in enumerate(data):
        #     print(i['comments'])
        if data[i]['comments'][:5] == 'Therm':
            CONV.append(i)
        elif data[i]['comments'][:2] == 'PV':
            PV.append(i)
        elif "Partially Controllable" in data[i]['comments']:
            Partially_Controllable.append(i)
        else:
            RES.append(i)

    RES_SP = []
    RES_no_SP = []
    PV_SP = []
    PV_no_SP = []
    # print(input_data['Generating_Units'])
    for i in RES+PV:
        if i in RES:
            if input_data["Generating_Units"][i]['Accepts_SP'] == 1:
                RES_SP.append(i)
            else:
                RES_no_SP.append(i)
        elif i in PV:
            if input_data["Generating_Units"][i]["Accepts_SP"] == 1:
                PV_SP.append(i)
            else:
                PV_no_SP.append(i)
    if input_data["Other_coefficients"]["include_PV"]:
        UNITS = CONV + RES + PV
    else:
        UNITS = CONV + RES
    print("Units:", UNITS)

    return UNITS, CONV, RES, PV, RES_SP, RES_no_SP, PV_SP, PV_no_SP, on_AGC, Partially_Controllable

def filter_generating_units(data):
    """Keep all generating units in the model-building data set.

    Earlier versions removed units with zero availability over the modeled
    horizon. That made post-filter list positions diverge from ``gen_id`` values
    whenever an unavailable unit was in the middle of the input list. The active
    formulation already has period-by-period availability constraints, so the
    safer behavior is to keep every unit and let those constraints handle zero
    availability.
    """
    return list(data)

def round_to_best(a, b):
    """Round a positive duration up to the nearest dispatch-period count."""
    # Treat the project's infinity marker as an effectively unbounded number of periods.
    if a == float('inf'):
        return 100000000000
    # For finite durations, preserve exact multiples without adding an extra period.
    else:
        # If the minute duration divides exactly by the dispatch period, the quotient is exact.
        if a % b == 0:
            return round(a / b)
        # Otherwise round up so a minimum-time rule is never shortened by discretization.
        else:
            return int(a / b) + 1


def round_min_time_to_periods(value, time_gran):
    """Round minimum-time data up so minimum durations remain conservative."""
    # Minimum dwell/transition times are lower bounds, so the period model must not understate them.
    return round_to_best(value, time_gran)


def round_max_time_to_periods(value, time_gran):
    """Round maximum-time data down so short maxima are not overstated."""
    # Keep explicit infinity unchanged as the large internal sentinel.
    if value == float('inf'):
        return 100000000000
    # Keep existing sentinel-like values unchanged.
    if value >= 100000000000:
        return 100000000000
    # Maximum dwell/transition times are upper bounds, so only complete dispatch periods are allowed.
    return int(value / time_gran)


def time_granularity(data, time_gran):
    """Convert minute-based timing parameters into dispatch-period counts."""
    # This function is called after prepare_operating_state_time_resolution.
    # Therefore, states that should be bypassed have already been embedded;
    # remaining states are intentionally represented at the dispatch-period scale.
    # Iterate over each generating unit in the data.
    for gen_unit in data["Generating_Units"]:
        # Convert state-level operating-state dwell timers from minutes to periods.
        for operating_state in gen_unit["operating-states"]:
            # Minimum enabled time rounds up to avoid permitting an early exit.
            operating_state["min-time-enabled"] = round_min_time_to_periods(operating_state.get("min-time-enabled", 0), time_gran)
            # Maximum enabled time rounds down to avoid permitting an overstay.
            operating_state["max-time-enabled"] = round_max_time_to_periods(operating_state.get("max-time-enabled", float('inf')), time_gran)
            # gen_unit["min_time_off"] = round_to_best(gen_unit["min_time_off"], time_gran)
            # Remaining minimum enabled time at the horizon start also rounds up.
            operating_state["min-time-enabled-left"] = round_min_time_to_periods(operating_state.get("min-time-enabled-left", 0), time_gran)
            # Remaining maximum enabled time at the horizon start also rounds down.
            operating_state["max-time-enabled-left"] = round_max_time_to_periods(operating_state.get("max-time-enabled-left", float('inf')), time_gran)

        # Convert timing rules attached to operating-state transition arcs.
        for allowed_transition in gen_unit['operating-state-transitions']:
            # Keep the source state id for readability and legacy debugging.
            from_oper_state_id = allowed_transition['from']
            # Read all allowed destination states/arcs from this source.
            to_oper_states = allowed_transition['transitions']  # all allowed states to transition to
            # to_oper_states.append({'id': from_oper_state_id})  # also we can stay in the current state

            # at this point we have 1 'from' id and 1 or more 'to' ids

            # for the start of the scheduling period
            # Convert every destination arc timing field to dispatch-period counts.
            for next_state in to_oper_states:
                # Source-side remaining minimum transition time rounds up.
                next_state['min-transition-time-left_a'] = round_min_time_to_periods(next_state.get('min-transition-time-left_a', 0), time_gran)  # if min-time key does not exist, use 0 as the default value for min-time
                # Source-side in-horizon minimum transition time rounds up.
                next_state['min-transition-time_a'] = round_min_time_to_periods(next_state.get('min-transition-time_a', 0), time_gran)
                # Destination-side in-horizon minimum transition time rounds up.
                next_state['min-transition-time_b'] = round_min_time_to_periods(next_state.get('min-transition-time_b', 0), time_gran)
                # Destination-side remaining minimum transition time rounds up.
                next_state['min-transition-time-left_b'] = round_min_time_to_periods(next_state.get('min-transition-time-left_b', 0), time_gran)
                # Destination-side remaining maximum transition time rounds down.
                next_state['max-transition-time-left_b'] = round_max_time_to_periods(next_state.get('max-transition-time-left_b', float('inf')), time_gran)
                # Destination-side in-horizon maximum transition time rounds down.
                next_state['max-transition-time_b'] = round_max_time_to_periods(next_state.get('max-transition-time_b', float('inf')), time_gran)
            # gen_unit["time_Off_left"] = round_to_best(gen_unit["time_Off_left"], time_gran)

            # operating_state["Therm_state_min_time_on"] = [round_to_best(t, time_gran) for t in operating_state["Therm_state_min_time_on"]]
            # operating_state["Therm_state_min_time_on_left"] = [round_to_best(t, time_gran) for t in operating_state["Therm_state_min_time_on_left"]]

        # Convert legacy unit-level on/off state-transition timing rules.
        for allowed_transition in gen_unit['state-transitions']:
            # from_oper_state_id = allowed_transition['from']
            # Read the nested transition timing dictionary.
            to_oper_states = allowed_transition['transitions']  # all allowed states to transition to
            # to_oper_states.append({'id': from_oper_state_id})  # also we can stay in the current state

            # at this point we have 1 'from' id and 1 or more 'to' ids

            # for the start of the scheduling period

            # Remaining on/off minimum transition time rounds up.
            to_oper_states['min-transition-time-left'] = round_min_time_to_periods(to_oper_states.get('min-transition-time-left', 0), time_gran)  # if min-time key does not exist, use 0 as the default value for min-time
            # In-horizon on/off minimum transition time rounds up.
            to_oper_states['min-transition-time'] = round_min_time_to_periods(to_oper_states.get('min-transition-time', 0), time_gran)

    # print(data)
    # Return the same data object after in-place timing conversion.
    return data

