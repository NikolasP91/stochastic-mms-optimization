"""One extensive-form MILP assembled from the preserved MMS constraint blocks."""

from contextlib import redirect_stdout
from copy import deepcopy
from dataclasses import dataclass, field
import io
import math
import re
from time import perf_counter

import pulp as pl

from mms.model.preprocessing import time_granularity, unit_categories
from mms.model.time_resolution import prepare_operating_state_time_resolution
from mms.model.problem import define_problem_and_solve_problem
from .data import PRODUCTS, number, scenario_input, stage_hours, tree_nodes, validate
from .artifacts import run_metadata
from .errors import InfeasibleModelError, OptimizationError


SHARED_PREFIXES = ("state_", "startup_", "shutdown_", "u_2_", "transition_arc_",
                   "primary_ActPR_", "secondary_ActPR_", "tertiary_ActPR_")
# Χαλαρώσεις που εξαρτώνται μόνο από κοινές αποφάσεις: κόστος πρώτου σταδίου.
FIRST_STAGE_SLACK_PREFIXES = ("s_must_run_", "s_min_a_", "s_min_b_", "s_min_state_",
                              "s_max_oper_state_time_b_", "s_maximum_on_")
# Κοινά αντικείμενα που δημιουργεί η επέκταση: μία μεταβλητή για όλα τα σενάρια.
SHARED_OBJECT_PREFIXES = ("reference_", "storage_reserve_")
# Αποφάσεις προσαρμογής (recourse) που εξισώνονται σε κοινό κόμβο του δέντρου.
# Βοηθητικές μεταβλητές (PWL, απαγορευμένες ζώνες, APRR) καθορίζονται από αυτές.
TREE_RECOURSE = re.compile(
    r"(power_\d+|activation_(?:primary|secondary|tertiary)_(?:up|down)_\d+|activation_direction_\d+"
    r"|s_load_(?:minus|plus)|s_power_(?:plus|minus)_\d+"
    r"|storage_(?:charge|discharge|energy|mode)_\d+)_(\d+)")


def is_slack(name):
    return name.startswith(("s_", "ramp_relax_"))


def compile_legacy(data):
    """Public build-only adapter; never mutates the caller or invokes a solver."""
    with redirect_stdout(io.StringIO()):
        prepared = prepare_operating_state_time_resolution(deepcopy(data))
        prepared = time_granularity(prepared, prepared["Time_granularity"])
        units = prepared["Generating_Units"]
        groups = unit_categories(prepared, units)
        UNITS, CONV, RES, PV, RES_SP, RES_no_SP, PV_SP, PV_no_SP, on_AGC, partial = groups
        return define_problem_and_solve_problem(
            data=units, input_data=prepared, UNITS=UNITS, CONV=CONV, RES=RES, PV=PV,
            RES_SP=RES_SP, RES_no_SP=RES_no_SP, PV_SP=PV_SP, PV_no_SP=PV_no_SP,
            Partially_Controllable=partial, on_AGC=on_AGC,
            RES_forecast=[list(row) for row in zip(*(g["Production_Forecast"] for g in units))],
            Load_forecast=prepared["Load_forecast"], intervals=list(range(len(prepared["Load_forecast"]))),
            x_load=prepared["Cost_parameters"]["x_load"], build_only=True,
        )


@dataclass
class ExtensiveModel:
    problem: pl.LpProblem
    data: dict
    shared: dict = field(default_factory=dict)
    blocks: dict = field(default_factory=dict)
    costs: dict = field(default_factory=dict)
    first_cost: object = None
    build_seconds: float = 0
    tree_constraints: int = 0


def _apply_slack_policy(prob, variables, policy, scenario):
    if policy["mode"] == "legacy":
        return
    caps = policy.get("caps", {})
    for prefix in caps:
        if not any(is_slack(name) and name.startswith(prefix) for name in variables):
            raise ValueError(f"slack_policy.caps.{prefix}: does not match any active slack variable")
    for name, var in variables.items():
        if is_slack(name):
            matching = [key for key in caps if name.startswith(key)]
            cap = caps[max(matching, key=len)] if matching else 0
            if name.startswith("s_load_minus_"):
                t = int(name.rsplit("_", 1)[1])
                cap = min(cap, scenario["load_mw"][t - 1]) if t else 0
            if var.upBound is not None:
                cap = min(cap, var.upBound)
            var.upBound = cap
            # Χαλάρωση επιτρέπεται μόνο όταν έχει δηλωμένη θετική ποινή.
            if cap and prob.objective.get(var, 0) <= 0:
                raise ValueError(f"Permitted slack {name} has no positive objective penalty")


def _reserve_eligibility(context, variables):
    # Στο legacy kernel, μονάδες χωρίς λειτουργική κατάσταση δεν αποκτούν
    # περιορισμούς εφεδρείας. Η αυστηρή διαδρομή αποκλείει πλασματική παροχή.
    for i, unit in enumerate(context["data"]):
        if not any(state["isOperational"] for state in unit["operating-states"]):
            for product in PRODUCTS:
                for direction in ("plus", "minus"):
                    for t in context["intervals"][1:]:
                        var = variables.get(f"{product}_ActPR_{direction}{i+1}_{t}")
                        if var is not None:
                            var.upBound = 0


def _equalities_by_variable(prob, names):
    """Map each named variable to the equality rows containing it (one pass)."""
    rows = {name: [] for name in names}
    for constraint in prob.constraints.values():
        if constraint.sense != pl.LpConstraintEQ:
            continue
        for var in constraint:
            if var.name in rows:
                rows[var.name].append(constraint)
    return rows


def _unique_row(rows, name, what):
    if len(rows[name]) != 1:
        raise RuntimeError(f"Cannot identify the preserved MMS {what} row containing {name}")
    return rows[name][0]


