"""Hourly rolling handover using observed paths, never expected dispatch."""

from copy import deepcopy
import math
import re

from mms.model.time_resolution import prepare_operating_state_time_resolution

from .data import number, validate


_REMAINING_FIELDS = {
    "min-transition-time-left", "min-transition-time-left_a",
    "min-transition-time-left_b", "max-transition-time-left_b",
    "min-time-enabled-left", "max-time-enabled-left", "isEnabled",
}
_UNLIMITED_MINUTES = 100000000000
# Μεταβλητές ορίου που καθορίζονται από την παρατηρημένη κατάσταση t=0· δεν δεσμεύονται.
_BOUNDARY_PREFIXES = ("startup_", "shutdown_", "transition_arc_")
SOC_METERING_TOLERANCE_MWH = 1e-6


def _definition(value):
    """Compare declared operating rules without comparing observed remainders."""
    if isinstance(value, dict):
        return {key: _definition(item) for key, item in value.items()
                if key not in _REMAINING_FIELDS}
    if isinstance(value, list):
        return [_definition(item) for item in value]
    return value


def _finite_maximum(value):
    return (isinstance(value, (int, float)) and not isinstance(value, bool)
            and math.isfinite(value) and 0 <= value < _UNLIMITED_MINUTES)


def _check_definitions(previous, refreshed):
    for old, new in zip(previous["Generating_Units"], refreshed["Generating_Units"]):
        for field in ("comments", "operating-states", "state-transitions",
                      "operating-state-transitions"):
            if _definition(old[field]) != _definition(new[field]):
                raise ValueError(f"Unit {old['gen_id']}: changing {field} requires an explicit migration")
    before = previous.get("optimization_parameters", {}).get("time_resolution", {})
    after = refreshed.get("optimization_parameters", {}).get("time_resolution", {})
    if before != after:
        raise ValueError("Changing time-resolution policy requires an explicit migration")
    before = {gid: spec["hours"] for gid, spec in previous["stochastic"].get("maximum_on", {}).items()}
    after = {gid: spec["hours"] for gid, spec in refreshed["stochastic"].get("maximum_on", {}).items()}
    if before != after:
        raise ValueError("Changing or removing maximum_on rules requires an explicit migration")


def _decision_time(name):
    patterns = (r"((?:state|startup|shutdown|reference)_\d+_)(\d+)(.*)",
                r"(u_2_\d+_)(\d+)(.*)", r"(transition_arc_\d+_)(\d+)(.*)",
                r"((?:primary|secondary|tertiary)_ActPR_(?:plus|minus)\d+_)(\d+)(.*)",
                r"(storage_reserve_(?:primary|secondary|tertiary)_(?:up|down)_\d+_)(\d+)(.*)")
    for pattern in patterns:
        match = re.fullmatch(pattern, name)
        if match:
            return match.group(1), int(match.group(2)), match.group(3)
    raise ValueError(f"Unrecognized shared decision name: {name}")


def _unit_number(prefix):
    """1-based unit number encoded in a shared-decision prefix, or None (storage)."""
    if prefix.startswith("storage_reserve_"):
        return None
    match = re.search(r"(?:plus|minus)?(\d+)_$", prefix.split("_ActPR_")[-1]) if "_ActPR_" in prefix else \
        re.match(r"(?:state|startup|shutdown|reference|u_2|transition_arc)_(\d+)_", prefix)
    return int(match.group(1)) if match else None


