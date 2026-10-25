"""Penalty hierarchy checks for soft-constraint coefficients."""

PENALTY_FIELDS = (
    "x_load",
    "x_primary_APR_up",
    "x_primary_APR_down",
    "x_secondary_APR_up",
    "x_secondary_APR_down",
    "x_tertiary_APR_up",
    "x_tertiary_APR_down",
    "x_forbidden_zones",
    "x_ramp",
    "x_must_run",
    "x_min_transition_oper_states_a",
    "x_min_transition_oper_states_a_left",
    "x_min_transition_oper_states_b",
    "x_min_transition_oper_states_b_left",
    "x_max_oper_state_time_b",
    "x_max_oper_state_time_b_left",
    "x_min_transition_states",
    "x_min_transition_states_left",
    "x_Grid_Capacity",
    "x_testing_mode",
    "x_RES_PV_power_plus",
    "x_RES_PV_power_minus",
    "x_OOS_more_than",
    "x_OOS_less_than",
)


def _is_number(value):
    """Return whether a value is a non-boolean numeric scalar."""
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _add_issue(issues, severity, code, message, **fields):
    """Append a structured issue record to a report."""
    issue = {
        "severity": severity,
        "code": code,
        "message": message,
    }
    issue.update({key: value for key, value in fields.items() if value is not None})
    issues.append(issue)


def _status(issues):
    """Derive an audit status from collected issue severities."""
    severities = {issue["severity"] for issue in issues}
    if "error" in severities:
        return "failed"
    if "warning" in severities:
        return "warning"
    return "passed"


def _value(values, key):
    """Internal helper for penalty hierarchy checks for soft-constraint coefficients."""
    value = values.get(key)
    return float(value) if _is_number(value) else None


def _check_at_least(issues, values, higher_key, lower_key, rationale):
    """Internal helper for penalty hierarchy checks for soft-constraint coefficients."""
    higher = _value(values, higher_key)
    lower = _value(values, lower_key)
    if higher is None or lower is None:
        return
    if higher < lower:
        _add_issue(
            issues,
            "warning",
            "penalty_priority_inversion",
            f"{higher_key} should be at least {lower_key}.",
            higher_priority_penalty=higher_key,
            lower_priority_penalty=lower_key,
            higher_priority_value=higher,
            lower_priority_value=lower,
            rationale=rationale,
        )


def audit_penalty_hierarchy(input_data):
    """Audit soft-constraint penalty weights for priority consistency."""

    cost_parameters = input_data.get("Cost_parameters", {})
    issues = []
    values = {}

    if not isinstance(cost_parameters, dict):
        _add_issue(
            issues,
            "error",
            "cost_parameters_not_object",
            "Cost_parameters must be an object containing soft-constraint penalty weights.",
        )
        cost_parameters = {}

    for key in PENALTY_FIELDS:
        value = cost_parameters.get(key)
        if value is None:
            _add_issue(
                issues,
                "warning",
                "missing_penalty",
                f"Cost_parameters.{key} is missing; the active model may fail if that term is enabled.",
                penalty=key,
            )
            continue
        if not _is_number(value):
            _add_issue(
                issues,
                "error",
                "non_numeric_penalty",
                f"Cost_parameters.{key} must be numeric.",
                penalty=key,
                value=value,
            )
            continue
        values[key] = float(value)
        if value <= 0:
            _add_issue(
                issues,
                "error",
                "non_positive_penalty",
                f"Cost_parameters.{key} must be positive.",
                penalty=key,
                value=value,
            )

    reserve_up_order = (
        ("x_primary_APR_up", "x_secondary_APR_up"),
        ("x_secondary_APR_up", "x_tertiary_APR_up"),
    )
    reserve_down_order = (
        ("x_primary_APR_down", "x_secondary_APR_down"),
        ("x_secondary_APR_down", "x_tertiary_APR_down"),
    )
    for higher_key, lower_key in reserve_up_order + reserve_down_order:
        _check_at_least(
            issues,
            values,
            higher_key,
            lower_key,
            "Higher-quality reserve shortfalls should not be cheaper than lower-quality reserve shortfalls.",
        )

    for reserve_key in (
        "x_primary_APR_up",
        "x_primary_APR_down",
        "x_secondary_APR_up",
        "x_secondary_APR_down",
        "x_tertiary_APR_up",
        "x_tertiary_APR_down",
    ):
        _check_at_least(
            issues,
            values,
            "x_load",
            reserve_key,
            "Load balance slack should normally dominate reserve-shortfall slack.",
        )

    for operational_key in (
        "x_forbidden_zones",
        "x_ramp",
        "x_Grid_Capacity",
        "x_testing_mode",
        "x_OOS_more_than",
        "x_OOS_less_than",
        "x_max_oper_state_time_b",
        "x_max_oper_state_time_b_left",
    ):
        _check_at_least(
            issues,
            values,
            operational_key,
            "x_primary_APR_up",
            "Operational feasibility slacks should be priced at least as strongly as the strongest reserve slack.",
        )

    for res_key in ("x_RES_PV_power_plus", "x_RES_PV_power_minus"):
        _check_at_least(
            issues,
            values,
            res_key,
            "x_load",
            "RES/PV forecast-deviation penalties should not make load slack attractive.",
        )

    return {
        "report_type": "penalty_hierarchy_audit",
        "status": _status(issues),
        "penalties": {key: values[key] for key in sorted(values)},
        "issue_count": len(issues),
        "warning_count": len([issue for issue in issues if issue["severity"] == "warning"]),
        "error_count": len([issue for issue in issues if issue["severity"] == "error"]),
        "interpretation": (
            "This audit checks soft-constraint penalty priorities. It does not infer "
            "market economics; it flags weights that can make lower-priority violations "
            "look cheaper than higher-priority violations."
        ),
        "issues": issues,
    }
