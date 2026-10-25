"""Post-solve validation checks for feasibility and output consistency."""

def _is_number(value):
    """Return whether a value is a non-boolean numeric scalar."""
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _as_list(value):
    """Return the value when it is a list, otherwise an empty list."""
    return value if isinstance(value, list) else []


def _max_abs(values):
    """Return the largest absolute numeric value from an iterable."""
    numeric_values = [abs(value) for value in values if _is_number(value)]
    return max(numeric_values) if numeric_values else 0.0


def _filtered_input_units(input_data):
    """Return input units in model order.

    Generating units are no longer removed merely because their availability is
    zero. Keeping the original list preserves the project invariant that
    ``gen_id`` equals the unit's list position.
    """
    return list(input_data.get("Generating_Units", []))


def _add_check(checks, name, passed, detail, severity="error"):
    """Internal helper for post-solve validation checks for feasibility and output consistency."""
    checks.append(
        {
            "name": name,
            "status": "passed" if passed else "failed",
            "severity": severity,
            "detail": detail,
        }
    )


def validate_solution(input_data, output_data, tolerance=1e-3):
    """Validate solved output arrays and feasibility evidence against input data."""
    checks = []
    output_units = output_data.get("Generating_Units", [])
    input_units = _filtered_input_units(input_data)
    load_forecast = input_data.get("Load_forecast", [])
    expected_periods = max(len(load_forecast) - 1, 0)

    solution_status = output_data.get("Solution_Status", "Unknown")
    _add_check(
        checks,
        "solver_status",
        solution_status == "Optimal",
        f"Solution status is {solution_status}.",
    )

    _add_check(
        checks,
        "unit_count",
        len(output_units) == len(input_units),
        f"Output has {len(output_units)} units; input has {len(input_units)} units.",
    )

    length_errors = []
    for index, unit in enumerate(output_units):
        for field in ("Power", "State", "Startup", "Shutdown"):
            values = unit.get(field)
            if isinstance(values, list) and len(values) != expected_periods:
                length_errors.append(
                    f"unit {index} field {field} has {len(values)} values, expected {expected_periods}"
                )
    _add_check(
        checks,
        "period_lengths",
        not length_errors,
        "; ".join(length_errors) if length_errors else f"All period arrays have {expected_periods} values.",
    )

    load_curtailment = output_data.get("Load_Cutrailment", [])
    if isinstance(load_curtailment, list):
        load_residuals = []
        for period in range(min(expected_periods, len(load_curtailment))):
            total_power = sum(
                unit.get("Power", [])[period]
                for unit in output_units
                if len(unit.get("Power", [])) > period and _is_number(unit.get("Power", [])[period])
            )
            target_load = load_forecast[period + 1]
            residual = total_power + load_curtailment[period] - target_load
            load_residuals.append(residual)
        max_load_residual = _max_abs(load_residuals)
        _add_check(
            checks,
            "load_balance",
            max_load_residual <= tolerance,
            f"Maximum absolute load-balance residual is {max_load_residual:.6g} MW.",
        )
        max_load_curtailment = _max_abs(load_curtailment)
        _add_check(
            checks,
            "load_curtailment",
            max_load_curtailment <= tolerance,
            f"Maximum reported load curtailment is {max_load_curtailment:.6g} MW.",
            severity="warning",
        )
    else:
        _add_check(
            checks,
            "load_balance",
            not input_data.get("constraints", {}).get("load_production_balance_constraint", False),
            "Load curtailment output is unavailable.",
        )
        max_load_residual = None

    availability_violations = []
    state_power_violations = []
    binary_violations = []
    startup_shutdown_violations = []
    for index, unit in enumerate(output_units):
        input_unit = input_units[index] if index < len(input_units) else {}
        availability = _as_list(input_unit.get("availability", []))
        powers = _as_list(unit.get("Power", []))
        states = _as_list(unit.get("State", []))
        startups = _as_list(unit.get("Startup", []))
        shutdowns = _as_list(unit.get("Shutdown", []))
        previous_state = input_unit.get("state", 0)
        for period, power in enumerate(powers):
            if not _is_number(power):
                continue
            if power < -tolerance:
                availability_violations.append(
                    f"unit {index} period {period + 1} has negative power {power}"
                )
            if period < len(availability) and power - availability[period] > tolerance:
                availability_violations.append(
                    f"unit {index} period {period + 1} power {power} exceeds availability {availability[period]}"
                )
            if period < len(states) and _is_number(states[period]):
                if abs(states[period]) <= tolerance and power > tolerance:
                    state_power_violations.append(
                        f"unit {index} period {period + 1} has state {states[period]} and power {power}"
                    )
        for period, state_value in enumerate(states):
            if not _is_number(state_value):
                continue
            if min(abs(state_value), abs(state_value - 1)) > tolerance:
                binary_violations.append(
                    f"unit {index} period {period + 1} has nonbinary state {state_value}"
                )
            if period < len(startups) and _is_number(startups[period]):
                if min(abs(startups[period]), abs(startups[period] - 1)) > tolerance:
                    binary_violations.append(
                        f"unit {index} period {period + 1} has nonbinary startup {startups[period]}"
                    )
            if period < len(shutdowns) and _is_number(shutdowns[period]):
                if min(abs(shutdowns[period]), abs(shutdowns[period] - 1)) > tolerance:
                    binary_violations.append(
                        f"unit {index} period {period + 1} has nonbinary shutdown {shutdowns[period]}"
                    )
            if _is_number(previous_state):
                expected_startup = max(0, round(state_value) - round(previous_state))
                expected_shutdown = max(0, round(previous_state) - round(state_value))
                if period < len(startups) and _is_number(startups[period]):
                    if abs(startups[period] - expected_startup) > tolerance:
                        startup_shutdown_violations.append(
                            f"unit {index} period {period + 1} startup {startups[period]} expected {expected_startup}"
                        )
                if period < len(shutdowns) and _is_number(shutdowns[period]):
                    if abs(shutdowns[period] - expected_shutdown) > tolerance:
                        startup_shutdown_violations.append(
                            f"unit {index} period {period + 1} shutdown {shutdowns[period]} expected {expected_shutdown}"
                        )
            previous_state = state_value
    _add_check(
        checks,
        "availability_bounds",
        not availability_violations,
        "; ".join(availability_violations[:10])
        if availability_violations
        else "Power values are nonnegative and do not exceed availability.",
    )
    _add_check(
        checks,
        "state_power_consistency",
        not state_power_violations,
        "; ".join(state_power_violations[:10])
        if state_power_violations
        else "No unit produces power while reported off.",
    )
    _add_check(
        checks,
        "binary_commitment_outputs",
        not binary_violations,
        "; ".join(binary_violations[:10])
        if binary_violations
        else "State, startup, and shutdown outputs are binary within tolerance.",
    )
    _add_check(
        checks,
        "startup_shutdown_consistency",
        not startup_shutdown_violations,
        "; ".join(startup_shutdown_violations[:10])
        if startup_shutdown_violations
        else "Startup and shutdown outputs match consecutive state changes.",
    )

    reserve_errors = []
    reserve_limits = {
        "Primary_Active_Power_Reserves(MW)": "Primary_Active_Power_Reserves(MW)",
        "Secondary_Active_Power_Reserves(MW)": "Secondary_Active_Power_Reserves(MW)",
        "Tertiary_Active_Power_Reserves(MW)": "Tertiary_Active_Power_Reserves(MW)",
    }
    for unit_index, unit in enumerate(output_units):
        input_unit = input_units[unit_index] if unit_index < len(input_units) else {}
        for reserve_field in (
            "Primary_Active_Power_Reserves(MW)",
            "Secondary_Active_Power_Reserves(MW)",
            "Tertiary_Active_Power_Reserves(MW)",
        ):
            reserve_pair = unit.get(reserve_field, [])
            if not isinstance(reserve_pair, list):
                continue
            for direction_index, values in enumerate(reserve_pair):
                if not isinstance(values, list):
                    reserve_errors.append(
                        f"unit {unit_index} {reserve_field}[{direction_index}] is not a list"
                    )
                    continue
                if len(values) != expected_periods:
                    reserve_errors.append(
                        f"unit {unit_index} {reserve_field}[{direction_index}] has {len(values)} values"
                    )
                negative_values = [value for value in values if _is_number(value) and value < -tolerance]
                if negative_values:
                    reserve_errors.append(
                        f"unit {unit_index} {reserve_field}[{direction_index}] has negative values"
                    )
                input_limits = input_unit.get(reserve_limits[reserve_field], [])
                if isinstance(input_limits, list) and direction_index < len(input_limits):
                    reserve_limit = input_limits[direction_index]
                    if _is_number(reserve_limit):
                        over_limit_values = [
                            value
                            for value in values
                            if _is_number(value) and value - reserve_limit > tolerance
                        ]
                        if over_limit_values:
                            reserve_errors.append(
                                f"unit {unit_index} {reserve_field}[{direction_index}] exceeds limit {reserve_limit}"
                            )
    _add_check(
        checks,
        "reserve_outputs",
        not reserve_errors,
        "; ".join(reserve_errors[:10]) if reserve_errors else "Reserve outputs are shaped correctly and nonnegative.",
    )

    violation_fields = [
        "primary_upwards_APRV",
        "primary_downwards_APRV",
        "secondary_upwards_APRV",
        "secondary_downwards_APRV",
        "tertiary_upwards_APRV",
        "tertiary_downwards_APRV",
    ]
    max_reported_violation = 0.0
    for field in violation_fields:
        max_reported_violation = max(max_reported_violation, _max_abs(_as_list(output_data.get(field))))
    _add_check(
        checks,
        "reported_apr_violations",
        max_reported_violation <= tolerance,
        f"Maximum reported APR violation is {max_reported_violation:.6g} MW.",
        severity="warning",
    )

    failed_errors = [check for check in checks if check["status"] == "failed" and check["severity"] == "error"]
    failed_warnings = [check for check in checks if check["status"] == "failed" and check["severity"] == "warning"]
    if failed_errors:
        report_status = "failed"
    elif failed_warnings:
        report_status = "warning"
    else:
        report_status = "passed"

    return {
        "status": report_status,
        "tolerance": tolerance,
        "max_load_balance_residual": max_load_residual,
        "max_reported_apr_violation": max_reported_violation,
        "checks": checks,
    }


def format_validation_report(report):
    """Render post-solve validation checks as console text."""
    lines = [f"Validation status: {report['status']}"]
    for check in report["checks"]:
        marker = "OK" if check["status"] == "passed" else check["severity"].upper()
        lines.append(f"[{marker}] {check['name']}: {check['detail']}")
    return "\n".join(lines)
