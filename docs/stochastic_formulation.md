# Step 2 — formulation and information timing

This document describes the implementation, including inherited limitations.
It does not assert that the prototype implements every requirement of the MDN
Code. The source audit is in `stochastic_mapping.md`.

## Sources inspected

The supplied tender, PDF pages 430–431, sections 5.2.4.3–5.2.4.4.2, describes
joint scheduling of all hours, renewable priority subject to secure operation,
energy balance, reserve coverage, technical limits, transitions and must-run
units. The supplied March 2022 MDN Code, articles 109 and 111, PDF pages 97–99,
describes distinct reserve products and balance including storage absorption.
These motivate retaining the existing constraint blocks. Exact contract,
priority and zone rules need additional modeling where absent from the original
kernel. The original traceability matrix and PDFs are retained locally.

## Indices, units and scenario support

Let $G$ be all generating units, $C\subset G$ the legacy dispatchable thermal
schema (also usable for dispatchable biomass with explicit technology metadata),
$R$ the legacy wind/other RES and PV groups, $B$ stores, $K_g$ input operating
states, $E_g$ allowed directed arcs including self-loops, and
$J=\{primary,secondary,tertiary\}\times\{up,down\}$ enabled reserve products.
Decision periods are $T=\{1,\ldots,H\}$, with $t=0$ a fixed historical state.
Positive-probability joint paths $s\in S$ have $\pi_s>0$, $\sum_s\pi_s=1$.
Zero-weight paths are validated but omitted from the extensive form.

All new power is MW, energy MWh, currency EUR. The implementation requires
$\Delta=1$ hour. Original ramp rates in kW/min convert to MW/hour by
$60/1000$. Original timers in minutes round minimum durations **up** and
maximum durations **down** to hours, after existing transient-state preprocessing.
New response times are minutes, so deliverable reserve is
$rate_{kW/min}\tau_{min}/1000$ MW.

Legacy `Load_forecast[0]` is history; `Load_forecast[t]` is decision period $t$.
Unit series use index $t-1$. Scenario series contain exactly $H$ values, never
the initial period. Current generation and initial state flags are common.
Known availability $A_{gt}$ stays identical across scenarios. Random outages
are not part of this implementation.

## Decisions and nonanticipativity

Before revelation: online $u_{gt}$, startup $v_{gt}$, shutdown $w_{gt}$,
operating state $z_{gtk}$, transition $a_{gtkl}$, purchased reserve $r^j_{gt}$,
and (when reserve linkage is enabled) reference output $p^0_{gt}$.
The same schedule must be committed without knowing which path will occur.

After revelation: generation $p_{gts}$, renewable injection $q_{gts}$,
curtailment $c_{gts}$, PWL increments/selectors, forbidden-zone selectors,
renewable setpoints/grid selectors, reserve activation $e^j_{gts}$, charge
$h_{bts}$, discharge $d_{bts}$, energy $E_{bts}$, charge-mode binary $m_{bts}$,
and allowed slacks. Legacy secondary reserve selector binaries `y_plus/minus`
remain recourse because they classify dispatch relative to limits; they are not
commitments or purchased capacities.

For each legacy block, preserve its complete constraint matrix
$A_s x_s+B_s y_s\ \{\le,=,\ge\}\ b_s$. The extensive form includes **every**
row and $x_s=x_{s_0}$ for every first-stage variable. It is solved once.
Reference variables are single shared objects. Scenario copies of first-stage
variables allow exact reuse of the existing kernel; their equalities prevent
independent scenario commitments.

Full-path recourse assumes all future uncertainty is revealed at once. It is
optimistic for sequential operation, especially storage. A multistage extension
requires a scenario tree with information history $\mathcal H_t(s)$ and
$y_{ts}=y_{ts'}$ whenever $\mathcal H_t(s)=\mathcal H_t(s')$. This must cover
charge/discharge, SOC, dispatch and any later commitments until branching.
Since the October 2026 review this tree is implemented as an **optional**
`scenario_tree` (see "Review extensions" below); without it the model remains
the two-stage full-path formulation described here.

