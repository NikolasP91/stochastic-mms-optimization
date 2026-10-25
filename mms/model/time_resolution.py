"""RDAS/DS time-resolution preprocessing for sub-period operating-state behavior."""

# This module runs before the normal time_granularity conversion. Its purpose is
# to decide whether a short operating state should remain as an explicit hourly
# model state or be embedded into direct transition arcs because its duration is
# shorter than the RDAS/DS dispatch period.

import copy  # Used to clone transition dictionaries before modifying embedded arcs.
import math  # Used to detect infinite numeric timing values safely.


# State-level minimum-time fields that may make a state relevant to time-resolution preprocessing.
STATE_MIN_TIME_FIELDS = (
    "min-time-enabled",
    "min-time-enabled-left",
)

# State-level maximum-time fields that may also be shorter than one dispatch period.
STATE_MAX_TIME_FIELDS = (
    "max-time-enabled",
    "max-time-enabled-left",
)

# Transition-level A-side timing fields apply to the source endpoint of an arc.
SOURCE_SIDE_OPERATING_TRANSITION_TIME_FIELDS = (
    "min-transition-time_a",
    "min-transition-time-left_a",
)

# Transition-level B-side timing fields apply to the destination endpoint of an arc.
DESTINATION_SIDE_OPERATING_TRANSITION_TIME_FIELDS = (
    "min-transition-time_b",
    "min-transition-time-left_b",
    "max-transition-time_b",
    "max-transition-time-left_b",
)

# Transition-level timing fields used by generic cleaning/reporting helpers.
OPERATING_TRANSITION_TIME_FIELDS = (
    SOURCE_SIDE_OPERATING_TRANSITION_TIME_FIELDS
    + DESTINATION_SIDE_OPERATING_TRANSITION_TIME_FIELDS
)

# Default semantic labels that count as explicit transient-state markers.
DEFAULT_TRANSIENT_ROLES = {
    "transient",
    "synchronization",
    "desynchronization",
    "startup",
    "shutdown",
}

# Shared large sentinel used elsewhere in the project to represent effectively infinite time.
LARGE_TIME_SENTINEL = 100000000000


def _is_number(value):
    """Return whether a value is a non-boolean numeric scalar."""
    # Booleans are subclasses of int in Python, so explicitly reject them.
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _finite_positive_minutes(value):
    """Return finite positive minute values and ignore open-ended sentinel values."""
    # Reject missing, non-numeric, non-positive, and sentinel-like durations.
    if not _is_number(value) or value <= 0 or value >= LARGE_TIME_SENTINEL:
        return None
    # Reject explicit positive infinity before the value is used in comparisons.
    if value == float("inf") or math.isinf(float(value)):
        return None
    # Normalize accepted durations to float minutes for report consistency.
    return float(value)


def _time_resolution_options(input_data):
    """Read optional policy switches controlling transient-state embedding."""
    # Read the optional optimization_parameters.time_resolution block.
    options = input_data.get("optimization_parameters", {}).get("time_resolution", {})
    # Treat malformed option blocks as empty here; validation reports the formal error earlier.
    if not isinstance(options, dict):
        options = {}
    # Return all switches with conservative defaults.
    return {
        # embed_transient enables bypassing; period_rounding keeps every state explicit.
        "policy": options.get("subperiod_operating_state_policy", "embed_transient"),
        # Caller may override the semantic labels treated as transient roles.
        "transient_roles": set(options.get("transient_state_roles", DEFAULT_TRANSIENT_ROLES)),
        # Initial enabled states are protected by default because they anchor the first-period condition.
        "allow_initial_state_embedding": bool(options.get("allow_initial_state_embedding", False)),
        # Operational states are protected by default because they may carry power/reserve capability.
        "allow_operational_state_embedding": bool(options.get("allow_operational_state_embedding", False)),
        # Shutdown states are protected by default because they belong to the offline state set.
        "allow_shutdown_state_embedding": bool(options.get("allow_shutdown_state_embedding", False)),
    }


