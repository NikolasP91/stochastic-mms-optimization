"""Figures for the Greek stochastic-programming chapter (docs/chapter_gr/figures).

Conceptual diagrams are drawn directly; the scenario and BESS figures are
computed from the shipped examples so they match the code.
"""

from copy import deepcopy
from pathlib import Path
import sys

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch, Rectangle  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
OUT = ROOT / "docs" / "chapter_gr" / "figures"
plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 10, "savefig.dpi": 200})
BLUE, ORANGE, GREEN, GREY, PURPLE = "#2F5597", "#C55A11", "#38761D", "#7F7F7F", "#7030A0"


def save(fig, name):
    OUT.mkdir(parents=True, exist_ok=True)
    fig.savefig(OUT / name, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def box(ax, x, y, w, h, text, color, fontsize=9.5):
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.02,rounding_size=0.08",
                                fc=color + "22", ec=color, lw=1.4))
    ax.text(x + w / 2, y + h / 2, text, ha="center", va="center", fontsize=fontsize, wrap=True)


def arrow(ax, a, b, color=GREY, style="-|>", lw=1.4):
    ax.add_patch(FancyArrowPatch(a, b, arrowstyle=style, mutation_scale=14, color=color, lw=lw))


def timeline():
    fig, ax = plt.subplots(figsize=(9, 2.6))
    ax.set_xlim(0, 10)
    ax.set_ylim(0, 3)
    ax.axis("off")
    arrow(ax, (0.3, 1.0), (9.8, 1.0), color="black")
    box(ax, 0.4, 1.5, 2.8, 1.2, "1ο στάδιο: απόφαση x\n(ένταξη, εφεδρείες)\nπριν την αβεβαιότητα", BLUE)
    box(ax, 3.7, 1.5, 2.6, 1.2, "Αποκάλυψη σεναρίου ξ_s\n(ζήτηση, ΑΠΕ)", ORANGE)
    box(ax, 6.8, 1.5, 2.9, 1.2, "2ο στάδιο: απόφαση y_s\n(κατανομή, BESS,\nενεργοποίηση εφεδρείας)", GREEN)
    for x, label in ((1.8, "«εδώ και τώρα»"), (5.0, "πληροφορία"), (8.25, "«περιμένω και βλέπω»")):
        ax.plot([x, x], [0.9, 1.1], color="black")
        ax.text(x, 0.55, label, ha="center", fontsize=9, style="italic")
    save(fig, "fig_timeline.png")


def fan_vs_tree():
    fig, axes = plt.subplots(1, 2, figsize=(10, 3.6))
    for ax, title in zip(axes, ("Δύο στάδια (βεντάλια)", "Τρία στάδια (δέντρο)")):
        ax.set_xlim(-0.3, 3.3)
        ax.set_ylim(-0.5, 4.5)
        ax.axis("off")
        ax.set_title(title, fontsize=11, color=BLUE)
    ax = axes[0]
    ax.plot(0, 2, "o", ms=14, color=BLUE)
    ax.text(0, 2.45, "ρίζα", ha="center")
    for k, y in enumerate((0, 1.33, 2.66, 4)):
        ax.plot([0, 3], [2, y], color=GREY)
        ax.plot(3, y, "o", ms=10, color=GREEN)
        ax.text(3.15, y, f"s{k+1}  π=0.25", va="center", fontsize=9)
    ax.text(1.5, -0.45, "η πλήρης διαδρομή γίνεται γνωστή αμέσως", ha="center", fontsize=9, style="italic")
    ax = axes[1]
    ax.plot(0, 2, "o", ms=14, color=BLUE)
    ax.text(0, 2.45, "ρίζα", ha="center")
    for i, ym in enumerate((0.67, 3.33)):
        ax.plot([0, 1.5], [2, ym], color=GREY)
        ax.plot(1.5, ym, "o", ms=12, color=ORANGE)
        ax.text(1.5, ym + 0.4, f"κόμβος {'ΧΥ'[i]}  π=0.5", ha="center", fontsize=9)
        for j, y in enumerate((ym - 0.67, ym + 0.67)):
            ax.plot([1.5, 3], [ym, y], color=GREY)
            ax.plot(3, y, "o", ms=10, color=GREEN)
            ax.text(3.15, y, f"s{2*i+j+1}  π=0.25", va="center", fontsize=9)
    ax.text(1.5, -0.45, "η πληροφορία αποκαλύπτεται σταδιακά", ha="center", fontsize=9, style="italic")
    save(fig, "fig_fan_vs_tree.png")


