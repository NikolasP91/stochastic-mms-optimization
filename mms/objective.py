"""Post-solve objective-component reconstruction from model outputs and input data."""

from mms.cost_curves import build_thermal_cost_report


RESERVE_FIELDS = {
    "primary": "Primary_Active_Power_Reserves(MW)",
    "secondary": "Secondary_Active_Power_Reserves(MW)",
    "tertiary": "Tertiary_Active_Power_Reserves(MW)",
}

RESERVE_COST_FIELDS = {
    "primary": "Primary_APR_Cost(euro/MW)",
    "secondary": "Secondary_APR_Cost(euro/MW)",
    "tertiary": "Tertiary_APR_Cost(euro/MW)",
}

RESERVE_VIOLATION_FIELDS = {
    ("primary", "upwards"): ("primary_upwards_APRV", "x_primary_APR_up"),
    ("primary", "downwards"): ("primary_downwards_APRV", "x_primary_APR_down"),
    ("secondary", "upwards"): ("secondary_upwards_APRV", "x_secondary_APR_up"),
    ("secondary", "downwards"): ("secondary_downwards_APRV", "x_secondary_APR_down"),
    ("tertiary", "upwards"): ("tertiary_upwards_APRV", "x_tertiary_APR_up"),
    ("tertiary", "downwards"): ("tertiary_downwards_APRV", "x_tertiary_APR_down"),
}


def _is_number(value):
    """Return whether a value is a non-boolean numeric scalar."""
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _round(value, digits=6):
    """Round a numeric value for JSON reports while preserving None."""
    return round(float(value), digits)


def _as_list(value):
    """Return the value when it is a list, otherwise an empty list."""
    return value if isinstance(value, list) else []


def _value_at(values, index, default=0.0):
    """Safely read a numeric value at an index with a default fallback."""
    values = _as_list(values)
    if index < len(values) and _is_number(values[index]):
        return float(values[index])
    return default


def _sum_numeric(values):
    """Sum only numeric values from a sequence."""
    return sum(float(value) for value in _as_list(values) if _is_number(value))


def _cost_parameter(cost_parameters, key):
    """Read a numeric cost parameter with a safe default."""
    value = cost_parameters.get(key, 0.0)
    return float(value) if _is_number(value) else 0.0


def _filtered_input_units(input_data):
    """Return input units in model/output order."""
    return list(input_data.get("Generating_Units", []))


def _unit_type(unit):
    """Classify a unit from its comments field for report logic."""
    comments = unit.get("comments", "")
    if isinstance(comments, str) and comments.startswith("Therm"):
        return "thermal"
    if isinstance(comments, str) and comments.startswith("PV"):
        return "pv"
    if isinstance(comments, str) and "Partially Controllable" in comments:
        return "partially_controllable"
    return "res"


def _period_count(output_data):
    """Infer the number of dispatch periods represented in output data."""
    units = output_data.get("Generating_Units", [])
    if not units:
        return 0
    return max(len(_as_list(unit.get("Power"))) for unit in units)


def _reserve_pair(unit, reserve_field, period):
    """Read upward and downward reserve values for one unit and period."""
    values = unit.get(reserve_field, [])
    if not isinstance(values, list) or len(values) < 2:
        return 0.0, 0.0
    return _value_at(values[0], period), _value_at(values[1], period)


def _cost_pair(unit, field):
    """Read a two-sided reserve cost pair safely."""
    values = unit.get(field, [0.0, 0.0])
    if not isinstance(values, list) or len(values) < 2:
        return 0.0, 0.0
    return (
        float(values[0]) if _is_number(values[0]) else 0.0,
        float(values[1]) if _is_number(values[1]) else 0.0,
    )


def _selected_operating_state_id(input_unit, output_unit, period):
    """Internal helper for objective reconstruction."""
    rows = _as_list(output_unit.get("Operating-states"))
    if period >= len(rows) or not isinstance(rows[period], list) or not rows[period]:
        return None
    selected_index = max(range(len(rows[period])), key=lambda index: rows[period][index])
    if rows[period][selected_index] < 0.5:
        return None
    states = _as_list(input_unit.get("operating-states"))
    if selected_index < len(states):
        return states[selected_index].get("id", selected_index)
    return selected_index


