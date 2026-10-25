"""Thin adapter between the GUI and the existing optimization programs.

Nothing here changes the optimization model. The adapter

* discovers and loads case JSON files,
* describes units, scenarios and storage as pandas tables,
* validates inputs with the engine's own validators (plus friendly GUI checks),
* builds the deterministic 15-min DS input from an hourly RDAS case,
* launches a solve in a separate process (``gui/runner.py``) and polls it,
* parses the result JSON of either engine into one set of pandas tables.

Engines wrapped:

* **RDAS** - ``mms.stochastic.model.solve`` / ``mms.stochastic.evaluation.compare``
  (hourly, two-stage or multistage stochastic MILP, extensive form).
* **DS** - the deterministic legacy MMS program ``main.py`` at 15-min resolution
  (the stochastic extension validates ``Time_granularity == 60`` only).
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from input_validation import validate_input_data  # noqa: E402
from mms.stochastic import data as sdata  # noqa: E402
from mms.stochastic.artifacts import write_json  # noqa: E402
from mms.stochastic.scenarios import expected_value_scenario, nominal, synthetic, synthetic_tree  # noqa: E402

RUNS_ROOT = ROOT / "runs" / "gui"
CASES_DIR = ROOT / "cases"
CONFIGS_DIR = ROOT / "configs"
CASE_SEARCH = [ROOT / "examples", CASES_DIR, ROOT]
PRODUCTS = ("primary", "secondary", "tertiary")
DIRECTIONS = ("up", "down")
EPS = 1e-6
DS_MINUTES = 15
EXPECTED_ID = "Expected value"
ALL_ID = "All scenarios"

BIOMASS_WORDS = ("BIOMASS", "BIOMAZA", "CHP", "ΒΙΟΜΑΖ", "ΣΗΘΥΑ")


# =============================================================== case discovery & IO
def discover_cases() -> list[Path]:
    """JSON files that look like MMS inputs (have ``Generating_Units``)."""
    found: list[Path] = []
    for folder in CASE_SEARCH:
        if not folder.exists():
            continue
        for path in sorted(folder.glob("*.json")):
            if path in found or path.name.startswith(("optimization_output", ".")):
                continue
            try:
                with path.open(encoding="utf-8-sig") as stream:
                    head = stream.read(4000)
            except OSError:
                continue
            if '"Generating_Units"' in head or '"Cost_parameters"' in head:
                found.append(path)
    return found


def case_label(path: Path) -> str:
    """Short display name of a case file, relative to the project root."""
    try:
        return str(path.resolve().relative_to(ROOT)).replace("\\", "/")
    except ValueError:
        return path.name


def read_json(path: Path | str) -> Any:
    with Path(path).open(encoding="utf-8-sig") as stream:
        return json.load(stream)


def prepare_case(raw: dict) -> tuple[dict, list[str]]:
    """Return a stochastic-ready copy of ``raw`` plus notes on what was added.

    A plain deterministic MMS input gets the nominal forecast as its single
    scenario and the regression ('legacy') slack policy - exactly how
    ``examples/original_single_scenario.json`` was built.
    """
    data = deepcopy(raw)
    notes: list[str] = []
    if "stochastic" not in data:
        data["stochastic"] = {"scenarios": [nominal(data)], "slack_policy": {"mode": "legacy"},
                              "reserve_link": False, "risk": {"alpha": 0.95, "weight": 0}}
        notes.append("The file has no `stochastic` section: the nominal forecast was added as a single "
                     "scenario (probability 1) with the legacy slack policy. Generate more scenarios "
                     "under Inputs → Scenarios.")
    return data, notes


def save_case(data: dict, name: str, overwrite: bool = False) -> Path:
    """Write a case JSON into ``cases/``; refuses to overwrite unless asked."""
    slug = re.sub(r"[^A-Za-z0-9_.-]+", "_", name.strip()).strip("_") or "case"
    if not slug.endswith(".json"):
        slug += ".json"
    path = CASES_DIR / slug
    if path.exists() and not overwrite:
        raise FileExistsError(f"{case_label(path)} already exists; choose another name.")
    write_json(path, data)
    return path


# =============================================================== small helpers
def horizon(data: dict) -> int:
    """Number of decision periods (index 0 of Load_forecast is history)."""
    return len(data["Load_forecast"]) - 1


def resolution_minutes(data: dict) -> int:
    return int(data.get("Time_granularity", 60))


def period_label(t: int, minutes: int) -> str:
    """Human label of decision period t (1-based)."""
    if minutes == 60:
        return f"h{t:02d}"
    end = t * minutes
    return f"{t:02d} · +{end // 60:d}:{end % 60:02d}"


def axis_title(minutes: int) -> str:
    return "Hour (h)" if minutes == 60 else f"Interval ({minutes} min)"


def at(value: Any, t: int) -> float:
    """Value of a scalar-or-hourly-list field at decision period t (1-based)."""
    if isinstance(value, list):
        return float(value[t - 1]) if t - 1 < len(value) else float(value[-1])
    return float(value or 0)


def get_path(obj: Any, path: str, default: Any = None) -> Any:
    """Read a dotted path like ``stochastic.risk.alpha``."""
    for part in path.split("."):
        if isinstance(obj, dict) and part in obj:
            obj = obj[part]
        else:
            return default
    return obj


def set_path(obj: dict, path: str, value: Any) -> None:
    """Set a dotted path; ``value is None`` removes an optional key."""
    parts = path.split(".")
    for part in parts[:-1]:
        obj = obj.setdefault(part, {})
    if value is None:
        obj.pop(parts[-1], None)
    else:
        obj[parts[-1]] = value


def flatten(obj: Any, prefix: str = "") -> dict[str, Any]:
    """Flatten nested JSON into {path: scalar} for diffs."""
    out: dict[str, Any] = {}
    if isinstance(obj, dict):
        for key, value in obj.items():
            out.update(flatten(value, f"{prefix}.{key}" if prefix else str(key)))
    elif isinstance(obj, list):
        for i, value in enumerate(obj):
            out.update(flatten(value, f"{prefix}[{i}]"))
    else:
        out[prefix] = obj
    return out


def diff(base: dict, work: dict) -> pd.DataFrame:
    """Changed / added / removed leaves between two JSON documents."""
    a, b = flatten(base), flatten(work)
    rows = []
    for key in sorted(set(a) | set(b)):
        old, new = a.get(key, "∅ (absent)"), b.get(key, "∅ (absent)")
        if old != new and not (isinstance(old, (int, float)) and isinstance(new, (int, float))
                               and not isinstance(old, bool) and math.isclose(old, new, abs_tol=1e-12)):
            rows.append({"path": humanize_path(key), "raw path": key, "file value": old, "current value": new})
    return pd.DataFrame(rows, columns=["path", "raw path", "file value", "current value"])


# =============================================================== units & metadata
def _short_name(comment: str) -> str:
    text = comment.split(":", 1)[1] if ":" in comment else comment
    text = re.sub(r"\s+", " ", text).strip(" -")
    return text[:26] if text else comment[:26]


def unit_type(unit: dict, hybrid_ids: set[int]) -> str:
    """Display type, consistent with the legacy classification by comment prefix."""
    comment = unit.get("comments", "")
    upper = comment.upper()
    if comment.startswith("Therm"):
        return "biomass" if any(w in upper for w in BIOMASS_WORDS) else "thermal"
    if "Partially Controllable" in comment:
        return "biomass" if any(w in upper for w in BIOMASS_WORDS) else "partial"
    if int(unit["gen_id"]) in hybrid_ids:
        return "hybrid"
    if comment.startswith("PV"):
        return "pv"
    return "wind"


def is_conventional(unit: dict) -> bool:
    return unit.get("comments", "").startswith("Therm")


def is_renewable(unit: dict) -> bool:
    comment = unit.get("comments", "")
    return not comment.startswith("Therm") and "Partially Controllable" not in comment


@dataclass
class UnitInfo:
    """Display metadata of one generating unit or storage."""
    index: int
    gen_id: int | str
    label: str
    type: str
    color: str
    name: str
    is_storage: bool = False


def unit_infos(data: dict) -> list[UnitInfo]:
    """Units (and storages) with stable labels and colours for every chart."""
    from gui import theme

    stores = data.get("stochastic", {}).get("storage", [])
    hybrid = {int(s["renewable_gen_id"]) for s in stores if "renewable_gen_id" in s}
    counters: dict[str, int] = {}
    infos: list[UnitInfo] = []
    for i, unit in enumerate(data["Generating_Units"]):
        kind = unit_type(unit, hybrid)
        k = counters.get(kind, 0)
        counters[kind] = k + 1
        infos.append(UnitInfo(i, unit["gen_id"], f"G{unit['gen_id']} {_short_name(unit['comments'])}",
                              kind, theme.type_shade(kind, k), unit["comments"]))
    for j, store in enumerate(stores):
        k = counters.get("storage", 0) + 1     # step away from the hybrid base hue
        counters["storage"] = k
        infos.append(UnitInfo(len(infos), store["id"], f"BESS {store['id']}", "storage",
                              theme.type_shade("storage", k), store["id"], is_storage=True))
    return infos


def color_map(data: dict) -> dict[str, str]:
    return {u.label: u.color for u in unit_infos(data)}


def operating_state_label(state: dict) -> str:
    if state.get("isShutdown"):
        return f"{state['id']} · shutdown"
    role = state.get("state_role") or ("transient" if state.get("isTransient") else None)
    if state.get("isOperational"):
        return f"{state['id']} · operational"
    return f"{state['id']} · {role or 'non-operational'}"


def state_class(state: dict | None) -> str:
    if state is None:
        return "Off"
    if state.get("isShutdown"):
        return "Off" if state["id"] == 0 else "Shutdown state"
    if state.get("isOperational"):
        return "Operational"
    return "Transient"


# ---------------------------------------------------------------- unit tables
UNIT_COLUMNS = {
    "max_power(MW)": "Max power (MW)",
    "min_power(MW)": "Min power (MW)",
    "ramp_up_rate(kW/min)": "Ramp up (kW/min)",
    "ramp_down_rate(kW/min)": "Ramp down (kW/min)",
    "start_up_cost(euro)": "Start-up cost (€)",
    "shut_down_cost(euro)": "Shut-down cost (€)",
    "Accepts_SP": "Accepts set-point",
}


def units_frame(data: dict) -> pd.DataFrame:
    """Editable scalar unit parameters, one row per unit."""
    infos = unit_infos(data)
    rows = []
    for unit, info in zip(data["Generating_Units"], infos):
        agc = unit.get("agc_configuration", {})
        row = {"gen_id": unit["gen_id"], "Unit": info.label, "Type": info.type,
               "Comment": unit.get("comments", "")}
        for key, label in UNIT_COLUMNS.items():
            row[label] = unit.get(key)
        row["Accepts set-point"] = bool(unit.get("Accepts_SP", 0))
        row["AGC connected"] = bool(agc.get("isConnected", 0))
        row["Var. cost curve"] = _cost_curve_text(unit)
        rows.append(row)
    return pd.DataFrame(rows)


def _cost_curve_text(unit: dict) -> str:
    curve = unit.get("var_gen_cost(euro/MW)")
    if not curve or len(curve) != 2:
        return ""
    return " | ".join(f"{p:g} MW→{c:g}" for p, c in zip(curve[0], curve[1]))


def apply_units_frame(data: dict, frame: pd.DataFrame) -> None:
    """Write edited unit scalars back into ``data`` (in place)."""
    for _, row in frame.iterrows():
        unit = data["Generating_Units"][int(row["gen_id"])]
        for key, label in UNIT_COLUMNS.items():
            if key == "Accepts_SP":
                continue
            value = row[label]
            if value is not None and not (isinstance(value, float) and math.isnan(value)):
                unit[key] = _num(value)
        if "Accepts_SP" in unit or row["Accepts set-point"]:
            unit["Accepts_SP"] = int(bool(row["Accepts set-point"]))
        if "agc_configuration" in unit or row["AGC connected"]:
            unit.setdefault("agc_configuration", {})["isConnected"] = int(bool(row["AGC connected"]))


def _num(value: Any) -> int | float:
    value = float(value)
    return int(value) if value.is_integer() else value


SERIES_FIELDS = {
    "availability": "Availability (MW)",
    "Production_Forecast": "Production forecast (MW)",
    "mustRun": "Must-run (0/1)",
    "testing_mode_enabled": "Testing mode (0/1)",
    "power_production_in_testing_mode": "Testing power (MW)",
}


def unit_series_frame(data: dict, index: int) -> pd.DataFrame:
    """Hourly series of one unit (decision periods 1..H)."""
    unit = data["Generating_Units"][index]
    n = horizon(data)
    minutes = resolution_minutes(data)
    frame = pd.DataFrame({"t": range(1, n + 1), "Period": [period_label(t, minutes) for t in range(1, n + 1)]})
    for key, label in SERIES_FIELDS.items():
        if isinstance(unit.get(key), list) and len(unit[key]) == n:
            frame[label] = unit[key]
    return frame


def apply_unit_series(data: dict, index: int, frame: pd.DataFrame) -> None:
    unit = data["Generating_Units"][index]
    for key, label in SERIES_FIELDS.items():
        if label in frame:
            unit[key] = [_num(v) for v in frame[label].tolist()]


def operating_states_frame(data: dict, index: int) -> pd.DataFrame:
    unit = data["Generating_Units"][index]
    rows = []
    for s in unit["operating-states"]:
        rows.append({"id": s["id"], "State": operating_state_label(s),
                     "Min power (MW)": s.get("min-power"), "Max power (MW)": s.get("max-power"),
                     "Enabled cost (€/period)": s.get("enabled-cost", 0),
                     "Shutdown": bool(s.get("isShutdown")), "Operational": bool(s.get("isOperational")),
                     "Transient": bool(s.get("isTransient")), "Initial": bool(s.get("isEnabled"))})
    return pd.DataFrame(rows)


def apply_operating_states(data: dict, index: int, frame: pd.DataFrame) -> None:
    states = {s["id"]: s for s in data["Generating_Units"][index]["operating-states"]}
    for _, row in frame.iterrows():
        state = states[int(row["id"])]
        for key, label in (("min-power", "Min power (MW)"), ("max-power", "Max power (MW)"),
                           ("enabled-cost", "Enabled cost (€/period)")):
            value = row[label]
            if isinstance(state.get(key), list) or value is None or (isinstance(value, float) and math.isnan(value)):
                continue                                   # hourly lists / empty cells are left untouched
            if key in state or value:
                state[key] = _num(value)


def transitions_frame(data: dict, index: int) -> pd.DataFrame:
    """Allowed operating-state arcs with costs and minute-based timers."""
    unit = data["Generating_Units"][index]
    rows = []
    for arc in unit["operating-state-transitions"]:
        for target in arc["transitions"]:
            row = {"from": arc["from"], "to": target["id"], "Transition cost (€)": target.get("transition-cost", 0)}
            for key, value in target.items():
                if "transition-time" in key:
                    row[f"{key} (min)"] = value
            rows.append(row)
    return pd.DataFrame(rows)


# ---------------------------------------------------------------- initial conditions
def initial_conditions_frame(data: dict) -> pd.DataFrame:
    config = data.get("stochastic", {})
    rows = []
    for unit, info in zip(data["Generating_Units"], unit_infos(data)):
        active = next((s for s in unit["operating-states"] if s.get("isEnabled")), None)
        st_tr = {row["from"]: row["transitions"] for row in unit.get("state-transitions", [])}
        row = {"gen_id": unit["gen_id"], "Unit": info.label,
               "Initial operating state": operating_state_label(active) if active else "",
               "On (state)": bool(unit.get("state")),
               "Current power (MW)": unit.get("current_Power(MW)", 0),
               "Min ON time left (min)": st_tr.get(1, {}).get("min-transition-time-left"),
               "Min OFF time left (min)": st_tr.get(0, {}).get("min-transition-time-left"),
               "Max-ON elapsed (h)": config.get("maximum_on", {}).get(str(unit["gen_id"]), {}).get("elapsed_hours")}
        rows.append(row)
    return pd.DataFrame(rows)


def state_options(data: dict, index: int) -> list[str]:
    return [operating_state_label(s) for s in data["Generating_Units"][index]["operating-states"]]


def apply_initial_conditions(data: dict, frame: pd.DataFrame) -> None:
    """Initial state choice sets ``isEnabled`` flags and the binary ``state``."""
    for _, row in frame.iterrows():
        unit = data["Generating_Units"][int(row["gen_id"])]
        chosen = str(row["Initial operating state"]).split(" · ")[0]
        if chosen.isdigit():
            for s in unit["operating-states"]:
                s["isEnabled"] = s["id"] == int(chosen)
            active = next(s for s in unit["operating-states"] if s["isEnabled"])
            unit["state"] = 0 if active.get("isShutdown") else 1
        unit["current_Power(MW)"] = _num(row["Current power (MW)"])
        st_tr = {r["from"]: r["transitions"] for r in unit.get("state-transitions", [])}
        for src, label in ((1, "Min ON time left (min)"), (0, "Min OFF time left (min)")):
            value = row[label]
            if src in st_tr and value is not None and not (isinstance(value, float) and math.isnan(value)):
                st_tr[src]["min-transition-time-left"] = _num(value)
        elapsed = row["Max-ON elapsed (h)"]
        spec = data.get("stochastic", {}).get("maximum_on", {}).get(str(unit["gen_id"]))
        if spec is not None and elapsed is not None and not (isinstance(elapsed, float) and math.isnan(elapsed)):
            spec["elapsed_hours"] = int(elapsed)


# ---------------------------------------------------------------- storage
STORAGE_COLUMNS = {
    "capacity_mwh": "Capacity (MWh)", "min_mwh": "Min SOC (MWh)", "initial_mwh": "Initial SOC (MWh)",
    "terminal_min_mwh": "Terminal min SOC (MWh)", "charge_mw": "Charge max (MW)",
    "discharge_mw": "Discharge max (MW)", "charge_efficiency": "Charge efficiency (-)",
    "discharge_efficiency": "Discharge efficiency (-)", "self_discharge_per_hour": "Self-discharge (1/h)",
    "export_limit_mw": "POI export limit (MW)",
}


def storage_frame(data: dict) -> pd.DataFrame:
    rows = []
    for store in data.get("stochastic", {}).get("storage", []):
        row = {"id": store["id"], "Linked RES unit": store.get("renewable_gen_id"),
               "Grid charging": bool(store.get("grid_charge"))}
        for key, label in STORAGE_COLUMNS.items():
            row[label] = store.get(key)
        cap = store.get("capacity_mwh") or 0
        row["Initial SOC (%)"] = round(100 * store.get("initial_mwh", 0) / cap, 1) if cap else None
        rows.append(row)
    return pd.DataFrame(rows)


def apply_storage_frame(data: dict, frame: pd.DataFrame) -> None:
    stores = {s["id"]: s for s in data.get("stochastic", {}).get("storage", [])}
    for _, row in frame.iterrows():
        store = stores[row["id"]]
        store["grid_charge"] = bool(row["Grid charging"])
        for key, label in STORAGE_COLUMNS.items():
            value = row[label]
            if value is None or (isinstance(value, float) and math.isnan(value)):
                if key in ("self_discharge_per_hour", "export_limit_mw"):
                    store.pop(key, None)
                continue
            store[key] = _num(value)


# ---------------------------------------------------------------- scenarios
def scenarios_frame(data: dict) -> pd.DataFrame:
    config = data.get("stochastic", {})
    n = horizon(data)
    rows = []
    for s in config.get("scenarios", []):
        rows.append({"id": s["id"], "Probability": s["probability"],
                     "Tree path": " / ".join(s.get("tree_path", [])) if s.get("tree_path") else "",
                     "Energy (MWh)": round(sum(s["load_mw"]), 3),
                     "Peak load (MW)": round(max(s["load_mw"]) if s["load_mw"] else 0, 3),
                     "RES energy (MWh)": round(sum(sum(v) for v in s["renewables_mw"].values()), 3),
                     "Periods": n})
    return pd.DataFrame(rows)


def scenario_ids(data: dict, positive_only: bool = False) -> list[str]:
    return [s["id"] for s in data.get("stochastic", {}).get("scenarios", [])
            if not positive_only or s["probability"] > 0]


def scenario_series(data: dict) -> pd.DataFrame:
    """Long table of scenario forecasts: scenario, series, t, MW."""
    infos = {str(u.gen_id): u.label for u in unit_infos(data) if not u.is_storage}
    rows = []
    for s in data.get("stochastic", {}).get("scenarios", []):
        for t, value in enumerate(s["load_mw"], 1):
            rows.append({"scenario": s["id"], "probability": s["probability"], "series": "Load", "t": t, "mw": value})
        for gid, values in s["renewables_mw"].items():
            for t, value in enumerate(values, 1):
                rows.append({"scenario": s["id"], "probability": s["probability"],
                             "series": infos.get(gid, f"G{gid}"), "t": t, "mw": value})
    return pd.DataFrame(rows, columns=["scenario", "probability", "series", "t", "mw"])


def scenario_editor_frame(data: dict, sid: str) -> pd.DataFrame:
    s = next(x for x in data["stochastic"]["scenarios"] if x["id"] == sid)
    minutes = resolution_minutes(data)
    frame = pd.DataFrame({"t": range(1, len(s["load_mw"]) + 1),
                          "Period": [period_label(t, minutes) for t in range(1, len(s["load_mw"]) + 1)],
                          "Load (MW)": s["load_mw"]})
    infos = {str(u.gen_id): u.label for u in unit_infos(data) if not u.is_storage}
    for gid, values in s["renewables_mw"].items():
        frame[f"{infos.get(gid, 'G' + gid)} (MW)"] = values
    return frame


def apply_scenario_editor(data: dict, sid: str, frame: pd.DataFrame) -> None:
    s = next(x for x in data["stochastic"]["scenarios"] if x["id"] == sid)
    s["load_mw"] = [float(v) for v in frame["Load (MW)"]]
    infos = {str(u.gen_id): u.label for u in unit_infos(data) if not u.is_storage}
    for gid in s["renewables_mw"]:
        column = f"{infos.get(gid, 'G' + gid)} (MW)"
        if column in frame:
            s["renewables_mw"][gid] = [float(v) for v in frame[column]]


def apply_probabilities(data: dict, frame: pd.DataFrame) -> None:
    probabilities = dict(zip(frame["id"], frame["Probability"]))
    for s in data["stochastic"]["scenarios"]:
        s["probability"] = float(probabilities.get(s["id"], s["probability"]))


def normalize_probabilities(data: dict) -> None:
    """Explicit user action: rescale probabilities to sum to one."""
    total = math.fsum(s["probability"] for s in data["stochastic"]["scenarios"])
    if total <= 0:
        raise ValueError("Probabilities sum to zero; set at least one positive probability.")
    for s in data["stochastic"]["scenarios"]:
        s["probability"] = s["probability"] / total


def generate_scenarios(data: dict, count: int, seed: int, stage_starts: list[int] | None = None,
                       branching: list[int] | None = None) -> None:
    """Replace scenarios by seeded synthetic AR(1) paths (or a tree) around the nominal forecast."""
    base = deepcopy(data)
    base.pop("stochastic", None)
    config = data["stochastic"]
    if stage_starts:
        config["scenarios"] = synthetic_tree(base, stage_starts, branching or [1] * len(stage_starts), seed=seed)
        config["scenario_tree"] = {"stage_start_hours": list(stage_starts)}
    else:
        config["scenarios"] = synthetic(base, count=count, seed=seed)
        config.pop("scenario_tree", None)


def tree_layout(data: dict) -> dict | None:
    """Nodes and edges of the scenario tree for plotting (None without a tree)."""
    config = data.get("stochastic", {})
    if "scenario_tree" not in config:
        return None
    nodes = sdata.tree_nodes(config)
    starts = config["scenario_tree"]["stage_start_hours"]
    prob = {s["id"]: s["probability"] for s in config["scenarios"]}
    points, edges = {}, []
    leaves = sorted(nodes[len(starts) - 1].keys())
    for stage in range(len(starts) - 1, -1, -1):
        for key, members in nodes[stage].items():
            if stage == len(starts) - 1:
                y = leaves.index(key)
            else:
                children = [points[c]["y"] for c in points if len(c) == stage + 2 and c[:stage + 1] == key]
                y = sum(children) / len(children) if children else 0
            points[key] = {"x": starts[stage], "y": y, "label": key[-1],
                           "p": math.fsum(prob[m] for m in members), "members": members}
            if stage > 0:
                edges.append((key[:-1], key))
    return {"points": points, "edges": edges, "starts": starts}


# =============================================================== validation
@dataclass
class Issue:
    severity: str          # "error" | "warning"
    location: str
    message: str


_PATH_PATTERNS = [
    (re.compile(r"Generating_Units\[(\d+)\]"), "unit"),
    (re.compile(r"stochastic\.scenarios\[(\d+)\]"), "scenario"),
    (re.compile(r"stochastic\.storage\[(\d+)\]"), "storage"),
]


def humanize_path(path: str, data: dict | None = None) -> str:
    """'Generating_Units[2].ramp_up_rate(kW/min)' -> 'Unit G2 · ramp_up_rate(kW/min)'."""
    text = path
    for pattern, kind in _PATH_PATTERNS:
        match = pattern.search(text)
        if not match:
            continue
        i = int(match.group(1))
        name = f"#{i}"
        if data is not None:
            try:
                if kind == "unit":
                    name = unit_infos(data)[i].label
                elif kind == "scenario":
                    name = f"'{data['stochastic']['scenarios'][i]['id']}'"
                else:
                    name = f"'{data['stochastic']['storage'][i]['id']}'"
            except (IndexError, KeyError):
                pass
        title = {"unit": "Unit", "scenario": "Scenario", "storage": "Storage"}[kind]
        text = pattern.sub(f"{title} {name} ›", text, count=1)
    text = text.replace("stochastic.", "Stochastic › ").replace("›.", "› ").replace("› .", "› ")
    return text.strip().rstrip("›").strip()


def _split_message(message: str, data: dict) -> tuple[str, str]:
    """Engine messages are 'path: text'; split into a readable location and text."""
    if ": " in message:
        path, text = message.split(": ", 1)
        if " " not in path.strip() or path.startswith(("Generating_Units", "stochastic", "constraints")):
            return humanize_path(path, data), text
    # Legacy messages embed the path in the sentence: point at the unit / scenario it names.
    match = re.search(r"(Generating_Units\[\d+\]|stochastic\.(?:scenarios|storage)\[\d+\])(\.[\w()/%-]+)?", message)
    if match:
        unit = humanize_path(match.group(1), data)
        return humanize_path(match.group(0), data), message.replace(match.group(1), unit)
    return "Input", message


def gui_checks(data: dict) -> list[Issue]:
    """Friendly cross-field checks that report *all* problems at once."""
    issues: list[Issue] = []
    n = horizon(data)
    infos = unit_infos(data)
    for unit, info in zip(data["Generating_Units"], infos):
        where = f"Unit {info.label}"
        pmax, pmin = unit.get("max_power(MW)", 0), unit.get("min_power(MW)", 0)
        if pmin is not None and pmax is not None and pmin > pmax:
            issues.append(Issue("error", where, f"Min power {pmin} MW exceeds max power {pmax} MW."))
        for key in ("ramp_up_rate(kW/min)", "ramp_down_rate(kW/min)", "start_up_cost(euro)", "shut_down_cost(euro)"):
            value = unit.get(key)
            if isinstance(value, (int, float)) and value < 0:
                issues.append(Issue("error", f"{where} › {key}", "Must be ≥ 0."))
        current = unit.get("current_Power(MW)", 0)
        if isinstance(current, (int, float)) and pmax is not None and not -EPS <= current <= pmax + EPS:
            issues.append(Issue("error", f"{where} › current power", f"{current} MW is outside [0, {pmax}] MW."))
        availability = unit.get("availability", [])
        if isinstance(availability, list):
            if len(availability) != n:
                issues.append(Issue("error", f"{where} › availability",
                                    f"Has {len(availability)} values; the horizon has {n} periods."))
            bad = [t + 1 for t, v in enumerate(availability) if pmax is not None and v > pmax + EPS]
            if bad:
                issues.append(Issue("error", f"{where} › availability",
                                    f"Exceeds max power at period(s) {bad[:8]}{'…' if len(bad) > 8 else ''}."))
        for s in unit.get("operating-states", []):
            lo, hi = s.get("min-power"), s.get("max-power")
            if isinstance(lo, (int, float)) and isinstance(hi, (int, float)) and lo > hi:
                issues.append(Issue("error", f"{where} › operating state {s['id']}",
                                    f"Min power {lo} MW exceeds max power {hi} MW."))
    config = data.get("stochastic", {})
    scenarios = config.get("scenarios", [])
    if scenarios:
        total = math.fsum(s.get("probability", 0) for s in scenarios)
        if not math.isclose(total, 1, abs_tol=1e-9):
            issues.append(Issue("error", "Scenarios › probabilities",
                                f"Sum to {total:.6f}; they must sum to exactly 1 (use 'Normalize' to rescale)."))
    for store in config.get("storage", []):
        where = f"Storage '{store.get('id')}'"
        cap = store.get("capacity_mwh", 0)
        for key in ("min_mwh", "initial_mwh", "terminal_min_mwh"):
            value = store.get(key)
            if isinstance(value, (int, float)) and value > cap + EPS:
                issues.append(Issue("error", f"{where} › {key}", f"{value} MWh exceeds capacity {cap} MWh."))
        for key in ("charge_efficiency", "discharge_efficiency"):
            value = store.get(key)
            if isinstance(value, (int, float)) and not 0 < value <= 1:
                issues.append(Issue("error", f"{where} › {key}", "Efficiency must be in (0, 1]."))
    return issues


def validate_case(data: dict, mode: str = "RDAS", scenario_choice: str = EXPECTED_ID,
                  ds_hours: int = 4) -> list[Issue]:
    """All issues found by the GUI checks and by the engine's own validators."""
    issues = gui_checks(data)
    target = data
    if mode == "DS":
        try:
            target = build_ds_input(data, scenario_choice, ds_hours)
        except (ValueError, KeyError, IndexError) as exc:
            return issues + [Issue("error", "DS conversion", str(exc))]
    try:
        report = validate_input_data(deepcopy(target))
        for message in report.get("errors", []):
            issues.append(Issue("error", *_split_message(message, target)))
        for message in report.get("warnings", []):
            issues.append(Issue("warning", *_split_message(message, target)))
    except Exception as exc:  # noqa: BLE001 - legacy helper may fail on malformed data
        issues.append(Issue("error", "Input structure", f"{type(exc).__name__}: {exc}"))
    if mode == "RDAS" and not any(i.severity == "error" for i in issues):
        try:
            sdata.validate(deepcopy(data))
        except ValueError as exc:
            issues.append(Issue("error", *_split_message(str(exc), data)))
        except Exception as exc:  # noqa: BLE001
            issues.append(Issue("error", "Stochastic input", f"{type(exc).__name__}: {exc}"))
    # De-duplicate (GUI check and engine may report the same thing)
    seen, unique = set(), []
    for issue in issues:
        key = (issue.severity, issue.location, issue.message)
        if key not in seen:
            seen.add(key)
            unique.append(issue)
    return unique