def _state_role(operating_state):
    """Normalize the state_role marker used to identify transient states."""
    # Convert missing roles to an empty string and normalize spacing/case.
    return str(operating_state.get("state_role", "")).strip().lower()


def _is_explicit_transient_state(operating_state, options):
    """Return whether input data explicitly marks a state as transient."""
    # When the input JSON contains isTransient, treat that boolean as the user's
    # explicit choice. This lets isTransient: false override older role-based
    # defaults such as state_role: "desynchronization".
    if "isTransient" in operating_state:
        return operating_state.get("isTransient") is True
    # Otherwise fall back to the older markers: time-resolution class or semantic role.
    return (
        operating_state.get("time_resolution_class") == "transient"
        or _state_role(operating_state) in options["transient_roles"]
    )


def _timing_values_from_state(operating_state):
    """Collect finite timing values declared directly on an operating state."""
    # Accumulate pairs of field name and duration in minutes.
    values = []
    # Check every state-level min/max timing field.
    for field in STATE_MIN_TIME_FIELDS + STATE_MAX_TIME_FIELDS:
        # Read only finite positive values because zero/missing/infinite values do not imply a sub-period state.
        value = _finite_positive_minutes(operating_state.get(field))
        # Keep the field only when it has a meaningful duration.
        if value is not None:
            values.append((field, value))
    # Return all state-level timing values found on the operating state.
    return values


def _transition_groups_by_from(unit):
    """Index transition groups by their source operating-state id."""
    # Create a dictionary keyed by the "from" operating-state id.
    groups = {}
    # Visit each transition group declared for the unit.
    for transition_group in unit.get("operating-state-transitions", []):
        # Store the whole group so callers can inspect outgoing arcs quickly.
        groups[transition_group.get("from")] = transition_group
    # Return the source-state index.
    return groups


def _incoming_transition_values(unit, state_id):
    """Collect timing values on arcs entering a candidate transient state."""
    # Accumulate tuples of field, duration, source state, and target state.
    values = []
    # Scan every source-state transition group.
    for transition_group in unit.get("operating-state-transitions", []):
        # Remember the source state so timing metadata can explain where it came from.
        from_state = transition_group.get("from")
        # Scan every outgoing arc from that source.
        for transition in transition_group.get("transitions", []):
            # Ignore arcs that do not enter the candidate state.
            if transition.get("id") != state_id:
                continue
            # Only B-side fields on an incoming arc apply to the candidate destination state.
            for field in DESTINATION_SIDE_OPERATING_TRANSITION_TIME_FIELDS:
                # Keep only finite positive minute values.
                value = _finite_positive_minutes(transition.get(field))
                # Add the timing value with its arc endpoints when present.
                if value is not None:
                    values.append((field, value, from_state, state_id))
    # Return all timing data attached to incoming arcs.
    return values


def _outgoing_transition_values(unit, state_id):
    """Collect timing values on arcs leaving a candidate transient state."""
    # Accumulate tuples of field, duration, source state, and target state.
    values = []
    # Select the transition group whose source is the candidate state.
    transition_group = _transition_groups_by_from(unit).get(state_id, {})
    # Scan each outgoing arc from the candidate state.
    for transition in transition_group.get("transitions", []):
        # Remember the destination state for report metadata.
        to_state = transition.get("id")
        # Only A-side fields on an outgoing arc apply to the candidate source state.
        for field in SOURCE_SIDE_OPERATING_TRANSITION_TIME_FIELDS:
            # Keep only finite positive minute values.
            value = _finite_positive_minutes(transition.get(field))
            # Add the timing value with its arc endpoints when present.
            if value is not None:
                values.append((field, value, state_id, to_state))
    # Return all timing data attached to outgoing arcs.
    return values


def _timing_values_for_state(unit, operating_state):
    """Collect all state and transition durations attached to one state."""
    # Read the candidate operating-state id.
    state_id = operating_state.get("id")
    # Start with timing values declared directly on the state; use state_id as both endpoints for metadata.
    values = [(field, value, state_id, state_id) for field, value in _timing_values_from_state(operating_state)]
    # Add B-side timing values from arcs entering the candidate state.
    values.extend(_incoming_transition_values(unit, state_id))
    # Add A-side timing values from arcs leaving the candidate state.
    values.extend(_outgoing_transition_values(unit, state_id))
    # Return the combined timing evidence used by the bypass decision.
    return values