## Objective and risk

Write total path cost as $L_s=C_0(x)+C_s(y_s)$ and minimize
$C_0+\sum_s\pi_s C_s$. The implementation equivalently minimizes
$\sum_s\pi_s L_s$; equality of first-stage coefficients is checked, so
$\sum_s\pi_s C_0=C_0$ (not $|S|C_0$).

$C_0$ contains startup, shutdown, operating-state, transition, online and
reserve-capacity costs. Preserve original scaling: operating-state and reserve
capacity coefficients are multiplied by 60, transition/startup/shutdown costs
are event costs, and the original online charge is `100 * 60` per online hour.
That hard-coded online charge is an inherited modeling assumption, not a
verified tariff. PWL cost scaling follows `cost_curve_time_unit`:
60 for legacy per-minute, 1 for EUR/MWh at hourly resolution, or 1 for already
per-period coefficients.

$C_s$ contains actual generation PWL cost, activation service cost
$\sum e^j k^j\Delta$, storage throughput cost
$\sum_b k_b(h+d)\Delta$, original renewable-priority terms and slack penalties.
Reference dispatch is unpriced. Reserve capacity is priced once; activation
costs are incremental service costs, not a second fuel bill. Actual generation
already includes the activated power. Reporting separates operating cost,
slack penalties and renewable-priority objective terms, which can be negative.

Original RES dispatch mode preserves the setpoint reward and grid-allocation
algebra. If that mode is explicitly disabled, the original alternative charges
$1000\cdot60\sum_{g\in RES,t}(W_{gts}-p_{gts})$; this alternative excludes PV
in the inherited code. These are weighted objectives, **not a proved
lexicographic renewable priority**. Their coefficients are preserved for
compatibility; the provided penalties do not establish the full priority
hierarchy required for a production regulatory implementation.

Optional risk objective is $E[L]+\lambda\operatorname{CVaR}_\alpha(L)$:

$$\min E[L]+\lambda\left(\eta+\frac1{1-\alpha}\sum_s\pi_s\xi_s\right),\qquad
\xi_s\ge L_s-\eta,\quad\xi_s\ge0,\quad\eta\in\mathbb R.$$

$0<\alpha<1$ is the upper-tail confidence level; $\lambda\ge0$ is risk weight.
CVaR includes total cost, including first-stage costs and penalties. Reported
CVaR is independently reconstructed by integrating the worst $1-\alpha$
probability mass, including fractional atoms. $\lambda=0$ gives risk neutrality.

## Physical and operating constraints

The following equations apply for each valid index; recourse rows repeat for
every $s$. Slacks are zero unless explicitly permitted by the chosen policy.

**Balance and renewables.**

$$\sum_{g\in G}p_{gts}+\sum_b(d_{bts}-h_{bts})+\ell_{ts}-o_{ts}=D_{ts},
\quad o_{ts}=0,\quad0\le\ell_{ts}\le\min(D_{ts},\bar\ell).$$

Here $\ell$ is unserved load; the original model prohibits surplus dumping
$o$. In bounded mode renewable generation has hard bounds
$0\le q_{gts}\le W_{gts}\le A_{gt}$ and reported curtailment is
$c_{gts}=W_{gts}-q_{gts}$. Legacy regression mode preserves the original
forecast slacks; its curtailment metric is clipped at zero and should not be
interpreted as certification of feasible renewable resource data.
For non-setpoint renewable units, the preserved equation is
$q-s^-+s^+=W$; for setpoint units $q-s^-\le W$. The separate hard bound in
bounded mode forbids generation above scenario availability even if a tracking
slack were permitted. Known technical availability also bounds every unit.

**State bounds and commitment.**

$$\sum_{k\in K_g}z_{gtk}=1,\quad
u_{gt}=1-\sum_{k:isShutdown(k)}z_{gtk},$$
$$\sum_k P^{min}_{gtk}z_{gtk}\le p_{gts}\le
\sum_k P^{max}_{gtk}z_{gtk},\quad p_{gts}\le A_{gt},\quad p_{gts}\le P_g^{max}.$$