# =============================================================== DS conversion
def build_ds_input(data: dict, scenario_choice: str = EXPECTED_ID, ds_hours: int = 4,
                   minutes: int = DS_MINUTES) -> dict:
    """Deterministic DS input at ``minutes`` resolution from an hourly RDAS case.

    The chosen scenario (or the probability-weighted expected scenario) becomes
    the deterministic forecast. Hourly per-period arrays are held constant over
    the sub-periods of each hour; minute-based timers are resolution-independent
    and stay as they are. Storage is not part of the legacy DS kernel.
    """
    if resolution_minutes(data) != 60:
        raise ValueError("DS conversion expects an hourly (60-min) RDAS case.")
    n = horizon(data)
    ds_hours = int(ds_hours)
    if not 1 <= ds_hours <= n:
        raise ValueError(f"DS horizon must be between 1 and {n} hours.")
    if 60 % minutes:
        raise ValueError("DS interval must divide 60 minutes.")
    k = 60 // minutes
    config = data.get("stochastic", {})
    scenarios = config.get("scenarios") or [nominal(data)]
    if scenario_choice in (EXPECTED_ID, ALL_ID):
        scenario = expected_value_scenario(scenarios) if len(scenarios) > 1 else scenarios[0]
    else:
        scenario = next((s for s in scenarios if s["id"] == scenario_choice), None)
        if scenario is None:
            raise ValueError(f"Unknown scenario {scenario_choice!r}.")
    ds = deepcopy(data)
    ds.pop("stochastic", None)

    def expand(values: list) -> list:
        return [values[t] for t in range(ds_hours) for _ in range(k)]

    ds["Time_granularity"] = minutes
    ds["Load_forecast"] = [data["Load_forecast"][0]] + expand(list(scenario["load_mw"]))
    for unit in ds["Generating_Units"]:
        gid = str(unit["gen_id"])
        if gid in scenario["renewables_mw"]:
            unit["Production_Forecast"] = list(scenario["renewables_mw"][gid])
        for key, value in list(unit.items()):
            if isinstance(value, list) and len(value) == n and all(isinstance(v, (int, float)) for v in value):
                unit[key] = expand(value)
        for state in unit.get("operating-states", []):
            for key in ("min-power", "max-power"):
                if isinstance(state.get(key), list) and len(state[key]) == n:
                    state[key] = expand(state[key])
    early = ds.setdefault("optimization_parameters", {}).setdefault("early_stopping", {})
    early.setdefault("time_limit", None)
    return ds                         # provenance (scenario, hours) is recorded in request.json