def _transition_cost(transition):
    """Read a transition cost as a number, defaulting missing costs to zero."""
    # Read the transition-cost field and default missing values to zero.
    value = transition.get("transition-cost", 0)
    # Return numeric costs as floats and ignore malformed costs as zero.
    return float(value) if _is_number(value) else 0.0


def _without_timing_fields(transition):
    """Copy a transition while removing period-level timing fields."""
    # Copy all non-timing data so the merged arc keeps metadata such as id and cost.
    cleaned = {
        key: copy.deepcopy(value)
        for key, value in transition.items()
        if key not in OPERATING_TRANSITION_TIME_FIELDS
    }
    # Remove timing fields defensively in case future field lists overlap or input has duplicate-like keys.
    for field in OPERATING_TRANSITION_TIME_FIELDS:
        cleaned.pop(field, None)
    # Return the transition dictionary that can safely represent a direct period-level arc.
    return cleaned


def _copy_existing_timing_fields(source_transition, field_names):
    """Copy selected timing fields from a transition when they still apply."""
    # Preserve exact input values because minute-to-period conversion happens later in preprocessing.
    return {
        field: copy.deepcopy(source_transition[field])
        for field in field_names
        if field in source_transition
    }


def _merge_embedded_transition(incoming, outgoing, transient_state, timing_values):
    """Create a direct arc that carries the skipped transient state's metadata."""
    # Preserve metadata from any transient states already embedded before this state.
    upstream_metadata = copy.deepcopy(incoming.get("embedded_transient_states", []))
    # Preserve metadata from any transient states already embedded after this state.
    downstream_metadata = copy.deepcopy(outgoing.get("embedded_transient_states", []))
    # Start from the outgoing arc because its target id is the destination after the transient state.
    merged = _without_timing_fields(outgoing)
    # Make the direct arc target equal to the original outgoing destination.
    merged["id"] = outgoing["id"]
    # Add the cost of entering and leaving the transient state.
    total_cost = _transition_cost(incoming) + _transition_cost(outgoing)
    # Preserve a nonzero combined transition cost when one exists.
    if total_cost:
        merged["transition-cost"] = total_cost
    # Preserve an explicit zero when the outgoing arc originally carried a transition-cost key.
    elif "transition-cost" in merged:
        merged["transition-cost"] = 0

    # Keep source-side timing from the incoming arc because it still constrains
    # the explicit predecessor state after the path is rewritten as source -> target.
    merged.update(_copy_existing_timing_fields(incoming, SOURCE_SIDE_OPERATING_TRANSITION_TIME_FIELDS))
    # Keep destination-side timing from the outgoing arc because it still constrains
    # the explicit successor state after the transient state is removed.
    merged.update(_copy_existing_timing_fields(outgoing, DESTINATION_SIDE_OPERATING_TRANSITION_TIME_FIELDS))

    # Build auditable metadata describing the operating state that is no longer explicit.
    metadata = {
        # Store the skipped state id.
        "id": transient_state["id"],
        # Preserve the semantic role used to mark the state as transient.
        "state_role": transient_state.get("state_role"),
        # Preserve whether the skipped state was operational for downstream review.
        "isOperational": transient_state.get("isOperational"),
        # Preserve whether the skipped state was shutdown for downstream review.
        "isShutdown": transient_state.get("isShutdown"),
        # Preserve every timing value that justified the embedding decision.
        "timing_minutes": [
            {
                # Store the original timing field name.
                "field": field,
                # Store the original duration in minutes.
                "value": value,
                # Store the source endpoint where the timing value was found.
                "from": from_state,
                # Store the target endpoint where the timing value was found.
                "to": to_state,
            }
            for field, value, from_state, to_state in timing_values
        ],
    }
    # Keep the full embedded chain in path order: upstream skipped states, the
    # current skipped state, then downstream skipped states.
    merged["embedded_transient_states"] = upstream_metadata + [metadata] + downstream_metadata
    # Return the direct arc replacing incoming -> transient -> outgoing.
    return merged