def _storage_reserve_variable(shared, first_cost, product, direction, j, t, store):
    """First-stage BESS reserve capacity: one shared variable for all scenarios."""
    key = f"storage_reserve_{product}_{direction}_{j}_{t}"
    if key not in shared:
        bound = store["discharge_mw"] + store["charge_mw"]
        shared[key] = pl.LpVariable(key, 0, bound)
        # Η δέσμευση ισχύος χρεώνεται μία φορά (πρώτο στάδιο), όχι ανά σενάριο.
        price = store["reserve"].get("capacity_cost_eur_per_mw_h", {}).get(direction, 0)
        if price:
            first_cost.addInPlace(price * shared[key])
    return shared[key]


def _add_storage(prob, context, variables, stores, scenario, shared=None, first_cost=None):
    """BESS / hybrid storage recourse; returns the scenario's added cost.

    Units: MW, MWh, hourly steps (Δ = 1 h). Every optional field defaults to the
    original aggregate-storage model.
    """
    if not stores:
        return pl.LpAffineExpression()
    shared = {} if shared is None else shared
    first_cost = pl.LpAffineExpression() if first_cost is None else first_cost
    cost = pl.LpAffineExpression()
    periods = context["intervals"][1:]
    slack_names = [f"s_load_minus_{t}" for t in periods]
    for b in stores:
        for product, directions in b.get("reserve", {}).get("products", {}).items():
            names = {"up": "upwards", "down": "downwards"}
            slack_names += [f"s_{product}_APR_{names[d]}_{t}" for d in directions for t in periods]
    rows = _equalities_by_variable(prob, slack_names)
    for j, b in enumerate(stores):
        energy = {0: b["initial_mwh"]}
        retention = 1 - b.get("self_discharge_per_hour", 0)
        reserve = b.get("reserve", {})
        availability = b.get("power_availability", [1.0] * len(periods))
        recovery = b.get("soc_recovery_penalty_eur_per_mwh")
        floor = {}
        discharged = []

        def above_min(t):
            # Ενέργεια πάνω από το λειτουργικό ελάχιστο· με ανάκαμψη μετρά και το έλλειμμα.
            if t == 0:
                return max(0.0, b["initial_mwh"] - b["min_mwh"])
            return energy[t] - b["min_mwh"] + (floor[t] if t in floor else 0)

        for t in periods:
            charge_max = b["charge_mw"] * availability[t - 1]
            discharge_max = b["discharge_mw"] * availability[t - 1]
            # Τα όρια ισχύος είναι τα ακριβή Big-M της δυαδικής επιλογής φόρτισης.
            charge = pl.LpVariable(f"storage_charge_{j}_{t}", 0, charge_max)
            discharge = pl.LpVariable(f"storage_discharge_{j}_{t}", 0, discharge_max)
            mode = pl.LpVariable(f"storage_mode_{j}_{t}", cat="Binary")
            energy[t] = pl.LpVariable(f"storage_energy_{j}_{t}", 0 if recovery else b["min_mwh"], b["capacity_mwh"])
            if recovery:
                # Μετρημένο SOC κάτω από το ελάχιστο: κοστολογημένη επαναφορά, όχι αδυναμία.
                floor[t] = pl.LpVariable(f"s_storage_soc_floor_{j}_{t}", 0, b["min_mwh"])
                prob += energy[t] + floor[t] >= b["min_mwh"]
                cost += recovery * floor[t]
            prob += charge <= charge_max * mode
            prob += discharge <= discharge_max * (1 - mode)
            # Ενεργειακό ισοζύγιο με αυτοεκφόρτιση σ: E_t = (1-σ)E_{t-1} + η_c h - d/η_d.
            prob += energy[t] == retention * energy[t-1] + b["charge_efficiency"] * charge - discharge / b["discharge_efficiency"]
            renewable = context["power"][int(b["renewable_gen_id"])][t] if "renewable_gen_id" in b else None
            if not b["grid_charge"]:
                prob += charge <= renewable
            if "export_limit_mw" in b:
                # Όριο στο σημείο σύνδεσης (POI) του υβριδικού σταθμού.
                prob += renewable + discharge - charge <= b["export_limit_mw"]
            # Αλλάζει μόνο το ισοζύγιο: η αποθήκευση προσθέτει καθαρή έγχυση.
            _unique_row(rows, f"s_load_minus_{t}", "load balance").addInPlace(discharge - charge)
            cost += b["throughput_eur_per_mwh"] * (charge + discharge)
            discharged.append(discharge / b["discharge_efficiency"])
            # Εφεδρεία BESS: κοινή δέσμευση, εφικτή σε κάθε σενάριο ως προς ισχύ και ενέργεια.
            totals = {"up": [], "down": []}
            energy_need = {"up": [], "down": []}
            for product, directions in reserve.get("products", {}).items():
                hours = reserve["sustain_minutes"][product] / 60
                for direction in directions:
                    r = _storage_reserve_variable(shared, first_cost, product, direction, j, t, b)
                    totals[direction].append(r)
                    energy_need[direction].append(r * hours)
                    label = "upwards" if direction == "up" else "downwards"
                    _unique_row(rows, f"s_{product}_APR_{label}_{t}", f"{product} reserve requirement").addInPlace(r)
            if totals["up"]:
                prob += pl.lpSum(totals["up"]) <= discharge_max - discharge + charge
                for k in (t - 1, t):
                    prob += pl.lpSum(energy_need["up"]) <= b["discharge_efficiency"] * above_min(k)
            if totals["down"]:
                prob += pl.lpSum(totals["down"]) <= charge_max - charge + discharge
                if not b["grid_charge"]:
                    prob += pl.lpSum(totals["down"]) <= renewable - charge + discharge
                for level in (energy[t-1], energy[t]):
                    prob += b["charge_efficiency"] * pl.lpSum(energy_need["down"]) <= b["capacity_mwh"] - level
        final = energy[periods[-1]]
        if "terminal_shortfall_penalty_eur_per_mwh" in b:
            # Μαλακός τελικός στόχος: το έλλειμμα κοστολογείται ρητά και αναφέρεται.
            shortfall = pl.LpVariable(f"s_storage_terminal_{j}", 0, b["terminal_min_mwh"])
            prob += final + shortfall >= b["terminal_min_mwh"]
            cost += b["terminal_shortfall_penalty_eur_per_mwh"] * shortfall
        else:
            prob += final >= b["terminal_min_mwh"]
        if "max_cycles_per_horizon" in b:
            usable = b["capacity_mwh"] - b["min_mwh"]
            prob += pl.lpSum(discharged) <= b["max_cycles_per_horizon"] * usable
        if b.get("terminal_value_eur_per_mwh"):
            # Αξία αποθηκευμένης ενέργειας στο τέλος του ορίζοντα (αρνητικό κόστος).
            cost += -b["terminal_value_eur_per_mwh"] * energy[periods[-1]]
    return cost


