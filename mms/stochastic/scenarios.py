"""Scenario generation is independent of optimization; no marginal quantile shortcut."""

from copy import deepcopy
import random

from .data import renewable_ids


def nominal(base, scenario_id="nominal"):
    return {"id": scenario_id, "probability": 1.0, "load_mw": list(base["Load_forecast"][1:]),
            "renewables_mw": {gid: list(base["Generating_Units"][int(gid)]["Production_Forecast"])
                              for gid in renewable_ids(base)}}


def synthetic(base, count=3, seed=42):
    """Seeded joint AR(1) paths for demonstration, not a calibrated forecast model.

    One shared weather innovation couples load/wind/PV. AR(1) memory gives
    temporal dependence; complete equally weighted Monte Carlo paths define
    an empirical distribution. This does not interpret P10/P50/P90 as scenarios.
    """
    if not isinstance(count, int) or isinstance(count, bool) or count < 1:
        raise ValueError("count must be a positive integer")
    rng = random.Random(seed)
    scenarios = []
    for s in range(count):
        item = nominal(base, f"seed{seed}_path{s}")
        item["probability"] = 1 / count
        weather = rng.gauss(0, 1)
        for t in range(len(item["load_mw"])):
            weather = 0.85 * weather + (1 - 0.85**2)**0.5 * rng.gauss(0, 1)
            item["load_mw"][t] = max(0, item["load_mw"][t] * (1 + 0.03 * weather))
            for gid, values in item["renewables_mw"].items():
                g = base["Generating_Units"][int(gid)]
                nominal_power = min(g["Production_Forecast"][t], g["availability"][t])
                # Το ίδιο καιρικό σήμα δίνει αρνητική συσχέτιση φορτίου-ΑΠΕ.
                values[t] = min(g["availability"][t], max(0, nominal_power * (1 - 0.12 * weather)))
        scenarios.append(item)
    return scenarios


def synthetic_tree(base, stage_start_hours, branching, seed=42, rho=0.85):
    """Seeded joint AR(1) scenario tree for demonstration (not calibrated).

    Stage k covers hours stage_start_hours[k] .. next start - 1 and every node
    of stage k-1 has branching[k] children (branching[0] = 1 gives a single,
    shared first-stage node). A child inherits its parent's history and AR(1)
    weather state, then draws fresh innovations for its own hours, so siblings
    share all data up to the branching hour. Leaves are equally likely.
    """
    n = len(base["Load_forecast"]) - 1
    starts = list(stage_start_hours)
    if (not starts or starts[0] != 1 or any(b <= a for a, b in zip(starts, starts[1:]))
            or starts[-1] > n or len(branching) != len(starts)):
        raise ValueError("stage_start_hours must start at 1, increase within the horizon and match branching")
    if any(isinstance(b, bool) or not isinstance(b, int) or b < 1 for b in branching):
        raise ValueError("branching factors must be positive integers")
    bounds = starts + [n + 1]
    rng = random.Random(seed)
    template = nominal(base)
    nodes = [{"path": [], "weather": rng.gauss(0, 1), "load_mw": [], "renewables_mw": {g: [] for g in template["renewables_mw"]}}]
    for k, children in enumerate(branching):
        grown = []
        for parent in nodes:
            for c in range(children):
                child = deepcopy(parent)
                child["path"].append("root" if children == 1 and k == 0 else f"s{k + 1}b{c}")
                for t in range(bounds[k] - 1, bounds[k + 1] - 1):
                    child["weather"] = rho * child["weather"] + (1 - rho**2)**0.5 * rng.gauss(0, 1)
                    child["load_mw"].append(max(0, template["load_mw"][t] * (1 + 0.03 * child["weather"])))
                    for gid in child["renewables_mw"]:
                        g = base["Generating_Units"][int(gid)]
                        nominal_power = min(g["Production_Forecast"][t], g["availability"][t])
                        # Ίδιο καιρικό σήμα: αρνητική συσχέτιση φορτίου-ΑΠΕ, όπως στο synthetic().
                        child["renewables_mw"][gid].append(
                            min(g["availability"][t], max(0, nominal_power * (1 - 0.12 * child["weather"]))))
                grown.append(child)
        nodes = grown
    return [{"id": "tree_" + "_".join(node["path"]), "probability": 1 / len(nodes),
             "tree_path": node["path"], "load_mw": node["load_mw"], "renewables_mw": node["renewables_mw"]}
            for node in nodes]


def expected_value_scenario(scenarios):
    positive = [s for s in scenarios if s["probability"] > 0]
    result = deepcopy(positive[0])
    result["id"], result["probability"] = "expected_value", 1.0
    result["load_mw"] = [sum(s["probability"] * s["load_mw"][t] for s in positive)
                         for t in range(len(result["load_mw"]))]
    for gid, values in result["renewables_mw"].items():
        result["renewables_mw"][gid] = [sum(s["probability"] * s["renewables_mw"][gid][t] for s in positive)
                                       for t in range(len(values))]
    return result