def extensive_form():
    fig, axes = plt.subplots(1, 2, figsize=(10, 4))
    titles = ("Συμπαγής μορφή (κοινό x)", "Μορφή ανά σενάριο (αντίγραφα x_s + μη προεξόφληση)")
    for ax, title in zip(axes, titles):
        ax.set_xlim(0, 10)
        ax.set_ylim(0, 10)
        ax.axis("off")
        ax.set_title(title, fontsize=10.5, color=BLUE)
        ax.invert_yaxis()
    ax = axes[0]
    ax.add_patch(Rectangle((0.5, 0.5), 2, 1.5, fc=BLUE + "55", ec=BLUE))
    ax.text(1.5, 1.25, "A", ha="center", va="center", fontsize=12)
    for k in range(3):
        y = 2.3 + 2.4 * k
        ax.add_patch(Rectangle((0.5, y), 2, 2, fc=ORANGE + "55", ec=ORANGE))
        ax.text(1.5, y + 1, f"T{k+1}", ha="center", va="center", fontsize=11)
        ax.add_patch(Rectangle((2.8 + 2.2 * k, y), 2, 2, fc=GREEN + "55", ec=GREEN))
        ax.text(3.8 + 2.2 * k, y + 1, f"W{k+1}", ha="center", va="center", fontsize=11)
    ax.text(1.5, 9.6, "x", ha="center")
    for k in range(3):
        ax.text(3.8 + 2.2 * k, 9.6, f"y{k+1}", ha="center")
    ax = axes[1]
    for k in range(3):
        y = 0.5 + 2.3 * k
        x = 0.5 + 3.1 * k
        ax.add_patch(Rectangle((x, y), 1.2, 2, fc=ORANGE + "55", ec=ORANGE))
        ax.text(x + 0.6, y + 1, f"T{k+1}", ha="center", va="center")
        ax.add_patch(Rectangle((x + 1.3, y), 1.6, 2, fc=GREEN + "55", ec=GREEN))
        ax.text(x + 2.1, y + 1, f"W{k+1}", ha="center", va="center")
        ax.text(x + 0.6, 9.6, f"x{k+1}", ha="center")
        ax.text(x + 2.1, 9.6, f"y{k+1}", ha="center")
    ax.add_patch(Rectangle((0.5, 7.6), 7.4, 1.5, fc=PURPLE + "33", ec=PURPLE))
    ax.text(4.2, 8.35, "x1 = x2 = x3   (μη προεξόφληση)", ha="center", va="center", fontsize=10)
    save(fig, "fig_extensive_form.png")


