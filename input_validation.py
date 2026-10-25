"""Input validation rules for MMS optimization JSON files before model construction."""

from mms.cost_curves import DEFAULT_COST_TIME_UNIT, audit_thermal_cost_curves
from mms.penalties import audit_penalty_hierarchy


REQUIRED_TOP_LEVEL_KEYS = {
    "Cost_parameters",
    "Other_coefficients",
    "constraints",
    "optimization_parameters",
    "Generating_Units",
    "Time_granularity",
    "Load_forecast",
}

REQUIRED_UNIT_KEYS = {
    "gen_id",
    "comments",
    "state",
    "current_Power(MW)",
    "availability",
    "Production_Forecast",
    "max_power(MW)",
    "min_power(MW)",
    "operating-states",
    "operating-state-transitions",
}

RESERVE_FIELDS = (
    "Primary_Active_Power_Reserves(MW)",
    "Secondary_Active_Power_Reserves(MW)",
    "Tertiary_Active_Power_Reserves(MW)",
)
UNSUPPORTED_OPERATING_STATE_MAX_TRANSITION_FIELDS = (
    "max-transition-time_a",
    "max-transition-time-left_a",
)


class InputValidationError(ValueError):
    """Exception carrying structured validation errors and warnings."""
    def __init__(self, errors, warnings=None):
        self.errors = errors
        self.warnings = warnings or []
        super().__init__("\n".join(errors))


def _is_number(value):
    """Return whether a value is a non-boolean numeric scalar."""
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _is_binary(value):
    """Return whether a value is accepted as a binary input flag."""
    return value in (0, 1, False, True)


def _check_numeric_list(errors, warnings, value, expected_len, path, *, allow_negative=False):
    """Internal helper for input validation rules for mms optimization json files before model construction."""
    if not isinstance(value, list):
        errors.append(f"{path} must be a list.")
        return
    if len(value) != expected_len:
        errors.append(f"{path} has {len(value)} values; expected {expected_len}.")
    for index, item in enumerate(value):
        if not _is_number(item):
            errors.append(f"{path}[{index}] must be numeric.")
        elif not allow_negative and item < 0:
            errors.append(f"{path}[{index}] must be nonnegative.")


