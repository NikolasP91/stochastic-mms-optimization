"""Local bound calculations used to tighten MIP constraints and reduce big-M reliance."""

def _is_number(value):
    """Return whether a value is a non-boolean numeric scalar."""
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def value_at(value, index, default=0.0):
    """Handle value at logic for local bound calculations used to tighten mip constraints and reduce big-m reliance."""
    if isinstance(value, list):
        if 0 <= index < len(value) and _is_number(value[index]):
            return float(value[index])
        return default
    if _is_number(value):
        return float(value)
    return default


def reserve_activation_bound(unit, reserve_field, direction_index, period_index, operating_state=None):
    """Handle reserve activation bound logic for local bound calculations used to tighten mip constraints and reduce big-m reliance."""
    reserve_limits = unit.get(reserve_field, [0.0, 0.0])
    reserve_cap = value_at(reserve_limits, direction_index, 0.0)
    availability = max(0.0, value_at(unit.get("availability", []), period_index, reserve_cap))

    if direction_index == 0:
        if operating_state is not None:
            state_max = value_at(operating_state.get("max-power"), period_index, availability)
            state_max = min(state_max, value_at(operating_state.get("user_max_power"), period_index, state_max))
            availability = min(availability, max(0.0, state_max))
        return max(0.0, min(reserve_cap, availability))

    if operating_state is not None:
        state_min = value_at(operating_state.get("min-power"), period_index, 0.0)
        state_min = max(state_min, value_at(operating_state.get("user_min_power"), period_index, state_min))
        availability = max(0.0, availability - max(0.0, state_min))
    return max(0.0, min(reserve_cap, availability))


def forbidden_zone_big_m(unit, zone, period_index, fallback_m):
    """Handle forbidden zone big m logic for local bound calculations used to tighten mip constraints and reduce big-m reliance."""
    availability = max(0.0, value_at(unit.get("availability", []), period_index, fallback_m))
    lower = float(zone[0])
    upper = float(zone[1])
    bound = max(
        abs(availability - lower),
        abs(availability - upper),
        abs(lower),
        abs(upper),
        1.0,
    )
    return min(float(fallback_m), 1.25 * bound)


def _sum_values(data, units, field, period_index):
    """Sum numeric values while ignoring malformed entries."""
    return sum(max(0.0, value_at(data[index].get(field), period_index, 0.0)) for index in units)


def res_pv_dispatch_bounds(input_data, data, CONV, RES_SP, PV_SP, RES_no_SP, PV_no_SP, Load_forecast, period):
    """Handle res pv dispatch bounds logic for local bound calculations used to tighten mip constraints and reduce big-m reliance."""
    period_index = period - 1
    other = input_data.get("Other_coefficients", {})
    load = max(0.0, value_at(Load_forecast, period, 0.0))
    pv_participation = value_at(other.get("PV_Participation_coefficient"), 0, 0.0) / 100.0
    if "PV_Participation_coefficient" in other and not isinstance(other["PV_Participation_coefficient"], list):
        pv_participation = float(other["PV_Participation_coefficient"]) / 100.0
    x_dynamic = float(other.get("x_res_pv_dynamic", 1.0))
    include_pv = float(other.get("include_PV", 0.0))

    conv_min_sum = _sum_values(data, CONV, "min_power(MW)", period_index)
    no_sp_availability = _sum_values(data, RES_no_SP + PV_no_SP, "availability", period_index)
    res_sp_availability = _sum_values(data, RES_SP, "availability", period_index)
    pv_sp_availability = _sum_values(data, PV_SP, "availability", period_index)

    grid_capacity2 = max(0.0, x_dynamic * load)
    grid_capacity3 = max(0.0, res_sp_availability + pv_participation * pv_sp_availability)
    grid_capacity2_slack_upper = max(0.0, grid_capacity3 - grid_capacity2)
    min_grid_capacity2_upper = max(grid_capacity2 + grid_capacity2_slack_upper, grid_capacity3)

    grid_capacity1_lower = load - conv_min_sum - include_pv * no_sp_availability
    grid_capacity1_upper = load
    grid_capacity1_abs = max(abs(grid_capacity1_lower), abs(grid_capacity1_upper), 1.0)

    return {
        "grid_capacity2_slack_upper": grid_capacity2_slack_upper,
        "grid_capacity2_big_m": max(abs(grid_capacity3 - grid_capacity2), grid_capacity2, grid_capacity3, 1.0),
        "grid_capacity1_big_m": max(grid_capacity1_abs, min_grid_capacity2_upper, 1.0),
        "positive_part_big_m": max(grid_capacity1_abs, min_grid_capacity2_upper, 1.0),
    }


def res_pv_unit_dispatch_bounds(unit, forecast, period_index, fallback_m):
    """Handle res pv unit dispatch bounds logic for local bound calculations used to tighten mip constraints and reduce big-m reliance."""
    availability = max(0.0, value_at(unit.get("availability"), period_index, fallback_m))
    min_power = max(0.0, value_at(unit.get("min_power(MW)"), period_index, 0.0))
    forecast = max(0.0, float(forecast) if _is_number(forecast) else 0.0)
    slack_upper = max(0.0, availability - forecast)
    setpoint_forecast_big_m = max(availability, forecast + slack_upper, abs(availability - forecast), 1.0)
    power_big_m = max(availability, min_power, abs(availability - min_power), 1.0)
    fallback_limit = max(float(fallback_m) * 10.0, 1.0)
    return {
        "s_power_minus_upper": min(slack_upper, fallback_limit),
        "setpoint_forecast_big_m": min(setpoint_forecast_big_m, fallback_limit),
        "power_big_m": min(power_big_m, fallback_limit),
    }
