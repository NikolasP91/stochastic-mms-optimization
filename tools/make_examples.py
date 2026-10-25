"""Rebuild small, explicitly synthetic examples from the supplied MMS schema."""

from copy import deepcopy
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from mms.stochastic.scenarios import nominal, synthetic, synthetic_tree


def make():
    original = json.loads((ROOT / "v2.1_last_real_values_RDAS_60_FAT---test-case_BIOMASS.json").read_text(encoding="utf-8"))
    data = deepcopy(original)
    n = 4
    data["Load_forecast"] = [0, 9, 11, 12, 10]
    data["optimization_parameters"]["cost_curve_time_unit"] = "euro_per_mwh"
    data["optimization_parameters"]["big_m"] = "auto"
    units = []
    for i, (capacity, forecast) in enumerate([(12, [0]*n), (8, [0]*n), (6, [2, 3, 1, 2]), (3, [0, 1, 2, 0])]):
        g = deepcopy(original["Generating_Units"][min(i, 3)])
        for key, value in list(g.items()):
            if isinstance(value, list) and len(value) == 24:
                g[key] = value[:n]
        g.update(gen_id=i, comments=("Thermo" if i < 2 else "RES" if i == 2 else "PV") + f": synthetic unit {i}",
                 state=0, availability=[capacity]*n, Production_Forecast=forecast,
                 mustRun=[0]*n, forbidden_zones=[], Accepts_SP=1)
        g.update({"current_Power(MW)": 0, "min_power(MW)": 0, "max_power(MW)": capacity,
                  "ramp_up_rate(kW/min)": 1000, "ramp_down_rate(kW/min)": 1000,
                  "start_up_cost(euro)": 250 if i == 0 else 10, "shut_down_cost(euro)": 0,
                  "var_gen_cost(euro/MW)": [[0, capacity/2, capacity], [0, 40 if i == 0 else 90, 60 if i == 0 else 120]],
                  "agc_configuration": {"isConnected": int(i < 2), "minLoad": 0, "maxLoad": capacity}})
        g["cost_curve_source"] = {"type": "manual_pwl", "reference": "Synthetic educational data", "currency": "EUR", "basis": "euro_per_mwh"}
        g["operating-states"] = [
            {"id": 0, "isEnabled": True, "isShutdown": True, "isOperational": False, "isTransient": False,
             "min-power": 0, "max-power": 0, "enabled-cost": 0},
            {"id": 1, "isEnabled": False, "isShutdown": False, "isOperational": True, "isTransient": False,
             "min-power": 0, "max-power": capacity, "user_min_power": 0, "user_max_power": capacity, "enabled-cost": 0},
        ]
        g["operating-state-transitions"] = [{"from": 0, "transitions": [{"id": 1, "transition-cost": 0}]},
                                             {"from": 1, "transitions": [{"id": 0, "transition-cost": 0}]}]
        g["state-transitions"] = [{"from": 0, "transitions": {"value": 1, "min-transition-time": 120 if i < 2 else 0}},
                                  {"from": 1, "transitions": {"value": 0, "min-transition-time": 60}}]
        for product in ("Primary", "Secondary", "Tertiary"):
            g[f"{product}_Active_Power_Reserves(MW)"] = [capacity/2]*2 if i < 2 else [0, 0]
            g[f"{product}_APR_Cost(euro/MW)"] = [0.01, 0.01]
        units.append(g)
    data["Generating_Units"] = units
    # Μόνο στο συνθετικό παράδειγμα δεν χρησιμοποιείται ο ειδικός αλγόριθμος setpoint.
    data["constraints"]["res_pv_dispatch_variables_constraints"] = False
    data["stochastic"] = {
        "description": "Synthetic 4-hour case; not Rodos operational data or regulatory defaults",
        "scenarios": synthetic(data, 3, 42),
        "risk": {"alpha": 0.9, "weight": 0},
        "reserve_link": True,
        "reserve_products": {p: {"response_minutes": minutes, "activation_eur_per_mwh_up": 1,
                                  "activation_eur_per_mwh_down": 1}
                             for p, minutes in (("primary", 1), ("secondary", 5), ("tertiary", 15))},
        "slack_policy": {"mode": "bounded", "caps": {"s_load_minus_": 20,
                           "s_primary_APR_": 10, "s_secondary_APR_": 10, "s_tertiary_APR_": 10,
                           "s_power_plus_": 10}},
    }
    examples = ROOT / "examples"
    examples.mkdir(exist_ok=True)
    def write(name, obj):
        (examples / name).write_text(json.dumps(obj, indent=2, ensure_ascii=False), encoding="utf-8")
    write("small_stochastic.json", data)
    write("held_out_scenarios.json", synthetic(data, 5, 2026))
    storage = deepcopy(data)
    # Χαμηλό πρώτο φορτίο ώστε η αποθήκευση να έχει ορατή οικονομική λειτουργία.
    storage["Load_forecast"] = [0, 3, 11, 12, 10]
    storage["stochastic"]["scenarios"] = synthetic(storage, 3, 42)
    storage["stochastic"]["storage"] = [{"id": "hybrid_wind_store", "capacity_mwh": 4,
        "min_mwh": 0, "initial_mwh": 2, "terminal_min_mwh": 2,
        "charge_mw": 2, "discharge_mw": 2, "charge_efficiency": 0.95, "discharge_efficiency": 0.95,
        "throughput_eur_per_mwh": 2, "grid_charge": False, "renewable_gen_id": 2}]
    storage["stochastic"]["risk"]["weight"] = 0.1
    write("small_storage_cvar.json", storage)
    # Τρισταδιακό δέντρο (ώρα 1 κοινή, διακλάδωση στις ώρες 2 και 3) με υβριδικό BESS
    # που παρέχει εφεδρεία· όλες οι νέες επιλογές αποθήκευσης είναι ενεργές.
    tree = deepcopy(storage)
    tree["stochastic"]["description"] = "Synthetic 4-hour three-stage tree with a hybrid BESS; not operational data"
    tree["stochastic"]["risk"]["weight"] = 0
    tree["stochastic"]["scenario_tree"] = {"stage_start_hours": [1, 2, 3]}
    # Ρητή ωριαία βάση κόστους αντί για τους κληρονομημένους όρους ×60 και
    # εφεδρεία που ενεργοποιείται από την προμηθευμένη ποσότητα· η FCR δεν
    # χρησιμοποιείται για ωριαίες αποκλίσεις.
    tree["stochastic"]["cost_policy"] = {"legacy_time_scaled_costs": "per_hour",
                                         "thermal_online_charge_eur_per_h": 100,
                                         "renewable_curtailment_eur_per_mwh": 1000}
    tree["stochastic"]["reserve_link_mode"] = "deploy_from_procured"
    tree["stochastic"]["reserve_products"]["primary"]["balancing_deployment"] = False
    tree["stochastic"]["scenarios"] = synthetic_tree(tree, [1, 2, 3], [1, 2, 2], seed=7)
    tree["stochastic"]["storage"][0].update({
        "terminal_min_mwh": 1, "terminal_value_eur_per_mwh": 45, "self_discharge_per_hour": 0.005,
        "max_cycles_per_horizon": 1.5, "export_limit_mw": 6,
        "reserve": {"products": {"primary": ["up", "down"], "secondary": ["up", "down"]},
                    "sustain_minutes": {"primary": 15, "secondary": 30},
                    "capacity_cost_eur_per_mw_h": {"up": 0.5, "down": 0.5}}})
    write("small_tree_bess.json", tree)
    original["stochastic"] = {"scenarios": [nominal(original)], "slack_policy": {"mode": "legacy"},
                              "reserve_link": False, "risk": {"alpha": 0.95, "weight": 0}}
    write("original_single_scenario.json", original)


if __name__ == "__main__":
    make()