def _transition_exists(transitions, target_id):
    """Return whether a target arc is already present in a transition list."""
    # Prevent duplicate outgoing arcs from the same source to the same destination.
    return any(transition.get("id") == target_id for transition in transitions)


def _embed_state(unit, transient_state, timing_values):
    """Remove one sub-period transient state and replace paths through it with direct arcs."""
    # Read the id of the candidate state to bypass.
    transient_id = transient_state["id"]
    # Index transition groups by source so the candidate state's outgoing arcs can be found quickly.
    groups_by_from = _transition_groups_by_from(unit)
    # Select the outgoing transition group from the candidate state.
    outgoing_group = groups_by_from.get(transient_id)
    # If the candidate has no outgoing arcs, it cannot be safely embedded.
    if not outgoing_group:
        return False, [], "missing_outgoing_arc"
    # Exclude self-loops because a bypass must connect a predecessor to a different successor.
    outgoing_transitions = [
        transition
        for transition in outgoing_group.get("transitions", [])
        if transition.get("id") != transient_id
    ]
    # If no usable outgoing arcs remain, the state cannot be bypassed.
    if not outgoing_transitions:
        return False, [], "missing_outgoing_arc"

    original_transition_groups = copy.deepcopy(unit.get("operating-state-transitions", []))
    has_incoming_arc = False
    for transition_group in original_transition_groups:
        from_state = transition_group.get("from")
        if from_state == transient_id:
            continue
        transitions = transition_group.get("transitions", [])
        incoming_arcs = [
            transition
            for transition in transitions
            if transition.get("id") == transient_id
        ]
        if not incoming_arcs:
            continue
        has_incoming_arc = True
        existing_targets = {
            transition.get("id")
            for transition in transitions
            if transition.get("id") != transient_id
        }
        for outgoing in outgoing_transitions:
            target_id = outgoing.get("id")
            if target_id == from_state:
                return False, [], "immediate_cycle"
            if target_id in existing_targets:
                return False, [], "duplicate_direct_arc"

    if not has_incoming_arc:
        return False, [], "missing_incoming_arc"

    # Track newly created direct arcs for the audit report.
    added_arcs = []
    # Build the replacement transition-group list.
    new_transition_groups = []
    # Visit every transition group in the original unit data.
    for transition_group in original_transition_groups:
        # Read the source state for this group.
        from_state = transition_group.get("from")
        # Drop the transition group that starts at the transient state because that state is being removed.
        if from_state == transient_id:
            continue

        # Build the replacement outgoing transition list for the current source state.
        next_transitions = []
        # Visit each arc from the current source state.
        for transition in transition_group.get("transitions", []):
            # Keep arcs that do not point into the transient state.
            if transition.get("id") != transient_id:
                next_transitions.append(transition)
                continue

            # Replace each source -> transient arc with source -> outgoing-target arcs.
            for outgoing in outgoing_transitions:
                # Read the final destination after the transient state.
                target_id = outgoing.get("id")
                # Avoid immediate cycles and avoid duplicating an arc that already exists.
                if target_id == from_state or _transition_exists(next_transitions, target_id):
                    continue
                # Merge incoming and outgoing arc information into one direct transition.
                merged = _merge_embedded_transition(transition, outgoing, transient_state, timing_values)
                # Add the direct arc to the current source state's transition list.
                next_transitions.append(merged)
                # Record the added arc for the time-resolution report.
                added_arcs.append(
                    {
                        "from": from_state,
                        "to": target_id,
                        "embedded_state_id": transient_id,
                        "transition_cost": merged.get("transition-cost", 0),
                    }
                )

        # Copy the original transition group before replacing its transitions.
        transition_group = copy.deepcopy(transition_group)
        # Install the modified transition list for this source state.
        transition_group["transitions"] = next_transitions
        # Keep the modified group in the unit transition topology.
        new_transition_groups.append(transition_group)

    if not added_arcs:
        return False, [], "no_replacement_arc"

    # Replace the unit transition topology with the embedded-state topology.
    unit["operating-state-transitions"] = new_transition_groups
    # Remove the transient state from the explicit operating-state list.
    unit["operating-states"] = [
        operating_state
        for operating_state in unit.get("operating-states", [])
        if operating_state.get("id") != transient_id
    ]
    # Report success together with the direct arcs created by the embedding operation.
    return True, added_arcs, None