Bounds incorporate existing user and AGC preprocessing. Initial $u,p,z$ are
fixed from observed inputs. The startup/shutdown inequalities are equivalently
$u_t-u_{t-1}=v_t-w_t$, $v_t\le u_t$, $v_t\le1-u_{t-1}$,
$w_t\le u_{t-1}$, $w_t\le1-u_t$.
For $k\to l\in E_g$, the continuous transition arc is exactly binary by
$a\le z_{t-1,k}$, $a\le z_{t,l}$, $a\ge z_{t-1,k}+z_{t,l}-1$, and
$\sum_{l:(k,l)\in E_g}a_{tkl}=z_{t-1,k}$. Prohibited arcs are absent.

**Minimum ON/OFF and maximum continuous ON.**
With input minimum durations $U_g,D_g$, for each startup time $t$ and
$\tau=t,\ldots,\min(H,t+U_g-1)$, enforce $u_{g\tau}+s^{on}_{g\tau}\ge v_{gt}$.
For each shutdown use $1-u_{g\tau}+s^{off}_{g\tau}\ge w_{gt}$ over $D_g$.
Inherited ON/OFF remainders fix the corresponding initial periods, with the
original priced binary slack if explicitly enabled.
Optional maximum ON $M_g$ adds
$\sum_{k=\max(1,t-M_g)}^t u_{gk}+h_{gt}\le M_g$, where $h_{gt}$ counts known
consecutive historical ON entries in the same $M_g+1$ window. This restriction
is hard and is absent unless `maximum_on` is supplied.

**Transition dwell obligations.**
For destination minimum $m^B_{gkl}$, entry $k\to l$ at $t$ imposes
$z_{g\tau l}+s^B_{g\tau}\ge z_{g,t-1,k}+z_{gtl}-1$
for $\tau=t,\ldots,t+m^B-1$ inside the horizon. Residual B time imposes
$z_{gtl}+s^{B,left}_{gt}\ge1$ in its protected prefix.
Let $e^A_{gtk}=z_{gtk}-z_{g,t-1,k}$. For a possible departure $k\to l$ at
$d\in[t,t+m^A_{gkl}-1]$, each remaining protected period $\tau\ge d$ obeys
$z_{g,d-1,k}+z_{gdl}\le2-e^A_{gtk}+s^A_{g\tau}$.
Residual A time uses the original conservative source-state lock:
$z_{gdk}\ge z_{g0k}-s^{A,left}_{g\tau}$ for every $d\le\tau$ in the prefix
whose length is the largest supplied remaining A time.
For finite maximum B dwell $M^B$, entry at $t$ and each
$v\ge t+M^B$ impose
$\sum_{\tau=t}^v z_{g\tau l}\le(v-t+1)-1+(1-z_{g,t-1,k})+s^{max}_{gklv}$.
Residual maximum B uses the same prefix-sum exclusion after its remaining time.
The rolling adapter additionally handles **zero** remaining maximum, which the
legacy helper otherwise skips, by requiring an exit in the next period.

**Ramps and mode requirements.**

$$p_{gts}-p_{g,t-1,s}\le RU_g60/1000+\rho_{gts},\qquad
p_{g,t-1,s}-p_{gts}\le RD_g60/1000+\rho_{gts}.$$

At $t=1$ use observed $p_{g0}$. These apply through startup and shutdown;
there is no invented ramp exemption. Startup/shutdown trajectories are limited
by the input state graph. Distinct startup/shutdown ramp limits and more detailed
sub-hour trajectories would require a separately verified extension.
Must-run uses $u_{gt}+s^{must}_{gt}\ge mustRun_{gt}$; testing mode fixes
$p-s^-+s^+=P^{test}_{gt}$ when enabled. OOS upper/lower instructions and their
original inequalities remain in their existing module.

