"""Soft-constraint slack extraction and penalty contribution reporting."""

import re


DEFAULT_TOLERANCE = 1e-6


def _is_number(value):
    """Return whether a value is a non-boolean numeric scalar."""
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _round(value, digits=6):
    """Round a numeric value for JSON reports while preserving None."""
    return round(float(value), digits)


def _cost_parameter(cost_parameters, key):
    """Read a numeric cost parameter with a safe default."""
    value = cost_parameters.get(key, 0.0)
    return float(value) if _is_number(value) else 0.0


def _numbers(value):
    """Extract numeric values from a report cell or container."""
    return [int(item) for item in re.findall(r"\d+", str(value))]


def _period_from_variable(variable):
    """Internal helper for slack normalization."""
    parsed = _numbers(variable)
    return parsed[-1] if parsed else None


def _unit_period_from_variable(variable):
    """Internal helper for slack normalization."""
    parsed = _numbers(variable)
    if len(parsed) < 2:
        return None, _period_from_variable(variable)
    return parsed[-2] - 1, parsed[-1]


def _unit_state_period_from_variable(variable):
    """Internal helper for slack normalization."""
    parsed = _numbers(variable)
    if len(parsed) < 3:
        unit_index, period = _unit_period_from_variable(variable)
        return unit_index, None, period
    return parsed[-3] - 1, parsed[-2], parsed[-1]


def _unit_from_to_period_from_variable(variable):
    """Internal helper for slack normalization."""
    parsed = _numbers(variable)
    if len(parsed) < 4:
        unit_index, operating_state_id, period = _unit_state_period_from_variable(variable)
        return unit_index, None, operating_state_id, period
    return parsed[-4] - 1, parsed[-3], parsed[-2], parsed[-1]


def _is_dataframe(value):
    """Internal helper for slack normalization."""
    return hasattr(value, "empty") and hasattr(value, "iterrows")


def _add_entry(
    entries,
    family,
    variable,
    value,
    penalty_key,
    penalty,
    unit_index=None,
    from_operating_state_id=None,
    operating_state_id=None,
    period=None,
    tolerance=DEFAULT_TOLERANCE,
):
    """Internal helper for slack normalization."""
    if not _is_number(value) or abs(float(value)) <= tolerance:
        return
    amount = float(value)
    entry = {
        "family": family,
        "variable": str(variable),
        "unit_index": unit_index,
        "period": period,
        "value": _round(amount),
        "penalty_key": penalty_key,
        "penalty_eur_per_unit": _round(penalty),
        "cost_eur": _round(amount * penalty),
    }
    if operating_state_id is not None:
        entry["operating_state_id"] = operating_state_id
    if from_operating_state_id is not None:
        entry["from_operating_state_id"] = from_operating_state_id
    entries.append(entry)


def _add_variable_rows(entries, frame, family, penalty_key, penalty, parser, tolerance):
    """Internal helper for slack normalization."""
    if not _is_dataframe(frame) or frame.empty or "Variable" not in frame or "Value" not in frame:
        return
    for _, row in frame.iterrows():
        variable = row["Variable"]
        value = row["Value"]
        parsed = parser(variable)
        if len(parsed) == 4:
            unit_index, from_operating_state_id, operating_state_id, period = parsed
        elif len(parsed) == 3:
            unit_index, operating_state_id, period = parsed
            from_operating_state_id = None
        else:
            unit_index, period = parsed
            from_operating_state_id = None
            operating_state_id = None
        _add_entry(
            entries,
            family,
            variable,
            value,
            penalty_key,
            penalty,
            unit_index=unit_index,
            from_operating_state_id=from_operating_state_id,
            operating_state_id=operating_state_id,
            period=period,
            tolerance=tolerance,
        )


def _add_matrix_rows(entries, frame, family, variable_prefix, penalty_key, penalty, tolerance):
    """Internal helper for slack normalization."""
    if not _is_dataframe(frame) or frame.empty:
        return
    for row_label, row in frame.iterrows():
        parsed_row = _numbers(row_label)
        unit_index = (parsed_row[-1] - 1) if parsed_row else int(row_label) - 1
        for column_label, value in row.items():
            parsed_col = _numbers(column_label)
            period = parsed_col[-1] if parsed_col else int(column_label)
            variable = f"{variable_prefix}_{unit_index + 1}_{period}"
            _add_entry(
                entries,
                family,
                variable,
                value,
                penalty_key,
                penalty,
                unit_index=unit_index,
                period=period,
                tolerance=tolerance,
            )


def _summarize(entries):
    """Internal helper for slack normalization."""
    families = {}
    total = 0.0
    for entry in entries:
        family = entry["family"]
        value = entry["value"]
        cost = entry["cost_eur"]
        total += cost
        summary = families.setdefault(
            family,
            {
                "entry_count": 0,
                "total_violation": 0.0,
                "total_penalty_eur": 0.0,
                "max_violation": 0.0,
            },
        )
        summary["entry_count"] += 1
        summary["total_violation"] += value
        summary["total_penalty_eur"] += cost
        summary["max_violation"] = max(summary["max_violation"], abs(value))

    family_rows = []
    for family, summary in sorted(families.items()):
        family_rows.append(
            {
                "family": family,
                "entry_count": summary["entry_count"],
                "total_violation": _round(summary["total_violation"]),
                "total_penalty_eur": _round(summary["total_penalty_eur"]),
                "max_violation": _round(summary["max_violation"]),
            }
        )
    return _round(total), family_rows


