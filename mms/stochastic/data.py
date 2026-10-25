"""Validate stochastic inputs before model construction, without repairing data.

New power and energy units are MW/MWh. Errors identify the invalid input path.
"""

from copy import deepcopy
import json
import math
from pathlib import Path

from input_validation import assert_valid_input
from mms.model.time_resolution import (
    LARGE_TIME_SENTINEL, STATE_MAX_TIME_FIELDS, STATE_MIN_TIME_FIELDS,
    prepare_operating_state_time_resolution,
)


PRODUCTS = ("primary", "secondary", "tertiary")
CONFIG_FIELDS = {"description", "scenarios", "risk", "reserve_link", "reserve_products",
                 "slack_policy", "storage", "maximum_on", "initial_operating_obligations",
                 "scenario_tree", "reserve_link_mode", "cost_policy"}
PRODUCT_FIELDS = {"response_minutes", "activation_eur_per_mwh_up", "activation_eur_per_mwh_down"}
PRODUCT_OPTIONAL = {"balancing_deployment"}
RESERVE_LINK_MODES = ("post_balancing_headroom", "deploy_from_procured")
COST_POLICY_FIELDS = {"thermal_online_charge_eur_per_h", "legacy_time_scaled_costs",
                      "renewable_curtailment_eur_per_mwh"}
STORAGE_REQUIRED = {"id", "capacity_mwh", "min_mwh", "initial_mwh", "terminal_min_mwh",
                    "charge_mw", "discharge_mw", "charge_efficiency", "discharge_efficiency",
                    "throughput_eur_per_mwh", "grid_charge"}
# Προαιρετικά πεδία BESS· η απουσία τους αναπαράγει ακριβώς το αρχικό μοντέλο.
STORAGE_OPTIONAL = {"renewable_gen_id", "self_discharge_per_hour", "terminal_value_eur_per_mwh",
                    "max_cycles_per_horizon", "export_limit_mw", "reserve",
                    "terminal_shortfall_penalty_eur_per_mwh", "soc_recovery_penalty_eur_per_mwh",
                    "power_availability"}
STORAGE_FIELDS = STORAGE_REQUIRED | STORAGE_OPTIONAL
STORAGE_RESERVE_FIELDS = {"products", "sustain_minutes", "capacity_cost_eur_per_mw_h"}
TREE_FIELDS = {"stage_start_hours"}
DIRECTIONS = ("up", "down")
TREE_DATA_TOLERANCE = 1e-9


def number(value, path, minimum=0):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{path}: expected a finite number")
    if minimum is not None and value < minimum:
        raise ValueError(f"{path}: must be >= {minimum}")
    return value


def _integer(value, path, minimum=0):
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ValueError(f"{path}: expected an integer >= {minimum}")
    return value


def _object(value, path, *, allowed=None, required=()):
    if not isinstance(value, dict):
        raise ValueError(f"{path}: expected an object")
    if any(not isinstance(key, str) for key in value):
        raise ValueError(f"{path}: object keys must be strings")
    missing = set(required) - value.keys()
    if missing:
        raise ValueError(f"{path}: missing required field(s): {', '.join(sorted(missing))}")
    if allowed is not None:
        unknown = value.keys() - allowed
        if unknown:
            raise ValueError(f"{path}: unknown field(s): {', '.join(sorted(unknown))}")
    return value


def _array(value, path, *, nonempty=False):
    if not isinstance(value, list) or (nonempty and not value):
        raise ValueError(f"{path}: expected {'a nonempty' if nonempty else 'an'} array")
    return value


def _boolean(value, path):
    if not isinstance(value, bool):
        raise ValueError(f"{path}: expected a boolean")


def _identifier(value, path):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{path}: expected a nonempty string")
    return value


