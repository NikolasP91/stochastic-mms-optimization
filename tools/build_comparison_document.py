"""Create the implementation comparison as an editable Word document.

Documentation dependency: python-docx==1.2.0.
Run from the workspace with: python tools/build_comparison_document.py
"""

import json
from pathlib import Path

from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT, WD_CELL_VERTICAL_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches, Pt, RGBColor


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "docs/MMS_Deterministic_vs_Stochastic_Comparison.docx"
NAVY = "17324D"
TEAL = "087E8B"
GRAY = "516170"
doc = Document()
section = doc.sections[0]
section.page_width, section.page_height = Inches(8.27), Inches(11.69)
section.top_margin, section.bottom_margin = Inches(0.7), Inches(0.65)
section.left_margin, section.right_margin = Inches(0.7), Inches(0.7)
section.header_distance, section.footer_distance = Inches(0.28), Inches(0.3)
normal = doc.styles["Normal"]
normal.font.name = "Calibri"
normal.font.size = Pt(10.5)
normal.paragraph_format.space_after = Pt(6)
normal.paragraph_format.line_spacing = 1.08
for name, size, color in (("Title", 29, NAVY), ("Subtitle", 14, GRAY),
                          ("Heading 1", 19, NAVY), ("Heading 2", 12, TEAL)):
    style = doc.styles[name]
    style.font.name = "Calibri"
    style.font.size = Pt(size)
    style.font.color.rgb = RGBColor.from_string(color)
    style.paragraph_format.space_before = Pt(10)
    style.paragraph_format.space_after = Pt(7)
    style.paragraph_format.keep_with_next = True
header = section.header.paragraphs[0]
header.text = "MMS OPTIMIZATION  /  MODEL CHANGE DOCUMENTATION"
header.runs[0].font.size = Pt(8)
header.runs[0].font.color.rgb = RGBColor.from_string(GRAY)
footer = section.footer.paragraphs[0]
footer.alignment = WD_ALIGN_PARAGRAPH.RIGHT
footer.add_run("12 October 2026  •  Version 1.1  |  Page ").font.size = Pt(8)
field = OxmlElement("w:fldSimple")
field.set(qn("w:instr"), "PAGE")
footer._p.append(field)
doc.core_properties.title = "MMS Optimization: Deterministic to Stochastic RDAS"
doc.core_properties.subject = "Changes to variables, constraints, objective and operational interpretation"
doc.core_properties.author = "MMS Optimization project"
doc.core_properties.keywords = "RDAS, stochastic MILP, PuLP, reserves, CVaR, storage"


def p(text, bold_lead=None):
    paragraph = doc.add_paragraph()
    if bold_lead and text.startswith(bold_lead):
        paragraph.add_run(bold_lead).bold = True
        paragraph.add_run(text[len(bold_lead):])
    else:
        paragraph.add_run(text)
    return paragraph


def h(text):
    doc.add_heading(text, level=2)


def page(title):
    paragraph = doc.add_heading(title, level=1)
    paragraph.paragraph_format.page_break_before = True


def equation(text, number):
    paragraph = doc.add_paragraph()
    paragraph.paragraph_format.left_indent = Inches(0.12)
    paragraph.paragraph_format.space_before = Pt(3)
    paragraph.paragraph_format.space_after = Pt(7)
    # Native Office Math: equations remain editable in Microsoft Word.
    math = OxmlElement("m:oMath")
    run = OxmlElement("m:r")
    value = OxmlElement("m:t")
    value.text = text
    run.append(value)
    math.append(run)
    paragraph._p.append(math)
    paragraph.add_run(f"   ({number})").font.size = Pt(9)