# =============================================================== running
@dataclass
class RunHandle:
    """A launched solve: its folder and process."""
    run_dir: Path
    process: subprocess.Popen | None
    started: datetime


def _slug(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "-", text).strip("-")[:40] or "case"


def start_run(data: dict, *, mode: str, case_name: str, solver: str, time_limit: float | None,
              accept_incumbent: bool, compare: bool, scenario_choice: str, ds_hours: int,
              params_snapshot: dict | None = None) -> RunHandle:
    """Write the run folder and start ``gui/runner.py`` in a separate process."""
    started = datetime.now()
    run_dir = RUNS_ROOT / f"{started:%Y%m%d-%H%M%S}_{mode}_{_slug(Path(case_name).stem)}"
    suffix = 1
    while run_dir.exists():
        suffix += 1
        run_dir = run_dir.with_name(f"{run_dir.name.split('__')[0]}__{suffix}")
    run_dir.mkdir(parents=True)
    engine_input = build_ds_input(data, scenario_choice, ds_hours) if mode == "DS" else deepcopy(data)
    write_json(run_dir / "input.json", engine_input)
    if mode == "DS":
        write_json(run_dir / "case_input.json", data)     # the hourly case it came from
    request = {"mode": mode, "case": case_name, "solver": solver, "time_limit": time_limit,
               "accept_incumbent": bool(accept_incumbent), "compare": bool(compare) and mode == "RDAS",
               "scenario_choice": scenario_choice, "ds_hours": ds_hours if mode == "DS" else None,
               "ds_minutes": DS_MINUTES if mode == "DS" else None,
               "created": started.isoformat(timespec="seconds"), "parameters": params_snapshot or {}}
    write_json(run_dir / "request.json", request)
    write_json(run_dir / "status.json", {"state": "queued", "status": "Running", "started": request["created"]})
    log = (run_dir / "solver_log.txt").open("w", encoding="utf-8")
    env = dict(os.environ, PYTHONUNBUFFERED="1", PYTHONIOENCODING="utf-8")
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    process = subprocess.Popen([sys.executable, "-u", str(ROOT / "gui" / "runner.py"), str(run_dir)],
                               cwd=str(ROOT), stdout=log, stderr=subprocess.STDOUT, env=env,
                               creationflags=flags)
    log.close()
    return RunHandle(run_dir, process, started)


