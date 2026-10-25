"""Thermal cost-curve preparation, audit, and post-solve cost reconstruction helpers."""

THERMAL_PREFIX = "Therm"
COST_CURVE_FIELD = "var_gen_cost(euro/MW)"
QUADRATIC_COST_FIELD = "quadratic_cost_coefficients"
LEGACY_QUADRATIC_COST_FIELD = "quadratic_cost(euro)"
DEFAULT_COST_TIME_UNIT = "euro_per_mw_per_minute"
DEFAULT_QUADRATIC_SEGMENTS = 3


def _is_number(value):
    """Return whether a value is a non-boolean numeric scalar."""
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _numeric_list(value):
    """Internal helper for thermal cost-curve handling."""
    if not isinstance(value, list):
        return None
    if any(not _is_number(item) for item in value):
        return None
    return [float(item) for item in value]


def _max_positive(value):
    """Internal helper for thermal cost-curve handling."""
    if isinstance(value, list):
        numeric_values = [float(item) for item in value if _is_number(item)]
        return max(numeric_values) if numeric_values else 0.0
    if _is_number(value):
        return max(0.0, float(value))
    return 0.0


def _unit_path(index):
    """Internal helper for thermal cost-curve handling."""
    return f"Generating_Units[{index}].{COST_CURVE_FIELD}"


def _add_issue(issues, severity, code, message, unit_index, gen_id=None, **fields):
    """Append a structured issue record to a report."""
    issue = {
        "severity": severity,
        "code": code,
        "message": message,
        "unit_index": unit_index,
        "gen_id": gen_id,
    }
    issue.update({key: value for key, value in fields.items() if value is not None})
    issues.append(issue)


def _unit_status(issues):
    """Derive a per-unit cost-curve status from issue severities."""
    severities = {issue["severity"] for issue in issues}
    if "error" in severities:
        return "failed"
    if "warning" in severities:
        return "warning"
    return "passed"


def _report_status(issues):
    """Derive a report status from collected issue severities."""
    severities = {issue["severity"] for issue in issues}
    if "error" in severities:
        return "failed"
    if "warning" in severities:
        return "warning"
    return "passed"


def _cost_at_breakpoints(base_cost, segment_slopes, segment_widths):
    """Internal helper for thermal cost-curve handling."""
    costs = [base_cost]
    running_cost = base_cost
    for slope, width in zip(segment_slopes, segment_widths):
        running_cost += slope * width
        costs.append(running_cost)
    return [round(value, 6) for value in costs]


def _quadratic_coefficients(unit):
    """Internal helper for thermal cost-curve handling."""
    coefficients = unit.get(QUADRATIC_COST_FIELD) or unit.get(LEGACY_QUADRATIC_COST_FIELD)
    if not isinstance(coefficients, dict):
        return None
    if not all(_is_number(coefficients.get(key)) for key in ("a", "b", "c")):
        return None
    return {
        "a": float(coefficients["a"]),
        "b": float(coefficients["b"]),
        "c": float(coefficients["c"]),
    }


def _quadratic_cost(coefficients, power):
    """Internal helper for thermal cost-curve handling."""
    return coefficients["a"] * power * power + coefficients["b"] * power + coefficients["c"]


def _generation_config(input_data, unit):
    """Internal helper for thermal cost-curve handling."""
    global_config = input_data.get("optimization_parameters", {}).get(
        "thermal_cost_curve_generation", {}
    )
    unit_config = unit.get("cost_curve_generation", {})
    config = {}
    if isinstance(global_config, dict):
        config.update(global_config)
    if isinstance(unit_config, dict):
        config.update(unit_config)
    return config


def _generated_breakpoints(unit, config):
    """Internal helper for thermal cost-curve handling."""
    explicit_breakpoints = config.get("breakpoints")
    numeric_breakpoints = _numeric_list(explicit_breakpoints)
    if numeric_breakpoints and len(numeric_breakpoints) >= 2:
        return numeric_breakpoints

    min_power = _max_positive(unit.get("min_power(MW)"))
    max_power = _max_positive(unit.get("max_power(MW)"))
    if max_power <= min_power:
        return []

    segment_count = config.get("segments", DEFAULT_QUADRATIC_SEGMENTS)
    if not isinstance(segment_count, int) or isinstance(segment_count, bool):
        return []
    if segment_count < 1:
        return []

    width = (max_power - min_power) / segment_count
    return [min_power + width * index for index in range(segment_count)] + [max_power]