def table(headers, rows, widths=None):
    result = doc.add_table(rows=1, cols=len(headers))
    result.alignment = WD_TABLE_ALIGNMENT.CENTER
    result.autofit = False
    result.style = "Table Grid"
    if widths is None:
        widths = [6.87 / len(headers)] * len(headers)
    for column, width in zip(result.columns, widths):
        column.width = Inches(width)
    for i, title in enumerate(headers):
        result.rows[0].cells[i].text = title
    for row in rows:
        cells = result.add_row().cells
        for i, text in enumerate(row):
            cells[i].text = str(text)
    for ri, row in enumerate(result.rows):
        properties = row._tr.get_or_add_trPr()
        no_split = OxmlElement("w:cantSplit")
        properties.append(no_split)
        if ri == 0:
            repeat = OxmlElement("w:tblHeader")
            properties.append(repeat)
        for ci, cell in enumerate(row.cells):
            cell.width = Inches(widths[ci])
            cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
            tcpr = cell._tc.get_or_add_tcPr()
            shade = OxmlElement("w:shd")
            shade.set(qn("w:fill"), NAVY if ri == 0 else ("F0F5F8" if ri % 2 else "FFFFFF"))
            tcpr.append(shade)
            for paragraph in cell.paragraphs:
                paragraph.paragraph_format.space_before = Pt(3)
                paragraph.paragraph_format.space_after = Pt(3)
                paragraph.paragraph_format.line_spacing = 1.02
                for run in paragraph.runs:
                    run.font.name = "Calibri"
                    run.font.size = Pt(9)
                    if ri == 0:
                        run.bold = True
                        run.font.color.rgb = RGBColor(255, 255, 255)
    doc.add_paragraph().paragraph_format.space_after = Pt(0)
    return result


doc.add_paragraph("TECHNICAL COMPARISON  •  RDAS / ΚΗΕΠ", style="Subtitle")
doc.add_heading("From deterministic to\nstochastic scheduling", level=0)
p("MMS Optimization | Implementation documentation", bold_lead="MMS Optimization")
p("Version 1.1  •  12 October 2026")
h("Purpose")
p("Explain what changed in the implemented hourly Rolling Day-Ahead Scheduling model: "
  "which decisions remain common, which depend on the scenario, which variables and constraints "
  "were added, and how the objective now accounts for expected cost and optional risk.")
h("The main change")
p("The deterministic model optimizes one load/renewable forecast. The stochastic model optimizes "
  "one shared pre-revelation schedule against several joint forecast paths, with conditional "
  "dispatch for each path. All scenario blocks are coupled in one MILP and solved together.")
table(["Aspect", "Deterministic baseline", "Stochastic extension"], [
    ("Uncertainty", "One forecast trajectory", "Joint paths with explicit probabilities"),
    ("Commitment and reserves", "Optimized for that trajectory", "Common across all supported scenarios"),
    ("Dispatch", "One power trajectory", "Scenario-specific recourse"),
    ("Cost criterion", "Cost for the input forecast", "Expected total cost; optional CVaR"),
    ("Optional additions", "No active storage algebra", "Reserve activation, storage, maximum ON and rolling handover"),
], [1.35, 2.65, 2.87])
h("Reading guide")
p("Sections 1–3 define the structure and variable changes; sections 4–6 explain the constraints; "
  "sections 7–8 explain the objective and risk treatment. Sections 9–10 cover rolling use, "
  "verification and the implementation boundaries. Section 11 records the implementation "
  "review and the corrections included in version 1.1.")
p("Scope: this document describes the supplied code and the implemented extension. Optional "
  "features are identified explicitly. Preserving the baseline algebra does not establish full "
  "compliance with all island-market or station-specific requirements.", bold_lead="Scope:")

page("1. Model structure, data and time")
h("One coupled extensive-form problem")
p("The original constraint builder now accepts build_only=True. It returns the deterministic "
  "PuLP model without solving or writing its MPS file. Each scenario uses a copy of that "
  "model, with updated decision-period load and renewable forecasts. Equalities connect "
  "the first-stage variables across copies. The original deterministic runner remains available.")
table(["Notation", "Meaning"], [
    ("g ∈ G; g ∈ C; r ∈ R", "All units; legacy thermal-schema dispatchable units; wind/other RES and PV units."),
    ("t ∈ {1,…,H}; t = 0", "Hourly decision periods; fixed historical initial condition."),
    ("s ∈ S; π[s]", "Positive-probability joint scenario; probability. Validated zero-weight paths are omitted."),
    ("k ∈ K[g]; (k,l) ∈ E[g]", "Input operating states and permitted transition arcs, including self-loops."),
    ("j ∈ J; b ∈ B", "Enabled reserve products (primary, secondary, tertiary); storage assets."),
    ("D[t,s]; W[r,t,s]; A[g,t]", "Load, renewable resource and known technical availability, in MW."),
    ("Δ; x; y[s]", "Period length of 1 hour; common decisions; scenario-specific recourse."),
], [2.0, 4.87])
h("Time indexing is preserved")
p("For the supplied 24-hour case, Load_forecast has 25 entries: index 0 belongs to the previous "
  "hour and indices 1–24 are decisions. Unit availability and Production_Forecast have 24 "
  "entries, accessed at t−1. New scenario arrays contain exactly H decision values. Initial "
  "power and operating-state flags remain identical across scenarios.")
