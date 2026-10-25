"""Solve one GUI run in its own process: ``python gui/runner.py <run_dir>``.

Reads ``request.json`` and ``input.json`` from the run folder, calls the
existing engine unchanged and writes ``result.json`` or ``error.json`` plus
``status.json``. Standard output (including the native HiGHS/CBC log) is
redirected by the GUI to ``solver_log.txt``.

The only hooks are observational: ``pulp.LpProblem.solve`` is wrapped to record
model size, binary count and the HiGHS MIP gap, and ``msg=True`` is passed so
the solver log is streamed. No constraint, bound or objective is touched.
"""

from __future__ import annotations

from datetime import datetime
from functools import partial
import json
import math
import os
from pathlib import Path
import shutil
import sys
from time import perf_counter
import traceback

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pulp as pl  # noqa: E402

from mms.stochastic.artifacts import write_json  # noqa: E402

STATS: list[dict] = []


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _install_stats_hook() -> None:
    """Record size/gap of every MILP solved in this process (read-only)."""
    original = pl.LpProblem.solve

    def solve(self, solver=None, **kwargs):
        info = {"problem": self.name, "variables": self.numVariables(), "constraints": self.numConstraints(),
                "integers": sum(1 for v in self.variables() if v.cat == pl.LpInteger)}
        print(f"[gui] solving {self.name}: {info['constraints']} rows, {info['variables']} columns, "
              f"{info['integers']} binaries", flush=True)
        started = perf_counter()
        try:
            return original(self, solver, **kwargs)
        finally:
            info["seconds"] = perf_counter() - started
            model = getattr(self, "solverModel", None)
            if model is not None and hasattr(model, "getInfo"):
                try:
                    hinfo = model.getInfo()
                    for key in ("mip_gap", "mip_dual_bound"):
                        value = float(getattr(hinfo, key))
                        info[key] = value if math.isfinite(value) else None   # inf when no incumbent
                    info["mip_node_count"] = int(hinfo.mip_node_count)
                except Exception:  # noqa: BLE001 - LP or non-HiGHS model
                    pass
            info["pulp_status"] = pl.LpStatus.get(self.status, str(self.status))
            STATS.append(info)
            print(f"[gui] finished {self.name} in {info['seconds']:.2f} s, status {info['pulp_status']}", flush=True)

    pl.LpProblem.solve = solve


def _status(run_dir: Path, **fields) -> None:
    path = run_dir / "status.json"
    current = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    current.update(fields)
    current["stats"] = STATS
    write_json(path, current)


def _classify(exc: Exception, time_limit: float | None) -> str:
    """GUI status for an engine failure."""
    status = getattr(exc, "status", None)
    if status == "Infeasible":
        return "Infeasible"
    details = getattr(exc, "details", {}) or {}
    if time_limit and status in ("Not Solved", "Optimal", "Undefined"):
        seconds = details.get("solve_seconds") or 0
        if seconds >= 0.95 * time_limit:
            return "Time limit"
    if isinstance(exc, ValueError):
        return "Input error"
    return "Error"


def run_rdas(request: dict, data: dict) -> dict:
    from mms.stochastic import evaluation, model
    from mms.stochastic.data import validate

    validate(data)
    kwargs = {"solver": request["solver"], "time_limit": request.get("time_limit")}
    if request.get("compare"):
        # Stream the log of each benchmark solve as well (msg only affects printing).
        evaluation.solve = partial(model.solve, msg=True)
        print("[gui] comparison mode: RP, EV, EEV, WS, VSS, EVPI (risk-neutral)", flush=True)
        result = evaluation.compare(data, **kwargs)
        if data["stochastic"].get("risk", {}).get("weight", 0):
            print("[gui] solving the risk-averse (CVaR) plan separately", flush=True)
            result["stochastic_risk_averse"] = model.solve(data, msg=True, **kwargs)
        return result
    return model.solve(data, msg=True, accept_incumbent=bool(request.get("accept_incumbent")), **kwargs)


def run_ds(request: dict, run_dir: Path) -> dict:
    import main as legacy

    output = run_dir / "ds_output.json"
    argv = ["main.py", str(run_dir / "input.json"), "-o", str(output), "--solver", request["solver"],
            "--artifacts-dir", str(run_dir / "legacy_artifacts"), "--log-file", str(run_dir / "legacy_run_log.txt")]
    if request.get("time_limit"):
        argv += ["--time-limit", str(request["time_limit"])]
    sys.argv = argv
    code = legacy.main()
    if code != 0 or not output.exists():
        raise RuntimeError(f"The deterministic DS program exited with code {code}; see the solver log.")
    result = json.loads(output.read_text(encoding="utf-8"))
    status = result.get("Solution_Status")
    if status != "Optimal":
        error = RuntimeError(f"DS solution status is {status!r}")
        error.status = "Infeasible" if status == "Infeasible" else status  # type: ignore[attr-defined]
        raise error
    return result


def main(run_dir: Path) -> int:
    request = json.loads((run_dir / "request.json").read_text(encoding="utf-8"))
    _install_stats_hook()
    _status(run_dir, state="running", status="Running", started=_now(), pid=os.getpid())
    print(f"[gui] {request['mode']} run of {request.get('case')} with {request['solver']}"
          f" (time limit: {request.get('time_limit') or 'none'})", flush=True)
    try:
        if request["mode"] == "DS":
            result = run_ds(request, run_dir)
            status = "Optimal"
        else:
            data = json.loads((run_dir / "input.json").read_text(encoding="utf-8"))
            result = run_rdas(request, data)
            status = (result.get("stochastic") or result).get("status", "Optimal")
        if request["mode"] == "DS":
            shutil.copyfile(run_dir / "ds_output.json", run_dir / "result.json")   # verbatim (may hold NaN)
        else:
            write_json(run_dir / "result.json", result)
        main_result = result.get("stochastic", result)
        _status(run_dir, state="finished", status=status, finished=_now(),
                expected_cost_eur=main_result.get("expected_cost_eur",
                                                  main_result.get("Solve_Metadata", {}).get("objective_value")),
                message="Solved and validated." if status == "Optimal" else
                "Time-limited incumbent accepted (optimality gap not closed).")
        print(f"[gui] done: {status}", flush=True)
        return 0
    except BaseException as exc:  # noqa: BLE001 - every failure must reach the GUI
        if isinstance(exc, KeyboardInterrupt):
            status = "Cancelled"
        else:
            status = _classify(exc, request.get("time_limit"))
        payload = exc.as_dict() if hasattr(exc, "as_dict") else {"status": getattr(exc, "status", status),
                                                                  "message": str(exc)}
        payload["gui_status"] = status
        payload["type"] = type(exc).__name__
        payload["traceback"] = traceback.format_exc()
        write_json(run_dir / "error.json", payload)
        _status(run_dir, state="finished", status=status, finished=_now(), message=str(exc)[:2000])
        print(f"[gui] failed: {status}: {exc}", flush=True)
        return 2


if __name__ == "__main__":
    raise SystemExit(main(Path(sys.argv[1]).resolve()))