def read_status(run_dir: Path) -> dict:
    try:
        return read_json(run_dir / "status.json")
    except (OSError, json.JSONDecodeError):
        return {"state": "unknown", "status": "Error", "message": "status.json missing or unreadable"}


def log_tail(run_dir: Path, lines: int = 60) -> str:
    try:
        text = (run_dir / "solver_log.txt").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    return "\n".join(text.splitlines()[-lines:])


def finalize_run(handle: RunHandle) -> str:
    """After the process exits: make sure status.json holds a final status."""
    status = read_status(handle.run_dir)
    if status.get("state") == "finished":
        return status.get("status", "Error")
    if (handle.run_dir / "error.json").exists():
        error = read_json(handle.run_dir / "error.json")
        final, message = error.get("gui_status", "Error"), error.get("message", "")
    else:
        code = handle.process.returncode if handle.process is not None else None
        final, message = "Error", f"The solver process exited unexpectedly (exit code {code}); see the solver log."
    write_json(handle.run_dir / "status.json", dict(status, state="finished", status=final, message=message,
                                                    finished=datetime.now().isoformat(timespec="seconds")))
    return final


def cancel_run(handle: RunHandle) -> None:
    if handle.process is not None and handle.process.poll() is None:
        handle.process.terminate()
    write_json(handle.run_dir / "status.json",
               dict(read_status(handle.run_dir), state="finished", status="Cancelled",
                    message="Cancelled by the user.", finished=datetime.now().isoformat(timespec="seconds")))