h("New inputs and validation")
p("The added stochastic JSON section contains scenarios (id, probability, load_mw and "
  "renewables_mw), risk settings and a slack policy. Optional sections declare reserve response "
  "times/activation prices, storage, maximum continuous ON and inherited obligations. "
  "Probabilities must be nonnegative and sum to one; duplicate IDs, wrong horizons, "
  "nonfinite values and inconsistent initial states are rejected. Bounded mode rejects "
  "renewable paths above known availability. Unit IDs must match their list positions.")
p("The synthetic generator uses joint AR(1) paths with temporal dependence and a common "
  "weather factor. Equal Monte Carlo weights are justified by sampling; marginal P10/P50/P90 "
  "values are not treated as three equiprobable paths. Conventional outages are excluded.")

page("2. Existing variables: what changed")
p("First stage means a decision made before the scenario is revealed. Recourse means a "
  "conditional decision after revelation. The implementation stores scenario copies of most "
  "first-stage variables, but equality constraints make their values identical.")
table(["Variable / code family", "Before", "After"], [
    ("u[g,t] — state_", "Binary online status", "First stage; identical in all paths."),
    ("v[g,t], w[g,t] — startup_, shutdown_", "Binary startup and shutdown", "First stage; same commitment transitions."),
    ("z[g,t,k] — u_2_", "Binary operating-state selection", "First stage; actual input states and graph retained."),
    ("a[g,t,k,l] — transition_arc_", "Continuous [0,1] arc; exact binary AND of state choices", "First stage; same chosen arc and transition cost."),
    ("r↑/r↓[g,t,j] — *_ActPR_plus/minus", "Procured reserve MW", "First stage; capacities shared across scenarios."),
    ("p[g,t,s] — power_", "Single dispatch trajectory p[g,t]", "Recourse; one physical dispatch per path."),
    ("PWL increments/selectors — delta_, u_1_", "One production-cost representation", "Recourse; price each path’s actual output."),
    ("Forbidden-zone selectors — y_zone_", "Selected side of each prohibited band", "Recourse; different feasible bands by path."),
    ("setpoint*, grid-capacity selectors", "Forecast-specific RES/PV allocation", "Recourse; original allocation algebra retained."),
    ("*_APRR, y_plus_, y_minus_", "Requirement envelopes and dispatch-dependent reserve selectors", "Recourse; not new purchased capacities."),
    ("s_*, ramp_relax_", "Technical/shortfall slacks with original domains", "Recourse; optionally capped or fixed to zero."),
], [2.1, 2.1, 2.67])
p("Renewable injection uses the same power variables. Curtailment W−p is reported as a "
  "derived quantity; the extension does not create a separate curtailment decision variable. "
  "Load shedding likewise reuses the existing s_load_minus variable.")
p("The name ActPR in the inherited code denotes reserve capacity, not activated reserve "
  "energy. New activation variables, listed next, provide that missing distinction.")