**PWL and prohibited bands.**
For thermal breakpoints $b_0<\cdots<b_N$, set
$p=b_0u+\sum_j\delta_j$, $0\le\delta_j\le(b_j-b_{j-1})u$ and cost
$c_0u+\sum_j c_j\delta_j$. Convex nondecreasing slopes fill increments in
cost order. For nonconvex slopes, ordered-fill binaries enforce
$\delta_j\ge(b_j-b_{j-1})y_{j+1}$ and
$\delta_{j+1}\le(b_{j+1}-b_j)y_{j+1}$, preserving the specified curve.
For each forbidden open band $(L,U)$, binary $b$ gives
$p-s^-\le L+M b$ and $p+s^+\ge U-M(1-b)$; boundaries are permitted.
The existing `forbidden_zone_big_m` uses the unit/availability range.
All original local bounds and automatically estimated fallback M values remain
in `bounds.py` / `mip_utils.py`; the extension introduces no arbitrary global M.

## Reserve procurement and activation

Original capacities `*_ActPR_plus/minus` are shared, even though their name
looks like activation. Original product capability, AGC eligibility, state
eligibility and headroom/footroom inequalities remain in **every** scenario.
Legacy primary is subtracted before secondary, and both before tertiary;
secondary selector binaries gate certain tertiary cases. Those constraints
are preserved, not replaced by a new N−1 or N−2 interpretation.

For product/direction $j$, original requirements $R^j_{ts}$ satisfy every
enabled lower bound: coefficients times total generation, generation excluding
PV, renewable generation, renewables excluding PV, largest committed available
capacity $L_{1t}$, and two largest $L_{2t}$. The envelope has
$L_{1t}\ge A_{gt}u_{gt}$, $L_{2t}\ge A_{gt}u_{gt}+A_{ht}u_{ht}$ for distinct
conventional $g,h$ (and individual-unit bounds), both bounded by total online
capacity. Thus $R^j\ge\beta^j_m f_{mts}$ for every enabled method $m$,
and $\sum_g r^j_{gt}+s^j_{ts}=R^j_{ts}$. Requirement variables are envelopes,
not asserted to be exact maxima. Scenario sampling does not disable them.
These are inherited capacity-sizing proxies, not explicit outage recourse or
a proof of N−1/N−2 security.

With reserve linkage, for $g\in C$:

$$p_{gts}=p^0_{gt}+\sum_j e^{j,up}_{gts}-\sum_j e^{j,down}_{gts},\qquad
0\le e^{j,d}_{gts}\le r^{j,d}_{gt}\le ramp^d_g\tau_j/1000.$$

Each distinct response deadline $\tau$ also imposes the cumulative envelope

$$\sum_{j:\tau_j\le\tau}r^{j,d}_{gt}\le ramp^d_g\tau/1000,\qquad d\in\{up,down\}.$$

All products called simultaneously share the same physical ramp trajectory.
Products with equal deadlines are grouped; faster products consume part of the
response capability available by each later deadline. Individual product bounds
alone would incorrectly allow the same ramp capability to be reused.

$$p^0_{gt}+\sum_jr^{j,up}_{gt}\le\min(A_{gt},\sum_kP^{max}_{gtk}z_{gtk}),\qquad
p^0_{gt}-\sum_jr^{j,down}_{gt}\ge\sum_kP^{min}_{gtk}z_{gtk}.$$

Use one activation-direction binary and bounds $A_{gt}$ to prevent simultaneous
up/down activation. All products require simultaneous capacity; none share a
MW in this extension. In the default `reserve_link_mode`
(`post_balancing_headroom`) the retained legacy rows also reserve capacity
around **actual** dispatch, so the exact rule is
$p^0_{gt}+\sum_j r^{j,up}_{gt}+e_{gts}\le A_{gt}$: activation is capped by the
procured reserve *and* the full reserve must remain available afterwards. This
is conservative and mixes balancing with contingency semantics. The optional
mode `deploy_from_procured` rewrites those legacy capability rows around
$p^0_{gt}$, so deployment consumes procured reserve ($r-e$ remains), which is
the usual two-stage reserve-deployment model. Products with
`balancing_deployment: false` (e.g. FCR) keep their capacity rows but get no
activation variable, so hourly deviations are not attributed to them. Reference output is a balancing
anchor, not itself an issued deterministic dispatch instruction (it need not
obey forbidden-zone/ramp trajectories). Only conditioned dispatch is physical.
No reserve activation linkage is added for legacy partially-controllable units
without a fully specified dispatchable thermal schema.