def _initial_operating_state_id(input_unit):
    """Internal helper for objective reconstruction."""
    for state in _as_list(input_unit.get("operating-states")):
        if state.get("isEnabled"):
            return state.get("id")
    return None


def _transition_cost(input_unit, from_state_id, to_state_id):
    """Internal helper for objective reconstruction."""
    if from_state_id is None or to_state_id is None or from_state_id == to_state_id:
        return 0.0
    for transition in _as_list(input_unit.get("operating-state-transitions")):
        if transition.get("from") != from_state_id:
            continue
        for destination in _as_list(transition.get("transitions")):
            if destination.get("id") == to_state_id:
                value = destination.get("transition-cost", 0.0)
                return float(value) if _is_number(value) else 0.0
    return 0.0


def _add_component(components, name, amount, unit="euro", source="reconstructed", note=None):
    """Internal helper for objective reconstruction."""
    components.append(
        {
            "name": name,
            "amount": _round(amount),
            "unit": unit,
            "source": source,
            "note": note,
        }
    )


def build_objective_breakdown_report(input_data, output_data):
    """Reconstruct observable objective components from the solved output."""
    input_units = _filtered_input_units(input_data)
    output_units = output_data.get("Generating_Units", [])
    periods = _period_count(output_data)
    cost_parameters = input_data.get("Cost_parameters", {})
    time_granularity = input_data.get("Time_granularity", 1.0)
    time_multiplier = float(time_granularity) if _is_number(time_granularity) else 1.0
    components = []

    thermal_report = output_data.get("Thermal_Cost_Report") or build_thermal_cost_report(
        input_data, output_data
    )
    _add_component(
        components,
        "thermal_variable_cost",
        thermal_report.get("summary", {}).get("thermal_cost", 0.0),
        source="Thermal_Cost_Report",
    )

    startup_cost = 0.0
    shutdown_cost = 0.0
    online_commitment_cost = 0.0
    operating_state_enabled_cost = 0.0
    operating_state_transition_cost = 0.0
    reserve_capacity_cost = 0.0
    res_pv_tracking_penalty = 0.0
    res_pv_setpoint_reward = 0.0

    for unit_index, input_unit in enumerate(input_units):
        if unit_index >= len(output_units):
            continue
        output_unit = output_units[unit_index]
        unit_type = _unit_type(input_unit)
        previous_state_id = _initial_operating_state_id(input_unit)
        for period in range(periods):
            power = _value_at(output_unit.get("Power"), period)
            if unit_type == "thermal":
                startup_cost += (
                    _value_at(output_unit.get("Startup"), period)
                    * float(input_unit.get("start_up_cost(euro)", 0.0))
                )
                shutdown_cost += (
                    _value_at(output_unit.get("Shutdown"), period)
                    * float(input_unit.get("shut_down_cost(euro)", 0.0))
                )
                online_commitment_cost += _value_at(output_unit.get("State"), period) * 100.0 * time_multiplier

            selected_state_id = _selected_operating_state_id(input_unit, output_unit, period)
            for operating_state in _as_list(input_unit.get("operating-states")):
                if operating_state.get("id") == selected_state_id:
                    operating_state_enabled_cost += (
                        float(operating_state.get("enabled-cost", 0.0)) * time_multiplier
                    )
                    break
            operating_state_transition_cost += _transition_cost(
                input_unit, previous_state_id, selected_state_id
            )
            if selected_state_id is not None:
                previous_state_id = selected_state_id

            for reserve_name, reserve_field in RESERVE_FIELDS.items():
                up, down = _reserve_pair(output_unit, reserve_field, period)
                up_cost, down_cost = _cost_pair(input_unit, RESERVE_COST_FIELDS[reserve_name])
                reserve_capacity_cost += (up * up_cost + down * down_cost) * time_multiplier

            if unit_type in ("res", "pv"):
                forecast = _value_at(input_unit.get("Production_Forecast"), period)
                accepts_setpoint = input_unit.get("Accepts_SP") == 1
                if accepts_setpoint:
                    res_pv_tracking_penalty += max(0.0, power - forecast) * _cost_parameter(
                        cost_parameters, "x_RES_PV_power_minus"
                    )
                    setpoints = output_unit.get("Setpoints")
                    if isinstance(setpoints, list):
                        res_pv_setpoint_reward += _value_at(setpoints, period) * -50.0
                else:
                    res_pv_tracking_penalty += abs(power - forecast) * _cost_parameter(
                        cost_parameters, "x_RES_PV_power_plus"
                    )

    _add_component(components, "startup_cost", startup_cost)
    _add_component(components, "shutdown_cost", shutdown_cost)
    _add_component(
        components,
        "thermal_online_commitment_cost",
        online_commitment_cost,
        note="Matches the model term state * 100 * Time_granularity for thermal units.",
    )
    _add_component(components, "operating_state_enabled_cost", operating_state_enabled_cost)
    _add_component(components, "operating_state_transition_cost", operating_state_transition_cost)
    _add_component(components, "reserve_capacity_cost", reserve_capacity_cost)

    load_curtailment_penalty = _sum_numeric(output_data.get("Load_Cutrailment")) * _cost_parameter(
        cost_parameters, "x_load"
    )
    _add_component(components, "load_curtailment_penalty", load_curtailment_penalty)

    reserve_shortage_penalty = 0.0
    for (reserve_name, direction), (field, penalty_key) in RESERVE_VIOLATION_FIELDS.items():
        amount = _sum_numeric(output_data.get(field)) * _cost_parameter(cost_parameters, penalty_key)
        reserve_shortage_penalty += amount
        _add_component(components, f"{reserve_name}_{direction}_shortage_penalty", amount)

    _add_component(components, "res_pv_tracking_penalty", res_pv_tracking_penalty)
    _add_component(components, "res_pv_setpoint_reward", res_pv_setpoint_reward)

    counted_slack_families = {
        "load_curtailment_plus",
        "load_curtailment_minus",
        "primary_upwards_shortage",
        "primary_downwards_shortage",
        "secondary_upwards_shortage",
        "secondary_downwards_shortage",
        "tertiary_upwards_shortage",
        "tertiary_downwards_shortage",
        "res_pv_power_plus",
        "res_pv_power_minus",
    }
    slack_report = output_data.get("Slack_Penalty_Report", {})
    additional_slack_penalties = sum(
        entry.get("cost_eur", 0.0)
        for entry in slack_report.get("entries", [])
        if entry.get("family") not in counted_slack_families
    )
    _add_component(
        components,
        "additional_soft_constraint_penalties",
        additional_slack_penalties,
        source="Slack_Penalty_Report",
        note="Excludes load, reserve-shortage, and RES/PV tracking slacks already listed above.",
    )

    reconstructed_total = sum(component["amount"] for component in components)
    solver_objective = output_data.get("Solve_Metadata", {}).get("objective_value")
    residual = None
    if _is_number(solver_objective):
        residual = float(solver_objective) - reconstructed_total
        _add_component(
            components,
            "unreconstructed_or_rounding_residual",
            residual,
            source="solver_objective_minus_reconstructed_components",
            note=(
                "Residual includes solver/output rounding and any objective terms not "
                "represented by exported reports."
            ),
        )

    return {
        "report_type": "objective_breakdown",
        "solver_objective": _round(solver_objective) if _is_number(solver_objective) else None,
        "reconstructed_total_before_residual": _round(reconstructed_total),
        "residual": _round(residual) if residual is not None else None,
        "component_count": len(components),
        "components": components,
        "limitations": [
            "Soft-constraint penalties are reconstructed from Slack_Penalty_Report where available.",
            "Components are reconstructed from rounded output values and may differ slightly from internal solver values.",
        ],
    }