page("3. New variables and their domains")
table(["Symbol / code family", "Stage and domain", "Purpose / enabled when"], [
    ("p⁰[g,t] — reference_", "First stage; 0 ≤ p⁰ ≤ availability; MW", "Common balancing reference; reserve_link=true."),
    ("e↑[g,t,j,s] — activation_*_up_", "Recourse; continuous ≥ 0; MW", "Upward dispatch adjustment, bounded by purchased reserve."),
    ("e↓[g,t,j,s] — activation_*_down_", "Recourse; continuous ≥ 0; MW", "Downward adjustment; reserve_link=true."),
    ("bᴬ[g,t,s] — activation_direction_", "Recourse; binary", "Prevents simultaneous upward and downward activation."),
    ("h[b,t,s] — storage_charge_", "Recourse; 0…charge_mw; MW", "Charging power for each declared store."),
    ("d[b,t,s] — storage_discharge_", "Recourse; 0…discharge_mw; MW", "Discharging power for each declared store."),
    ("E[b,t,s] — storage_energy_", "Recourse; min_mwh…capacity_mwh; MWh", "Stored energy / SOC as energy, not percentage."),
    ("m[b,t,s] — storage_mode_", "Recourse; binary", "Selects charge mode versus discharge mode."),
    ("η — cvar_eta", "Global risk auxiliary; unrestricted EUR", "Optimized tail threshold; risk.weight > 0."),
    ("ξ[s] — cvar_excess_", "Scenario risk auxiliary; continuous ≥ 0; EUR", "Excess total cost above η; risk.weight > 0."),
], [2.22, 2.13, 2.52])
h("Quantities that are not new decision variables")
p("Scenario probabilities, forecasts, response times, activation prices, storage efficiencies, "
  "terminal targets, elapsed ON hours and residual transition times are input parameters. "
  "Expected costs, expected energy metrics, curtailment and empirical CVaR are calculated outputs. "
  "Maximum ON and rolling handover add constraints or update parameters; they do not introduce "
  "a new commitment-variable family.")
h("Interpretation of the common schedule")
p("Commitment, state transitions and capacity allocations can be committed in advance. "
  "Reference output p⁰ is a balancing anchor: the implementation does not impose a separate "
  "ramp trajectory or forbidden-zone selection on it. Conditional actual dispatch p is what "
  "satisfies the scenario’s technical constraints. Neither p⁰ nor mean scenario dispatch should "
  "automatically be issued as an executable dispatch instruction.")

page("4. Retained and scenario-indexed constraints")
h("New coupling: nonanticipativity")
equation("x[s] = x[s₀]     for every s ∈ S", "1")
p("Here x includes commitment, startup/shutdown, operating-state selections, transition arcs "
  "and all six reserve-capacity families. Reference output is a single shared variable. "
  "Without this coupling, separate scenario solves would assume advance knowledge of the path.")
h("Balance now holds for every scenario")
equation("∑g p[g,t,s] + ∑b (d[b,t,s] − h[b,t,s]) + ℓ[t,s] = D[t,s]", "2")
p("ℓ is existing load shedding. The original surplus-dumping variable remains fixed at zero. "
  "Storage contributes net injection only when configured. Without storage, the balance is "
  "the original equation repeated with scenario-specific demand and dispatch.")
table(["Original restriction", "Treatment in the stochastic model"], [
    ("Power bounds and availability", "Same state-dependent minimum/maximum, nameplate, AGC and availability rules, for every path."),
    ("Startup/shutdown logic", "Same logical equations, linked to common online decisions."),
    ("Minimum ON/OFF and state dwell", "Same enabled timing rules and transient preprocessing; common state decisions."),
    ("Ramps and initial output", "Same limits for each path, including observed output at t=0; no new startup exemption."),
    ("PWL production costs", "Same convex/nonconvex construction, applied to actual scenario production."),
    ("Forbidden zones; must-run; testing/OOS", "Same enabled algebra; scenario selectors/dispatch and selected slack policy."),
    ("Reserve requirements", "Same enabled sizing expressions and eligibility rules in every path."),
    ("RES/PV allocation", "Same enabled setpoint/grid-capacity logic with scenario forecasts."),
], [2.05, 4.82])
h("Additional renewable and load bounds in bounded mode")
equation("0 ≤ p[r,t,s] ≤ W[r,t,s] ≤ A[r,t]", "3")
equation("0 ≤ ℓ[t,s] ≤ min(D[t,s], declared load-shedding cap)", "4")
p("These tighten legacy behavior deliberately. A permitted renewable tracking slack cannot "
  "override the hard resource bound. Their effect is separate from merely adding a scenario index.")

page("5. New reserve-activation restrictions")
p("Enabled by reserve_link=true and applied to legacy thermal-schema dispatchable units. "
  "The input must declare response_minutes and incremental activation prices for each enabled product.")
h("Dispatch adjustments must be covered by purchased capacity")
equation("p[g,t,s] = p⁰[g,t] + ∑j e↑[g,t,j,s] − ∑j e↓[g,t,j,s]", "5")
equation("0 ≤ e↑[g,t,j,s] ≤ r↑[g,t,j];   0 ≤ e↓[g,t,j,s] ≤ r↓[g,t,j]", "6")
equation("r↑[g,t,j] ≤ RU[g] τ[j] / 1000;   r↓[g,t,j] ≤ RD[g] τ[j] / 1000", "7")
p("RU and RD are the existing kW/min rates and τ is response time in minutes. Equation (7) "
  "therefore limits capacity to the MW that can be delivered within that response time. "
  "The cumulative response envelope added in version 1.1 also prevents simultaneous products "
  "from reusing the same ramp capability; see equation (26).")