def _finite_tree(value, path="input"):
    """Reject nonfinite numbers even in fields inherited from the legacy API."""
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError(f"{path}: expected a finite number")
    if isinstance(value, dict):
        for key, item in value.items():
            _finite_tree(item, f"{path}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _finite_tree(item, f"{path}[{index}]")


def series(values, n, path, upper=None):
    if not isinstance(values, list) or len(values) != n:
        raise ValueError(f"{path}: expected {n} decision periods (no initial period)")
    for t, value in enumerate(values):
        number(value, f"{path}[{t}]")
        if upper is not None and value > upper[t] + 1e-8:
            raise ValueError(f"{path}[{t}]: exceeds physical availability")


def renewable_ids(base):
    # Match legacy classification, without inferring technology from filenames.
    return [str(g["gen_id"]) for g in base["Generating_Units"]
            if not g["comments"].startswith("Therm")
            and "Partially Controllable" not in g["comments"]]


def load(path):
    """Read a self-contained legacy JSON with an added stochastic section."""
    with Path(path).open(encoding="utf-8-sig") as stream:
        data = json.load(stream)
    validate(data)
    return data


def _validate_structure(base):
    """Guard container types before invoking the legacy audit helpers."""
    _object(base, "input", required={"Cost_parameters", "Other_coefficients", "constraints",
                                     "optimization_parameters", "Generating_Units",
                                     "Time_granularity", "Load_forecast", "stochastic"})
    _finite_tree(base)
    for field in ("Cost_parameters", "Other_coefficients", "constraints", "optimization_parameters"):
        _object(base[field], field)
    for key, flag in base["constraints"].items():
        if key != "APRR_calculations":
            _boolean(flag, f"constraints.{key}")
    for index, unit in enumerate(_array(base["Generating_Units"], "Generating_Units", nonempty=True)):
        path = f"Generating_Units[{index}]"
        _object(unit, path)
        _identifier(unit.get("comments"), f"{path}.comments")
        for field in ("operating-states", "operating-state-transitions", "state-transitions"):
            for j, row in enumerate(_array(unit.get(field), f"{path}.{field}")):
                _object(row, f"{path}.{field}[{j}]")


def _validate_state_graph(unit, path):
    states = unit["operating-states"]
    state_ids = set()
    for index, state in enumerate(states):
        state_path = f"{path}.operating-states[{index}]"
        state_id = _integer(state["id"], f"{state_path}.id")
        if state_id in state_ids:
            raise ValueError(f"{state_path}.id: duplicate operating state {state_id}")
        state_ids.add(state_id)
        if state["isShutdown"] and state["isOperational"]:
            raise ValueError(f"{state_path}: shutdown state cannot also be operational")
        if state["isShutdown"] and state["max-power"] != 0:
            raise ValueError(f"{state_path}.max-power: shutdown state must have zero power")
        if state["max-power"] > unit["max_power(MW)"]:
            raise ValueError(f"{state_path}.max-power: exceeds unit maximum power")
        for key in ("enabled-cost", "min-time-enabled", "max-time-enabled",
                    "min-time-enabled-left", "max-time-enabled-left", "user_min_power", "user_max_power"):
            if key in state:
                number(state[key], f"{state_path}.{key}")
        if "user_min_power" in state and "user_max_power" in state:
            if not state["user_min_power"] <= state["user_max_power"] <= unit["max_power(MW)"]:
                raise ValueError(f"{state_path}: invalid user power bounds")
    sources = set()
    for index, row in enumerate(unit["operating-state-transitions"]):
        arc_path = f"{path}.operating-state-transitions[{index}]"
        _object(row, arc_path, required={"from", "transitions"})
        source = _integer(row["from"], f"{arc_path}.from")
        if source not in state_ids or source in sources:
            raise ValueError(f"{arc_path}.from: unknown or duplicate source state {source}")
        sources.add(source)
        targets = set()
        for target_index, target in enumerate(_array(row["transitions"], f"{arc_path}.transitions")):
            target_path = f"{arc_path}.transitions[{target_index}]"
            _object(target, target_path, required={"id"})
            dest = _integer(target["id"], f"{target_path}.id")
            if dest not in state_ids or dest in targets:
                raise ValueError(f"{target_path}.id: unknown or duplicate destination state {dest}")
            targets.add(dest)
            for key, value in target.items():
                if key == "transition-cost" or "transition-time" in key:
                    number(value, f"{target_path}.{key}")
    sources = set()
    for index, row in enumerate(unit["state-transitions"]):
        arc_path = f"{path}.state-transitions[{index}]"
        _object(row, arc_path, required={"from", "transitions"})
        source = _integer(row["from"], f"{arc_path}.from")
        if source not in (0, 1) or source in sources:
            raise ValueError(f"{arc_path}.from: expected a unique binary source state")
        sources.add(source)
        target = _object(row["transitions"], f"{arc_path}.transitions", required={"value"})
        dest = _integer(target["value"], f"{arc_path}.transitions.value")
        if dest not in (0, 1) or dest == source:
            raise ValueError(f"{arc_path}.transitions.value: expected the opposite binary state")
        for key in ("min-transition-time", "min-transition-time-left"):
            if key in target:
                number(target[key], f"{arc_path}.transitions.{key}")
    active = [state for state in states if state["isEnabled"]]
    if len(active) != 1 or int(not active[0]["isShutdown"]) != unit["state"]:
        raise ValueError(f"{path}: inconsistent initial operating state (exactly one must be enabled)")
    if not active[0]["min-power"] <= unit["current_Power(MW)"] <= active[0]["max-power"]:
        raise ValueError(f"{path}.current_Power(MW): initial power outside initial operating state")


def _validate_policy(config):
    path = "stochastic.slack_policy"
    policy = _object(config["slack_policy"], path, allowed={"mode", "caps"}, required={"mode"})
    if policy["mode"] not in ("legacy", "bounded"):
        raise ValueError(f"{path}.mode: expected legacy (regression) or bounded")
    caps = _object(policy.get("caps", {}), f"{path}.caps")
    for prefix, cap in caps.items():
        _identifier(prefix, f"{path}.caps")
        number(cap, f"{path}.caps.{prefix}")
    if policy["mode"] == "legacy" and caps:
        raise ValueError(f"{path}.caps: caps are ignored in legacy mode; use bounded mode")
    return policy


def _validate_effective_state_timers(base):
    """Do not silently accept dwell limits the legacy kernel never enforces.

    Short transient states can legitimately use these fields for embedding. Only
    inspect states that survive that preprocessing, preserving this supported use.
    """
    prepared = prepare_operating_state_time_resolution(deepcopy(base))
    for index, unit in enumerate(prepared["Generating_Units"]):
        for state in unit["operating-states"]:
            for field in STATE_MIN_TIME_FIELDS + STATE_MAX_TIME_FIELDS:
                if field not in state:
                    continue
                value = state[field]
                has_limit = value > 0 if field in STATE_MIN_TIME_FIELDS else value < LARGE_TIME_SENTINEL
                if has_limit:
                    raise ValueError(
                        f"Generating_Units[{index}].operating-states(id={state['id']}).{field}: "
                        "state-level dwell limits are not enforced on retained states; "
                        "use supported transition-time fields instead"
                    )


def _validate_reserves(config, flags):
    _boolean(config.get("reserve_link", False), "stochastic.reserve_link")
    products = _object(config.get("reserve_products", {}), "stochastic.reserve_products", allowed=set(PRODUCTS))
    for product, spec in products.items():
        path = f"stochastic.reserve_products.{product}"
        _object(spec, path, allowed=PRODUCT_FIELDS | PRODUCT_OPTIONAL, required=PRODUCT_FIELDS)
        if number(spec["response_minutes"], f"{path}.response_minutes") <= 0:
            raise ValueError(f"{path}.response_minutes: must be positive")
        for direction in ("up", "down"):
            number(spec[f"activation_eur_per_mwh_{direction}"], f"{path}.activation_eur_per_mwh_{direction}")
        if "balancing_deployment" in spec:
            _boolean(spec["balancing_deployment"], f"{path}.balancing_deployment")
    mode = config.get("reserve_link_mode", RESERVE_LINK_MODES[0])
    if mode not in RESERVE_LINK_MODES:
        raise ValueError(f"stochastic.reserve_link_mode: expected one of {list(RESERVE_LINK_MODES)}")
    if "reserve_link_mode" in config and not config.get("reserve_link", False):
        raise ValueError("stochastic.reserve_link_mode: only meaningful with reserve_link=true")
    if config.get("reserve_link", False):
        enabled = [p for p in PRODUCTS if flags.get(f"{p}_active_power_reserves_constraint")]
        # Χωρίς κανένα προϊόν η σύνδεση θα «πάγωνε» κάθε θερμική κατανομή στο reference.
        if not enabled:
            raise ValueError("stochastic.reserve_link: requires at least one enabled reserve product")
        for product in enabled:
            if product not in products:
                raise ValueError(f"stochastic.reserve_products.{product}: required for enabled reserve_link")
        if not any(products[p].get("balancing_deployment", True) for p in enabled):
            raise ValueError("stochastic.reserve_products: reserve_link needs at least one product with balancing_deployment")


def _validate_cost_policy(config, flags):
    policy = _object(config.get("cost_policy", {}), "stochastic.cost_policy", allowed=COST_POLICY_FIELDS)
    path = "stochastic.cost_policy"
    if "thermal_online_charge_eur_per_h" in policy:
        number(policy["thermal_online_charge_eur_per_h"], f"{path}.thermal_online_charge_eur_per_h")
    if policy.get("legacy_time_scaled_costs", "legacy") not in ("legacy", "per_hour"):
        raise ValueError(f"{path}.legacy_time_scaled_costs: expected legacy or per_hour")
    if "renewable_curtailment_eur_per_mwh" in policy:
        number(policy["renewable_curtailment_eur_per_mwh"], f"{path}.renewable_curtailment_eur_per_mwh")
        if flags.get("res_pv_dispatch_variables_constraints"):
            raise ValueError(f"{path}.renewable_curtailment_eur_per_mwh: the setpoint dispatch algorithm "
                             "has its own priority terms; disable it or omit this weight")


def _validate_history(config, units):
    ids = {str(unit["gen_id"]) for unit in units}
    for gid, spec in _object(config.get("maximum_on", {}), "stochastic.maximum_on").items():
        path = f"stochastic.maximum_on.{gid}"
        if gid not in ids:
            raise ValueError(f"{path}: unknown unit ID")
        _object(spec, path, allowed={"hours", "elapsed_hours", "violation_penalty_eur_per_h"},
                required={"hours", "elapsed_hours"})
        maximum = _integer(spec["hours"], f"{path}.hours", minimum=1)
        elapsed = _integer(spec["elapsed_hours"], f"{path}.elapsed_hours")
        penalty = spec.get("violation_penalty_eur_per_h")
        if penalty is not None and number(penalty, f"{path}.violation_penalty_eur_per_h") <= 0:
            raise ValueError(f"{path}.violation_penalty_eur_per_h: must be positive")
        # Παρατηρημένη υπέρβαση (π.χ. μετά από κυλιόμενη μετάβαση) γίνεται δεκτή μόνο
        # όταν υπάρχει ρητή ποινή· αλλιώς το μοντέλο θα ήταν προφανώς ανέφικτο.
        if elapsed > maximum and penalty is None:
            raise ValueError(f"{path}.elapsed_hours: exceeds maximum ON hours (set violation_penalty_eur_per_h "
                             "to schedule a penalized recovery)")
        if not units[int(gid)]["state"] and elapsed:
            raise ValueError(f"{path}.elapsed_hours: offline unit cannot have elapsed ON hours")
        if units[int(gid)]["state"] and elapsed < 1:
            raise ValueError(f"{path}.elapsed_hours: an online unit counts the current ON period t=0 (>= 1)")
    for gid, spec in _object(config.get("initial_operating_obligations", {}), "stochastic.initial_operating_obligations").items():
        path = f"stochastic.initial_operating_obligations.{gid}"
        if gid not in ids:
            raise ValueError(f"{path}: unknown unit ID")
        _object(spec, path, allowed={"state_id", "maximum_remaining_hours"}, required={"state_id", "maximum_remaining_hours"})
        _integer(spec["maximum_remaining_hours"], f"{path}.maximum_remaining_hours")
        state_id = _integer(spec["state_id"], f"{path}.state_id")
        active = next(state for state in units[int(gid)]["operating-states"] if state["isEnabled"])
        if state_id != active["id"]:
            raise ValueError(f"{path}.state_id: rolling obligation must refer to the initial operating state")


def _validate_storage_reserve(spec, path, flags):
    _object(spec, path, allowed=STORAGE_RESERVE_FIELDS, required={"products", "sustain_minutes"})
    products = _object(spec["products"], f"{path}.products", allowed=set(PRODUCTS))
    if not products:
        raise ValueError(f"{path}.products: list at least one reserve product")
    sustain = _object(spec["sustain_minutes"], f"{path}.sustain_minutes", allowed=set(PRODUCTS))
    for product, directions in products.items():
        product_path = f"{path}.products.{product}"
        if not flags.get(f"{product}_active_power_reserves_constraint"):
            raise ValueError(f"{product_path}: the legacy {product} reserve constraint is disabled")
        _array(directions, product_path, nonempty=True)
        if len(set(directions)) != len(directions) or not set(directions) <= set(DIRECTIONS):
            raise ValueError(f"{product_path}: expected unique directions among {list(DIRECTIONS)}")
        if product not in sustain:
            raise ValueError(f"{path}.sustain_minutes.{product}: required for an offered product")
        if number(sustain[product], f"{path}.sustain_minutes.{product}") <= 0:
            raise ValueError(f"{path}.sustain_minutes.{product}: must be positive")
    costs = _object(spec.get("capacity_cost_eur_per_mw_h", {}), f"{path}.capacity_cost_eur_per_mw_h",
                    allowed=set(DIRECTIONS))
    for direction, value in costs.items():
        number(value, f"{path}.capacity_cost_eur_per_mw_h.{direction}")


def _validate_storage(config, renewable_units, flags=None):
    ids, linked = set(), set()
    flags = flags or {}
    for index, store in enumerate(_array(config.get("storage", []), "stochastic.storage")):
        path = f"stochastic.storage[{index}]"
        _object(store, path, allowed=STORAGE_FIELDS, required=STORAGE_REQUIRED)
        sid = _identifier(store["id"], f"{path}.id")
        if sid in ids:
            raise ValueError(f"{path}.id: duplicate storage ID {sid!r}")
        ids.add(sid)
        for key in ("capacity_mwh", "min_mwh", "initial_mwh", "terminal_min_mwh", "charge_mw", "discharge_mw", "throughput_eur_per_mwh"):
            number(store[key], f"{path}.{key}")
        if store["min_mwh"] > store["capacity_mwh"]:
            raise ValueError(f"{path}.min_mwh: exceeds capacity_mwh")
        if not store["min_mwh"] <= store["terminal_min_mwh"] <= store["capacity_mwh"]:
            raise ValueError(f"{path}.terminal_min_mwh: outside energy bounds")
        # Μετρημένο SOC κάτω από το λειτουργικό ελάχιστο είναι φυσικά δυνατό (π.χ.
        # έκτακτη εκφόρτιση)· επιτρέπεται μόνο με ρητή, κοστολογημένη ανάκαμψη.
        if not 0 <= store["initial_mwh"] <= store["capacity_mwh"]:
            raise ValueError(f"{path}.initial_mwh: outside physical energy bounds [0, capacity_mwh]")
        for key in ("terminal_shortfall_penalty_eur_per_mwh", "soc_recovery_penalty_eur_per_mwh"):
            if key in store and number(store[key], f"{path}.{key}") <= 0:
                raise ValueError(f"{path}.{key}: must be positive")
        if store["initial_mwh"] < store["min_mwh"] and "soc_recovery_penalty_eur_per_mwh" not in store:
            raise ValueError(f"{path}.initial_mwh: below min_mwh; set soc_recovery_penalty_eur_per_mwh "
                             "to allow a penalized recovery to the operating band")
        if "power_availability" in store:
            values = _array(store["power_availability"], f"{path}.power_availability")
            for t, value in enumerate(values):
                if not 0 <= number(value, f"{path}.power_availability[{t}]") <= 1:
                    raise ValueError(f"{path}.power_availability[{t}]: expected a fraction in [0, 1]")
        if store["grid_charge"] and "renewable_gen_id" in store and "export_limit_mw" not in store:
            raise ValueError(f"{path}.renewable_gen_id: has no effect with grid_charge=true unless "
                             "export_limit_mw defines the hybrid connection limit")
        for key in ("charge_efficiency", "discharge_efficiency"):
            if not 0 < number(store[key], f"{path}.{key}") <= 1:
                raise ValueError(f"{path}.{key}: efficiency must be in (0, 1]")
        _boolean(store["grid_charge"], f"{path}.grid_charge")
        if "renewable_gen_id" in store:
            gid = _integer(store["renewable_gen_id"], f"{path}.renewable_gen_id")
            if str(gid) not in renewable_units:
                raise ValueError(f"{path}.renewable_gen_id: must identify a renewable unit")
        if not store["grid_charge"]:
            if "renewable_gen_id" not in store:
                raise ValueError(f"{path}.renewable_gen_id: required for renewable-only charging")
            gid = store["renewable_gen_id"]
            if gid in linked:
                raise ValueError(f"{path}.renewable_gen_id: a renewable unit may feed at most one renewable-only store")
            linked.add(gid)
        if "self_discharge_per_hour" in store:
            if not 0 <= number(store["self_discharge_per_hour"], f"{path}.self_discharge_per_hour") < 1:
                raise ValueError(f"{path}.self_discharge_per_hour: expected a fraction in [0, 1)")
        if "terminal_value_eur_per_mwh" in store:
            number(store["terminal_value_eur_per_mwh"], f"{path}.terminal_value_eur_per_mwh")
        if "max_cycles_per_horizon" in store:
            if number(store["max_cycles_per_horizon"], f"{path}.max_cycles_per_horizon") <= 0:
                raise ValueError(f"{path}.max_cycles_per_horizon: must be positive")
            if store["capacity_mwh"] <= store["min_mwh"]:
                raise ValueError(f"{path}.max_cycles_per_horizon: requires usable energy capacity")
        if "export_limit_mw" in store:
            number(store["export_limit_mw"], f"{path}.export_limit_mw")
            if "renewable_gen_id" not in store:
                raise ValueError(f"{path}.export_limit_mw: a hybrid export limit requires renewable_gen_id")
        if "reserve" in store:
            _validate_storage_reserve(store["reserve"], f"{path}.reserve", flags)


def _validate_storage_horizon(config, n):
    """Series lengths and hard-target reachability, which need the horizon/scenarios."""
    for index, store in enumerate(config.get("storage", [])):
        path = f"stochastic.storage[{index}]"
        availability = store.get("power_availability", [1.0] * n)
        if len(availability) != n:
            raise ValueError(f"{path}.power_availability: expected {n} decision periods")
        if "terminal_shortfall_penalty_eur_per_mwh" in store:
            continue  # μαλακός στόχος: πάντα εφικτός, με κοστολογημένο έλλειμμα
        # Άνω περιβάλλουσα SOC: μέγιστη φόρτιση κάθε ώρα (περιορισμένη από την ΑΠΕ
        # του σεναρίου όταν δεν επιτρέπεται φόρτιση από το δίκτυο).
        retention = 1 - store.get("self_discharge_per_hour", 0)
        for scenario in config["scenarios"]:
            if scenario["probability"] <= 0:
                continue
            reachable = store["initial_mwh"]
            for t in range(n):
                charge = store["charge_mw"] * availability[t]
                if not store["grid_charge"]:
                    charge = min(charge, scenario["renewables_mw"][str(store["renewable_gen_id"])][t])
                reachable = min(store["capacity_mwh"], retention * reachable + store["charge_efficiency"] * charge)
            if reachable < store["terminal_min_mwh"] - 1e-9:
                raise ValueError(
                    f"{path}.terminal_min_mwh: unreachable in scenario {scenario['id']!r} "
                    f"(at most {reachable:.6g} MWh); lower it or set terminal_shortfall_penalty_eur_per_mwh")


def tree_nodes(config):
    """Return {stage: {node_key: [scenario ids]}} for positive-probability scenarios.

    A node is identified by the tree-path prefix up to its stage, so equal labels
    under different parents are different nodes.
    """
    tree = config.get("scenario_tree")
    if tree is None:
        return {}
    nodes = {}
    for stage in range(len(tree["stage_start_hours"])):
        groups = {}
        for scenario in config["scenarios"]:
            if scenario["probability"] > 0:
                groups.setdefault(tuple(scenario["tree_path"][:stage + 1]), []).append(scenario["id"])
        nodes[stage] = groups
    return nodes


def stage_hours(config, n):
    """Hours (1-based decision periods) belonging to each stage of the tree."""
    starts = list(config["scenario_tree"]["stage_start_hours"]) + [n + 1]
    return [list(range(starts[k], starts[k + 1])) for k in range(len(starts) - 1)]


def _validate_tree(config, n):
    """Information structure: equal path prefixes must carry equal observed data."""
    tree = config.get("scenario_tree")
    scenarios = config["scenarios"]
    if tree is None:
        for index, scenario in enumerate(scenarios):
            if "tree_path" in scenario:
                raise ValueError(f"stochastic.scenarios[{index}].tree_path: requires stochastic.scenario_tree")
        return
    path = "stochastic.scenario_tree"
    _object(tree, path, allowed=TREE_FIELDS, required=TREE_FIELDS)
    starts = _array(tree["stage_start_hours"], f"{path}.stage_start_hours", nonempty=True)
    for k, start in enumerate(starts):
        _integer(start, f"{path}.stage_start_hours[{k}]", minimum=1)
    if starts[0] != 1 or any(b <= a for a, b in zip(starts, starts[1:])) or starts[-1] > n:
        raise ValueError(f"{path}.stage_start_hours: must start at 1, increase strictly and lie within 1..{n}")
    for index, scenario in enumerate(scenarios):
        tree_path = scenario.get("tree_path")
        item = f"stochastic.scenarios[{index}].tree_path"
        if not isinstance(tree_path, list) or len(tree_path) != len(starts):
            raise ValueError(f"{item}: expected one node label per stage ({len(starts)})")
        for k, label in enumerate(tree_path):
            _identifier(label, f"{item}[{k}]")
    roots = {s["tree_path"][0] for s in scenarios if s["probability"] > 0}
    if len(roots) != 1:
        # Διαφορετικές ρίζες θα κωδικοποιούσαν πληροφορία που ο διαχειριστής δεν έχει.
        raise ValueError(f"{path}: all positive-probability scenarios must share one root node (got {sorted(roots)})")
    hours = stage_hours(config, n)
    by_id = {s["id"]: s for s in scenarios}
    for stage, groups in tree_nodes(config).items():
        for key, members in groups.items():
            reference = by_id[members[0]]
            for sid in members[1:]:
                other = by_id[sid]
                series_pairs = [("load_mw", reference["load_mw"], other["load_mw"])]
                series_pairs += [(f"renewables_mw.{gid}", values, other["renewables_mw"][gid])
                                 for gid, values in reference["renewables_mw"].items()]
                for label, left, right in series_pairs:
                    for t in hours[stage]:
                        if abs(left[t - 1] - right[t - 1]) > TREE_DATA_TOLERANCE:
                            raise ValueError(
                                f"{path}: scenarios {members[0]!r} and {sid!r} share node {'/'.join(key)} "
                                f"but differ in {label} at hour {t}; shared nodes must carry identical data")
    paths = [tuple(s["tree_path"]) for s in scenarios if s["probability"] > 0]
    if len(paths) != len(set(paths)):
        raise ValueError(f"{path}: two positive-probability scenarios have the same complete tree path")


def validate(base):
    """Validate a complete stochastic RDAS input without modifying it."""
    _validate_structure(base)
    assert_valid_input(base)
    if base["Time_granularity"] != 60:
        raise ValueError("Time_granularity: this extension implements hourly RDAS; must be 60")
    config = _object(base["stochastic"], "stochastic", allowed=CONFIG_FIELDS, required={"scenarios", "slack_policy"})
    if "description" in config and not isinstance(config["description"], str):
        raise ValueError("stochastic.description: expected a string")
    policy = _validate_policy(config)
    units = base["Generating_Units"]
    n = len(base["Load_forecast"]) - 1
    for index, unit in enumerate(units):
        path = f"Generating_Units[{index}]"
        if _integer(unit["gen_id"], f"{path}.gen_id") != index:
            raise ValueError(f"{path}.gen_id: legacy kernel requires its zero-based list index")
        if _integer(unit["state"], f"{path}.state") not in (0, 1):
            raise ValueError(f"{path}.state: must be 0 or 1")
        _validate_state_graph(unit, path)
        series(unit["availability"], n, f"{path}.availability", [unit["max_power(MW)"]] * n)
        upper = None if policy["mode"] == "legacy" else unit["availability"]
        series(unit["Production_Forecast"], n, f"{path}.Production_Forecast", upper)
        for key in ("ramp_up_rate(kW/min)", "ramp_down_rate(kW/min)", "start_up_cost(euro)", "shut_down_cost(euro)"):
            number(unit.get(key), f"{path}.{key}")
    scenarios = _array(config["scenarios"], "stochastic.scenarios", nonempty=True)
    required = set(renewable_ids(base))
    ids = set()
    fields = {"id", "probability", "load_mw", "renewables_mw"}
    for index, scenario in enumerate(scenarios):
        path = f"stochastic.scenarios[{index}]"
        _object(scenario, path, allowed=fields | {"tree_path"}, required=fields)
        sid = _identifier(scenario["id"], f"{path}.id")
        if sid in ids:
            raise ValueError(f"{path}.id: duplicate scenario ID {sid!r}")
        ids.add(sid)
        if number(scenario["probability"], f"{path}.probability") > 1:
            raise ValueError(f"{path}.probability: must be <= 1")
        series(scenario["load_mw"], n, f"{path}.load_mw")
        renewables = _object(scenario["renewables_mw"], f"{path}.renewables_mw")
        if set(renewables) != required:
            raise ValueError(f"{path}.renewables_mw: keys must be exactly {sorted(required)}")
        for gid, values in renewables.items():
            # Original inconsistent forecasts are retained only for explicit regression mode.
            upper = None if policy["mode"] == "legacy" else units[int(gid)]["availability"]
            series(values, n, f"{path}.renewables_mw.{gid}", upper)
    if not math.isclose(math.fsum(s["probability"] for s in scenarios), 1, abs_tol=1e-9, rel_tol=0):
        raise ValueError("stochastic.scenarios: probabilities must sum to 1; they are never silently normalized")
    risk = _object(config.get("risk", {}), "stochastic.risk", allowed={"alpha", "weight"})
    if not 0 < number(risk.get("alpha", 0.95), "stochastic.risk.alpha") < 1:
        raise ValueError("stochastic.risk.alpha: CVaR alpha must lie strictly between 0 and 1")
    number(risk.get("weight", 0), "stochastic.risk.weight")
    flags = base["constraints"]
    for flag in ("load_production_balance_constraint", "allowed_thermal_states_transition_constraints"):
        if not flags.get(flag):
            raise ValueError(f"constraints.{flag}: required for stochastic RDAS")
    if flags.get("tertiary_active_power_reserves_constraint") and not flags.get("secondary_active_power_reserves_constraint"):
        raise ValueError("Legacy tertiary reserves require secondary reserves enabled")
    if flags.get("secondary_active_power_reserves_constraint") and not flags.get("primary_active_power_reserves_constraint"):
        raise ValueError("Legacy secondary reserves require primary reserves enabled")
    _validate_reserves(config, flags)
    _validate_history(config, units)
    _validate_storage(config, required, flags)
    _validate_storage_horizon(config, n)
    _validate_cost_policy(config, flags)
    _validate_tree(config, n)
    if policy["mode"] == "bounded":
        _validate_effective_state_timers(base)
    return base


def scenario_input(base, scenario):
    data = deepcopy(base)
    data.pop("stochastic", None)
    # t=0 is observed history: replace decision periods only.
    data["Load_forecast"] = [base["Load_forecast"][0]] + list(scenario["load_mw"])
    for gid, forecast in scenario["renewables_mw"].items():
        data["Generating_Units"][int(gid)]["Production_Forecast"] = list(forecast)
    return data