def advance(previous, solution, observations, refreshed, executed_steps=1, committed_steps=0,
            released_units=()):
    """Return (next_input, fixed_decisions) after executing an observed prefix.

    observations['units'][str(gen_id)] is a list (one item per elapsed hour)
    of {'power_mw': ..., 'operating_state_id': ...}. Storage observations are
    final measured MWh in observations['storage_mwh']. `refreshed` is a full
    new-horizon input with updated forecasts, scenarios and known availability.
    committed_steps is the count of still-binding hours in the *new* horizon.
    Observations may differ from the issued schedule, but must use the same
    operating definitions, valid model transitions, and physical state bounds.
    Historical dwell violations are not retroactively optimized: exhausted
    maximum obligations remain zero until the observed unit exits that state.
    An observed maximum_on overrun is carried as-is when the rule has a
    violation_penalty_eur_per_h (penalized recovery); otherwise it is clamped
    to the limit, which requires an immediate shutdown.

    Committed decisions exclude startup/shutdown/transition arcs, which follow
    from the observed t=0 state. released_units lists gen_ids whose committed
    decisions are released (forced outage, failed start): their commitment and
    reserve awards are re-optimized instead of conflicting with observations.
    Measured SOC within SOC_METERING_TOLERANCE_MWH of [0, capacity] is clamped.
    """
    validate(previous)
    validate(refreshed)
    n = len(previous["Load_forecast"]) - 1
    if isinstance(executed_steps, bool) or not isinstance(executed_steps, int) or not 1 <= executed_steps <= n:
        raise ValueError("executed_steps must select a nonempty prefix of the previous horizon")
    if isinstance(committed_steps, bool) or not isinstance(committed_steps, int) or not 0 <= committed_steps <= n - executed_steps:
        raise ValueError("committed_steps must fit in the unexecuted previous horizon")
    result = deepcopy(refreshed)
    if len(result["Load_forecast"]) - 1 < committed_steps:
        raise ValueError("Refreshed horizon is shorter than the committed prefix")
    units = result["Generating_Units"]
    if [g["gen_id"] for g in units] != [g["gen_id"] for g in previous["Generating_Units"]]:
        raise ValueError("Rolling handover requires the same unit IDs and order")
    _check_definitions(previous, result)
    if not isinstance(observations, dict) or not isinstance(observations.get("units"), dict):
        raise ValueError("Observations must contain a units object")
    if set(observations["units"]) != {str(g["gen_id"]) for g in units}:
        raise ValueError("Supply actual/estimated observations for every unit")
    if not isinstance(solution, dict) or not isinstance(solution.get("common_schedule"), dict):
        raise ValueError("Solution must contain a common_schedule object")
    if committed_steps and not solution["common_schedule"]:
        raise ValueError("A committed prefix requires the previous common schedule")
    effective = prepare_operating_state_time_resolution(deepcopy(previous))
    obligations = {}
    for old, new, prepared in zip(previous["Generating_Units"], units, effective["Generating_Units"]):
        gid = str(old["gen_id"])
        path = observations["units"][gid]
        if not isinstance(path, list) or len(path) != executed_steps:
            raise ValueError("Observed path length must equal executed_steps")
        states = {k["id"]: k for k in old["operating-states"]}
        effective_states = {k["id"] for k in prepared["operating-states"]}
        effective_arcs = {(row["from"], spec["id"]): spec
                          for row in prepared["operating-state-transitions"]
                          for spec in row["transitions"]}
        current = next(k["id"] for k in states.values() if k["isEnabled"])
        online = int(not states[current]["isShutdown"])
        transitions = deepcopy(old["state-transitions"])
        arcs = deepcopy(old["operating-state-transitions"])
        state_timers = deepcopy(states)
        inherited = deepcopy(previous["stochastic"].get("initial_operating_obligations", {}).get(gid))
        elapsed = previous["stochastic"].get("maximum_on", {}).get(gid, {}).get("elapsed_hours", 0)
        for observation in path:
            if not isinstance(observation, dict) or set(observation) != {"operating_state_id", "power_mw"}:
                raise ValueError("Each unit observation must contain operating_state_id and power_mw")
            dest = observation["operating_state_id"]
            if isinstance(dest, bool) or not isinstance(dest, int) or dest not in effective_states:
                raise ValueError(f"Unknown observed operating state {dest}")
            if dest != current and (current, dest) not in effective_arcs:
                raise ValueError(f"Unit {gid}: observed transition {current} -> {dest} is not allowed")
            power = number(observation["power_mw"], f"Observed unit {gid} power_mw")
            if not states[dest]["min-power"] <= power <= states[dest]["max-power"]:
                raise ValueError("Observed power outside operating-state bounds")
            entry = effective_arcs.get((current, dest), {}) if current != dest else {}
            chain = entry.get("embedded_transient_states", [])
            last_source = chain[-1]["id"] if chain else current
            if current != dest:
                matching = [spec for row in arcs if row["from"] == last_source
                            for spec in row["transitions"] if spec["id"] == dest]
                if len(matching) != 1:
                    raise ValueError(f"Unit {gid}: observed transition has ambiguous timer provenance")
            if inherited is not None:
                if inherited["state_id"] != dest:
                    inherited = None
                else:
                    inherited["maximum_remaining_hours"] = max(0, int(inherited["maximum_remaining_hours"]) - 1)
            now_online = int(not states[dest]["isShutdown"])
            elapsed = elapsed + 1 if online and now_online else int(now_online)
            for arc in transitions:
                spec = arc["transitions"]
                target = spec["value"]
                remaining = spec.get("min-transition-time-left", 0)
                if now_online != online and now_online == target:
                    remaining = spec.get("min-transition-time", 0)
                spec["min-transition-time-left"] = max(0, remaining - 60) if now_online == target else 0
            for arc in arcs:
                source = arc["from"]
                for spec in arc["transitions"]:
                    target = spec["id"]
                    a = spec.get("min-transition-time-left_a", 0)
                    if dest == source and current != dest:
                        a = spec.get("min-transition-time_a", 0)
                    spec["min-transition-time-left_a"] = max(0, a - 60) if dest == source else 0
                    b = spec.get("min-transition-time-left_b", 0)
                    maximum = spec.get("max-transition-time-left_b")
                    if last_source == source and dest == target and current != dest:
                        b = spec.get("min-transition-time_b", 0)
                        maximum = spec.get("max-transition-time_b")
                    spec["min-transition-time-left_b"] = max(0, b - 60) if dest == target else 0
                    if _finite_maximum(maximum):
                        if dest == target:
                            spec["max-transition-time-left_b"] = max(0, maximum - 60)
                        else:
                            spec.pop("max-transition-time-left_b", None)
                    elif dest != target or current != dest:
                        spec.pop("max-transition-time-left_b", None)
            for state_id, state in state_timers.items():
                if state_id != dest:
                    state["min-time-enabled-left"] = 0
                    state.pop("max-time-enabled-left", None)
                    continue
                minimum = state.get("min-time-enabled-left", 0)
                maximum = state.get("max-time-enabled-left")
                if current != dest:
                    minimum = state.get("min-time-enabled", 0)
                    maximum = state.get("max-time-enabled")
                state["min-time-enabled-left"] = max(0, minimum - 60)
                if _finite_maximum(maximum):
                    state["max-time-enabled-left"] = max(0, maximum - 60)
                else:
                    state.pop("max-time-enabled-left", None)
            current, online = dest, now_online
        # Υπολειπόμενοι χρόνοι διατηρούνται σε λεπτά μέχρι το κανονικό preprocessing.
        new["state-transitions"] = transitions
        new["operating-state-transitions"] = arcs
        new["state"] = online
        new["current_Power(MW)"] = path[-1]["power_mw"]
        for state in new["operating-states"]:
            state["isEnabled"] = state["id"] == current
            for field in ("min-time-enabled-left", "max-time-enabled-left"):
                if field in state_timers[state["id"]]:
                    state[field] = state_timers[state["id"]][field]
                else:
                    state.pop(field, None)
        if gid in previous["stochastic"].get("maximum_on", {}):
            rule = previous["stochastic"]["maximum_on"][gid]
            if "violation_penalty_eur_per_h" not in rule:
                elapsed = min(elapsed, rule["hours"])
            result["stochastic"].setdefault("maximum_on", {})[gid] = {**rule, "elapsed_hours": elapsed}
        # Το legacy helper αγνοεί μέγιστο υπόλοιπο μηδέν. Το διατηρούμε αυστηρά.
        limits = [a["max-transition-time-left_b"] for row in arcs for a in row["transitions"]
                  if a["id"] == current and _finite_maximum(a.get("max-transition-time-left_b"))]
        state_maximum = state_timers[current].get("max-time-enabled-left")
        if _finite_maximum(state_maximum):
            limits.append(state_maximum)
        if inherited is not None:
            limits.append(inherited["maximum_remaining_hours"] * 60)
        if limits:
            obligations[gid] = {"state_id": current, "maximum_remaining_hours": int(min(limits) // 60)}
    result["stochastic"]["initial_operating_obligations"] = obligations
    previous_storage = {b["id"] for b in previous["stochastic"].get("storage", [])}
    next_storage = {b["id"] for b in result["stochastic"].get("storage", [])}
    if previous_storage != next_storage or set(observations.get("storage_mwh", {})) != next_storage:
        raise ValueError("Storage IDs and observed final SOC must match across rolling horizons")
    for store in result["stochastic"].get("storage", []):
        measured = number(observations["storage_mwh"][store["id"]], f"Observed SOC {store['id']}", minimum=None)
        if -SOC_METERING_TOLERANCE_MWH <= measured < 0:
            measured = 0.0
        elif store["capacity_mwh"] < measured <= store["capacity_mwh"] + SOC_METERING_TOLERANCE_MWH:
            measured = store["capacity_mwh"]
        store["initial_mwh"] = measured
    validate(result)
    released = set()
    for gid in released_units:
        if str(gid) not in observations["units"]:
            raise ValueError(f"released_units: unknown unit {gid!r}")
        released.add(int(gid) + 1)
    fixed = {}
    for name, value in solution["common_schedule"].items():
        if not isinstance(name, str):
            raise ValueError("Common schedule decision names must be strings")
        prefix, t, suffix = _decision_time(name)
        next_t = t - executed_steps
        if prefix.startswith(_BOUNDARY_PREFIXES) or _unit_number(prefix) in released:
            continue
        if 1 <= next_t <= committed_steps:
            number(value, f"Committed decision {name}", minimum=None)
            fixed[f"{prefix}{next_t}{suffix}"] = value
    if committed_steps:
        # Build one positive-probability path only to recover the canonical
        # first-stage names. A partial schedule must not release commitments.
        from .model import build_model

        check = deepcopy(previous)
        path = next(s for s in check["stochastic"]["scenarios"] if s["probability"] > 0)
        check["stochastic"]["scenarios"] = [dict(path, probability=1.0)]
        expected = set()
        for name in build_model(check).shared:
            prefix, t, suffix = _decision_time(name)
            next_t = t - executed_steps
            if prefix.startswith(_BOUNDARY_PREFIXES) or _unit_number(prefix) in released:
                continue
            if 1 <= next_t <= committed_steps:
                expected.add(f"{prefix}{next_t}{suffix}")
        if set(fixed) != expected:
            missing = sorted(expected - set(fixed))
            extra = sorted(set(fixed) - expected)
            raise ValueError(f"Committed prefix must be complete; missing={missing[:5]}, extra={extra[:5]}")
        check = deepcopy(result)
        path = next(s for s in check["stochastic"]["scenarios"] if s["probability"] > 0)
        check["stochastic"]["scenarios"] = [dict(path, probability=1.0)]
        if not set(fixed).issubset(build_model(check).shared):
            raise ValueError("Time-resolution preprocessing changed binding decision names; explicit migration is required")
    return result, fixed