def build_slack_penalty_report(input_data, slack_frames, tolerance=DEFAULT_TOLERANCE):
    """Normalize nonzero soft-constraint slacks and their penalty costs."""
    cost_parameters = input_data.get("Cost_parameters", {})
    entries = []

    no_unit = lambda variable: (None, _period_from_variable(variable))
    unit_period = _unit_period_from_variable

    variable_specs = [
        ("load_curtailment_plus", "s_load_plus", "x_load", no_unit),
        ("load_curtailment_minus", "s_load_minus", "x_load", no_unit),
        ("primary_upwards_shortage", "s_primary_APR_upwards", "x_primary_APR_up", no_unit),
        ("primary_downwards_shortage", "s_primary_APR_downwards", "x_primary_APR_down", no_unit),
        ("secondary_upwards_shortage", "s_secondary_APR_upwards", "x_secondary_APR_up", no_unit),
        ("secondary_downwards_shortage", "s_secondary_APR_downwards", "x_secondary_APR_down", no_unit),
        ("tertiary_upwards_shortage", "s_tertiary_APR_upwards", "x_tertiary_APR_up", no_unit),
        ("tertiary_downwards_shortage", "s_tertiary_APR_downwards", "x_tertiary_APR_down", no_unit),
        ("grid_capacity_1", "s_Grid_Capacity_1", "x_Grid_Capacity", no_unit),
        ("grid_capacity_2", "s_Grid_Capacity_2", "x_Grid_Capacity", no_unit),
        ("grid_capacity_3", "s_Grid_Capacity_3", "x_Grid_Capacity", no_unit),
        ("forbidden_zone_plus", "s_forbidden_zones_plus", "x_forbidden_zones", unit_period),
        ("forbidden_zone_minus", "s_forbidden_zones_minus", "x_forbidden_zones", unit_period),
        ("operating_state_min_transition_a_left", "s_min_a_left", "x_min_transition_oper_states_a_left", unit_period),
        ("operating_state_min_transition_a", "s_min_a_1", "x_min_transition_oper_states_a", unit_period),
        ("operating_state_min_transition_b_left", "s_min_b_left", "x_min_transition_oper_states_b_left", unit_period),
        ("operating_state_min_transition_b", "s_min_b_1", "x_min_transition_oper_states_b", unit_period),
        ("operating_state_max_time_left", "s_max_oper_state_time_left", "x_max_oper_state_time_left", _unit_state_period_from_variable),
        ("operating_state_max_time", "s_max_oper_state_time_1", "x_max_oper_state_time", _unit_state_period_from_variable),
        ("operating_state_max_time_b_left", "s_max_oper_state_time_b_left", "x_max_oper_state_time_b_left", _unit_from_to_period_from_variable),
        ("operating_state_max_time_b", "s_max_oper_state_time_b_1", "x_max_oper_state_time_b", _unit_from_to_period_from_variable),
        ("operating_state_min_time_a_left", "s_min_oper_state_time_a_left", "x_min_oper_state_time_a_left", _unit_state_period_from_variable),
        ("operating_state_min_time_a", "s_min_oper_state_time_a_1", "x_min_oper_state_time_a", _unit_state_period_from_variable),
        ("operating_state_min_time_b_left", "s_min_oper_state_time_b_left", "x_min_oper_state_time_b_left", _unit_state_period_from_variable),
        ("operating_state_min_time_b", "s_min_oper_state_time_b_1", "x_min_oper_state_time_b", _unit_state_period_from_variable),
        ("state_min_transition_left", "s_min_state_b_left", "x_min_transition_states_left", unit_period),
        ("state_min_transition", "s_min_state_b_1", "x_min_transition_states", unit_period),
    ]
    for family, frame_key, penalty_key, parser in variable_specs:
        _add_variable_rows(
            entries,
            slack_frames.get(frame_key),
            family,
            penalty_key,
            _cost_parameter(cost_parameters, penalty_key),
            parser,
            tolerance,
        )

    matrix_specs = [
        ("ramp_relaxation", "ramp_relax", "x_ramp"),
        ("must_run_relaxation", "s_must_run", "x_must_run"),
        ("testing_mode_plus", "s_power_testing_mode_plus", "x_testing_mode"),
        ("testing_mode_minus", "s_power_testing_mode_minus", "x_testing_mode"),
        ("oos_less_than", "s_power_OOS_less_plus", "x_OOS_less_than"),
        ("oos_more_than", "s_power_OOS_more_minus", "x_OOS_more_than"),
        ("res_pv_power_plus", "s_power_plus", "x_RES_PV_power_plus"),
        ("res_pv_power_minus", "s_power_minus", "x_RES_PV_power_minus"),
    ]
    for family, frame_key, penalty_key in matrix_specs:
        _add_matrix_rows(
            entries,
            slack_frames.get(frame_key),
            family,
            frame_key,
            penalty_key,
            _cost_parameter(cost_parameters, penalty_key),
            tolerance,
        )

    entries.sort(key=lambda item: (item["family"], item.get("period") or 0, item.get("unit_index") or -1, item["variable"]))
    total_penalty, family_summary = _summarize(entries)
    return {
        "report_type": "slack_penalty_report",
        "status": "passed" if not entries else "warning",
        "tolerance": tolerance,
        "nonzero_slack_count": len(entries),
        "total_penalty_eur": total_penalty,
        "family_summary": family_summary,
        "entries": entries,
    }