def generate_pwl_from_quadratic(unit, input_data=None):
    """Generate [breakpoints, base + secant slopes] from a quadratic cost curve."""

    input_data = input_data or {}
    coefficients = _quadratic_coefficients(unit)
    if coefficients is None:
        return None

    breakpoints = _generated_breakpoints(unit, _generation_config(input_data, unit))
    if len(breakpoints) < 2:
        return None

    slopes = []
    for left, right in zip(breakpoints, breakpoints[1:]):
        width = right - left
        if width <= 0:
            return None
        slopes.append((_quadratic_cost(coefficients, right) - _quadratic_cost(coefficients, left)) / width)

    base_cost = _quadratic_cost(coefficients, breakpoints[0])
    return [
        [round(value, 6) for value in breakpoints],
        [round(base_cost, 6)] + [round(value, 6) for value in slopes],
    ]


def prepare_thermal_cost_curves(input_data):
    """Populate missing/generated thermal PWL curves from quadratic coefficients."""

    generation_report = {
        "report_type": "thermal_cost_curve_generation",
        "status": "passed",
        "generated_count": 0,
        "skipped_count": 0,
        "issue_count": 0,
        "warning_count": 0,
        "error_count": 0,
        "issues": [],
        "units": [],
    }
    global_config = input_data.get("optimization_parameters", {}).get(
        "thermal_cost_curve_generation", {}
    )
    enabled = True
    replace_existing_default = False
    if isinstance(global_config, dict):
        enabled = global_config.get("enabled", True)
        replace_existing_default = global_config.get("replace_existing", False)
    if not enabled:
        generation_report["status"] = "skipped"
        return generation_report

    for unit_index, unit in enumerate(input_data.get("Generating_Units", [])):
        comments = unit.get("comments", "")
        if not isinstance(comments, str) or not comments.startswith(THERMAL_PREFIX):
            continue

        unit_config = unit.get("cost_curve_generation", {})
        if isinstance(unit_config, dict) and unit_config.get("enabled") is False:
            generation_report["skipped_count"] += 1
            continue

        replace_existing = replace_existing_default
        if isinstance(unit_config, dict):
            replace_existing = unit_config.get("replace_existing", replace_existing)

        existing_curve = unit.get(COST_CURVE_FIELD)
        if existing_curve is not None and not replace_existing:
            generation_report["skipped_count"] += 1
            continue

        generated_curve = generate_pwl_from_quadratic(unit, input_data)
        if generated_curve is None:
            if _quadratic_coefficients(unit) is not None:
                _add_issue(
                    generation_report["issues"],
                    "warning",
                    "quadratic_curve_generation_failed",
                    "Thermal PWL curve could not be generated from quadratic coefficients.",
                    unit_index,
                    unit.get("gen_id", unit_index),
                )
            generation_report["skipped_count"] += 1
            continue

        unit[COST_CURVE_FIELD] = generated_curve
        unit.setdefault(
            "cost_curve_source",
            {
                "type": "generated_from_quadratic",
                "reference": QUADRATIC_COST_FIELD,
                "currency": "EUR",
                "basis": input_data.get("optimization_parameters", {}).get(
                    "cost_curve_time_unit", DEFAULT_COST_TIME_UNIT
                ),
                "method": "secant_slopes_between_breakpoints",
            },
        )
        generation_report["generated_count"] += 1
        generation_report["units"].append(
            {
                "unit_index": unit_index,
                "gen_id": unit.get("gen_id", unit_index),
                "breakpoints_mw": generated_curve[0],
                "coefficients": generated_curve[1],
                "source": unit.get("cost_curve_source"),
            }
        )

    if generation_report["issues"]:
        generation_report["status"] = _report_status(generation_report["issues"])
    generation_report["issue_count"] = len(generation_report["issues"])
    generation_report["warning_count"] = len(
        [issue for issue in generation_report["issues"] if issue["severity"] == "warning"]
    )
    generation_report["error_count"] = len(
        [issue for issue in generation_report["issues"] if issue["severity"] == "error"]
    )
    return generation_report


def is_non_decreasing(values, tolerance=1e-6):
    """Return whether a numeric sequence is nondecreasing within tolerance."""
    return all(right + tolerance >= left for left, right in zip(values, values[1:]))


def cost_curve_time_multiplier(input_data):
    """Return the multiplier applied to cost-curve coefficients in the objective.

    The legacy input data has historically multiplied thermal coefficients by
    Time_granularity directly. For academically standard EUR/MWh slopes, set
    optimization_parameters.cost_curve_time_unit to "euro_per_mwh".
    """

    parameters = input_data.get("optimization_parameters", {})
    if _is_number(parameters.get("cost_curve_time_multiplier")):
        return float(parameters["cost_curve_time_multiplier"])

    time_granularity = input_data.get("Time_granularity", 1.0)
    time_granularity = float(time_granularity) if _is_number(time_granularity) else 1.0
    unit = parameters.get("cost_curve_time_unit", DEFAULT_COST_TIME_UNIT)

    if unit == "euro_per_mwh":
        return time_granularity / 60.0
    if unit == "euro_per_dispatch_period":
        return 1.0
    return time_granularity