def _add_issue(report, severity, code, message, **fields):
    """Append a structured time-resolution issue record to a report."""
    # Start with the common issue fields used by every report entry.
    issue = {
        "severity": severity,
        "code": code,
        "message": message,
    }
    # Add optional context fields while skipping None values to keep the report compact.
    issue.update({key: value for key, value in fields.items() if value is not None})
    # Append the completed issue to the report.
    report["issues"].append(issue)


def _record_subperiod_timing_issues(report, unit, time_granularity):
    """Report timing data shorter than the active RDAS/DS dispatch period."""
    # First scan timing fields declared directly on operating states.
    for operating_state in unit.get("operating-states", []):
        # Read the state id for report context.
        state_id = operating_state.get("id")
        # Check each finite positive state-level timing value.
        for field, value in _timing_values_from_state(operating_state):
            # Skip values that are representable at the current dispatch-period resolution.
            if value >= time_granularity:
                continue
            # Treat sub-period maximum-time data as a warning because rounding down may create zero-period limits.
            severity = "warning" if field in STATE_MAX_TIME_FIELDS else "info"
            # Use separate codes for min and max timing so reports can be filtered by risk.
            code = "subperiod_state_max_time" if field in STATE_MAX_TIME_FIELDS else "subperiod_state_min_time"
            # Add the structured issue to the report.
            _add_issue(
                report,
                severity,
                code,
                f"{field}={value:g} min is shorter than the DS/RDAS dispatch period.",
                unit_index=unit.get("gen_id"),
                operating_state_id=state_id,
                field=field,
                value_minutes=value,
            )

    # Then scan timing fields declared on operating-state transition arcs.
    for transition_group in unit.get("operating-state-transitions", []):
        # Read the source state for report context.
        from_state = transition_group.get("from")
        # Visit each outgoing arc from the source state.
        for transition in transition_group.get("transitions", []):
            # Read the destination state for report context.
            to_state = transition.get("id")
            # Check each transition-level timing field.
            for field in OPERATING_TRANSITION_TIME_FIELDS:
                # Keep only finite positive values.
                value = _finite_positive_minutes(transition.get(field))
                # Skip missing, infinite, zero, negative, or period-representable values.
                if value is None or value >= time_granularity:
                    continue
                # A-side timing belongs to the source state; B-side timing belongs to the destination state.
                timing_side = (
                    "source"
                    if field in SOURCE_SIDE_OPERATING_TRANSITION_TIME_FIELDS
                    else "destination"
                )
                # Report the operating state whose timing obligation the field actually describes.
                relevant_state = from_state if timing_side == "source" else to_state
                # Treat sub-period maximum-time data as a warning for the same reason as state-level maxima.
                severity = "warning" if field.startswith("max-") else "info"
                # Use separate issue codes for sub-period min and max transition timers.
                code = "subperiod_transition_max_time" if field.startswith("max-") else "subperiod_transition_min_time"
                # Add the structured issue to the report.
                _add_issue(
                    report,
                    severity,
                    code,
                    f"{field}={value:g} min is shorter than the DS/RDAS dispatch period.",
                    unit_index=unit.get("gen_id"),
                    from_operating_state_id=from_state,
                    to_operating_state_id=to_state,
                    operating_state_id=relevant_state,
                    timing_side=timing_side,
                    field=field,
                    value_minutes=value,
                )