def _maximum_on(prob, context, config):
    """Maximum continuous ON time; returns the cost of optional priced violations."""
    cost = pl.LpAffineExpression()
    n = len(context["intervals"]) - 1
    for gid, spec in config.get("initial_operating_obligations", {}).items():
        remaining = int(spec["maximum_remaining_hours"])
        if remaining < n:
            prob += pl.lpSum(context["operating_states"][int(gid), t, spec["state_id"]]
                             for t in range(1, remaining + 2)) <= remaining
    for gid, spec in config.get("maximum_on", {}).items():
        u = context["state"][int(gid)]
        maximum, elapsed = int(spec["hours"]), int(spec["elapsed_hours"])
        penalty = spec.get("violation_penalty_eur_per_h")
        # Παράθυρα περιλαμβάνουν το γνωστό συνεχές ιστορικό ON πριν από t=1.
        for t in range(1, n + 1):
            start = t - maximum
            history = max(0, 1 - max(start, 1 - elapsed)) if start <= 0 and elapsed else 0
            lhs = pl.lpSum(u[k] for k in range(max(1, start), t + 1)) + history
            if penalty is None:
                prob += lhs <= maximum
            else:
                # Κοστολογημένη υπέρβαση: η σβέση γίνεται όσο νωρίτερα επιτρέπουν οι χρονιστές.
                excess = pl.LpVariable(f"s_maximum_on_{int(gid) + 1}_{t}", 0)
                prob += lhs - excess <= maximum
                cost += penalty * excess
    return cost


def _apply_cost_policy(block, context, variables, scenario, policy, flags):
    """Replace legacy minute-scaled objective terms by explicit hourly values.

    The legacy kernel multiplies reserve-capacity prices, operating-state
    enabled-costs, a hard-coded online charge (100) and the RES curtailment
    weight (1000) by Time_granularity = 60. Only declared options change the
    coefficients; the deterministic kernel source is untouched.
    """
    if not policy:
        return
    objective, tg = block.objective, 60
    periods = context["intervals"][1:]
    per_hour = policy.get("legacy_time_scaled_costs", "legacy") == "per_hour"
    online = policy.get("thermal_online_charge_eur_per_h", 100 if per_hour else None)
    if online is not None:
        for i in context["CONV"]:
            for t in periods:
                var = context["state"][i][t]
                objective[var] = objective.get(var, 0) - 100 * tg + online
    if per_hour:
        for i, gen in enumerate(context["data"]):
            for product in PRODUCTS:
                prices = gen.get(f"{product.capitalize()}_APR_Cost(euro/MW)", [0, 0])
                for suffix, price in zip(("plus", "minus"), prices):
                    for t in periods:
                        var = variables.get(f"{product}_ActPR_{suffix}{i+1}_{t}")
                        if var is not None and price:
                            objective[var] = objective.get(var, 0) + price * (1 - tg)
            for state in gen["operating-states"]:
                if state.get("enabled-cost"):
                    for t in periods:
                        var = context["operating_states"][i, t, state["id"]]
                        objective[var] = objective.get(var, 0) + state["enabled-cost"] * (1 - tg)
    weight = policy.get("renewable_curtailment_eur_per_mwh", 1000 if per_hour else None)
    if weight is not None and not flags.get("res_pv_dispatch_variables_constraints"):
        # Αρχικός όρος: (W - p)·1000·60 μόνο για αιολικά. Αντικαθίσταται από (W - p)·w
        # και, όταν δηλώνεται ρητό βάρος, εφαρμόζεται και στα φωτοβολταϊκά.
        units = [(i, 1000 * tg) for i in context["RES"]]
        if "renewable_curtailment_eur_per_mwh" in policy:
            units += [(i, 0) for i in context["PV"]]
        for i, legacy in units:
            for t in periods:
                var = context["power"][i][t]
                available = scenario["renewables_mw"][str(i)][t - 1]
                objective[var] = objective.get(var, 0) + legacy - weight
                objective.constant += (weight - legacy) * available


def _renewable_reserve_bounds(prob, context, variables, scenario):
    """RES/PV reserve must be deliverable from the scenario resource, not nameplate."""
    for i in list(context["RES"]) + list(context["PV"]):
        resource = scenario["renewables_mw"].get(str(i))
        if resource is None:
            continue
        for t in context["intervals"][1:]:
            up = [variables[n] for p in PRODUCTS if (n := f"{p}_ActPR_plus{i+1}_{t}") in variables]
            down = [variables[n] for p in PRODUCTS if (n := f"{p}_ActPR_minus{i+1}_{t}") in variables]
            if up:
                prob += context["power"][i][t] + pl.lpSum(up) <= resource[t - 1]
            if down:
                prob += context["power"][i][t] - pl.lpSum(down) >= 0