def cvar():
    import numpy as np

    costs = np.array([100, 110, 120, 135, 150, 170, 200, 260])
    probs = np.array([0.15, 0.2, 0.2, 0.15, 0.12, 0.08, 0.06, 0.04])
    alpha = 0.9
    order = np.argsort(costs)
    cum = np.cumsum(probs[order])
    var = costs[order][np.searchsorted(cum, alpha - 1e-12)]
    remaining, tail = 1 - alpha, 0.0
    for c, p in sorted(zip(costs, probs), reverse=True):
        take = min(remaining, p)
        tail += take * c
        remaining -= take
        if remaining <= 1e-12:
            break
    cvar_value = tail / (1 - alpha)
    mean = float(costs @ probs)
    fig, ax = plt.subplots(figsize=(8, 3.4))
    colors = [ORANGE if c >= var else BLUE for c in costs]
    ax.bar(costs, probs, width=7, color=colors)
    for value, label, color in ((mean, f"E[L]={mean:.1f}", GREEN), (var, f"VaR₀.₉={var}", PURPLE),
                                (cvar_value, f"CVaR₀.₉={cvar_value:.1f}", ORANGE)):
        ax.axvline(value, color=color, ls="--", lw=1.5)
        ax.text(value + 2, max(probs) * 0.95, label, color=color, fontsize=9, rotation=90, va="top")
    ax.set_xlabel("Κόστος σεναρίου L_s (χιλ. €)")
    ax.set_ylabel("Πιθανότητα π_s")
    ax.set_title("Το CVaR είναι ο μέσος όρος του χειρότερου 10% της κατανομής κόστους", fontsize=10)
    save(fig, "fig_cvar.png")


def dataflow():
    fig, ax = plt.subplots(figsize=(10, 4.4))
    ax.set_xlim(0, 10)
    ax.set_ylim(0, 5)
    ax.axis("off")
    box(ax, 0.1, 2.9, 2.5, 1.9, "Είσοδοι JSON\nGenerating_Units\nLoad_forecast[0]=ιστορικό\nConstraints, Cost_parameters", BLUE, 8.5)
    box(ax, 0.1, 0.3, 2.5, 2.3, "stochastic\nscenarios (π_s, load_mw,\nrenewables_mw, tree_path)\nrisk, reserve_link, storage,\nslack_policy, cost_policy", ORANGE, 8.5)
    box(ax, 3.2, 0.3, 3.4, 4.5, "data.validate()\n↓\nγια κάθε σενάριο s:\nlegacy MMS block (build_only)\n+ πολιτική χαλαρώσεων\n+ BESS, εφεδρείες, κόστη\n↓\nκοινές μεταβλητές 1ου σταδίου\n+ ισότητες μη προεξόφλησης\n(+ δέντρο σεναρίων)\n↓\nΕνιαίο MILP → HiGHS / CBC", GREEN, 8.5)
    box(ax, 7.2, 2.9, 2.7, 1.9, "common_schedule\nimplementable_dispatch\nfirst_stage_breakdown", PURPLE, 8.5)
    box(ax, 7.2, 0.3, 2.7, 2.3, "scenario_dispatch\n(κόστη, slacks, storage)\nexpected_metrics, CVaR\nscenario_tree, validation", PURPLE, 8.5)
    for y in (3.85, 1.45):
        arrow(ax, (2.65, y), (3.15, y))
        arrow(ax, (6.65, y), (7.15, y))
    save(fig, "fig_dataflow.png")


def rolling():
    fig, ax = plt.subplots(figsize=(9, 3))
    ax.set_xlim(0, 30)
    ax.set_ylim(0, 4)
    ax.set_yticks([])
    for k in range(3):
        y = 3 - k
        ax.add_patch(Rectangle((k, y - 0.35), 24, 0.6, fc=BLUE + "22", ec=BLUE))
        ax.add_patch(Rectangle((k, y - 0.35), 1, 0.6, fc=GREEN + "aa", ec=GREEN))
        ax.add_patch(Rectangle((k + 1, y - 0.35), 1, 0.6, fc=ORANGE + "88", ec=ORANGE))
        ax.text(-0.3, y - 0.05, f"Επίλυση {k+1}", ha="right", va="center", fontsize=9)
    ax.set_xlabel("Ώρα")
    ax.text(25.5, 2.9, "ορίζοντας H=24", fontsize=9)
    ax.add_patch(Rectangle((25.2, 1.8), 0.8, 0.4, fc=GREEN + "aa", ec=GREEN))
    ax.text(26.2, 2.0, "εκτελείται", va="center", fontsize=9)
    ax.add_patch(Rectangle((25.2, 1.1), 0.8, 0.4, fc=ORANGE + "88", ec=ORANGE))
    ax.text(26.2, 1.3, "δεσμευμένο", va="center", fontsize=9)
    save(fig, "fig_rolling.png")