def prepare_operating_state_time_resolution(input_data):
    """Classify and embed eligible sub-period transient states before time discretization."""
    # Read the dispatch-period length in minutes before timing values are rounded to periods.
    time_granularity = input_data.get("Time_granularity")
    # Initialize the audit report with a passed status that later issues may downgrade.
    report = {
        "report_type": "time_resolution",
        "scope": "RDAS_DS",
        "status": "passed",
        "dispatch_period_minutes": time_granularity,
        "policy": "embed_transient",
        "embedded_state_count": 0,
        "embedded_states": [],
        "issues": [],
    }

    # Validate that preprocessing has a usable dispatch-period length.
    if not _is_number(time_granularity) or time_granularity <= 0:
        # Mark the report failed because no bypass or rounding decision is meaningful without this value.
        report["status"] = "failed"
        # Add a blocking error that explains the missing or invalid model clock.
        _add_issue(
            report,
            "error",
            "invalid_time_granularity",
            "Time_granularity must be a positive number before time-resolution preprocessing.",
        )
        # Attach issue counters before returning.
        _add_issue_counts(report)
        # Store the report in the input payload so callers can expose it in artifacts.
        input_data["Time_Resolution_Report"] = report
        # Return unchanged input data because no safe preprocessing can be performed.
        return input_data

    # Read policy switches and transient-role configuration.
    options = _time_resolution_options(input_data)
    # Store the active policy in the report for traceability.
    report["policy"] = options["policy"]
    # If policy is period_rounding, do not bypass any operating state.
    if options["policy"] != "embed_transient":
        # Still report sub-period timing fields so the user knows what will be rounded.
        for unit in input_data.get("Generating_Units", []):
            _record_subperiod_timing_issues(report, unit, time_granularity)
        # Derive the final status from collected warning/error severities.
        report["status"] = _status_from_issues(report)
        # Attach issue counters for diagnostics.
        _add_issue_counts(report)
        # Store the report in the input payload.
        input_data["Time_Resolution_Report"] = report
        # Return with all operating states still explicit.
        return input_data

    # With embed_transient policy active, inspect each generating unit independently.
    for unit in input_data.get("Generating_Units", []):
        # Snapshot operating states by id so iteration is stable even if a state is removed.
        state_by_id = {
            operating_state.get("id"): operating_state
            for operating_state in unit.get("operating-states", [])
        }
        # Evaluate each operating state as a possible bypass candidate.
        for operating_state in list(state_by_id.values()):
            # Ignore malformed state entries and entries without an id.
            if not isinstance(operating_state, dict) or "id" not in operating_state:
                continue
            # Do not bypass a state unless the input explicitly marks it as transient.
            if not _is_explicit_transient_state(operating_state, options):
                continue

            # Collect all positive timing values attached to the state or its incident arcs.
            timing_values = _timing_values_for_state(unit, operating_state)
            # Extract only the numeric durations for the sub-period test.
            positive_durations = [value for _, value, _, _ in timing_values]
            # If no duration exists, the state may be semantically transient but has no timing reason to bypass.
            if not positive_durations:
                _add_issue(
                    report,
                    "info",
                    "transient_state_without_duration",
                    "Explicit transient state has no positive timing data, so it remains period-level.",
                    unit_index=unit.get("gen_id"),
                    operating_state_id=operating_state["id"],
                )
                continue
            # If any positive duration reaches the dispatch period, the state is representable at period resolution.
            if max(positive_durations) >= time_granularity:
                _add_issue(
                    report,
                    "info",
                    "transient_state_not_subperiod",
                    "Explicit transient state has timing at least as long as the dispatch period, so it remains period-level.",
                    unit_index=unit.get("gen_id"),
                    operating_state_id=operating_state["id"],
                    max_duration_minutes=max(positive_durations),
                )
                continue
            # Protect initial enabled states unless the user explicitly accepts this embedding risk.
            if operating_state.get("isEnabled") and not options["allow_initial_state_embedding"]:
                _add_issue(
                    report,
                    "warning",
                    "initial_transient_state_not_embedded",
                    "Initial enabled operating state cannot be embedded safely in an hourly DS/RDAS model.",
                    unit_index=unit.get("gen_id"),
                    operating_state_id=operating_state["id"],
                )
                continue
            # Protect operational states unless the user explicitly allows embedding them.
            if operating_state.get("isOperational") and not options["allow_operational_state_embedding"]:
                _add_issue(
                    report,
                    "warning",
                    "operational_transient_state_not_embedded",
                    "Operational transient state was not embedded because it may carry reserve/dispatch capability.",
                    unit_index=unit.get("gen_id"),
                    operating_state_id=operating_state["id"],
                )
                continue
            # Protect shutdown states unless the user explicitly allows embedding them.
            if operating_state.get("isShutdown") and not options["allow_shutdown_state_embedding"]:
                _add_issue(
                    report,
                    "warning",
                    "shutdown_transient_state_not_embedded",
                    "Shutdown transient state was not embedded because it is part of the offline state set.",
                    unit_index=unit.get("gen_id"),
                    operating_state_id=operating_state["id"],
                )
                continue

            # Attempt the graph rewrite that replaces source -> transient -> target with source -> target.
            embedded, added_arcs, blocked_reason = _embed_state(unit, operating_state, timing_values)
            # If the graph lacks usable incoming/outgoing arcs, keep the state explicit and report the reason.
            if not embedded:
                if blocked_reason == "duplicate_direct_arc":
                    code = "transient_state_duplicate_direct_arc"
                    message = (
                        "Transient state was kept explicit because embedding would collide "
                        "with an already declared direct transition arc."
                    )
                else:
                    code = "transient_state_not_embeddable"
                    message = (
                        "Transient state could not be embedded because it lacks usable "
                        "incoming/outgoing transition paths."
                    )
                _add_issue(
                    report,
                    "warning",
                    code,
                    message,
                    unit_index=unit.get("gen_id"),
                    operating_state_id=operating_state["id"],
                    blocked_reason=blocked_reason,
                )
                continue

            # Record successful embedding details for traceability.
            report["embedded_states"].append(
                {
                    "unit_index": unit.get("gen_id"),
                    "operating_state_id": operating_state["id"],
                    "state_role": operating_state.get("state_role"),
                    "max_duration_minutes": max(positive_durations),
                    "added_transition_arcs": added_arcs,
                }
            )
            # Add an informational report issue confirming the bypass action.
            _add_issue(
                report,
                "info",
                "transient_state_embedded",
                "Sub-period transient operating state was embedded into allowed transition arcs.",
                unit_index=unit.get("gen_id"),
                operating_state_id=operating_state["id"],
            )

        # After embedding attempts, report any remaining sub-period timers on explicit states/arcs.
        _record_subperiod_timing_issues(report, unit, time_granularity)

    # Count successful embeddings after all units have been processed.
    report["embedded_state_count"] = len(report["embedded_states"])
    # Derive the final report status from warnings and errors.
    report["status"] = _status_from_issues(report)
    # Attach issue counters for output artifacts and diagnostics.
    _add_issue_counts(report)
    # Store the report in the payload consumed by later pipeline stages.
    input_data["Time_Resolution_Report"] = report
    # Return the modified input data, possibly with embedded transient states removed.
    return input_data


def _status_from_issues(report):
    """Derive report status from warning/error severities."""
    # Collect all severities that appear in the issue list.
    severities = {issue.get("severity") for issue in report.get("issues", [])}
    # Any error makes the report failed.
    if "error" in severities:
        return "failed"
    # Warnings without errors make the report warning.
    if "warning" in severities:
        return "warning"
    # If only info/no issues exist, the report passed.
    return "passed"


def _add_issue_counts(report):
    """Attach issue severity counters to the time-resolution report."""
    # Read the issue list once for the counter calculations.
    issues = report.get("issues", [])
    # Count all issues.
    report["issue_count"] = len(issues)
    # Count warnings.
    report["warning_count"] = sum(1 for issue in issues if issue.get("severity") == "warning")
    # Count errors.
    report["error_count"] = sum(1 for issue in issues if issue.get("severity") == "error")
    # Count informational messages.
    report["info_count"] = sum(1 for issue in issues if issue.get("severity") == "info")