## Storage and hybrid interpretation

$$E_{bts}=E_{b,t-1,s}+\eta_b^c h_{bts}\Delta-d_{bts}\Delta/\eta_b^d,$$
$$E_b^{min}\le E_{bts}\le E_b^{max},\quad E_{b0}=E_b^{initial},\quad
0\le h\le H_b m,\quad0\le d\le D_b(1-m),\quad E_{bHs}\ge E_b^{terminal}.$$

For renewable-only charging, $h_{bts}\le q_{g(b),ts}$. A renewable unit may
feed at most one such store. Gross renewable production enters the balance
once; charging subtracts it, so no energy is counted twice. `grid_charge` must
be explicitly true to omit this coupling. Optional BESS reserve, self-discharge,
terminal value, soft terminal target, SOC recovery, cycle limit, connection
(export) limit and hourly power availability are described under "Review
extensions"; without them the original aggregate model is unchanged.
The example's terminal target equals initial energy. A lower target is allowed
only as an explicit input choice. SOC is energy in MWh, not a percentage.

This is an aggregate RES-plus-storage hybrid, not a complete station contract
model: shared export limits, contractual energy offers, charging permissions
from the operator, and detailed pumping/generation rules are not supplied.
If original grid/setpoint constraints are enabled, they continue to apply to
gross RES production, conservatively including energy sent to the store.
Production use requires station-specific constraints and data.

## Strictness, bounds and penalties

`legacy` mode retains all original slack domains and forecast conventions and
exists for comparison. The original named BIOMASS fixture includes an 8 MW
wind forecast against 3 MW nameplate; regression mode preserves this inconsistency.
New bounded scenarios reject resource paths above declared availability.

Bounded mode also fixes every enabled reserve capacity to zero for a unit with
no operational state eligible for reserve. Input validation rejects unknown
stochastic options, nonfinite numbers and unsupported active dwell timers on
retained operating states. Supported transition A/B timers and transient-state
embedding remain the timing representation. Every configured slack-cap prefix
must match an active model slack; misspelled or inactive caps are rejected.

In `bounded` mode every `s_*` or `ramp_relax_*` is fixed to zero unless its
prefix has a supplied finite cap. Longest-prefix match wins; existing binary
upper bounds are retained. Permitted slacks must have a positive original
penalty coefficient. Load shedding is additionally capped by demand. Physical
state bounds, availability, balance, storage physics, nonanticipativity,
reserve activation limits and optional maximum ON remain hard.
The example permits bounded load loss, reserve shortage and renewable tracking
curtailment. It does not permit ramp, forbidden-zone, must-run or transition
violations. Reports enumerate nonzero slacks, caps, coefficients and EUR costs.
Caps and inherited penalties are explicit study assumptions, not calibrated
values of lost load or automatic regulatory defaults.

## Rolling horizon and evaluation

`rolling.advance` consumes an actual/estimated hourly prefix, updates current
power/state and measured energy, decrements residual ON/OFF and A/B transition
timers, starts new obligations on observed transitions, and carries elapsed ON
and remaining maximum B time. It requires refreshed full-horizon forecasts and
scenarios. Previously committed unexecuted decisions are shifted and fixed in
the next solve. Only the observed prefix is considered executed. Data updates
do not silently append/drop an hour or substitute mean scenario production.