def parse_thermal_cost_curve(unit):
    """Parse one unit's PWL curve into breakpoints, base cost, and marginal slopes."""
    curve = unit.get(COST_CURVE_FIELD, [[], []])
    if not isinstance(curve, list) or len(curve) != 2:
        return [], [], [], None
    breakpoints = _numeric_list(curve[0]) or []
    coefficients = _numeric_list(curve[1]) or []
    if len(breakpoints) < 2 or len(coefficients) != len(breakpoints):
        return breakpoints, coefficients, [], None
    widths = [right - left for left, right in zip(breakpoints, breakpoints[1:])]
    slopes = coefficients[1:]
    return breakpoints, coefficients, widths, is_non_decreasing(slopes)


def _as_list(value):
    """Return the value when it is a list, otherwise an empty list."""
    return value if isinstance(value, list) else []


def _value_at(values, index, default=0.0):
    """Safely read a numeric value at an index with a default fallback."""
    if isinstance(values, list) and index < len(values) and _is_number(values[index]):
        return float(values[index])
    return default


def _filtered_input_units(input_data):
    """Return input units in model/output order."""
    return list(input_data.get("Generating_Units", []))


def _period_count(output_data):
    """Infer the number of dispatch periods represented in output data."""
    units = output_data.get("Generating_Units", [])
    if not units:
        return 0
    return max(len(_as_list(unit.get("Power"))) for unit in units)


def _segment_dispatch(power, state, breakpoints, widths):
    """Internal helper for thermal cost-curve handling."""
    remaining = max(0.0, power - breakpoints[0] * state)
    dispatch = []
    for width in widths:
        segment_mw = min(max(0.0, width), remaining)
        dispatch.append(segment_mw)
        remaining -= segment_mw
    return dispatch, max(0.0, remaining)


def build_thermal_cost_report(input_data, output_data):
    """Reconstruct solved thermal cost and segment dispatch by period."""
    input_units = _filtered_input_units(input_data)
    output_units = output_data.get("Generating_Units", [])
    periods = _period_count(output_data)
    multiplier = cost_curve_time_multiplier(input_data)
    entries = []
    summary = {"thermal_cost": 0.0, "unpriced_mw": 0.0}

    for unit_index, input_unit in enumerate(input_units):
        comments = input_unit.get("comments", "")
        if not isinstance(comments, str) or not comments.startswith(THERMAL_PREFIX):
            continue
        if unit_index >= len(output_units):
            continue

        output_unit = output_units[unit_index]
        breakpoints, coefficients, widths, is_convex = parse_thermal_cost_curve(input_unit)
        if not breakpoints or len(coefficients) != len(breakpoints):
            continue

        slopes = coefficients[1:]
        for period in range(periods):
            power = _value_at(output_unit.get("Power"), period)
            state = _value_at(output_unit.get("State"), period)
            segment_dispatch, unpriced_mw = _segment_dispatch(power, state, breakpoints, widths)
            base_cost = coefficients[0] * state * multiplier
            segments = []
            segment_cost_total = 0.0
            for segment_index, (segment_mw, slope, width) in enumerate(
                zip(segment_dispatch, slopes, widths),
                start=1,
            ):
                segment_cost = segment_mw * slope * multiplier
                segment_cost_total += segment_cost
                segments.append(
                    {
                        "segment": segment_index,
                        "width_mw": round(max(0.0, width), 6),
                        "dispatch_mw": round(segment_mw, 6),
                        "marginal_cost": round(slope, 6),
                        "cost": round(segment_cost, 6),
                    }
                )

            total_cost = base_cost + segment_cost_total
            summary["thermal_cost"] += total_cost
            summary["unpriced_mw"] += unpriced_mw
            entries.append(
                {
                    "period": period + 1,
                    "unit_index": unit_index,
                    "gen_id": output_unit.get("gen_id", input_unit.get("gen_id", unit_index)),
                    "state": round(state, 6),
                    "power_mw": round(power, 6),
                    "formulation": "convex_incremental_pwl"
                    if is_convex
                    else "nonconvex_incremental_pwl",
                    "base_cost": round(base_cost, 6),
                    "segments": segments,
                    "unpriced_mw": round(unpriced_mw, 6),
                    "total_cost": round(total_cost, 6),
                }
            )

    summary["thermal_cost"] = round(summary["thermal_cost"], 6)
    summary["unpriced_mw"] = round(summary["unpriced_mw"], 6)
    return {
        "report_type": "thermal_cost_report",
        "cost_time_multiplier": round(multiplier, 6),
        "summary": summary,
        "entries": entries,
    }