h("Common reference must leave enough headroom and footroom")
equation("p⁰[g,t] + ∑j r↑[g,t,j] ≤ ∑k Pmax[g,t,k] z[g,t,k]", "8")
equation("p⁰[g,t] + ∑j r↑[g,t,j] ≤ A[g,t]", "9")
equation("p⁰[g,t] − ∑j r↓[g,t,j] ≥ ∑k Pmin[g,t,k] z[g,t,k]", "10")
p("The sum is across primary, secondary and tertiary products. Capacity is required "
  "simultaneously; the same MW is not reused for several products in this extension.")
h("Activation direction")
equation("∑j e↑[g,t,j,s] ≤ A[g,t] bᴬ[g,t,s]", "11")
equation("∑j e↓[g,t,j,s] ≤ A[g,t] (1 − bᴬ[g,t,s])", "12")
p("This binary choice prevents simultaneous up/down activation. The bound is known availability, "
  "rather than an arbitrary global Big-M.")
h("Important consequence of preserving the old reserve rows")
p("The baseline also reserves headroom/footroom around actual dispatch p. Those rows remain. "
  "Together with equations (8)–(10), the formulation is conservative: reserves must still be "
  "available after forecast-balancing activation. No original reserve requirement is replaced "
  "by scenario sampling, and no new N−1/N−2 outage model is claimed. Legacy largest-unit/two-unit "
  "capacity-sizing proxies retain their original meaning.")

page("6. Storage and additional operating limits")
h("Storage is new to the inspected baseline")
equation("E[b,t,s] = E[b,t−1,s] + ηc[b] h[b,t,s] Δ − d[b,t,s] Δ / ηd[b]", "13")
equation("Emin[b] ≤ E[b,t,s] ≤ Emax[b];   E[b,0,s] = Einitial[b]", "14")
equation("0 ≤ h[b,t,s] ≤ Hmax[b] m[b,t,s]", "15")
equation("0 ≤ d[b,t,s] ≤ Dmax[b] (1 − m[b,t,s])", "16")
equation("E[b,H,s] ≥ Eterminal[b]", "17")
p("Δ=1 hour is implicit in the code. Efficiencies lie in (0,1]. Rated charge/discharge powers "
  "are the exact bounds in the binary disjunction, preventing simultaneous charging and "
  "discharging. A terminal minimum prevents unpriced depletion according to the chosen target; "
  "the example sets that target equal to initial energy.")
p("Renewable-only charging additionally requires h[b,t,s] ≤ p[r(b),t,s]. Each linked renewable "
  "unit can feed at most one such store. Gross renewable production enters balance once and "
  "charging subtracts it. grid_charge must be explicitly true to omit this coupling. "
  "Storage does not provide reserves in this implementation.")
h("Optional maximum continuous ON")
equation("∑k=max(1,t−M[g])…t u[g,k] + Hhist[g,t] ≤ M[g]", "18")
p("M[g] is the allowed number of consecutive online hours. Hhist counts known consecutive "
  "historical ON entries in the same M+1-hour window. This hard restriction is new and only "
  "applies when maximum_on supplies both the maximum and elapsed history. For example, "
  "a three-hour maximum with two hours already online cannot permit two more consecutive hours.")
h("Remaining maximum state dwell at a rolling boundary")
equation("∑t=1…R+1 z[g,t,k₀] ≤ R     when R < H", "19")
p("k₀ is the initial operating state and R is its remaining maximum stay. This requires an "
  "exit within R+1 periods. In particular, R=0 forces departure in the next period, addressing "
  "the zero-remainder case skipped by the original helper.")
p("The hybrid extension is an aggregate RES-plus-storage representation. Shared export limits, "
  "station contracts and detailed charging rights are not supplied. If legacy grid/setpoint "
  "logic is enabled, it still applies to gross renewable production, including store charging.")

