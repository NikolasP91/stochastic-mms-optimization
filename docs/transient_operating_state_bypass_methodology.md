# Transient Operating State Bypass Methodology

This document explains, at a high level, how the project handles transient
operating states in RDAS/DS runs.

## 1. The Problem

RDAS/DS is modeled with fixed dispatch periods. In our current cases, one
period can represent 60 minutes.

Some thermal/conventional operating states may last only a few minutes, for
example:

- synchronization for 5 minutes;
- desynchronization for 25 minutes;
- a short startup or shutdown intermediate state.

An hourly binary variable cannot accurately represent a 5-minute state. If we
force that state to exist for a whole hourly period, the model may become too
conservative or physically misleading.

So the project uses this rule:

> If a state is truly transient and shorter than the dispatch period, the model
> may bypass it by replacing the two-step path through that state with one
> direct transition arc.

## 2. The Basic Idea

Assume the input has this operating-state path:

```text
A -> T -> B
```

where:

- `A` is the state before the transient state;
- `T` is the transient operating state;
- `B` is the state after the transient state.

If `T` is eligible for bypassing, the preprocessing step changes the graph to:

```text
A -> B
```

The transient state `T` is removed from the explicit hourly MIP model.

The direct transition `A -> B` keeps audit metadata saying that `T` was skipped.
It also preserves the combined transition cost of `A -> T` plus `T -> B`.

## 3. When a State Can Be Bypassed

A state is considered for bypassing only if it is explicitly marked as
transient. The code recognizes any of these markers:

```json
"isTransient": true
```

or:

```json
"time_resolution_class": "transient"
```

or a transient role such as:

```json
"state_role": "synchronization"
```

or:

```json
"state_role": "desynchronization"
```

When `isTransient` is present, it is the authoritative user choice:

```json
"isTransient": false
```

keeps the state explicit even if `state_role` or `time_resolution_class` would
otherwise mark it as transient. If `isTransient` is omitted, the older
`time_resolution_class` and `state_role` markers are used as fallbacks.

The default recognized roles are:

```text
transient, synchronization, desynchronization, startup, shutdown
```

After a state is marked as transient, the code checks its timing data. The state
is bypassed only if all positive timing values attached to that state or to its
incoming/outgoing transition arcs are shorter than `Time_granularity`.

Example:

```json
"Time_granularity": 60
```

If the transient state has a 25-minute duration, it is shorter than 60 minutes
and may be bypassed.

If it has a 90-minute duration, it is not shorter than 60 minutes, so it remains
explicit in the MIP.

## 4. Safety Rules

The bypass logic is intentionally conservative.

Even if a state is marked transient, it is not bypassed by default when it is:

- initially enabled;
- operational;
- a shutdown state.

The reason is simple: removing such a state can change the meaning of the unit's
initial condition, dispatch capability, reserve capability, or offline status.

These protections can be changed through:

```json
"optimization_parameters": {
  "time_resolution": {
    "allow_initial_state_embedding": true,
    "allow_operational_state_embedding": true,
    "allow_shutdown_state_embedding": true
  }
}
```

Use these override switches carefully.

The bypass strategy itself is selected through:

```json
"optimization_parameters": {
  "time_resolution": {
    "subperiod_operating_state_policy": "embed_transient"
  }
}
```

Use `"embed_transient"` to allow eligible transient states to be bypassed. Use
`"period_rounding"` to disable bypassing and keep every operating state explicit
in the MIP.

## 5. Step-by-Step Algorithm

The methodology is:

1. Read the original input JSON.
2. Before converting minutes to dispatch-period counts, scan every generating
   unit.
3. For each operating state, check whether it is explicitly marked as
   transient.
4. If it is not marked transient, keep it explicit.
5. If it is marked transient, collect timing data that actually belongs to that
   state:
   - timing declared directly on the operating state;
   - B-side timing fields on arcs entering the state;
   - A-side timing fields on arcs leaving the state.
6. If the state has no positive timing data, keep it explicit and report this.
7. If any positive timing value is greater than or equal to `Time_granularity`,
   keep it explicit and report this.
8. Apply the safety checks for initial, operational, and shutdown states.
9. Before embedding, check whether the source already has a direct `A -> B`
   transition. If it does, keep `T` explicit and write an audit warning, because
   otherwise the model would have to merge two distinct path definitions.
10. If the state passes all checks, remove it from the explicit state list.
11. Replace every usable path `A -> T -> B` with a direct arc `A -> B`.
12. Add the cost of `A -> T` and `T -> B` onto the new direct arc.
13. Preserve timing fields that still belong to explicit endpoint states:
    A-side timing from `A -> T` remains on `A -> B`, and B-side timing from
    `T -> B` remains on `A -> B`.
