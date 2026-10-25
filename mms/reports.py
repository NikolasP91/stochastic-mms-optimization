"""MMS-style dispatch, reserve-monitoring, and RES-curtailment report builders."""

RESERVE_FIELDS = {
    "primary": "Primary_Active_Power_Reserves(MW)",
    "secondary": "Secondary_Active_Power_Reserves(MW)",
    "tertiary": "Tertiary_Active_Power_Reserves(MW)",
}

RESERVE_VIOLATION_FIELDS = {
    ("primary", "upwards"): "primary_upwards_APRV",
    ("primary", "downwards"): "primary_downwards_APRV",
    ("secondary", "upwards"): "secondary_upwards_APRV",
    ("secondary", "downwards"): "secondary_downwards_APRV",
    ("tertiary", "upwards"): "tertiary_upwards_APRV",
    ("tertiary", "downwards"): "tertiary_downwards_APRV",
}


def _is_number(value):
    """Return whether a value is a non-boolean numeric scalar."""
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _round(value, digits=6):
    """Round a numeric value for JSON reports while preserving None."""
    if value is None:
        return None
    return round(float(value), digits)


def _series(value):
    """Return the value when it is a list, otherwise an empty list."""
    return value if isinstance(value, list) else []


def _value_at(values, index, default=0.0):
    """Safely read a numeric value at an index with a default fallback."""
    values = _series(values)
    if index < len(values) and _is_number(values[index]):
        return float(values[index])
    return default


def _filtered_input_units(input_data):
    """Return input units in model/output order."""
    return list(input_data.get("Generating_Units", []))


def _unit_type(unit):
    """Classify a unit from its comments field for report logic."""
    comments = unit.get("comments", "")
    if comments.startswith("Therm"):
        return "thermal"
    if comments.startswith("PV"):
        return "pv"
    if "Partially Controllable" in comments:
        return "partially_controllable"
    return "res"


def _period_count(output_data):
    """Infer the number of dispatch periods represented in output data."""
    units = output_data.get("Generating_Units", [])
    if not units:
        return 0
    return max(len(_series(unit.get("Power"))) for unit in units)


def _reserve_pair(unit, reserve_field, period):
    """Read upward and downward reserve values for one unit and period."""
    reserve_data = unit.get(reserve_field, [])
    if not isinstance(reserve_data, list) or len(reserve_data) < 2:
        return 0.0, 0.0
    return _value_at(reserve_data[0], period), _value_at(reserve_data[1], period)


def _operating_state_id(input_unit, output_unit, period):
    """Internal helper for MMS report construction."""
    rows = _series(output_unit.get("Operating-states"))
    if period >= len(rows) or not isinstance(rows[period], list) or not rows[period]:
        return None
    selected_index = max(range(len(rows[period])), key=lambda idx: rows[period][idx])
    if rows[period][selected_index] < 0.5:
        return None
    operating_states = _series(input_unit.get("operating-states"))
    if selected_index < len(operating_states):
        return operating_states[selected_index].get("id", selected_index)
    return selected_index