The refreshed operating graph, technical timing definitions and maximum-ON
configuration must agree with the previous input. Invalid observed transitions
or incomplete committed decision prefixes fail explicitly. Remaining maximum
state dwell is carried across successive updates, including supported embedded
transient transitions; infinite/default unlimited maxima create no obligation.

For risk-neutral minimization, RP is the stochastic optimum; EV solves the
mean-data deterministic problem; EEV fixes **all** its first-stage decisions
and reevaluates against the same scenarios; WS averages independent perfect-
information optima. $VSS=EEV-RP$, $EVPI=RP-WS$. With exact solves and feasible
recourse, $WS\le RP\le EEV$. EEV infeasibility is reported, with null numeric
VSS representing infinity, rather than relaxed away. These definitions are
not applied to a nonzero CVaR objective.

Held-out evaluation fixes the trained schedule and evaluates new joint paths,
reporting cost, unserved MWh, curtailed renewable MWh, reserve-shortfall MW-hours
(a capacity-time metric, not activated energy) and solve time. It still has
full-path recourse; it is not a multistage operational simulation. Seeded paths
are independent draws from a toy joint AR(1) process, not calibrated evidence
about a real island. P10/P50/P90 are not used: marginal quantiles alone do not
specify joint path probabilities or dependence.

Held-out evaluation requires the complete common schedule, reports identical
training/evaluation paths, and leaves independence to external data provenance.
Reports reject missing or nonfinite solution values and reconcile the objective
against expected total cost plus weighted empirical CVaR. `operational_status`
flags nonzero permitted slacks independently of algebraic feasibility.

## Review extensions (October 2026)

All options below are optional; omitting them reproduces the previous model
exactly (regression tests check the original 24-hour fixture and the example
objectives). The change log is [REVIEW_CHANGES.md](REVIEW_CHANGES.md).

**Multistage scenario tree.** `scenario_tree.stage_start_hours`
$=(\tau_1=1<\tau_2<\dots<\tau_K)$ defines stages
$\mathcal T_k=\{\tau_k,\dots,\tau_{k+1}-1\}$; each scenario carries a
`tree_path` $(n_1(s),\dots,n_K(s))$. A node of stage $k$ is the prefix
$(n_1,\dots,n_k)$, so equal labels under different parents are different
nodes. Validation requires one common root, identical load and renewable data
for all scenarios sharing a node in that node's hours, and distinct complete
paths. For every $k$, node $n$ and $t\in\mathcal T_k$:

$$y_{ts}=y_{ts'}\quad\forall s,s'\ \text{with}\ (n_1,\dots,n_k)(s)=(n_1,\dots,n_k)(s'),$$

for $y\in\{p_{gt},e^j_{gt}$, activation direction, $\ell_t$, RES tracking slacks,
$h_{bt},d_{bt},E_{bt},m_{bt}\}$. Auxiliary PWL, forbidden-zone, requirement
and selector variables are determined by these and are not equated. Within a
stage, the data of all its hours are revealed at its first hour (stage-wise
discretization). Commitment, states, reserve capacity, reference power and
BESS reserve stay first-stage for the whole horizon (day-ahead RDAS). With a
tree, `implementable_dispatch` reports the root-node decisions (identical in
all scenarios) as the instruction to issue. Theory gives
$RP_{tree}\ge RP_{full\ path}$, which a test verifies. Held-out paths without
`tree_path` are evaluated with full-path recourse and the report says so.

**BESS.** For store $b$ with hourly availability $a_{bt}\in[0,1]$ and
self-discharge $\sigma_b$:

$$E_{bts}=(1-\sigma_b)E_{b,t-1,s}+\eta^c_bh_{bts}-d_{bts}/\eta^d_b,\quad
0\le h\le a_{bt}\bar H_bm,\ 0\le d\le a_{bt}\bar D_b(1-m).$$

Optional first-stage reserve $\rho^{j,u}_{bt}$ (shared variable
`storage_reserve_<product>_<up|down>_<b>_<t>`) is added to the legacy
requirement row $\sum_g r^{j,u}_{gt}+\rho^{j,u}_{bt}+s^{j,u}_{ts}=R^{j,u}_{ts}$
of every scenario and must be deliverable in every scenario:

$$\textstyle\sum_j\rho^{j,up}_{bt}\le a_{bt}\bar D_b-d_{bts}+h_{bts},\qquad
\sum_j\rho^{j,dn}_{bt}\le a_{bt}\bar H_b-h_{bts}+d_{bts}\ (\text{and}\le q_{g(b)ts}-h_{bts}+d_{bts}\ \text{without grid charging}),$$
$$\textstyle\sum_j\rho^{j,up}_{bt}\theta_j\le\eta^d_b(E_{b,k,s}-E^{min}_b),\quad
\eta^c_b\sum_j\rho^{j,dn}_{bt}\theta_j\le E^{max}_b-E_{b,k,s},\quad k\in\{t-1,t\},$$

with sustain duration $\theta_j$ in hours. The capacity cost is first-stage and
counted once. Further options: terminal value $-v_bE_{bHs}$; soft terminal
target $E_{bHs}+s^{T}_{bs}\ge E^{T}_b$ priced by
`terminal_shortfall_penalty_eur_per_mwh` (otherwise the hard target is checked
for reachability per scenario before solving); SOC recovery
$E_{bts}+s^{F}_{bts}\ge E^{min}_b$ with $E\ge0$ when the measured initial SOC
is below the operating minimum; cycle limit
$\sum_t d_{bts}/\eta^d_b\le N_b(E^{max}_b-E^{min}_b)$; hybrid connection limit
$q_{g(b)ts}+d_{bts}-h_{bts}\le X_b$. A hard terminal target outranks load
shedding; use the soft target or a terminal value when that is undesirable.
The BESS is not included in the legacy largest-unit reserve envelopes, and the
legacy grid-penetration (setpoint) limits still apply to gross RES output of a
hybrid station.

**Cost policy.** `cost_policy.thermal_online_charge_eur_per_h` replaces the
hard-coded $100\cdot60$ EUR per online thermal hour;
`legacy_time_scaled_costs: per_hour` divides the legacy minute-scaled reserve
capacity and operating-state enabled costs by 60 (EUR/MW-h and EUR/h) and sets
defaults of 100 EUR/h online charge and 1000 EUR/MWh RES curtailment;
`renewable_curtailment_eur_per_mwh` replaces the $1000\cdot60$ RES weight and
extends it to PV (only with the setpoint algorithm disabled). The default keeps
legacy coefficients. `first_stage_breakdown` reports the online charge and the
BESS reserve cost.

**Other corrections.** In bounded mode RES/PV reserve is bounded by the
scenario resource ($q+\sum r^{up}\le W_s$, $q-\sum r^{dn}\ge0$). Slacks of rows
containing only first-stage variables (must-run, state timers, maximum ON) are
attributed to `first_stage_cost_eur` and tagged `stage: first`.
`maximum_on.elapsed_hours` must be at least 1 for an online unit; an optional
`violation_penalty_eur_per_h` turns the rule into a priced recovery and allows
an observed overrun. `reserve_link` needs at least one enabled product.
Zero-probability paths are listed in an `EXCLUDED_ZERO_PROBABILITY` note.
`compare()` reports a non-additive VSS decomposition (commitment only,
commitment and reserves, full). For the base example it is about 0, 485 and
3108 EUR: the reported VSS mainly reflects freezing reserve awards and
reference points under reserve linkage, and most of the EEV excess is
load-shedding penalty, not the value of a stochastic commitment.

**Rolling.** Committed prefixes no longer fix startup/shutdown/transition arcs,
which follow from the observed state; `released_units` releases a tripped or
failed unit's commitments and reserve awards; SOC metering noise within
$10^{-6}$ MWh is clamped; a `maximum_on` overrun is carried when priced and
otherwise clamped (immediate shutdown required). When a fixed schedule is
infeasible, the error states whether the problem is feasible without it.