page("7. Objective: from one forecast to expected cost")
h("Baseline and risk-neutral extension")
equation("Deterministic:   min C₀(x) + Cdet(y; D, W)", "20")
equation("Stochastic:   min C₀(x) + ∑s π[s] C[s](y[s])", "21")
p("C₀ contains common costs. C[s] contains path-dependent dispatch costs, new activation/storage "
  "costs when enabled, inherited renewable-priority terms and permitted penalties.")
table(["Cost component", "Treatment", "Difference from baseline"], [
    ("Startup / shutdown", "First stage; EUR per event", "Same coefficients and events, common across paths."),
    ("Operating state / transitions / online", "First stage", "Same costs. Inherited online charge remains 100 × 60 EUR per online hour."),
    ("Reserve capacity", "First stage", "Same enabled procurement coefficients, paid once through probability weighting."),
    ("PWL production", "Scenario dependent", "Charge actual output p, then weight by π[s]. Reference p⁰ is unpriced."),
    ("Activation service", "New recourse cost", "Σ activation_eur_per_mwh × e × Δ; separate up/down prices."),
    ("Storage throughput", "New recourse cost", "Σ throughput_eur_per_mwh × (h+d) × Δ."),
    ("Shortfall / technical slacks", "Scenario dependent", "Original penalty coefficients; expected penalty and optional finite caps."),
    ("Renewable-priority terms", "Scenario dependent", "Original reward/curtailment objective retained and reported separately."),
], [1.8, 1.75, 3.32])
h("Why common costs are not multiplied by the number of paths")
equation("L[s] = C₀(x) + C[s](y[s]);   ∑s π[s] L[s] = C₀(x) + ∑s π[s] C[s]", "22")
p("The implementation sums complete scenario objectives, but verifies identical first-stage "
  "coefficients and enforces ∑π=1. Thus common costs occur once. Actual production already "
  "includes activation; its PWL fuel/energy cost is not charged again against p⁰. Activation "
  "prices must represent incremental service costs rather than a second fuel bill.")
p("New energy prices use EUR/MWh. Original PWL scaling follows cost_curve_time_unit: 60 for "
  "per-minute coefficients, 1 for hourly EUR/MWh or per-period coefficients. Original "
  "state/capacity charges retain their ×60 convention; event costs are not duration-scaled.")

page("8. Risk, penalties and renewable priority")
h("Optional CVaR changes the optimization criterion")
equation("min ∑s π[s] L[s] + λ { η + [1/(1−α)] ∑s π[s] ξ[s] }", "23")
equation("ξ[s] ≥ L[s] − η;   ξ[s] ≥ 0;   η unrestricted", "24")
p("α∈(0,1) selects the upper cost tail and λ≥0 controls its importance. For example, α=0.90 "
  "targets the worst 10% of probability mass; λ=0.1 adds 10% of that tail-cost measure to "
  "expected cost. The CVaR loss is total scenario cost, including first-stage cost, penalties "
  "and renewable-priority terms. λ=0 gives the risk-neutral model and adds no CVaR variables.")
p("This is an exact linear reformulation for the finite scenario distribution. The model "
  "remains a MILP. Reported CVaR is also independently reconstructed from the probability "
  "distribution, including a fractional share of a scenario at the tail boundary.")
h("Explicit slack policy")
table(["Policy", "Effect"], [
    ("legacy", "Preserves original slack domains and forecast conventions; used for exact baseline regression."),
    ("bounded", "All s_* and ramp_relax_* variables fixed to zero unless an explicit finite prefix cap is supplied."),
    ("Permitted slack", "Longest prefix match selects the cap; existing binary upper bounds remain. A positive original penalty is required."),
    ("Load loss", "Cap additionally limited by the scenario’s demand; never larger than the load."),
    ("Always hard additions", "Nonanticipativity, activation limits, storage physics and configured maximum ON; no new violation variables."),
], [1.45, 5.42])
p("The small example permits bounded load shedding, reserve shortage and renewable tracking "
  "curtailment, but no ramp, forbidden-zone, must-run or transition violation. Reports show "
  "each nonzero slack, its upper bound, penalty coefficient and contribution in EUR.")
h("Renewable priority is inherited, not newly proven")
p("With the original allocation algorithm enabled, its setpoint reward and constraints remain. "
  "With it disabled, the inherited alternative uses 1000 × 60 × (forecast − power) for the "
  "legacy RES group; this alternative excludes PV. These are weighted objectives, not a "
  "proved lexicographic priority rule. Original tariffs, penalty magnitudes and the hard-coded "
  "online cost remain study assumptions requiring calibration.")