def audit_thermal_cost_curves(input_data, tolerance=1e-6):
    """Audit thermal-unit PWL production-cost curves used by the MIP.

    The current formulation expects var_gen_cost(euro/MW) = [breakpoints, costs],
    where costs[0] is the base cost at the first breakpoint and costs[1:] are
    marginal segment costs for consecutive breakpoint intervals.
    """

    units = []
    issues = []

    for unit_index, unit in enumerate(input_data.get("Generating_Units", [])):
        comments = unit.get("comments", "")
        if not isinstance(comments, str) or not comments.startswith(THERMAL_PREFIX):
            continue

        gen_id = unit.get("gen_id", unit_index)
        unit_issues = []
        curve = unit.get(COST_CURVE_FIELD)
        unit_record = {
            "unit_index": unit_index,
            "gen_id": gen_id,
            "comments": comments,
            "status": "passed",
            "field": _unit_path(unit_index),
            "formulation": "incremental_piecewise_linear",
            "recommended_model": None,
            "cost_curve_source": unit.get("cost_curve_source"),
            "cost_curve_source_present": isinstance(unit.get("cost_curve_source"), dict),
            "quadratic_source_coefficients_present": False,
            "quadratic_source_verified": False,
            "breakpoints_mw": [],
            "base_cost_coefficient": None,
            "segment_slopes": [],
            "segments": [],
            "cost_at_breakpoints": [],
        }

        quadratic_coefficients = _quadratic_coefficients(unit)
        if quadratic_coefficients is not None:
            unit_record["quadratic_source_coefficients_present"] = True

        if not isinstance(curve, list) or len(curve) != 2:
            _add_issue(
                unit_issues,
                "error",
                "missing_or_malformed_cost_curve",
                f"{_unit_path(unit_index)} must contain [breakpoints, cost_coefficients].",
                unit_index,
                gen_id,
            )
            unit_record["status"] = _unit_status(unit_issues)
            unit_record["issues"] = unit_issues
            units.append(unit_record)
            issues.extend(unit_issues)
            continue

        breakpoints = _numeric_list(curve[0])
        costs = _numeric_list(curve[1])
        if breakpoints is None or costs is None:
            _add_issue(
                unit_issues,
                "error",
                "non_numeric_cost_curve",
                f"{_unit_path(unit_index)} breakpoints and coefficients must be numeric lists.",
                unit_index,
                gen_id,
            )
            unit_record["status"] = _unit_status(unit_issues)
            unit_record["issues"] = unit_issues
            units.append(unit_record)
            issues.extend(unit_issues)
            continue

        unit_record["breakpoints_mw"] = [round(value, 6) for value in breakpoints]
        unit_record["base_cost_coefficient"] = round(costs[0], 6) if costs else None
        unit_record["segment_slopes"] = [round(value, 6) for value in costs[1:]]

        if len(breakpoints) < 2:
            _add_issue(
                unit_issues,
                "error",
                "too_few_cost_breakpoints",
                f"{_unit_path(unit_index)} must have at least two breakpoints.",
                unit_index,
                gen_id,
            )
        if len(costs) != len(breakpoints):
            _add_issue(
                unit_issues,
                "error",
                "cost_curve_length_mismatch",
                f"{_unit_path(unit_index)} coefficients must match breakpoint count.",
                unit_index,
                gen_id,
                breakpoint_count=len(breakpoints),
                coefficient_count=len(costs),
            )

        segment_widths = []
        if len(breakpoints) >= 2:
            for segment_index, (left, right) in enumerate(zip(breakpoints, breakpoints[1:])):
                width = right - left
                segment_widths.append(width)
                if width <= tolerance:
                    _add_issue(
                        unit_issues,
                        "error",
                        "non_increasing_cost_breakpoints",
                        "Thermal cost-curve breakpoints must be strictly increasing.",
                        unit_index,
                        gen_id,
                        segment_index=segment_index,
                        left_mw=left,
                        right_mw=right,
                    )

        for cost_index, coefficient in enumerate(costs):
            if coefficient < -tolerance:
                _add_issue(
                    unit_issues,
                    "error",
                    "negative_cost_coefficient",
                    "Thermal cost-curve coefficients must be nonnegative.",
                    unit_index,
                    gen_id,
                    coefficient_index=cost_index,
                    value=coefficient,
                )

        if len(costs) >= 2:
            slopes = costs[1:]
            unit_record["recommended_model"] = (
                "convex_incremental_pwl"
                if is_non_decreasing(slopes, tolerance=tolerance)
                else "nonconvex_incremental_pwl"
            )
            for segment_index, (left, right) in enumerate(zip(slopes, slopes[1:]), start=1):
                if right + tolerance < left:
                    _add_issue(
                        unit_issues,
                        "warning",
                        "nonconvex_marginal_costs",
                        (
                            "PWL marginal costs decrease between adjacent segments; "
                            "this is not a convex quadratic-cost approximation."
                        ),
                        unit_index,
                        gen_id,
                        segment_index=segment_index,
                        previous_slope=left,
                        next_slope=right,
                    )

        if breakpoints:
            min_power = _max_positive(unit.get("min_power(MW)"))
            if abs(breakpoints[0] - min_power) > tolerance:
                _add_issue(
                    unit_issues,
                    "warning",
                    "first_breakpoint_differs_from_min_power",
                    "First thermal cost-curve breakpoint differs from unit minimum power.",
                    unit_index,
                    gen_id,
                    first_breakpoint_mw=breakpoints[0],
                    min_power_mw=min_power,
                )

            max_power = _max_positive(unit.get("max_power(MW)"))
            if breakpoints[-1] + tolerance < max_power:
                _add_issue(
                    unit_issues,
                    "warning",
                    "cost_curve_does_not_cover_max_power",
                    (
                        "Last thermal cost-curve breakpoint is below the unit's declared "
                        "maximum power. Production-cost curves should normally cover the "
                        "full technical dispatch range, while availability limits should "
                        "remain period-specific constraints."
                    ),
                    unit_index,
                    gen_id,
                    last_breakpoint_mw=breakpoints[-1],
                    declared_max_power_mw=max_power,
                )
            max_availability = _max_positive(unit.get("availability"))
            if breakpoints[-1] + tolerance < max_availability:
                _add_issue(
                    unit_issues,
                    "warning",
                    "cost_curve_does_not_cover_availability",
                    (
                        "Last thermal cost-curve breakpoint is below the unit's maximum "
                        "available power in this input scenario, so dispatch above the "
                        "curve endpoint would be impossible or unpriced."
                    ),
                    unit_index,
                    gen_id,
                    last_breakpoint_mw=breakpoints[-1],
                    max_available_power_mw=max_availability,
                )

        if len(breakpoints) >= 2 and len(costs) == len(breakpoints):
            slopes = costs[1:]
            positive_widths = [max(0.0, width) for width in segment_widths]
            unit_record["cost_at_breakpoints"] = _cost_at_breakpoints(
                costs[0], slopes, positive_widths
            )
            if quadratic_coefficients is not None:
                quadratic_costs = [
                    round(_quadratic_cost(quadratic_coefficients, point), 6)
                    for point in breakpoints
                ]
                unit_record["quadratic_cost_at_breakpoints"] = quadratic_costs
                unit_record["quadratic_source_verified"] = all(
                    abs(left - right) <= tolerance
                    for left, right in zip(unit_record["cost_at_breakpoints"], quadratic_costs)
                )
            for segment_index, (left, right, slope, width) in enumerate(
                zip(breakpoints, breakpoints[1:], slopes, positive_widths),
                start=1,
            ):
                unit_record["segments"].append(
                    {
                        "segment": segment_index,
                        "from_mw": round(left, 6),
                        "to_mw": round(right, 6),
                        "width_mw": round(width, 6),
                        "marginal_cost": round(slope, 6),
                    }
                )

        unit_record["status"] = _unit_status(unit_issues)
        unit_record["issues"] = unit_issues
        units.append(unit_record)
        issues.extend(unit_issues)

    return {
        "report_type": "thermal_cost_curve_audit",
        "status": _report_status(issues),
        "tolerance": tolerance,
        "thermal_unit_count": len(units),
        "issue_count": len(issues),
        "warning_count": len([issue for issue in issues if issue["severity"] == "warning"]),
        "error_count": len([issue for issue in issues if issue["severity"] == "error"]),
        "interpretation": (
            "The active MIP uses an incremental piecewise-linear production-cost "
            "formulation for thermal units. The audit verifies the supplied PWL "
            "data and checks whether marginal segment costs are consistent with a "
            "convex quadratic-cost approximation."
        ),
        "units": units,
        "issues": issues,
    }