def list_runs() -> list[dict]:
    """Run history (newest first)."""
    runs = []
    if not RUNS_ROOT.exists():
        return runs
    for folder in sorted(RUNS_ROOT.iterdir(), reverse=True):
        if not (folder / "request.json").exists():
            continue
        try:
            request = read_json(folder / "request.json")
        except (OSError, json.JSONDecodeError):
            continue
        status = read_status(folder)
        if status.get("state") != "finished" and (folder / "error.json").exists():
            try:
                status = dict(status, status=read_json(folder / "error.json").get("gui_status", "Error"))
            except (OSError, json.JSONDecodeError):
                status = dict(status, status="Error")
        runs.append({"run_dir": folder, "name": folder.name, "mode": request.get("mode"),
                     "case": request.get("case"), "created": request.get("created"),
                     "status": status.get("status"), "state": status.get("state"),
                     "expected_cost": status.get("expected_cost_eur"), "compare": request.get("compare")})
    return runs


# =============================================================== results
SLACK_CATEGORIES = [
    ("s_load_minus_", "Load shedding"),
    ("s_load_plus_", "Excess generation"),
    ("s_primary_APR_", "Reserve shortfall (primary)"),
    ("s_secondary_APR_", "Reserve shortfall (secondary)"),
    ("s_tertiary_APR_", "Reserve shortfall (tertiary)"),
    ("ramp_relax_", "Ramp relaxation"),
    ("s_forbidden_zones_", "Forbidden zone"),
    ("s_power_testing_", "Testing mode"),
    ("s_power_OOS_", "Out-of-service mode"),
    ("s_must_run_", "Must-run"),
    ("s_min_", "State timer (min time)"),
    ("s_max_oper_state_time_", "State timer (max time)"),
    ("s_maximum_on_", "Maximum ON time"),
    ("s_power_plus_", "RES tracking (above forecast)"),
    ("s_power_minus_", "RES tracking (below forecast)"),
    ("s_Grid_Capacity_", "Grid capacity"),
    ("s_avail_", "Availability"),
    ("s_storage_terminal_", "BESS terminal SOC shortfall"),
    ("s_storage_soc_floor_", "BESS SOC below minimum"),
]


def slack_category(name: str) -> str:
    for prefix, label in SLACK_CATEGORIES:
        if name.startswith(prefix):
            return label
    return "Other slack"


def _slack_period(name: str) -> int | None:
    match = re.search(r"_(\d+)$", name)
    return int(match.group(1)) if match else None


@dataclass
class Results:
    """One solved (or failed) run, normalised to pandas tables."""
    run_dir: str
    mode: str
    status: str
    message: str = ""
    request: dict = field(default_factory=dict)
    meta: dict = field(default_factory=dict)
    minutes: int = 60
    periods: list[int] = field(default_factory=list)
    units: pd.DataFrame = field(default_factory=pd.DataFrame)
    scenarios: pd.DataFrame = field(default_factory=pd.DataFrame)
    dispatch: pd.DataFrame = field(default_factory=pd.DataFrame)
    load: pd.DataFrame = field(default_factory=pd.DataFrame)
    res_available: pd.DataFrame = field(default_factory=pd.DataFrame)
    commitment: pd.DataFrame = field(default_factory=pd.DataFrame)
    reserves_provided: pd.DataFrame = field(default_factory=pd.DataFrame)
    reserves_required: pd.DataFrame = field(default_factory=pd.DataFrame)
    headroom: pd.DataFrame = field(default_factory=pd.DataFrame)
    storage: pd.DataFrame = field(default_factory=pd.DataFrame)
    costs: pd.DataFrame = field(default_factory=pd.DataFrame)
    waterfall: pd.DataFrame = field(default_factory=pd.DataFrame)
    slacks: pd.DataFrame = field(default_factory=pd.DataFrame)
    limits: pd.DataFrame = field(default_factory=pd.DataFrame)
    implementable: pd.DataFrame = field(default_factory=pd.DataFrame)
    benchmarks: dict = field(default_factory=dict)
    notes: list = field(default_factory=list)
    error: dict = field(default_factory=dict)
    tree: dict | None = None

    @property
    def ok(self) -> bool:
        return self.status in ("Optimal", "Feasible")

    def tables(self) -> dict[str, pd.DataFrame]:
        """Every non-empty table, for CSV/Excel export."""
        names = ["dispatch", "load", "res_available", "commitment", "reserves_provided", "reserves_required",
                 "headroom", "storage", "costs", "waterfall", "slacks", "limits", "implementable", "scenarios",
                 "units"]
        return {n: getattr(self, n) for n in names if isinstance(getattr(self, n), pd.DataFrame)
                and not getattr(self, n).empty}


def load_results(run_dir: Path | str) -> Results:
    """Parse a run folder written by ``gui/runner.py``."""
    run_dir = Path(run_dir)
    request = read_json(run_dir / "request.json") if (run_dir / "request.json").exists() else {}
    status = read_status(run_dir)
    if status.get("state") != "finished" and (run_dir / "error.json").exists():
        # The runner wrote its diagnosis but could not update status.json.
        error = read_json(run_dir / "error.json")
        status = dict(status, state="finished", status=error.get("gui_status", "Error"),
                      message=error.get("message", ""))
    mode = request.get("mode", "RDAS")
    res = Results(str(run_dir), mode, status.get("status", "Unknown"), status.get("message", ""), request)
    res.meta = {"started": status.get("started"), "finished": status.get("finished"),
                "solver": request.get("solver"), "time_limit": request.get("time_limit"),
                "stats": status.get("stats", []), "case": request.get("case")}
    if (run_dir / "error.json").exists():
        try:
            res.error = read_json(run_dir / "error.json")
        except (OSError, json.JSONDecodeError):
            res.error = {"message": "error.json unreadable"}
    if not (run_dir / "result.json").exists():
        return res
    data = read_json(run_dir / "input.json")
    result = read_json(run_dir / "result.json")
    try:
        if mode == "DS":
            _parse_ds(res, data, result)
        else:
            _parse_rdas(res, data, result)
    except Exception as exc:  # noqa: BLE001 - never crash the GUI on an unexpected result shape
        import traceback
        res.error = {"status": "ParseError", "message": f"Could not parse result: {exc}",
                     "traceback": traceback.format_exc()}
    return res


def _units_table(data: dict) -> pd.DataFrame:
    return pd.DataFrame([{"index": u.index, "gen_id": u.gen_id, "unit": u.label, "type": u.type,
                          "color": u.color, "is_storage": u.is_storage} for u in unit_infos(data)])


def _solve_stats(res: Results) -> dict:
    stats = res.meta.get("stats") or []
    return stats[0] if stats else {}