p("Output separates operating_cost_eur, penalty_cost_eur and renewable_priority_cost_eur. "
  "Their sum is the scenario total. The total objective can therefore differ from actual "
  "cash operating expenditure; renewable rewards may be negative.")

page("9. Rolling operation and result interpretation")
h("New handover interface")
p("rolling.advance receives the previous input/solution, actual or estimated hourly observations "
  "for the executed prefix, and a complete refreshed input for the next horizon. It returns "
  "updated initial conditions plus a dictionary of still-binding first-stage decisions.")
table(["Transferred item", "How it is handled"], [
    ("Current generation / state", "Use final observed power and operating-state ID for each unit, not averaged dispatch."),
    ("Minimum ON/OFF", "Decrement remaining minutes; start new obligations on observed startup/shutdown."),
    ("A/B transition timing", "Carry source/destination residual obligations and maximum B dwell."),
    ("Maximum continuous ON", "Update consecutive elapsed ON hours; retain the configured maximum."),
    ("Stored energy", "Require measured/estimated final MWh for every configured store."),
    ("Prior commitments", "Shift unexecuted shared decisions into the next horizon and fix the requested prefix."),
    ("Forecasts and scenarios", "Caller supplies full refreshed paths and known availability; no automatic dropped or appended hour."),
], [1.8, 5.07])
h("Output has three distinct meanings")
p("common_schedule contains the pre-revelation commitment/state/capacity decisions and reference "
  "output. scenario_dispatch contains each conditional physical dispatch, costs and violations. "
  "expected_metrics and risk outputs are probability-weighted summaries, not dispatch instructions.")
h("Information assumption and the multistage boundary")
p("All second-stage decisions may use the entire scenario path. This assumes full-path "
  "revelation and can understate sequential operating cost, particularly with storage. Rolling "
  "re-solving updates observations and obligations but does not turn this into a multistage model.")
equation("y[t,s] = y[t,s′] whenever history[t,s] = history[t,s′]", "25")
p("A multistage extension would add these history-based equalities over a scenario tree for "
  "dispatch, storage and any later decisions until scenarios branch. That extension is "
  "described conceptually but is not implemented.")
h("Configuration matters when comparing solutions")
p("One scenario with probability one recovers the baseline only when optional changes are "
  "disabled and the legacy slack policy is selected. Bounded slacks, reserve activation linkage, "
  "storage and maximum ON can change the feasible set even with one scenario. The four-hour "
  "teaching case also has an explicitly synthetic two-state schema; it does not replace the "
  "original multi-state 24-hour instance.")

page("10. Verification and implementation traceability")
report = json.loads((ROOT / "docs/verification_report.json").read_text(encoding="utf-8"))
h("Evidence already recorded in the project")
p("The review regression run passed 231 tests and 36 subtests. In legacy single-scenario "
  "mode the original objective is reproduced at 382,562.14962105 EUR, with the same 5,191 "
  "variables and 12,032 constraints. These results establish preservation for that fixture; "
  "they do not certify every possible input or regulatory rule.")
comparison = report["comparison"]
table(["Risk-neutral comparison on the same paths", "EUR"], [
    ("RP — stochastic optimum", f"{comparison['RP']:,.6f}"),
    ("EEV — mean-data plan fixed and evaluated on all paths", f"{comparison['EEV']:,.6f}"),
    ("WS — probability-weighted perfect-information optima", f"{comparison['WS']:,.6f}"),
    ("VSS = EEV − RP", f"{comparison['VSS']:,.6f}"),
    ("EVPI = RP − WS", f"{comparison['EVPI']:,.6f}"),
], [5.3, 1.57])
out_of_sample = report["out_of_sample"]
p("Independent deterministic solves are used for WS benchmarking only. On five held-out "
  f"synthetic paths, stochastic and deterministic schedules cost {out_of_sample['stochastic']['expected_cost_eur']:,.2f} "
  f"and {out_of_sample['deterministic']['expected_cost_eur']:,.2f} EUR "
  "respectively, but both show unserved energy and reserve shortage. Algebraic validation "
  "passing means the declared constraints and slack caps hold, not that all demand is served.")