def _legacy_reserve_rows(prob):
    """Index legacy reserve-capability rows by unit power-variable name."""
    rows = {}
    for name, constraint in prob.constraints.items():
        if name.startswith(tuple(f"mms_{p}_active_power_reserves" for p in PRODUCTS)):
            for var in constraint.keys():
                if var.name.startswith("power_"):
                    rows.setdefault(var.name, []).append(constraint)
    return rows


def _reserve_rows_around_reference(power, reference, i, t, rows):
    """deploy_from_procured: legacy headroom/footroom rows use the reference.

    Balancing deployment then consumes procured reserve (remaining r - e), as in
    two-stage reserve-deployment models, instead of requiring r + e of room.
    Requirement rows (APRR ~ total generation) contain no unit reserve variable
    and stay scenario-dependent.
    """
    own = {f"{p}_ActPR_{d}{i+1}_{t}" for p in PRODUCTS for d in ("plus", "minus")}
    for constraint in rows.get(power.name, []):
        if any(var.name in own for var in constraint.keys()):
            coefficient = constraint.get(power, 0)
            constraint.addInPlace(coefficient * reference - coefficient * power)


def _reserve_links(prob, context, variables, config, shared):
    extra_cost = pl.LpAffineExpression()
    rows = _legacy_reserve_rows(prob) if config.get("reserve_link_mode") == "deploy_from_procured" else {}
    for i in context["CONV"]:
        g = context["data"][i]
        for t in context["intervals"][1:]:
            key = f"reference_{i+1}_{t}"
            if key not in shared:
                shared[key] = pl.LpVariable(key, 0, g["availability"][t-1])
            reference = shared[key]
            low = pl.lpSum(context["operating_states"][i, t, k["id"]] * k["min-power"][t-1] for k in g["operating-states"])
            high = pl.lpSum(context["operating_states"][i, t, k["id"]] * k["max-power"][t-1] for k in g["operating-states"])
            up, down, capacity_up, capacity_down = [], [], [], []
            response_capacities = {"up": [], "down": []}
            for product in PRODUCTS:
                for direction, suffix, acts, caps in (("up", "plus", up, capacity_up), ("down", "minus", down, capacity_down)):
                    name = f"{product}_ActPR_{suffix}{i+1}_{t}"
                    if name not in variables:
                        continue
                    spec = config["reserve_products"][product]
                    reserve = variables[name]
                    rate = g[f"ramp_{direction}_rate(kW/min)"] / 1000
                    prob += reserve <= rate * spec["response_minutes"]
                    caps.append(reserve)
                    response_capacities[direction].append((spec["response_minutes"], reserve))
                    # Ωριαίες αποκλίσεις καλύπτονται μόνο από προϊόντα που το επιτρέπουν
                    # (π.χ. όχι FCR όταν balancing_deployment=false).
                    if spec.get("balancing_deployment", True):
                        activation = pl.LpVariable(f"activation_{product}_{direction}_{i+1}_{t}", 0)
                        prob += activation <= reserve
                        acts.append(activation)
                        extra_cost += spec[f"activation_eur_per_mwh_{direction}"] * activation
            # A simultaneous call shares one ramp trajectory. By each deadline,
            # all products with that deadline or an earlier one must be supplied.
            for reserve_direction, timed_capacities in response_capacities.items():
                rate = g[f"ramp_{reserve_direction}_rate(kW/min)"] / 1000
                for deadline_index, deadline in enumerate(sorted({minutes for minutes, _ in timed_capacities})):
                    prob += (
                        pl.lpSum(reserve for minutes, reserve in timed_capacities if minutes <= deadline)
                        <= rate * deadline,
                        f"reserve_response_{reserve_direction}_{i+1}_{t}_{deadline_index}",
                    )
            # Τα προϊόντα καλύπτονται ταυτόχρονα, χωρίς διπλή χρήση του ίδιου MW.
            prob += reference + pl.lpSum(capacity_up) <= high
            prob += reference + pl.lpSum(capacity_up) <= g["availability"][t-1]
            prob += reference - pl.lpSum(capacity_down) >= low
            prob += context["power"][i][t] == reference + pl.lpSum(up) - pl.lpSum(down)
            if config.get("reserve_link_mode") == "deploy_from_procured":
                _reserve_rows_around_reference(context["power"][i][t], reference, i, t, rows)
            # Αποφεύγεται ταυτόχρονη ανοδική/καθοδική ενεργοποίηση.
            direction = pl.LpVariable(f"activation_direction_{i+1}_{t}", cat="Binary")
            bound = g["availability"][t-1]
            prob += pl.lpSum(up) <= bound * direction
            prob += pl.lpSum(down) <= bound * (1 - direction)
    return extra_cost


def _tree_nonanticipativity(result, config, n):
    """Multistage information: equal tree-path prefixes imply equal recourse.

    Stage k covers hours stage_start_hours[k] .. next start - 1. Scenarios that
    share the stage-k node have observed identical data so far (validated), so
    the operator cannot distinguish them and must issue identical dispatch,
    storage and activation decisions in those hours. Without a tree, recourse
    sees the whole path (two-stage, full-path recourse).
    """
    if "scenario_tree" not in config:
        return 0
    hours = stage_hours(config, n)
    count = 0
    for stage, groups in tree_nodes(config).items():
        stage_set = set(hours[stage])
        for members in groups.values():
            reference = result.blocks[members[0]]["variables"]
            for sid in members[1:]:
                block = result.blocks[sid]
                for name, var in reference.items():
                    match = TREE_RECOURSE.fullmatch(name)
                    if match and int(match.group(2)) in stage_set:
                        result.problem += (block["variables"][name] == var,
                                           f"tree_nonanticipativity_{block['index']}__{name}")
                        count += 1
    return count