def build_dispatch_instructions(input_data, output_data):
    """Build period-by-period dispatch instruction records for MMS consumers."""
    input_units = _filtered_input_units(input_data)
    output_units = output_data.get("Generating_Units", [])
    periods = _period_count(output_data)
    instructions = []

    for period in range(periods):
        for unit_index, output_unit in enumerate(output_units):
            input_unit = input_units[unit_index] if unit_index < len(input_units) else {}
            power = _value_at(output_unit.get("Power"), period)
            state = _value_at(output_unit.get("State"), period)
            startup = _value_at(output_unit.get("Startup"), period)
            shutdown = _value_at(output_unit.get("Shutdown"), period)
            if startup >= 0.5:
                commitment_action = "synchronize"
            elif shutdown >= 0.5:
                commitment_action = "desynchronize"
            elif state >= 0.5:
                commitment_action = "remain_online"
            else:
                commitment_action = "remain_offline"

            reserves = {}
            for reserve_name, reserve_field in RESERVE_FIELDS.items():
                upward, downward = _reserve_pair(output_unit, reserve_field, period)
                reserves[reserve_name] = {
                    "upwards_mw": _round(upward, 3),
                    "downwards_mw": _round(downward, 3),
                }

            setpoints = output_unit.get("Setpoints")
            setpoint = _value_at(setpoints, period, default=None) if isinstance(setpoints, list) else None

            instructions.append(
                {
                    "period": period + 1,
                    "source": "DS",
                    "gen_id": output_unit.get("gen_id", input_unit.get("gen_id", unit_index)),
                    "unit_index": unit_index,
                    "unit_type": _unit_type(input_unit or output_unit),
                    "commitment_action": commitment_action,
                    "state": _round(state, 3),
                    "active_power_mw": _round(power, 3),
                    "operating_state_id": _operating_state_id(input_unit, output_unit, period),
                    "setpoint": _round(setpoint, 6),
                    "reserves": reserves,
                }
            )

    return {
        "report_type": "dispatch_instructions",
        "scope": "DS",
        "source_requirements": [
            "Tender Part C 5.3 Dispatch Scheduling",
            "MDN Code Articles 115-123",
        ],
        "rtd_scope": "excluded",
        "period_count": periods,
        "instructions": instructions,
    }


def _reserve_coefficients(input_data, reserve_name, direction):
    """Internal helper for MMS report construction."""
    return input_data.get("Other_coefficients", {}).get(f"{reserve_name}_{direction}", [])


def _calculation_methods(input_data, direction):
    """Internal helper for MMS report construction."""
    key = f"calculation-method_{direction}"
    return input_data.get("constraints", {}).get("APRR_calculations", {}).get(key, [])


def _method_flag(methods, group, index=None):
    """Internal helper for MMS report construction."""
    try:
        if index is None:
            value = methods[group]
        else:
            value = methods[group][index]
    except (IndexError, TypeError):
        return 0.0
    return float(value) if _is_number(value) else 0.0


def _coefficient(coefficients, group, index=None):
    """Internal helper for MMS report construction."""
    try:
        if index is None:
            value = coefficients[group]
        else:
            value = coefficients[group][index]
    except (IndexError, TypeError):
        return 0.0
    return float(value) / 100.0 if _is_number(value) else 0.0


def _online_capacity_values(input_units, output_units, period):
    """Internal helper for MMS report construction."""
    values = []
    for unit_index, input_unit in enumerate(input_units):
        if _unit_type(input_unit) != "thermal" or unit_index >= len(output_units):
            continue
        state = _value_at(output_units[unit_index].get("State"), period)
        if state >= 0.5:
            values.append(_value_at(input_unit.get("availability"), period))
    values.sort(reverse=True)
    return values