h("Where each change is implemented")
table(["Project file", "Responsibility"], [
    ("mms/model/problem.py", "Optional build_only return; original deterministic solve path retained."),
    ("mms/stochastic/model.py", "Shared-variable coupling, reserve links, storage, maximum ON, expected objective, CVaR and reports."),
    ("mms/stochastic/data.py; scenarios.py", "Scenario import/validation and separate synthetic-path generation."),
    ("mms/stochastic/rolling.py; evaluation.py", "Observed-state handover; RP/EEV/WS and held-out evaluation."),
    ("tests/test_stochastic.py", "Nonanticipativity, balance, reserve, CVaR, storage, rolling and invalid-input tests."),
], [2.7, 4.17])
h("Source qualifications")
p("The inspected first thermal unit defines six states, not an assumed seven; its IDs and "
  "flags are preserved. The file named BIOMASS actually contains two thermal, one RES and "
  "two PV units. Its legacy wind forecast reaches 8 MW for a 3 MW unit: regression mode "
  "preserves that inconsistency; bounded scenario input rejects it. No station-contract "
  "model, new outage recourse, distinct startup/shutdown ramp rates or storage reserve service "
  "is implied by the extension.")
p("References: docs/stochastic_mapping.md; docs/stochastic_formulation.md; "
  "docs/stochastic_verification.md; docs/verification_report.json. The supplied tender "
  "§§5.2.4.3–5.2.4.4.2 and March 2022 MDN Code Articles 109/111 provide the retained project "
  "context; new assumptions are not represented as requirements of that Code.")

page("11. Implementation review and corrections in version 1.1")
p("The implementation review tightened physical feasibility, input contracts, rolling "
  "handover, evaluation and reproducibility. These corrections add no new decision-variable "
  "families or objective terms. The two-stage information assumption and study limitations "
  "described above still apply. Detailed findings and regression evidence are recorded in "
  "docs/implementation_review.md.")
h("Reserve eligibility and simultaneous response")
p("In bounded mode, reserve capacities are fixed to zero for any unit with "
  "no operational state. This closes a gap in the legacy eligibility logic; legacy mode "
  "retains the original behavior for baseline regression. With reserve_link=true, all "
  "products due by each distinct response deadline must also fit within one cumulative "
  "ramp envelope, separately for upward and downward response.")
equation("∑j:τ[j]≤τ rᵈ[g,t,j] ≤ Rᵈ[g] τ / 1000     d ∈ {↑,↓}", "26")
p("Equation (26) applies at every enabled response deadline τ. R↑ and R↓ denote RU and RD "
  "in kW/min. Faster products consume response capacity at later deadlines, and products "
  "with equal deadlines are grouped. The individual bounds in equation (7) alone could "
  "otherwise allocate the same ramp capability to several simultaneous products.")
h("Input and rolling contracts")
p("Validation now rejects invalid types, missing required options and nonfinite values. "
  "In bounded mode it also rejects state-level dwell declarations on retained states that "
  "the kernel cannot enforce; supported embedded transient states remain accepted, and "
  "legacy mode preserves its original behavior. Rolling updates "
  "preserve technical unit definitions and inherited timing obligations while accepting "
  "refreshed forecasts and availability. A refreshed input cannot silently replace those "
  "definitions or erase an obligation. Evaluating a fixed schedule requires the complete "
  "common schedule, so omitted decisions cannot be reoptimized in the evaluation solve.")
h("Audited results and reproducible execution")
p("Post-solve audits check finite values, variable domains and constraint residuals, and "
  "reconcile the reconstructed expected/risk-adjusted objective with the solver objective. "
  "The separate operational_status field is degraded when permitted nonzero_slacks are used; "
  "an Optimal solver status alone does not establish service adequacy. A value of "
  "no_reported_violations describes the implemented checks, not operational certification.")
p("Default CLI runs create unique folders with input and result snapshots plus a hash "
  "manifest. Metadata records inputs, fixed decisions, source files, package versions and "
  "solver settings. Atomic JSON writes prevent partial result files. Typed optimization "
  "failures distinguish proven infeasibility from solver failures or an unvalidated result, "
  "and preserve failure diagnostics for review.")

OUTPUT.parent.mkdir(parents=True, exist_ok=True)
doc.save(OUTPUT)
print(OUTPUT)