def build_model(data, fixed_first_stage=None, *, require_complete_first_stage=False):
    validate(data)
    started = perf_counter()
    result = ExtensiveModel(pl.LpProblem("Stochastic_RDAS", pl.LpMinimize), deepcopy(data))
    config = data["stochastic"]
    expected = pl.LpAffineExpression()
    shared_coefficients = None
    storage_first_cost = pl.LpAffineExpression()
    first_slack_expected = pl.LpAffineExpression()
    for index, scenario in enumerate(config["scenarios"]):
        if scenario["probability"] == 0:
            continue  # Σενάρια εκτός της πιθανοτικής στήριξης δεν επιβάλλουν περιορισμούς.
        block, context = compile_legacy(scenario_input(data, scenario))
        variables = {v.name: v for v in block.variables()}
        _apply_cost_policy(block, context, variables, scenario, config.get("cost_policy", {}), data["constraints"])
        _apply_slack_policy(block, variables, config["slack_policy"], scenario)
        if config["slack_policy"]["mode"] == "bounded":
            _reserve_eligibility(context, variables)
        for name, var in variables.items():
            if name.startswith(SHARED_PREFIXES):
                if name in result.shared:
                    block += var == result.shared[name], f"nonanticipativity_{name}"
                else:
                    result.shared[name] = var
        stage_terms = {name: block.objective.get(var, 0) for name, var in variables.items()
                       if name.startswith(SHARED_PREFIXES)}
        if shared_coefficients is None:
            shared_coefficients = stage_terms
            result.first_cost = pl.lpSum(coef * result.shared[name] for name, coef in stage_terms.items())
        elif stage_terms != shared_coefficients:
            raise ValueError("First-stage cost coefficients differ across scenarios")
        additions = _add_storage(block, context, variables, config.get("storage", []), scenario,
                                 result.shared, storage_first_cost)
        additions += _maximum_on(block, context, config)
        if config.get("reserve_link", False):
            additions += _reserve_links(block, context, variables, config, result.shared)
        if config["slack_policy"]["mode"] == "bounded":
            for gid, available in scenario["renewables_mw"].items():
                for t, value in enumerate(available, 1):
                    block += context["power"][int(gid)][t] <= value
            _renewable_reserve_bounds(block, context, variables, scenario)
        cost = block.objective.copy() + additions
        # Ποινές χαλάρωσης περιορισμών που περιέχουν μόνο κοινές μεταβλητές
        # (must-run, χρονιστές καταστάσεων, μέγιστο ON) ανήκουν στο πρώτο στάδιο.
        first_slack_expected += scenario["probability"] * pl.lpSum(
            coef * var for var, coef in cost.items() if var.name.startswith(FIRST_STAGE_SLACK_PREFIXES))
        variables = {v.name: v for v in block.variables()}
        # Οι νέες μεταβλητές μόνο του κόστους περιλαμβάνονται ρητά.
        for v in additions:
            variables.setdefault(v.name, v)
        for name, var in variables.items():
            # Κοινές reference/εφεδρείες BESS έχουν μία ταυτότητα στο συνολικό μοντέλο.
            if not name.startswith(SHARED_OBJECT_PREFIXES) and not var.name.startswith("scenario_"):
                var.name = f"scenario_{index}__{name}"
        for name, constraint in block.constraints.items():
            result.problem += constraint, f"scenario_{index}__{name}"
        sid = scenario["id"]
        result.blocks[sid] = {"variables": variables, "context": context, "scenario": scenario,
                              "legacy_objective": block.objective.copy(), "additions": additions,
                              "index": index}
        result.costs[sid] = cost
        expected += scenario["probability"] * cost
    # Το κόστος δέσμευσης εφεδρείας BESS ανήκει στο πρώτο στάδιο: προστίθεται
    # σε κάθε L_s, άρα μία φορά στο αναμενόμενο κόστος (Σ π_s = 1).
    result.first_cost = result.first_cost + first_slack_expected
    if storage_first_cost.items():
        result.first_cost = result.first_cost + storage_first_cost
        for sid in result.costs:
            result.costs[sid] = result.costs[sid] + storage_first_cost
        expected += storage_first_cost
    result.tree_constraints = _tree_nonanticipativity(result, config, len(data["Load_forecast"]) - 1)
    # Προηγούμενες δεσμεύσεις: επιτρέπεται μερικό λεξικό, αλλά όχι άγνωστα ονόματα.
    if fixed_first_stage is not None and not isinstance(fixed_first_stage, dict):
        raise ValueError("fixed_first_stage: expected a mapping of decision names to values")
    if any(not isinstance(key, str) for key in (fixed_first_stage or {})):
        raise ValueError("fixed_first_stage keys must be decision-name strings")
    if require_complete_first_stage:
        supplied = set(fixed_first_stage or {})
        missing, extra = set(result.shared) - supplied, supplied - set(result.shared)
        if missing or extra:
            raise ValueError(f"Evaluation schedule must be complete; missing={sorted(missing)}, unknown={sorted(extra)}")
    for name, value in (fixed_first_stage or {}).items():
        if name not in result.shared:
            raise ValueError(f"Unknown first-stage decision: {name}")
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ValueError(f"Nonfinite fixed first-stage value: {name}")
        if result.shared[name].cat == pl.LpInteger and abs(value - round(value)) > 1e-7:
            raise ValueError(f"fixed_first_stage.{name}: binary decision must be integral")
        result.problem += result.shared[name] == value, f"fixed_{name}"
    risk = config.get("risk", {})
    weight, alpha = risk.get("weight", 0), risk.get("alpha", 0.95)
    if weight:
        eta = pl.LpVariable("cvar_eta", lowBound=None)
        excess = {}
        for index, (sid, block) in enumerate(result.blocks.items()):
            excess[sid] = pl.LpVariable(f"cvar_excess_{index}", 0)
            result.problem += excess[sid] >= result.costs[sid] - eta
        cvar = eta + pl.lpSum(b["scenario"]["probability"] * excess[sid] for sid, b in result.blocks.items()) / (1 - alpha)
        expected += weight * cvar
    result.problem += expected
    result.build_seconds = perf_counter() - started
    return result