14. Store metadata on the new direct arc explaining which transient state was
    embedded.
15. Write the decision into `Time_Resolution_Report`.
16. Convert the remaining minute-based timing values to dispatch-period counts.
17. Build the MIP using the remaining explicit operating states and rewritten
    transition graph.

## 6. Simple Example

Original input topology:

```text
State 1 -> State 2 -> State 3
```

Suppose:

- state 2 is marked as `state_role: "synchronization"`;
- state 2 has a 25-minute timing value;
- `Time_granularity` is 60 minutes;
- state 2 is not initially enabled, not operational, and not shutdown.

Then state 2 is eligible for bypassing.

The preprocessing creates:

```text
State 1 -> State 3
```

and removes state 2 from the explicit hourly MIP.

If the original costs were:

```text
1 -> 2 cost = 4
2 -> 3 cost = 6
```

then the new direct arc has:

```text
1 -> 3 cost = 10
```

The new arc also contains metadata showing that state 2 was embedded.

## 7. Consecutive Transient States

If two transient states appear one after the other:

```text
A -> T1 -> T2 -> B
```

the preprocessing embeds them sequentially.

First, it may replace:

```text
A -> T1 -> T2
```

with:

```text
A -> T2
```

Then it may replace:

```text
A -> T2 -> B
```

with:

```text
A -> B
```

The final direct arc preserves:

- the total transition cost of the full path;
- audit metadata for both skipped states, in path order.

So the final `A -> B` arc should contain metadata equivalent to:

```json
"embedded_transient_states": [
  {"id": "T1"},
  {"id": "T2"}
]
```

This lets the MIP avoid hourly variables for `T1` and `T2`, while the run
artifacts still explain which transient states were skipped.

## 8. What Bypassing Means in the MIP

If a transient state is bypassed:

- the MIP does not create an hourly `u_2[unit, period, transient_state]`
  decision variable for that state;
- the unit cannot be scheduled to spend a full dispatch period in that
  transient state;
- transition costs are preserved through the direct arc;
- audit metadata is preserved;
- sub-period timing fields are not kept as ordinary period-level constraints on
  the direct arc.

This is intentional. The transient event is treated as happening inside the
period-to-period transition, not as a full period commitment state.

## 9. What Bypassing Does Not Mean

Bypassing does not mean we simulate real-time dispatch.

It also does not mean we have an exact continuous-time model of every
minute-by-minute trajectory.

It means the hourly RDAS/DS MIP avoids representing very short transient states
as if they lasted a full dispatch period.

## 10. How to Check the Result

After a run, inspect:

```text
runs/latest/preprocessed_mip_input.json
```

This is the most direct inspection file. It contains the input data after
transient-state bypass decisions and minute-to-dispatch-period conversion, just
before the MIP is built.

Also inspect:

```text
runs/latest/time_resolution_report.json
```

or inside:

```text
optimization_output.json
```

under:

```json
"Time_Resolution_Report"
```

Important fields:

- `embedded_state_count`: how many states were bypassed;
- `embedded_states`: which states were bypassed and what arcs were added;
- `issues`: why other states were or were not bypassed;
- `status`: whether the preprocessing passed, produced warnings, or failed.

## 11. Where the Methodology Lives in the Code

Read these files in this order:

1. `mms/pipeline.py`
   - Shows that time-resolution preprocessing happens before timing conversion.

2. `mms/model/time_resolution.py`
   - Main implementation of transient-state bypassing.

3. `mms/model/preprocessing.py`
   - Converts remaining minute-based timing values into dispatch-period counts.

4. `tests/test_time_resolution.py`
   - Small examples that show when a transient state is embedded and when it is
     kept explicit.

5. `docs/model_notes.md`
   - Broader research and modeling notes around RDAS/DS timing resolution.

## 12. Practical Input Checklist

For a transient state you want the model to bypass, check:

1. Is the state explicitly marked as transient?
2. Are its positive timing values shorter than `Time_granularity`?
3. Is it not initially enabled?
4. Is it not operational, unless you intentionally allow operational embedding?
5. Is it not a shutdown state, unless you intentionally allow shutdown
   embedding?
6. Does it have a valid incoming path and outgoing path, for example `A -> T`
   and `T -> B`?
7. Is there no already-declared direct `A -> B` transition that would collide
   with the embedded path?

If all answers are yes, the state should be bypassed.

If not, the state should remain explicit in the MIP, and the reason should be
visible in `Time_Resolution_Report`.