def _parse_rdas(res: Results, data: dict, result: dict) -> None:
    sol = result["stochastic"] if "RP" in result else result
    n = horizon(data)
    res.minutes = 60
    res.periods = list(range(1, n + 1))
    units = data["Generating_Units"]
    infos = [u for u in unit_infos(data) if not u.is_storage]
    res.units = _units_table(data)
    common = sol["common_schedule"]
    outputs = sol["scenario_dispatch"]
    scen_input = {s["id"]: s for s in data["stochastic"]["scenarios"]}
    res.scenarios = pd.DataFrame([{"scenario": sid, "probability": o["probability"],
                                   "tree_path": " / ".join(o.get("tree_path", []))} for sid, o in outputs.items()])

    dispatch, load, avail, headroom = [], [], [], []
    for sid, o in outputs.items():
        v, p, s = o["variables"], o["probability"], scen_input[sid]
        for t in res.periods:
            shed = v.get(f"s_load_minus_{t}", 0) or 0
            load.append({"scenario": sid, "probability": p, "t": t, "load_mw": s["load_mw"][t - 1],
                         "shed_mw": shed, "excess_mw": v.get(f"s_load_plus_{t}", 0) or 0})
        for info, unit in zip(infos, units):
            i = info.index
            for t in res.periods:
                mw = v.get(f"power_{i + 1}_{t}", 0) or 0
                dispatch.append({"scenario": sid, "probability": p, "unit": info.label, "type": info.type,
                                 "t": t, "mw": mw})
                if str(unit["gen_id"]) in s["renewables_mw"]:
                    avail.append({"scenario": sid, "probability": p, "unit": info.label, "t": t,
                                  "mw": s["renewables_mw"][str(unit["gen_id"])][t - 1]})
        headroom += _headroom_rows(data, infos, sid, p,
                                   lambda i, t, v=v: v.get(f"power_{i + 1}_{t}", 0) or 0,
                                   lambda i, t: _active_state_id(common, i, t),
                                   lambda i, t: common.get(f"state_{i + 1}_{t}", 0) or 0,
                                   s["renewables_mw"])
    res.dispatch = pd.DataFrame(dispatch)
    res.load = pd.DataFrame(load)
    res.res_available = pd.DataFrame(avail, columns=["scenario", "probability", "unit", "t", "mw"])
    res.headroom = pd.DataFrame(headroom)

    # Common (first-stage) commitment
    rows = []
    for info, unit in zip(infos, units):
        i = info.index
        states = {s["id"]: s for s in unit["operating-states"]}
        for t in res.periods:
            sid_state = _active_state_id(common, i, t)
            state = states.get(sid_state)
            rows.append({"unit": info.label, "type": info.type, "t": t,
                         "on": round(common.get(f"state_{i + 1}_{t}", 0) or 0),
                         "operating_state": sid_state,
                         "state_label": operating_state_label(state) if state else "",
                         "state_class": state_class(state) if state else (
                             "Operational" if round(common.get(f"state_{i + 1}_{t}", 0) or 0) else "Off"),
                         "startup": round(common.get(f"startup_{i + 1}_{t}", 0) or 0),
                         "shutdown": round(common.get(f"shutdown_{i + 1}_{t}", 0) or 0)})
    res.commitment = pd.DataFrame(rows)

    # Reserves: provided capacity is first-stage, requirements are per scenario
    provided = []
    for info in infos:
        i = info.index
        for product in PRODUCTS:
            for direction, suffix in (("up", "plus"), ("down", "minus")):
                for t in res.periods:
                    value = common.get(f"{product}_ActPR_{suffix}{i + 1}_{t}")
                    if value is not None:
                        provided.append({"product": product, "direction": direction, "unit": info.label,
                                         "t": t, "mw": value})
    stores = data["stochastic"].get("storage", [])
    store_infos = [u for u in unit_infos(data) if u.is_storage]
    for j, (store, info) in enumerate(zip(stores, store_infos)):
        for product in PRODUCTS:
            for direction in DIRECTIONS:
                for t in res.periods:
                    value = common.get(f"storage_reserve_{product}_{direction}_{j}_{t}")
                    if value is not None:
                        provided.append({"product": product, "direction": direction, "unit": info.label,
                                         "t": t, "mw": value})
    res.reserves_provided = pd.DataFrame(provided, columns=["product", "direction", "unit", "t", "mw"])
    required = []
    for sid, o in outputs.items():
        v = o["variables"]
        for product in PRODUCTS:
            for direction, k, word in (("up", 0, "upwards"), ("down", 1, "downwards")):
                for t in res.periods:
                    req = v.get(f"{product}_APRR_{t}_{k}")
                    if req is None:
                        continue
                    required.append({"scenario": sid, "probability": o["probability"], "product": product,
                                     "direction": direction, "t": t, "required_mw": req,
                                     "shortfall_mw": v.get(f"s_{product}_APR_{word}_{t}", 0) or 0})
    res.reserves_required = pd.DataFrame(
        required, columns=["scenario", "probability", "product", "direction", "t", "required_mw", "shortfall_mw"])

    # Storage
    srows = []
    for sid, o in outputs.items():
        for store_id, rep in (o.get("storage") or {}).items():
            for t in range(0, n + 1):
                srows.append({"scenario": sid, "probability": o["probability"], "store": store_id, "t": t,
                              "energy_mwh": rep["energy_mwh"][t],
                              "charge_mw": rep["charge_mw"][t - 1] if t else 0.0,
                              "discharge_mw": rep["discharge_mw"][t - 1] if t else 0.0})
    res.storage = pd.DataFrame(srows)
    if not res.storage.empty:
        label = {s["id"]: u.label for s, u in zip(stores, store_infos)}
        res.storage["unit"] = res.storage["store"].map(label)
        # BESS net injection belongs in the dispatch stack.
        net = res.storage[res.storage["t"] > 0].copy()
        net["mw"] = net["discharge_mw"] - net["charge_mw"]
        net["type"] = "storage"
        res.dispatch = pd.concat([res.dispatch, net[["scenario", "probability", "unit", "type", "t", "mw"]]],
                                 ignore_index=True)

    # Costs
    crows, slacks, first_slack = [], [], 0.0
    for sid, o in outputs.items():
        crows.append({"scenario": sid, "probability": o["probability"], "total_eur": o["total_cost_eur"],
                      "operating_eur": o["operating_cost_eur"], "penalty_eur": o["penalty_cost_eur"],
                      "res_priority_eur": o["renewable_priority_cost_eur"],
                      "unserved_mwh": o["metrics"]["unserved_mwh"],
                      "curtailed_res_mwh": o["metrics"]["curtailed_res_mwh"],
                      "reserve_shortfall_mwh": o["metrics"]["reserve_shortfall_mw_hours"]})
        for e in o["nonzero_slacks"]:
            if e["stage"] == "first":
                first_slack += o["probability"] * (e["penalty_eur"] or 0)
            slacks.append({"scenario": sid, "probability": o["probability"], "variable": e["variable"],
                           "category": slack_category(e["variable"]), "stage": e["stage"],
                           "t": _slack_period(e["variable"]), "value": e["value"],
                           "upper_bound": e.get("upper_bound"), "penalty_eur": e["penalty_eur"]})
    res.costs = pd.DataFrame(crows)
    res.costs["weighted_total_eur"] = res.costs["probability"] * res.costs["total_eur"]
    res.slacks = pd.DataFrame(slacks, columns=["scenario", "probability", "variable", "category", "stage", "t",
                                               "value", "upper_bound", "penalty_eur"])
    res.waterfall = _rdas_waterfall(sol, data, res.costs, first_slack)

    res.limits = _binding_limits(data, infos, res)
    if sol.get("implementable_dispatch"):
        imp = sol["implementable_dispatch"]
        res.implementable = pd.DataFrame([{"decision": k, "value": v} for k, v in imp["decisions"].items()])
    res.tree = sol.get("scenario_tree")
    res.notes = sol.get("model_notes", [])
    stats = _solve_stats(res)
    res.meta.update({
        "objective_eur": sol.get("objective_eur"), "expected_cost_eur": sol.get("expected_cost_eur"),
        "first_stage_cost_eur": sol.get("first_stage_cost_eur"),
        "expected_recourse_cost_eur": sol.get("expected_recourse_cost_eur"), "cvar_eur": sol.get("cvar_eur"),
        "cvar_alpha": data["stochastic"].get("risk", {}).get("alpha", 0.95),
        "risk_weight": data["stochastic"].get("risk", {}).get("weight", 0),
        "solve_seconds": sol.get("solve_seconds"), "build_seconds": sol.get("build_seconds"),
        "num_variables": sol.get("num_variables"), "num_constraints": sol.get("num_constraints"),
        "num_binaries": stats.get("integers"), "mip_gap": stats.get("mip_gap"),
        "operational_status": sol.get("operational_status"), "validation": sol.get("validation", {}),
        "expected_metrics": sol.get("expected_metrics", {}), "interpretation": sol.get("interpretation"),
        "first_stage_breakdown": sol.get("first_stage_breakdown", {}), "status_engine": sol.get("status"),
    })
    if "RP" in result:
        res.benchmarks = {k: result.get(k) for k in ("RP", "EV_objective", "EEV", "EEV_status", "WS", "VSS",
                                                      "EVPI", "VSS_decomposition", "requested_risk_weight")}
        if "stochastic_risk_averse" in result:
            res.benchmarks["risk_averse_expected_cost"] = result["stochastic_risk_averse"].get("expected_cost_eur")
            res.benchmarks["risk_averse_cvar"] = result["stochastic_risk_averse"].get("cvar_eur")
    if result.get("out_of_sample"):
        res.benchmarks["out_of_sample"] = {k: (v.get("expected_cost_eur") if isinstance(v, dict) else None)
                                           for k, v in result["out_of_sample"].items()}


def _active_state_id(common: dict, i: int, t: int) -> int | None:
    best, best_val = None, 0.5
    prefix = f"u_2_{i + 1}_{t}_"
    for name, value in common.items():
        if name.startswith(prefix) and (value or 0) > best_val:
            best, best_val = int(name[len(prefix):]), value
    return best


def _headroom_rows(data, infos, sid, p, power, state_id, on, renewables) -> list[dict]:
    """Upward headroom and downward footroom of every unit (MW)."""
    rows = []
    n = horizon(data)
    for info in infos:
        unit = data["Generating_Units"][info.index]
        states = {s["id"]: s for s in unit["operating-states"]}
        for t in range(1, n + 1):
            mw = power(info.index, t)
            avail = at(unit.get("availability", unit.get("max_power(MW)", 0)), t)
            if is_conventional(unit):
                st = states.get(state_id(info.index, t))
                is_on = round(on(info.index, t)) == 1
                hi = min(avail, at(st["max-power"], t)) if (st and is_on) else 0.0
                lo = at(st["min-power"], t) if (st and is_on) else 0.0
            else:
                resource = renewables.get(str(unit["gen_id"]))
                hi = min(avail, resource[t - 1]) if resource else avail
                lo = 0.0
            rows.append({"scenario": sid, "probability": p, "unit": info.label, "type": info.type, "t": t,
                         "mw": mw, "upper_mw": hi, "lower_mw": lo,
                         "headroom_mw": max(0.0, hi - mw), "footroom_mw": max(0.0, mw - lo)})
    return rows