def empirical_cvar(costs, alpha):
    """Exact upper-tail average for a finite distribution, including partial atoms."""
    if not 0 < number(alpha, "CVaR alpha") < 1:
        raise ValueError("CVaR alpha must lie strictly between 0 and 1")
    costs = list(costs)
    for value, probability in costs:
        number(value, "CVaR cost", minimum=None)
        number(probability, "CVaR probability")
    if not costs or not math.isclose(math.fsum(p for _, p in costs), 1, rel_tol=0, abs_tol=1e-9):
        raise ValueError("CVaR probabilities must sum to 1")
    remaining, total = 1 - alpha, 0.0
    for value, probability in sorted(costs, reverse=True):
        take = min(remaining, probability)
        total += take * value
        remaining -= take
        if remaining <= 0:
            break
    return total / (1 - alpha)


def audit_model(model, tolerance=1e-5):
    number(tolerance, "audit tolerance")
    violations = []
    max_residual = 0.0
    # Πρώτα ελέγχουμε τις τιμές: NaN/None δεν πρέπει να θεωρηθούν εφικτή λύση.
    for var in model.problem.variables():
        value = var.varValue
        if value is None or not math.isfinite(value):
            violations.append({"variable": var.name, "violation": "missing or nonfinite value"})
            continue
        if ((var.lowBound is not None and value < var.lowBound - tolerance)
                or (var.upBound is not None and value > var.upBound + tolerance)
                or (var.cat == pl.LpInteger and abs(value - round(value)) > tolerance)):
            violations.append({"variable": var.name, "violation": "bound/integrality"})
    for name, constraint in model.problem.constraints.items():
        residual = constraint.value()
        if residual is None or not math.isfinite(residual):
            violations.append({"constraint": name, "violation": "missing or nonfinite residual"})
            continue
        amount = abs(residual) if constraint.sense == 0 else max(0, -constraint.sense * residual)
        max_residual = max(max_residual, amount)
        if amount > tolerance:
            violations.append({"constraint": name, "violation": amount})
    objective = pl.value(model.problem.objective)
    if objective is None or not math.isfinite(objective):
        violations.append({"objective": "missing or nonfinite value"})
    return {"passed": not violations, "max_constraint_residual": max_residual,
            "absolute_tolerance": tolerance,
            "checked_constraints": len(model.problem.constraints), "violations": violations}