def _reserve_requirement_breakdown(input_data, input_units, output_units, reserve_name, direction, period):
    """Internal helper for MMS report construction."""
    coefficients = _reserve_coefficients(input_data, reserve_name, direction)
    methods = _calculation_methods(input_data, direction)

    total_power = sum(_value_at(unit.get("Power"), period) for unit in output_units)
    pv_power = sum(
        _value_at(output_units[index].get("Power"), period)
        for index, input_unit in enumerate(input_units)
        if index < len(output_units) and _unit_type(input_unit) == "pv"
    )
    res_power = sum(
        _value_at(output_units[index].get("Power"), period)
        for index, input_unit in enumerate(input_units)
        if index < len(output_units) and _unit_type(input_unit) in ("res", "pv", "partially_controllable")
    )
    online_capacity = _online_capacity_values(input_units, output_units, period)
    largest_online = online_capacity[0] if online_capacity else 0.0
    largest_two_online = sum(online_capacity[:2])

    candidates = [
        {
            "method": "total_generation_percent",
            "metric_mw": total_power,
            "coefficient": _coefficient(coefficients, 0, 0),
            "enabled": _method_flag(methods, 0, 0),
        },
        {
            "method": "generation_excluding_pv_percent",
            "metric_mw": total_power - pv_power,
            "coefficient": _coefficient(coefficients, 0, 1),
            "enabled": _method_flag(methods, 0, 1),
        },
        {
            "method": "res_pv_generation_percent",
            "metric_mw": res_power,
            "coefficient": _coefficient(coefficients, 1, 0),
            "enabled": _method_flag(methods, 1, 0),
        },
        {
            "method": "res_generation_excluding_pv_percent",
            "metric_mw": res_power - pv_power,
            "coefficient": _coefficient(coefficients, 1, 1),
            "enabled": _method_flag(methods, 1, 1),
        },
        {
            "method": "largest_online_unit_percent",
            "metric_mw": largest_online,
            "coefficient": _coefficient(coefficients, 2),
            "enabled": _method_flag(methods, 2),
        },
        {
            "method": "largest_two_online_units_percent",
            "metric_mw": largest_two_online,
            "coefficient": _coefficient(coefficients, 3),
            "enabled": _method_flag(methods, 3),
        },
    ]

    for candidate in candidates:
        candidate["requirement_mw"] = (
            candidate["metric_mw"] * candidate["coefficient"] * candidate["enabled"]
        )
        candidate["metric_mw"] = _round(candidate["metric_mw"], 6)
        candidate["coefficient"] = _round(candidate["coefficient"], 6)
        candidate["enabled"] = _round(candidate["enabled"], 6)
        candidate["requirement_mw"] = _round(candidate["requirement_mw"], 6)

    required = max(candidate["requirement_mw"] for candidate in candidates) if candidates else 0.0
    active_method = max(candidates, key=lambda candidate: candidate["requirement_mw"])["method"] if candidates else None
    return required, active_method, candidates


def build_reserve_monitoring_report(input_data, output_data, tolerance=1e-3):
    """Recompute reserve requirements and compare them with solved provision."""
    input_units = _filtered_input_units(input_data)
    output_units = output_data.get("Generating_Units", [])
    periods = _period_count(output_data)
    period_reports = []
    summary = {}

    for period in range(periods):
        reserve_entries = {}
        for reserve_name, reserve_field in RESERVE_FIELDS.items():
            reserve_entries[reserve_name] = {}
            for direction, direction_index in (("upwards", 0), ("downwards", 1)):
                required, active_method, candidates = _reserve_requirement_breakdown(
                    input_data,
                    input_units,
                    output_units,
                    reserve_name,
                    direction,
                    period,
                )
                provided = sum(
                    _reserve_pair(output_unit, reserve_field, period)[direction_index]
                    for output_unit in output_units
                )
                violation_field = RESERVE_VIOLATION_FIELDS[(reserve_name, direction)]
                reported_shortage = _value_at(output_data.get(violation_field), period)
                surplus = provided - required
                status = "ok" if surplus + tolerance >= 0 else "shortfall"
                reserve_entries[reserve_name][direction] = {
                    "required_mw": _round(required, 6),
                    "provided_mw": _round(provided, 6),
                    "surplus_mw": _round(surplus, 6),
                    "reported_shortage_mw": _round(reported_shortage, 6),
                    "status": status,
                    "active_method": active_method,
                    "requirement_breakdown": candidates,
                }
                key = f"{reserve_name}_{direction}"
                item = summary.setdefault(
                    key,
                    {
                        "minimum_surplus_mw": None,
                        "maximum_reported_shortage_mw": 0.0,
                        "shortfall_periods": [],
                    },
                )
                if item["minimum_surplus_mw"] is None or surplus < item["minimum_surplus_mw"]:
                    item["minimum_surplus_mw"] = surplus
                item["maximum_reported_shortage_mw"] = max(
                    item["maximum_reported_shortage_mw"], reported_shortage
                )
                if status != "ok":
                    item["shortfall_periods"].append(period + 1)
        period_reports.append({"period": period + 1, "reserves": reserve_entries})

    for item in summary.values():
        item["minimum_surplus_mw"] = _round(item["minimum_surplus_mw"], 6)
        item["maximum_reported_shortage_mw"] = _round(item["maximum_reported_shortage_mw"], 6)

    return {
        "report_type": "reserve_monitoring",
        "scope": "RDAS_DS",
        "source_requirements": [
            "Tender reserve monitoring requirements",
            "MDN Code Article 109",
            "MDN Code Articles 127-130",
            "MDN Code Article 209",
        ],
        "period_count": periods,
        "summary": summary,
        "periods": period_reports,
    }