def validate_input_data(input_data):
    """Validate the optimization input and return structured errors and warnings."""
    errors = []
    warnings = []

    if not isinstance(input_data, dict):
        raise InputValidationError(["Input data must be a JSON object."])

    missing = sorted(REQUIRED_TOP_LEVEL_KEYS - set(input_data))
    if missing:
        errors.append(f"Missing required top-level keys: {', '.join(missing)}.")

    load_forecast = input_data.get("Load_forecast", [])
    if not isinstance(load_forecast, list) or len(load_forecast) < 2:
        errors.append("Load_forecast must contain the initial period plus at least one dispatch period.")
        dispatch_periods = 0
    else:
        dispatch_periods = len(load_forecast) - 1
        for index, value in enumerate(load_forecast):
            if not _is_number(value):
                errors.append(f"Load_forecast[{index}] must be numeric.")
            elif value < 0:
                errors.append(f"Load_forecast[{index}] must be nonnegative.")

    time_granularity = input_data.get("Time_granularity")
    if not _is_number(time_granularity) or time_granularity <= 0:
        errors.append("Time_granularity must be a positive number.")

    run_mode = input_data.get("run_mode", "DS")
    if run_mode == "RTD":
        errors.append("run_mode 'RTD' is explicitly out of scope for this project.")
    elif run_mode not in ("RDAS", "DS"):
        errors.append("run_mode must be 'RDAS' or 'DS' when provided.")

    units = input_data.get("Generating_Units", [])
    if not isinstance(units, list) or not units:
        errors.append("Generating_Units must be a nonempty list.")
        units = []

    gen_ids = []
    for unit_index, unit in enumerate(units):
        path = f"Generating_Units[{unit_index}]"
        if not isinstance(unit, dict):
            errors.append(f"{path} must be an object.")
            continue

        missing_unit_keys = sorted(REQUIRED_UNIT_KEYS - set(unit))
        if missing_unit_keys:
            errors.append(f"{path} missing keys: {', '.join(missing_unit_keys)}.")

        gen_id = unit.get("gen_id")
        if isinstance(gen_id, int):
            gen_ids.append(gen_id)
        else:
            errors.append(f"{path}.gen_id must be an integer.")

        if not isinstance(unit.get("comments", ""), str) or not unit.get("comments", ""):
            errors.append(f"{path}.comments must be a nonempty string.")

        if not _is_binary(unit.get("state")):
            errors.append(f"{path}.state must be 0 or 1.")

        current_power = unit.get("current_Power(MW)")
        if not _is_number(current_power) or current_power < 0:
            errors.append(f"{path}.current_Power(MW) must be a nonnegative number.")

        for field in ("availability", "Production_Forecast"):
            _check_numeric_list(errors, warnings, unit.get(field), dispatch_periods, f"{path}.{field}")

        for field in ("max_power(MW)", "min_power(MW)"):
            value = unit.get(field)
            if not _is_number(value) or value < 0:
                errors.append(f"{path}.{field} must be a nonnegative number.")

        if _is_number(unit.get("min_power(MW)")) and _is_number(unit.get("max_power(MW)")):
            if unit["min_power(MW)"] > unit["max_power(MW)"]:
                errors.append(f"{path}.min_power(MW) cannot exceed max_power(MW).")

        for reserve_field in RESERVE_FIELDS:
            reserve_values = unit.get(reserve_field)
            if not isinstance(reserve_values, list) or len(reserve_values) != 2:
                errors.append(f"{path}.{reserve_field} must contain [up, down] values.")
            else:
                for index, value in enumerate(reserve_values):
                    if not _is_number(value) or value < 0:
                        errors.append(f"{path}.{reserve_field}[{index}] must be a nonnegative number.")

        operating_states = unit.get("operating-states", [])
        if not isinstance(operating_states, list) or not operating_states:
            errors.append(f"{path}.operating-states must be a nonempty list.")
        else:
            seen_state_ids = set()
            operational_state_ids = []
            for state_index, operating_state in enumerate(operating_states):
                state_path = f"{path}.operating-states[{state_index}]"
                if not isinstance(operating_state, dict):
                    errors.append(f"{state_path} must be an object.")
                    continue
                state_id = operating_state.get("id")
                if not isinstance(state_id, int):
                    errors.append(f"{state_path}.id must be an integer.")
                elif state_id in seen_state_ids:
                    errors.append(f"{state_path}.id duplicates state id {state_id}.")
                else:
                    seen_state_ids.add(state_id)
                for binary_field in ("isShutdown", "isEnabled", "isOperational"):
                    if not isinstance(operating_state.get(binary_field), bool):
                        errors.append(f"{state_path}.{binary_field} must be a boolean.")
                if operating_state.get("isOperational") is True and isinstance(state_id, int):
                    operational_state_ids.append(state_id)
                if "isTransient" in operating_state and not isinstance(operating_state["isTransient"], bool):
                    errors.append(f"{state_path}.isTransient must be a boolean.")
                for numeric_field in ("max-power", "min-power"):
                    value = operating_state.get(numeric_field)
                    if not _is_number(value) or value < 0:
                        errors.append(f"{state_path}.{numeric_field} must be a nonnegative number.")
                if _is_number(operating_state.get("min-power")) and _is_number(operating_state.get("max-power")):
                    if operating_state["min-power"] > operating_state["max-power"]:
                        errors.append(f"{state_path}.min-power cannot exceed max-power.")
            if len(operational_state_ids) > 1:
                errors.append(
                    f"{path}.operating-states has multiple isOperational=true states "
                    f"({operational_state_ids}). Current reserve formulation assumes at most one "
                    "operational state per generating unit."
                )

        operating_state_transitions = unit.get("operating-state-transitions", [])
        if isinstance(operating_state_transitions, list):
            for transition_index, transition in enumerate(operating_state_transitions):
                if not isinstance(transition, dict):
                    continue
                transitions = transition.get("transitions", [])
                if not isinstance(transitions, list):
                    continue
                for target_index, target in enumerate(transitions):
                    if not isinstance(target, dict):
                        continue
                    target_path = (
                        f"{path}.operating-state-transitions[{transition_index}]"
                        f".transitions[{target_index}]"
                    )
                    for field in UNSUPPORTED_OPERATING_STATE_MAX_TRANSITION_FIELDS:
                        if field in target:
                            warnings.append(
                                f"{target_path}.{field} is ignored; A-style maximum "
                                "operating-state transition-time constraints are not "
                                "implemented. Use max-transition-time_b for B-style "
                                "destination-state maximum timing when needed."
                            )

    if len(gen_ids) != len(set(gen_ids)):
        errors.append("Generating unit gen_id values must be unique.")
    if gen_ids and sorted(gen_ids) != list(range(len(gen_ids))):
        warnings.append(
            "gen_id values are not contiguous from 0. Current model code assumes gen_id equals list position."
        )

    cost_curve_audit = audit_thermal_cost_curves(input_data)
    for issue in cost_curve_audit.get("issues", []):
        message = (
            f"Thermal cost curve audit {issue.get('code')} for "
            f"Generating_Units[{issue.get('unit_index')}]: {issue.get('message')}"
        )
        if issue.get("severity") == "error":
            errors.append(message)
        elif issue.get("severity") == "warning":
            warnings.append(message)

    penalty_audit = audit_penalty_hierarchy(input_data)
    for issue in penalty_audit.get("issues", []):
        message = f"Penalty hierarchy audit {issue.get('code')}: {issue.get('message')}"
        if issue.get("severity") == "error":
            errors.append(message)
        elif issue.get("severity") == "warning":
            warnings.append(message)

    constraints = input_data.get("constraints", {})
    optimization_parameters = input_data.get("optimization_parameters", {})
    if not isinstance(optimization_parameters, dict):
        errors.append("optimization_parameters must be an object.")
        optimization_parameters = {}

    solver_name = optimization_parameters.get("solver", "highs")
    if solver_name not in ("highs", "cbc"):
        errors.append("optimization_parameters.solver must be 'highs' or 'cbc'.")

    big_m = optimization_parameters.get("big_m", "auto")
    if big_m != "auto" and (not _is_number(big_m) or big_m <= 0):
        errors.append("optimization_parameters.big_m must be 'auto' or a positive number.")

    cost_curve_time_unit = optimization_parameters.get("cost_curve_time_unit", DEFAULT_COST_TIME_UNIT)
    if cost_curve_time_unit not in (
        "euro_per_mw_per_minute",
        "euro_per_mwh",
        "euro_per_dispatch_period",
    ):
        errors.append(
            "optimization_parameters.cost_curve_time_unit must be "
            "'euro_per_mw_per_minute', 'euro_per_mwh', or 'euro_per_dispatch_period'."
        )
    cost_curve_time_multiplier = optimization_parameters.get("cost_curve_time_multiplier")
    if cost_curve_time_multiplier is not None and (
        not _is_number(cost_curve_time_multiplier) or cost_curve_time_multiplier <= 0
    ):
        errors.append("optimization_parameters.cost_curve_time_multiplier must be a positive number.")

    # Read the optional block that controls sub-period operating-state embedding.
    time_resolution = optimization_parameters.get("time_resolution", {})
    # Allow the block to be omitted or explicitly null; validate it only when present.
    if time_resolution is not None:
        # The time-resolution options must be a dictionary because the pipeline expects named switches.
        if not isinstance(time_resolution, dict):
            errors.append("optimization_parameters.time_resolution must be an object.")
        else:
            # Decide whether sub-period operating states are embedded or merely rounded at period scale.
            policy = time_resolution.get("subperiod_operating_state_policy", "embed_transient")
            # Only the two implemented policies are accepted.
            if policy not in ("embed_transient", "period_rounding"):
                errors.append(
                    "optimization_parameters.time_resolution.subperiod_operating_state_policy "
                    "must be 'embed_transient' or 'period_rounding'."
                )
            # Read optional semantic labels that identify explicit transient operating states.
            roles = time_resolution.get("transient_state_roles")
            # Roles must be strings so the preprocessing logic can compare normalized names safely.
            if roles is not None and (
                not isinstance(roles, list)
                or any(not isinstance(role, str) or not role for role in roles)
            ):
                errors.append(
                    "optimization_parameters.time_resolution.transient_state_roles must be a list of strings."
                )
            # Validate the three safety switches that allow otherwise protected state classes to be embedded.
            for field in (
                "allow_initial_state_embedding",
                "allow_operational_state_embedding",
                "allow_shutdown_state_embedding",
            ):
                # Each switch must be boolean because non-boolean truthiness would make bypass decisions ambiguous.
                if field in time_resolution and not isinstance(time_resolution[field], bool):
                    errors.append(f"optimization_parameters.time_resolution.{field} must be boolean.")

    early_stopping = optimization_parameters.get("early_stopping", {})
    if early_stopping is not None:
        if not isinstance(early_stopping, dict):
            errors.append("optimization_parameters.early_stopping must be an object.")
        else:
            time_limit = early_stopping.get("time_limit")
            if time_limit is not None and (not _is_number(time_limit) or time_limit <= 0):
                errors.append("optimization_parameters.early_stopping.time_limit must be null or positive.")

    return {"status": "failed" if errors else "passed", "errors": errors, "warnings": warnings}


def assert_valid_input(input_data):
    """Raise an InputValidationError when validation finds blocking errors."""
    report = validate_input_data(input_data)
    if report["errors"]:
        raise InputValidationError(report["errors"], report["warnings"])
    return report


def format_input_validation_report(report):
    """Render the validation report as console-readable text."""
    lines = [f"Input validation status: {report['status']}"]
    for warning in report.get("warnings", []):
        lines.append(f"[WARNING] {warning}")
    for error in report.get("errors", []):
        lines.append(f"[ERROR] {error}")
    return "\n".join(lines)