def solve(data, solver="highs", time_limit=None, fixed_first_stage=None, msg=False,
          *, require_complete_first_stage=False, accept_incumbent=False):
    """Build and solve the extensive form; return a validated, structured report.

    accept_incumbent=True reports a time-limited feasible MIP solution with
    status "Feasible" (never used for VSS/EVPI benchmarks, which need optima).
    """
    backend = {"highs": pl.HiGHS, "cbc": pl.PULP_CBC_CMD}.get(solver)
    if backend is None:
        raise ValueError("Solver must be highs or cbc")
    if time_limit is not None and number(time_limit, "time_limit") <= 0:
        raise ValueError("time_limit must be positive")
    model = build_model(data, fixed_first_stage, require_complete_first_stage=require_complete_first_stage)
    engine = backend(msg=msg, timeLimit=time_limit, gapRel=0, threads=1)
    if not engine.available():
        raise OptimizationError(f"Solver {solver!r} is not available in this environment",
                                status="SolverUnavailable", solver=solver)
    if solver == "highs":
        _reset_highs_scheduler()
    started = perf_counter()
    try:
        model.problem.solve(engine)
    except pl.PulpSolverError as exc:
        raise OptimizationError(f"Solver {solver!r} failed: {exc}",
                                status="SolverError", solver=solver) from exc
    elapsed = perf_counter() - started
    # PuLP/CBC/HiGHS label a time-limited incumbent Optimal with sol_status=2.
    incumbent = (accept_incumbent and model.problem.status == pl.LpStatusOptimal
                 and model.problem.sol_status == pl.LpSolutionIntegerFeasible)
    if not incumbent and (model.problem.status != pl.LpStatusOptimal
                          or model.problem.sol_status != pl.LpSolutionOptimal):
        status = pl.LpStatus[model.problem.status]
        infeasible = model.problem.status == pl.LpStatusInfeasible
        details = {"solution_status": model.problem.sol_status,
                   "solve_seconds": elapsed, "time_limit_seconds": time_limit}
        if infeasible and fixed_first_stage:
            details["diagnosis"] = _diagnose_fixed(data, solver, time_limit)
        error = InfeasibleModelError if infeasible else OptimizationError
        raise error(f"Optimal solution required; status={status}, solution_status={model.problem.sol_status}",
                    status=status, solver=solver, details=details)
    audit = audit_model(model)
    if not audit["passed"]:
        raise OptimizationError(f"Solved model failed residual validation: {audit['violations'][:3]}",
                                status="InvalidSolution", solver=solver, details=audit)
    common = {name: pl.value(var) for name, var in model.shared.items()}
    outputs = {}
    expected_metrics = {"unserved_mwh": 0.0, "curtailed_res_mwh": 0.0, "reserve_shortfall_mw_hours": 0.0}
    for sid, b in model.blocks.items():
        values = {name: pl.value(var) for name, var in b["variables"].items() if not name.startswith("scenario_")}
        scenario = b["scenario"]
        n = len(scenario["load_mw"])
        metrics = {
            "unserved_mwh": sum(values.get(f"s_load_minus_{t}", 0) for t in range(1, n+1)),
            "curtailed_res_mwh": sum(max(0, p - values[f"power_{int(gid)+1}_{t}"]) for gid, series in scenario["renewables_mw"].items() for t, p in enumerate(series, 1)),
            "reserve_shortfall_mw_hours": sum(v for name, v in values.items() if name.startswith(tuple(f"s_{p}_APR_" for p in PRODUCTS))),
        }
        objective_s = b["legacy_objective"] + b["additions"]
        penalties = sum(coef * pl.value(var) for var, coef in objective_s.items()
                        if is_slack(var.name.split("__", 1)[-1]))
        incentives = b["legacy_objective"].constant
        for var, coef in b["legacy_objective"].items():
            name = var.name.split("__", 1)[-1]
            if name.startswith("setpoint") or (name.startswith("power_") and coef < 0):
                incentives += coef * pl.value(var)
        slack_report = [{"variable": name, "value": pl.value(var), "upper_bound": var.upBound,
                         "stage": "first" if name.startswith(FIRST_STAGE_SLACK_PREFIXES) else "recourse",
                         "penalty_coefficient": objective_s.get(var, 0),
                         "penalty_eur": objective_s.get(var, 0) * pl.value(var)}
                        for name, var in b["variables"].items()
                        if is_slack(name) and pl.value(var) > 1e-7]
        total = pl.value(model.costs[sid])
        outputs[sid] = {"probability": scenario["probability"], "total_cost_eur": total,
                        "penalty_cost_eur": penalties, "operating_cost_eur": total - penalties - incentives,
                        "renewable_priority_cost_eur": incentives,
                        "nonzero_slacks": slack_report, "metrics": metrics, "variables": values}
        if data["stochastic"].get("storage"):
            outputs[sid]["storage"] = storage_report(data["stochastic"]["storage"], values, common, n)
        if "tree_path" in scenario:
            outputs[sid]["tree_path"] = list(scenario["tree_path"])
        for key in expected_metrics:
            expected_metrics[key] += scenario["probability"] * metrics[key]
    distribution = [(o["total_cost_eur"], o["probability"]) for o in outputs.values()]
    first_cost = pl.value(model.first_cost)
    expected_cost = math.fsum(c*p for c, p in distribution)
    cvar = empirical_cvar(distribution, data["stochastic"].get("risk", {}).get("alpha", 0.95))
    objective = pl.value(model.problem.objective)
    reconstructed = expected_cost + data["stochastic"].get("risk", {}).get("weight", 0) * cvar
    if not math.isclose(objective, reconstructed, abs_tol=1e-4, rel_tol=1e-7):
        raise OptimizationError("Objective does not reconcile with independently reconstructed expected cost/CVaR",
                                status="InvalidObjective", solver=solver,
                                details={"solver_objective": objective, "reconstructed": reconstructed})
    audit["objective_reconciliation_residual_eur"] = abs(objective - reconstructed)
    degraded = any(output["nonzero_slacks"] for output in outputs.values())
    tree = tree_report(data["stochastic"], len(data["Load_forecast"]) - 1)
    if tree is None:
        notes = [{"code": "FULL_PATH_RECOURSE", "message": "Dispatch uses the complete scenario path; this is a two-stage model."}]
    else:
        tree["nonanticipativity_constraints"] = model.tree_constraints
        notes = [{"code": "MULTISTAGE_SCENARIO_TREE",
                  "message": "Recourse decisions are identical for scenarios sharing a tree node; within a stage the "
                             "stage's data are revealed at its first hour. Commitment and reserve capacity remain first-stage."}]
    excluded = [s["id"] for s in data["stochastic"]["scenarios"] if s["probability"] == 0]
    if excluded:
        notes.append({"code": "EXCLUDED_ZERO_PROBABILITY", "scenario_ids": excluded,
                      "message": "Zero-probability paths are validated but impose no constraints; evaluate them "
                                 "separately with the common schedule fixed for a stress test."})
    if incumbent:
        notes.append({"code": "INCUMBENT_NOT_PROVEN_OPTIMAL",
                      "message": "Time-limited feasible solution; optimality gap not closed. Not valid for VSS/EVPI."})
    if data["stochastic"]["slack_policy"]["mode"] == "legacy":
        notes.append({"code": "LEGACY_REGRESSION_POLICY", "message": "Original slack domains and known modeling limitations are preserved for regression; this policy is not operational certification."})
    if degraded:
        notes.append({"code": "NONZERO_SLACKS", "message": "The optimum uses permitted constraint relaxations; inspect scenario nonzero_slacks and reliability metrics."})
    return {"schema_version": "1.2", "status": "Feasible" if incumbent else "Optimal", "objective_eur": objective,
            "operational_status": "degraded" if degraded else "no_reported_violations",
            "model_notes": notes, "run_metadata": run_metadata(data, solver, time_limit, fixed_first_stage),
            "expected_cost_eur": expected_cost, "first_stage_cost_eur": first_cost,
            "first_stage_breakdown": first_stage_breakdown(model, data, common),
            "implementable_dispatch": implementable_dispatch(model, data),
            "expected_recourse_cost_eur": expected_cost - first_cost,
            "cvar_eur": cvar,
            "common_schedule": common, "scenario_dispatch": outputs, "expected_metrics": expected_metrics,
            "scenario_tree": tree,
            "validation": audit, "build_seconds": model.build_seconds, "solve_seconds": elapsed,
            "num_variables": model.problem.numVariables(), "num_constraints": model.problem.numConstraints(),
            "policy": deepcopy(data["stochastic"]),
            "interpretation": ("Common schedule is pre-revelation; scenario dispatch is conditional on "
                               + ("the information available at each tree node." if tree else "the full path.")
                               + " Expected metrics are not dispatch instructions.")}