def build_res_curtailment_report(input_data, output_data):
    """Summarize RES/PV available, dispatched, and curtailed energy."""
    input_units = _filtered_input_units(input_data)
    output_units = output_data.get("Generating_Units", [])
    periods = _period_count(output_data)
    time_granularity = input_data.get("Time_granularity", 1)
    time_multiplier = float(time_granularity) if _is_number(time_granularity) else 1.0
    entries = []
    total_available = 0.0
    total_dispatched = 0.0
    total_curtailed = 0.0

    for period in range(periods):
        for unit_index, input_unit in enumerate(input_units):
            unit_type = _unit_type(input_unit)
            if unit_type not in ("res", "pv", "partially_controllable") or unit_index >= len(output_units):
                continue
            output_unit = output_units[unit_index]
            available = _value_at(input_unit.get("Production_Forecast"), period)
            if available == 0.0:
                available = _value_at(input_unit.get("availability"), period)
            dispatched = _value_at(output_unit.get("Power"), period)
            curtailed = max(0.0, available - dispatched)
            total_available += available
            total_dispatched += dispatched
            total_curtailed += curtailed
            setpoints = output_unit.get("Setpoints")
            setpoint = _value_at(setpoints, period, default=None) if isinstance(setpoints, list) else None
            entries.append(
                {
                    "period": period + 1,
                    "gen_id": output_unit.get("gen_id", input_unit.get("gen_id", unit_index)),
                    "unit_index": unit_index,
                    "unit_type": unit_type,
                    "available_mw": _round(available, 6),
                    "dispatched_mw": _round(dispatched, 6),
                    "curtailed_mw": _round(curtailed, 6),
                    "curtailed_mwh": _round(curtailed * time_multiplier, 6),
                    "curtailment_share": _round(curtailed / available, 6) if available > 0 else 0.0,
                    "setpoint": _round(setpoint, 6),
                }
            )

    return {
        "report_type": "res_curtailment",
        "scope": "RDAS_DS",
        "source_requirements": [
            "Tender Part C 5.3 Dispatch Scheduling",
            "MDN Code Articles 108, 208, 209",
            "MDN Code Appendix A RES setpoint rules",
        ],
        "summary": {
            "available_mwh": _round(total_available * time_multiplier, 6),
            "dispatched_mwh": _round(total_dispatched * time_multiplier, 6),
            "curtailed_mwh": _round(total_curtailed * time_multiplier, 6),
            "curtailment_share": _round(total_curtailed / total_available, 6)
            if total_available > 0
            else 0.0,
        },
        "entries": entries,
    }


def build_mms_reports(input_data, output_data, tolerance=1e-3):
    """Build all MMS-facing post-solve reports."""
    return {
        "Dispatch_Instructions": build_dispatch_instructions(input_data, output_data),
        "Reserve_Monitoring_Report": build_reserve_monitoring_report(
            input_data, output_data, tolerance=tolerance
        ),
        "RES_Curtailment_Report": build_res_curtailment_report(input_data, output_data),
    }