def scenarios_and_bess():
    from mms.stochastic.data import load
    from mms.stochastic.model import solve

    data = load(ROOT / "examples/small_stochastic.json")
    fig, axes = plt.subplots(1, 2, figsize=(10, 3.4))
    hours = range(1, 5)
    for s, color in zip(data["stochastic"]["scenarios"], (BLUE, ORANGE, GREEN)):
        axes[0].plot(hours, s["load_mw"], "-o", color=color, label=s["id"])
        axes[1].plot(hours, s["renewables_mw"]["2"], "-o", color=color, label=s["id"])
    axes[0].plot(hours, data["Load_forecast"][1:], "k--", label="πρόβλεψη")
    axes[1].plot(hours, data["Generating_Units"][2]["Production_Forecast"], "k--", label="πρόβλεψη")
    axes[0].set_title("Ζήτηση ανά σενάριο (MW)", fontsize=10)
    axes[1].set_title("Διαθέσιμη αιολική παραγωγή (MW)", fontsize=10)
    for ax in axes:
        ax.set_xlabel("Ώρα t")
        ax.set_xticks(list(hours))
        ax.legend(fontsize=8)
    save(fig, "fig_scenarios.png")

    full, tree = bess_information_cases()
    fig, axes = plt.subplots(1, 2, figsize=(10, 3.4), sharey=True)
    for ax, case, title in ((axes[0], full, "Δύο στάδια, πλήρης διαδρομή"),
                            (axes[1], tree, "Δέντρο: διακλάδωση στην ώρα 3")):
        result = solve(case)
        for (sid, output), color in zip(result["scenario_dispatch"].items(), (BLUE, ORANGE)):
            energy = output["storage"]["hybrid_wind_store"]["energy_mwh"]
            ax.plot(range(0, 5), energy, "-o", color=color, label=sid, alpha=0.85)
        ax.axvspan(0, 2, color=GREY, alpha=0.12)
        ax.set_title(f"{title}\nE[κόστος]={result['expected_cost_eur']:.2f} €", fontsize=10)
        ax.set_xlabel("Ώρα t (γκρι: κοινή πληροφορία)")
        ax.set_xticks(range(0, 5))
    axes[0].set_ylabel("Ενέργεια BESS E_t (MWh)")
    axes[1].legend(fontsize=8)
    save(fig, "fig_bess_tree.png")


def bess_information_cases():
    """Two equiprobable paths, identical in hours 1-2, load x0.8 / x1.25 in hours 3-4."""
    from mms.stochastic.data import load

    base = load(ROOT / "examples/small_storage_cvar.json")
    base["stochastic"]["risk"]["weight"] = 0
    template = base["stochastic"]["scenarios"][0]
    scenarios = []
    for sid, factor in (("χαμηλό_αργότερα", 0.8), ("υψηλό_αργότερα", 1.25)):
        s = deepcopy(template)
        s.update(id=sid, probability=0.5)
        s["load_mw"] = s["load_mw"][:2] + [v * factor for v in s["load_mw"][2:]]
        scenarios.append(s)
    full = deepcopy(base)
    full["stochastic"]["scenarios"] = scenarios
    tree = deepcopy(full)
    tree["stochastic"]["scenario_tree"] = {"stage_start_hours": [1, 3]}
    for s, branch in zip(tree["stochastic"]["scenarios"], ("low", "high")):
        s["tree_path"] = ["root", branch]
    return full, tree


def main():
    timeline()
    fan_vs_tree()
    extensive_form()
    cvar()
    dataflow()
    rolling()
    scenarios_and_bess()
    print(f"Figures in {OUT}")


if __name__ == "__main__":
    main()