def _reset_highs_scheduler():
    """HiGHS keeps a process-wide thread scheduler. If an earlier solve in the
    same process used another thread count, threads=1 makes every later run end
    "Not Solved". Resetting it keeps API/notebook use reproducible."""
    try:
        import highspy
        highspy.Highs.resetGlobalScheduler(True)
    except (ImportError, AttributeError):
        pass


def _diagnose_fixed(data, solver, time_limit):
    """Tell whether infeasibility comes from the fixed first-stage decisions."""
    try:
        solve(data, solver=solver, time_limit=time_limit)
    except OptimizationError as exc:
        return {"feasible_without_fixed_decisions": False, "status_without_fixed": exc.status}
    return {"feasible_without_fixed_decisions": True,
            "message": "The fixed first-stage decisions conflict with this input (e.g. observed state, timers or scenarios)."}


def first_stage_breakdown(model, data, common):
    """Separate the online charge and BESS reserve cost inside the first-stage cost."""
    policy = data["stochastic"].get("cost_policy", {})
    per_hour = policy.get("legacy_time_scaled_costs", "legacy") == "per_hour"
    charge = policy.get("thermal_online_charge_eur_per_h", 100 if per_hour else 100 * 60)
    online = 0.0
    for block in model.blocks.values():
        context = block["context"]
        online = math.fsum(charge * common.get(f"state_{i+1}_{t}", 0)
                           for i in context["CONV"] for t in context["intervals"][1:])
        break
    storage = 0.0
    for j, store in enumerate(data["stochastic"].get("storage", [])):
        prices = store.get("reserve", {}).get("capacity_cost_eur_per_mw_h", {})
        storage += math.fsum(prices.get(name.split("_")[3], 0) * value for name, value in common.items()
                             if name.startswith("storage_reserve_") and name.split("_")[4] == str(j))
    return {"thermal_online_charge_eur": online, "thermal_online_charge_eur_per_h": charge,
            "online_charge_source": "cost_policy" if ("thermal_online_charge_eur_per_h" in policy or per_hour)
            else "legacy_100_times_time_granularity",
            "storage_reserve_capacity_eur": storage}


def implementable_dispatch(model, data):
    """Root-node recourse decisions: identical in every scenario, hence issuable.

    Exists only with a scenario tree; under full-path two-stage recourse no
    scenario-independent dispatch exists (see FULL_PATH_RECOURSE).
    """
    config = data["stochastic"]
    if "scenario_tree" not in config:
        return None
    hours = set(stage_hours(config, len(data["Load_forecast"]) - 1)[0])
    first = next(iter(model.blocks.values()))
    decisions = {}
    for name, var in first["variables"].items():
        match = TREE_RECOURSE.fullmatch(name)
        if match and int(match.group(2)) in hours and not name.startswith(("s_load", "s_power")):
            decisions[name] = pl.value(var)
    return {"hours": sorted(hours), "decisions": decisions,
            "interpretation": "Root-node dispatch, BESS charge/discharge/SOC and activations; identical across scenarios."}


def tree_report(config, n):
    """Stages, nodes and node probabilities of an optional scenario tree."""
    if "scenario_tree" not in config:
        return None
    probability = {s["id"]: s["probability"] for s in config["scenarios"]}
    hours = stage_hours(config, n)
    stages = []
    for stage, groups in tree_nodes(config).items():
        stages.append({"stage": stage + 1, "hours": hours[stage],
                       "nodes": [{"path": list(key), "probability": math.fsum(probability[s] for s in members),
                                  "scenarios": members} for key, members in groups.items()]})
    return {"stages": stages}


def storage_report(stores, values, common, n):
    """Per-store SOC trajectory, flows, cycles and committed reserve (MW, MWh)."""
    report = {}
    for j, b in enumerate(stores):
        charge = [values[f"storage_charge_{j}_{t}"] for t in range(1, n + 1)]
        discharge = [values[f"storage_discharge_{j}_{t}"] for t in range(1, n + 1)]
        energy = [b["initial_mwh"]] + [values[f"storage_energy_{j}_{t}"] for t in range(1, n + 1)]
        usable = b["capacity_mwh"] - b["min_mwh"]
        reserve = {}
        for product, directions in b.get("reserve", {}).get("products", {}).items():
            for direction in directions:
                reserve[f"{product}_{direction}_mw"] = [
                    common[f"storage_reserve_{product}_{direction}_{j}_{t}"] for t in range(1, n + 1)]
        report[b["id"]] = {
            "energy_mwh": energy, "charge_mw": charge, "discharge_mw": discharge,
            "net_injection_mw": [d - c for c, d in zip(charge, discharge)],
            "terminal_energy_mwh": energy[-1],
            "equivalent_full_cycles": (math.fsum(d / b["discharge_efficiency"] for d in discharge) / usable
                                       if usable > 0 else None),
            "throughput_cost_eur": b["throughput_eur_per_mwh"] * math.fsum(charge + discharge),
            "terminal_value_eur": b.get("terminal_value_eur_per_mwh", 0) * energy[-1],
            "committed_reserve": reserve,
        }
    return report