def _binding_limits(data: dict, infos: list[UnitInfo], res: Results) -> pd.DataFrame:
    """Physical limits that are active in the solution (detected from values)."""
    rows = []
    tol = 1e-4
    minutes = res.minutes
    if not res.headroom.empty:
        h = res.headroom
        conv = {u.label for u in infos if is_conventional(data["Generating_Units"][u.index])}
        at_max = h[(h["headroom_mw"] <= tol) & (h["upper_mw"] > tol)]
        for _, r in at_max.iterrows():
            rows.append({"scenario": r["scenario"], "t": r["t"], "unit": r["unit"],
                         "limit": "At upper limit" if r["unit"] in conv else "At RES resource",
                         "value": r["mw"], "bound": r["upper_mw"]})
        at_min = h[(h["footroom_mw"] <= tol) & (h["lower_mw"] > tol)]
        for _, r in at_min.iterrows():
            rows.append({"scenario": r["scenario"], "t": r["t"], "unit": r["unit"], "limit": "At minimum stable",
                         "value": r["mw"], "bound": r["lower_mw"]})
    if not res.dispatch.empty:
        for info in infos:
            unit = data["Generating_Units"][info.index]
            if not is_conventional(unit):
                continue
            up = unit.get("ramp_up_rate(kW/min)", 0) * minutes / 1000
            down = unit.get("ramp_down_rate(kW/min)", 0) * minutes / 1000
            d = res.dispatch[res.dispatch["unit"] == info.label]
            for sid, grp in d.groupby("scenario"):
                series = [unit.get("current_Power(MW)", 0)] + grp.sort_values("t")["mw"].tolist()
                for t in range(1, len(series)):
                    delta = series[t] - series[t - 1]
                    if up > 0 and delta >= up - tol:
                        rows.append({"scenario": sid, "t": t, "unit": info.label, "limit": "Ramp-up limited",
                                     "value": delta, "bound": up})
                    if down > 0 and -delta >= down - tol:
                        rows.append({"scenario": sid, "t": t, "unit": info.label, "limit": "Ramp-down limited",
                                     "value": -delta, "bound": down})
    if not res.storage.empty:
        caps = {s["id"]: s for s in data.get("stochastic", {}).get("storage", [])}
        for _, r in res.storage[res.storage["t"] > 0].iterrows():
            store = caps[r["store"]]
            if r["energy_mwh"] >= store["capacity_mwh"] - tol:
                rows.append({"scenario": r["scenario"], "t": r["t"], "unit": r["unit"], "limit": "BESS full",
                             "value": r["energy_mwh"], "bound": store["capacity_mwh"]})
            elif r["energy_mwh"] <= store["min_mwh"] + tol:
                rows.append({"scenario": r["scenario"], "t": r["t"], "unit": r["unit"], "limit": "BESS at min SOC",
                             "value": r["energy_mwh"], "bound": store["min_mwh"]})
    return pd.DataFrame(rows, columns=["scenario", "t", "unit", "limit", "value", "bound"])


def _rdas_waterfall(sol: dict, data: dict, costs: pd.DataFrame, first_slack: float) -> pd.DataFrame:
    """Expected objective split into first-stage and recourse components (EUR).

    Reconciles exactly: the components sum to ``expected_cost_eur``.
    """
    common = sol["common_schedule"]
    breakdown = sol.get("first_stage_breakdown", {})
    online = breakdown.get("thermal_online_charge_eur", 0.0)
    storage_res = breakdown.get("storage_reserve_capacity_eur", 0.0)
    startup = shutdown = 0.0
    for i, unit in enumerate(data["Generating_Units"]):
        if not is_conventional(unit):
            continue
        for t in range(1, horizon(data) + 1):
            startup += unit.get("start_up_cost(euro)", 0) * (common.get(f"startup_{i + 1}_{t}", 0) or 0)
            shutdown += unit.get("shut_down_cost(euro)", 0) * (common.get(f"shutdown_{i + 1}_{t}", 0) or 0)
    first_non_penalty = sol["first_stage_cost_eur"] - first_slack
    other_first = first_non_penalty - online - startup - shutdown - storage_res
    p = costs["probability"]
    e_oper = float((p * costs["operating_eur"]).sum())
    e_pen = float((p * costs["penalty_eur"]).sum())
    e_inc = float((p * costs["res_priority_eur"]).sum())
    rows = [
        ("First stage", "Thermal online charge", online),
        ("First stage", "Start-up", startup),
        ("First stage", "Shut-down", shutdown),
        ("First stage", "Reserve capacity, state & transition costs", other_first),
    ]
    if storage_res:
        rows.append(("First stage", "BESS reserve capacity", storage_res))
    rows += [
        ("Recourse (expected)", "Generation, activation & BESS", e_oper - first_non_penalty),
        ("Penalties (expected)", "Slack penalties", e_pen),
        ("Recourse (expected)", "RES priority / curtailment terms", e_inc),
    ]
    frame = pd.DataFrame(rows, columns=["stage", "component", "eur"])
    frame.attrs["total"] = sol["expected_cost_eur"]
    return frame


# ---------------------------------------------------------------- DS (deterministic legacy) results
def _parse_ds(res: Results, data: dict, result: dict) -> None:
    n = horizon(data)
    res.minutes = resolution_minutes(data)
    res.periods = list(range(1, n + 1))
    infos = [u for u in unit_infos(data) if not u.is_storage]
    res.units = _units_table(data)
    sid = "deterministic"
    res.scenarios = pd.DataFrame([{"scenario": sid, "probability": 1.0, "tree_path": ""}])
    out_units = {int(g["gen_id"]): g for g in result.get("Generating_Units", [])}
    shed = result.get("Load_Cutrailment")
    shed = shed if isinstance(shed, list) else [0.0] * n
    res.load = pd.DataFrame([{"scenario": sid, "probability": 1.0, "t": t, "load_mw": data["Load_forecast"][t],
                              "shed_mw": shed[t - 1] if t - 1 < len(shed) else 0.0, "excess_mw": 0.0}
                             for t in res.periods])
    instr = {}
    for item in result.get("Dispatch_Instructions", {}).get("instructions", []):
        instr[(item["unit_index"], item["period"])] = item
    dispatch, avail, commitment, provided = [], [], [], []
    for info in infos:
        unit = data["Generating_Units"][info.index]
        g = out_units.get(int(unit["gen_id"]), {})
        states = {s["id"]: s for s in unit["operating-states"]}
        power = g.get("Power", [0.0] * n)
        for t in res.periods:
            dispatch.append({"scenario": sid, "probability": 1.0, "unit": info.label, "type": info.type, "t": t,
                             "mw": power[t - 1]})
            if is_renewable(unit):
                avail.append({"scenario": sid, "probability": 1.0, "unit": info.label, "t": t,
                              "mw": unit["Production_Forecast"][t - 1]})
            item = instr.get((info.index, t), {})
            state_id = item.get("operating_state_id")
            state = states.get(state_id) if state_id is not None else None
            on = round(g.get("State", [0] * n)[t - 1])
            commitment.append({"unit": info.label, "type": info.type, "t": t, "on": on,
                               "operating_state": state_id,
                               "state_label": operating_state_label(state) if state else "",
                               "state_class": state_class(state) if state else ("Operational" if on else "Off"),
                               "startup": round(g.get("Startup", [0] * n)[t - 1]),
                               "shutdown": round(g.get("Shutdown", [0] * n)[t - 1])})
        for product in PRODUCTS:
            values = g.get(f"{product.capitalize()}_Active_Power_Reserves(MW)")
            if isinstance(values, list) and len(values) == 2:
                for direction, series in zip(DIRECTIONS, values):
                    for t in res.periods:
                        provided.append({"product": product, "direction": direction, "unit": info.label, "t": t,
                                         "mw": abs(series[t - 1])})
    res.dispatch = pd.DataFrame(dispatch)
    res.res_available = pd.DataFrame(avail, columns=["scenario", "probability", "unit", "t", "mw"])
    res.commitment = pd.DataFrame(commitment)
    res.reserves_provided = pd.DataFrame(provided, columns=["product", "direction", "unit", "t", "mw"])
    required = []
    for period in result.get("Reserve_Monitoring_Report", {}).get("periods", []):
        for product, dirs in period.get("reserves", {}).items():
            for word, direction in (("upwards", "up"), ("downwards", "down")):
                cell = dirs.get(word)
                if cell:
                    required.append({"scenario": sid, "probability": 1.0, "product": product,
                                     "direction": direction, "t": period["period"],
                                     "required_mw": cell.get("required_mw", 0),
                                     "shortfall_mw": cell.get("reported_shortage_mw", 0)})
    res.reserves_required = pd.DataFrame(
        required, columns=["scenario", "probability", "product", "direction", "t", "required_mw", "shortfall_mw"])
    states_by_t = {(row["unit"], row["t"]): row["operating_state"] for row in commitment}
    on_by_t = {(row["unit"], row["t"]): row["on"] for row in commitment}
    label_of = {u.index: u.label for u in infos}
    renew = {str(data["Generating_Units"][u.index]["gen_id"]): data["Generating_Units"][u.index]["Production_Forecast"]
             for u in infos if is_renewable(data["Generating_Units"][u.index])}
    power_of = {(r["unit"], r["t"]): r["mw"] for r in dispatch}
    res.headroom = pd.DataFrame(_headroom_rows(
        data, infos, sid, 1.0, lambda i, t: power_of[(label_of[i], t)],
        lambda i, t: states_by_t.get((label_of[i], t)), lambda i, t: on_by_t.get((label_of[i], t), 0), renew))
    objective = result.get("Solve_Metadata", {}).get("objective_value")
    breakdown = result.get("Objective_Breakdown_Report", {})
    wf = [("Deterministic", c["name"].replace("_", " ").capitalize(), c["amount"])
          for c in breakdown.get("components", []) if abs(c.get("amount") or 0) > 1e-9]
    res.waterfall = pd.DataFrame(wf, columns=["stage", "component", "eur"])
    res.waterfall.attrs["total"] = objective
    penalty = sum(c["amount"] for c in breakdown.get("components", [])
                  if "penalty" in c["name"] or "slack" in c["name"])
    res.costs = pd.DataFrame([{"scenario": sid, "probability": 1.0, "total_eur": objective,
                               "operating_eur": (objective or 0) - penalty, "penalty_eur": penalty,
                               "res_priority_eur": 0.0, "unserved_mwh": sum(shed) * res.minutes / 60,
                               "curtailed_res_mwh": None, "reserve_shortfall_mwh": None,
                               "weighted_total_eur": objective}])
    slacks = []
    for e in result.get("Slack_Penalty_Report", {}).get("entries", []):
        name = e.get("variable") or e.get("name") or ""
        slacks.append({"scenario": sid, "probability": 1.0, "variable": name, "category": slack_category(name),
                       "stage": "deterministic", "t": e.get("period", _slack_period(name)),
                       "value": e.get("value"), "upper_bound": None,
                       "penalty_eur": e.get("penalty_eur", e.get("penalty"))})
    for t, value in enumerate(shed, 1):
        if value and value > 1e-7 and not any(s["category"] == "Load shedding" and s["t"] == t for s in slacks):
            slacks.append({"scenario": sid, "probability": 1.0, "variable": f"s_load_minus_{t}",
                           "category": "Load shedding", "stage": "deterministic", "t": t, "value": value,
                           "upper_bound": None, "penalty_eur": None})
    res.slacks = pd.DataFrame(slacks, columns=["scenario", "probability", "variable", "category", "stage", "t",
                                               "value", "upper_bound", "penalty_eur"])
    res.limits = _binding_limits(data, infos, res)
    meta = result.get("Solve_Metadata", {})
    stats = _solve_stats(res)
    validation = result.get("Validation", {})
    res.meta.update({
        "objective_eur": objective, "expected_cost_eur": objective, "first_stage_cost_eur": None,
        "expected_recourse_cost_eur": None, "cvar_eur": None,
        "solve_seconds": stats.get("seconds"), "build_seconds": None,
        "num_variables": meta.get("num_variables"), "num_constraints": meta.get("num_constraints"),
        "num_binaries": stats.get("integers"), "mip_gap": stats.get("mip_gap"),
        "operational_status": "degraded" if len(res.slacks) else "no_reported_violations",
        "validation": {"passed": validation.get("status") == "passed",
                       "max_constraint_residual": validation.get("max_load_balance_residual"),
                       "checked_constraints": len(validation.get("checks", []))},
        "expected_metrics": {"unserved_mwh": sum(shed) * res.minutes / 60},
        "interpretation": "Deterministic DS schedule of the legacy MMS kernel for the selected forecast.",
        "status_engine": result.get("Solution_Status"),
    })
    res.notes = [{"code": "DETERMINISTIC_DS",
                  "message": f"DS run with {res.minutes}-min intervals using the "
                             f"'{res.request.get('scenario_choice')}' forecast; storage is not modelled by the "
                             "legacy DS kernel."}]


