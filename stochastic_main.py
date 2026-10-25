"""CLI for stochastic RDAS; the original main.py still runs deterministic MMS."""

import argparse
from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
from uuid import uuid4

from mms.stochastic.artifacts import canonical_hash, write_json
from mms.stochastic.data import load, number, validate
from mms.stochastic.errors import InfeasibleModelError, OptimizationError
from mms.stochastic.evaluation import compare, evaluate_out_of_sample
from mms.stochastic.model import solve


def _parser():
    parser = argparse.ArgumentParser(description=__doc__, epilog="Example: python stochastic_main.py examples/small_stochastic.json")
    parser.add_argument("input", type=Path, help="Input JSON containing model data and stochastic settings")
    parser.add_argument("-o", "--output", type=Path, default=Path("runs/stochastic.json"))
    parser.add_argument("--solver", choices=("highs", "cbc"), default="highs")
    parser.add_argument("--time-limit", type=float, help="Positive solver time limit in seconds")
    parser.add_argument("--compare", action="store_true", help="Risk-neutral RP/EEV/WS/VSS/EVPI")
    parser.add_argument("--evaluation-scenarios", type=Path, help="JSON list of independent held-out paths")
    parser.add_argument("--validate-only", action="store_true", help="Validate input without optimizing or writing results")
    parser.add_argument("--artifacts-dir", type=Path, help="Parent of unique run folders; defaults to <output stem>_artifacts")
    parser.add_argument("--accept-incumbent", action="store_true",
                        help="With --time-limit, report a feasible incumbent as status Feasible (not with --compare)")
    return parser


def main(argv=None):
    args = _parser().parse_args(argv)
    protected = {args.input.resolve()}
    if args.evaluation_scenarios:
        protected.add(args.evaluation_scenarios.resolve())
    diagnostic = args.output.with_suffix(".error.json")
    artifacts = None
    manifest = None
    try:
        if args.output.resolve() in protected:
            raise ValueError("Output must not overwrite an input file")
        data = load(args.input)
        if args.time_limit is not None and number(args.time_limit, "time_limit") <= 0:
            raise ValueError("time_limit must be positive")
        scenarios = None
        if args.evaluation_scenarios:
            scenarios = json.loads(args.evaluation_scenarios.read_text(encoding="utf-8-sig"))
            evaluation_data = deepcopy(data)
            evaluation_data["stochastic"]["scenarios"] = scenarios
            if isinstance(scenarios, list) and not any(isinstance(s, dict) and "tree_path" in s for s in scenarios):
                evaluation_data["stochastic"].pop("scenario_tree", None)  # full-path evaluation, as in evaluate_out_of_sample
            validate(evaluation_data)
        if args.validate_only:
            print(f"Valid input: {args.input}; {len(data['stochastic']['scenarios'])} scenarios; no optimization performed.")
            return 0
        artifact_root = args.artifacts_dir or args.output.parent / f"{args.output.stem}_artifacts"
        run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ") + "_" + uuid4().hex[:8]
        artifacts = artifact_root / run_id
        targets = [artifacts / name for name in ("input.json", "manifest.json", "evaluation_scenarios.json", "result.json")]
        if any(p.resolve() in protected | {args.output.resolve(), diagnostic.resolve()} for p in targets):
            raise ValueError("Artifact files must not overwrite inputs, output or diagnostic files")
        write_json(artifacts / "input.json", data)
        if scenarios is not None:
            write_json(artifacts / "evaluation_scenarios.json", scenarios)
        manifest = {
            "run_id": run_id, "status": "Running",
            "created_utc": datetime.now(timezone.utc).isoformat(),
            "input_path": str(args.input.resolve()), "input_sha256": canonical_hash(data),
            "output_path": str(args.output.resolve()),
            "solver": args.solver, "time_limit_seconds": args.time_limit, "compare": args.compare,
            "evaluation_scenarios_sha256": canonical_hash(scenarios) if scenarios is not None else None,
        }
        write_json(artifacts / "manifest.json", manifest)
        kwargs = {"solver": args.solver, "time_limit": args.time_limit}
        if args.accept_incumbent and args.compare:
            raise ValueError("--accept-incumbent cannot be combined with --compare: VSS/EVPI require proven optima")
        risk_weight = data["stochastic"].get("risk", {}).get("weight", 0)
        if args.compare and risk_weight:
            print("Comparison uses risk-neutral costs: CVaR weight is set to zero for all benchmark models.")
        result = compare(data, **kwargs) if args.compare else solve(data, accept_incumbent=args.accept_incumbent, **kwargs)
        if args.compare and risk_weight:
            # Το σχέδιο που ζήτησε ο χρήστης (με CVaR) λύνεται και αξιολογείται ξεχωριστά.
            result["stochastic_risk_averse"] = solve(data, **kwargs)
        if scenarios is not None:
            plans = {"stochastic": result["stochastic"], "deterministic": result["deterministic"]} if args.compare else {"stochastic": result}
            if "stochastic_risk_averse" in result:
                plans["stochastic_risk_averse"] = result["stochastic_risk_averse"]
            result["out_of_sample"] = {}
            for name, plan in plans.items():
                try:
                    result["out_of_sample"][name] = evaluate_out_of_sample(data, plan["common_schedule"], scenarios, **kwargs)
                except InfeasibleModelError as exc:
                    result["out_of_sample"][name] = exc.as_dict()
        result["artifact_directory"] = str(artifacts.resolve())
        manifest.update(status="Completed", result_sha256=canonical_hash(result))
        write_json(artifacts / "result.json", result)
        write_json(args.output, result)
        write_json(artifacts / "manifest.json", manifest)
        print(f"Wrote {args.output}; run artifacts: {artifacts}")
        if args.compare:
            print({key: result[key] for key in ("RP", "EEV", "WS", "VSS", "EVPI")})
        else:
            print(f"Expected cost: {result['expected_cost_eur']:.6f}; validation passed: {result['validation']['passed']}; operational status: {result['operational_status']}")
        return 0
    except Exception as exc:  # noqa: BLE001 - every failure gets a manifest and diagnostic
        if isinstance(exc, OptimizationError):
            payload = exc.as_dict()
        elif isinstance(exc, (ValueError, OSError)):
            payload = {"status": "InputError" if isinstance(exc, ValueError) else "FileError", "message": str(exc)}
        else:
            payload = {"status": "InternalError", "message": f"{type(exc).__name__}: {exc}"}
        payload["created_utc"] = datetime.now(timezone.utc).isoformat()
        print(f"{payload['status']}: {exc}", file=sys.stderr)
        if manifest is not None:
            manifest.update(status="Failed", failure=payload)
            try:
                write_json(artifacts / "manifest.json", manifest)
            except OSError as manifest_error:
                print(f"Cannot write failed-run manifest: {manifest_error}", file=sys.stderr)
        if diagnostic.resolve() not in protected:
            try:
                write_json(diagnostic, payload)
                print(f"Failure diagnostic: {diagnostic}", file=sys.stderr)
            except OSError as diagnostic_error:
                print(f"Cannot write failure diagnostic: {diagnostic_error}", file=sys.stderr)
        print("This run did not complete successfully; any existing output may be from an earlier run.", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