# =============================================================== derived views
def expected(frame: pd.DataFrame, keys: list[str], value: str = "mw") -> pd.DataFrame:
    """Probability-weighted mean over scenarios."""
    if frame.empty:
        return frame
    weighted = frame.assign(_w=frame["probability"] * frame[value])
    out = weighted.groupby(keys, as_index=False)["_w"].sum().rename(columns={"_w": value})
    return out


def pick_scenario(frame: pd.DataFrame, choice: str, keys: list[str], value: str = "mw") -> pd.DataFrame:
    """Rows of one scenario, or the expected value when ``choice`` is not a scenario id."""
    if frame.empty:
        return frame
    if choice in frame["scenario"].unique():
        return frame[frame["scenario"] == choice]
    return expected(frame, keys, value)


def kpis(res: Results) -> dict:
    """Headline numbers for the Overview page."""
    out: dict[str, Any] = {}
    meta = res.meta
    out["expected_cost"] = meta.get("expected_cost_eur")
    out["objective"] = meta.get("objective_eur")
    out["cvar"] = meta.get("cvar_eur")
    out["n_scenarios"] = int((res.scenarios["probability"] > 0).sum()) if not res.scenarios.empty else 0
    if not res.commitment.empty:
        conv = res.commitment[res.commitment["type"].isin(["thermal", "biomass"])]
        out["units_committed"] = int(conv.groupby("unit")["on"].max().sum())
        out["units_conventional"] = int(conv["unit"].nunique())
        out["startups"] = int(conv["startup"].sum())
        peak = conv.groupby("t")["on"].sum()
        out["peak_online"] = int(peak.max()) if not peak.empty else 0
    if not res.load.empty:
        h = res.minutes / 60
        e_shed = float((res.load["probability"] * res.load["shed_mw"]).sum()) * h
        out["load_shed_mwh"] = e_shed
        e_load = float((res.load["probability"] * res.load["load_mw"]).sum()) * h
        out["energy_mwh"] = e_load
        d = res.dispatch
        if not d.empty and e_load > 0:
            ren = d[d["type"].isin(["wind", "pv", "hybrid"])]
            out["res_share"] = float((ren["probability"] * ren["mw"]).sum()) * h / e_load
    wf = res.waterfall
    if not wf.empty:
        def part(*words):
            mask = wf["component"].str.lower().str.contains("|".join(words))
            return float(wf.loc[mask, "eur"].sum())
        out["cost_startup"] = part("start-up", "shut-down", "startup", "shutdown")
        out["cost_penalties"] = part("penalt", "slack")
        out["cost_reserves"] = part("reserve")
        out["cost_generation"] = float(wf["eur"].sum()) - out["cost_startup"] - out["cost_penalties"] \
            - out["cost_reserves"]
    out["mip_gap"] = meta.get("mip_gap")
    out["solve_seconds"] = meta.get("solve_seconds")
    out["rows"] = meta.get("num_constraints")
    out["cols"] = meta.get("num_variables")
    out["binaries"] = meta.get("num_binaries")
    return out


def warnings_summary(res: Results) -> pd.DataFrame:
    """Non-zero slacks grouped by category (expected value and scenarios affected)."""
    s = res.slacks
    if s.empty:
        return pd.DataFrame(columns=["category", "scenarios affected", "periods", "expected amount", "max amount",
                                     "expected penalty (€)"])
    g = s.assign(w=s["probability"] * s["value"], wp=s["probability"] * s["penalty_eur"].fillna(0))
    out = g.groupby("category").agg(**{
        "scenarios affected": ("scenario", "nunique"), "periods": ("t", lambda x: ", ".join(
            str(int(v)) for v in sorted(set(x.dropna())))[:60]),
        "expected amount": ("w", "sum"), "max amount": ("value", "max"),
        "expected penalty (€)": ("wp", "sum")}).reset_index()
    return out.sort_values("expected penalty (€)", ascending=False)


def excel_bytes(res: Results) -> bytes | None:
    """All result tables as one Excel workbook (None if openpyxl is missing)."""
    import io
    try:
        import openpyxl  # noqa: F401
    except ImportError:
        return None
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        for name, frame in res.tables().items():
            frame.to_excel(writer, sheet_name=name[:31], index=False)
    return buffer.getvalue()


# =============================================================== parameter configs
PARAMETER_PATHS = [
    "Cost_parameters", "Other_coefficients", "constraints", "optimization_parameters.big_m",
    "stochastic.risk", "stochastic.slack_policy", "stochastic.cost_policy", "stochastic.reserve_link",
    "stochastic.reserve_link_mode", "stochastic.reserve_products",
]
STORAGE_ECONOMICS = ["terminal_value_eur_per_mwh", "terminal_shortfall_penalty_eur_per_mwh",
                     "soc_recovery_penalty_eur_per_mwh", "throughput_eur_per_mwh", "max_cycles_per_horizon"]


def parameters_snapshot(data: dict) -> dict:
    """The parameter subset of a case (what the Parameters page edits)."""
    snap = {path: deepcopy(get_path(data, path)) for path in PARAMETER_PATHS}
    snap["storage_economics"] = {s["id"]: {k: s[k] for k in STORAGE_ECONOMICS if k in s}
                                 for s in data.get("stochastic", {}).get("storage", [])}
    return snap


def apply_parameters(data: dict, snapshot: dict) -> list[str]:
    """Apply a parameter snapshot to ``data``; returns skipped items."""
    skipped = []
    for path in PARAMETER_PATHS:
        if path in snapshot:
            set_path(data, path, deepcopy(snapshot[path]))
    stores = {s["id"]: s for s in data.get("stochastic", {}).get("storage", [])}
    for sid, values in snapshot.get("storage_economics", {}).items():
        if sid not in stores:
            skipped.append(f"storage '{sid}' not in this case")
            continue
        for key in STORAGE_ECONOMICS:
            if key in values:
                stores[sid][key] = values[key]
            elif key != "throughput_eur_per_mwh":
                stores[sid].pop(key, None)
    return skipped


def save_config(name: str, payload: dict) -> Path:
    slug = re.sub(r"[^A-Za-z0-9_.-]+", "_", name.strip()).strip("_") or "config"
    path = CONFIGS_DIR / (slug if slug.endswith(".json") else slug + ".json")
    write_json(path, payload)
    return path


def list_configs() -> list[Path]:
    return sorted(CONFIGS_DIR.glob("*.json")) if CONFIGS_DIR.exists() else []
