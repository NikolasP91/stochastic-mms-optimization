"""Full CLI regression test for the accepted biomass optimization case."""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONFIG_FILE = ROOT / "v2.1_last_real_values_RDAS_60_FAT---test-case_BIOMASS.json"


class FullRunRegressionTests(unittest.TestCase):
    """Runs the accepted biomass case through the CLI as an end-to-end regression."""
    def test_default_biomass_case_matches_known_solver_regression(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            output_path = tmp_path / "optimization_output.json"
            artifact_dir = tmp_path / "artifacts"
            log_path = tmp_path / "run_log.txt"

            completed = subprocess.run(
                [
                    sys.executable,
                    "main.py",
                    str(CONFIG_FILE),
                    "-o",
                    str(output_path),
                    "--artifacts-dir",
                    str(artifact_dir),
                    "--log-file",
                    str(log_path),
                    "--solver-log-file",
                    str(artifact_dir / "solver_log.txt"),
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                timeout=180,
            )

            if completed.returncode != 0:
                self.fail(
                    "Full optimization regression failed.\n"
                    f"STDOUT:\n{completed.stdout}\nSTDERR:\n{completed.stderr}"
                )

            with output_path.open(encoding="utf-8") as f:
                output = json.load(f)
            compact_output_path = tmp_path / "optimization_output_through_solution_status.json"
            with compact_output_path.open(encoding="utf-8") as f:
                compact_output = json.load(f)

            solve_metadata = output["Solve_Metadata"]
            self.assertEqual("Optimal", output["Solution_Status"])
            self.assertEqual("Optimal", compact_output["Solution_Status"])
            self.assertNotIn("Solve_Metadata", compact_output)
            self.assertNotIn("Run_Metadata", compact_output)
            self.assertNotIn("Dispatch_Instructions", compact_output)
            self.assertEqual("Solution_Status", list(compact_output)[-1])
            self.assertNotIn("_Preprocessed_MIP_Input", output)
            self.assertEqual("passed", output["Validation"]["status"])
            self.assertAlmostEqual(382562.14962105, solve_metadata["objective_value"], delta=1e-3)
            self.assertEqual(12032, solve_metadata["num_constraints"])
            self.assertEqual(5191, solve_metadata["num_variables"])
            self.assertEqual(1000.0, solve_metadata["big_m"])
            self.assertGreaterEqual(solve_metadata["mps_write_seconds"], 0)
            self.assertGreaterEqual(solve_metadata["solver_seconds"], 0)
            self.assertEqual("passed", output["Diagnostics_Report"]["status"])
            self.assertEqual("passed", output["Warning_Report"]["status"])
            self.assertEqual(0, output["Warning_Report"]["warning_count"])
            self.assertEqual("passed", output["Thermal_Cost_Curve_Audit"]["status"])
            self.assertEqual(0, output["Thermal_Cost_Curve_Audit"]["warning_count"])
            self.assertEqual("passed", output["Penalty_Hierarchy_Audit"]["status"])
            self.assertEqual(0, output["Penalty_Hierarchy_Audit"]["warning_count"])
            self.assertEqual("passed", output["Slack_Penalty_Report"]["status"])
            self.assertEqual(0, output["Slack_Penalty_Report"]["nonzero_slack_count"])
            self.assertAlmostEqual(0.0, output["Slack_Penalty_Report"]["total_penalty_eur"])
            self.assertAlmostEqual(95734.152, output["Thermal_Cost_Report"]["summary"]["thermal_cost"])
            self.assertAlmostEqual(
                solve_metadata["objective_value"],
                sum(item["amount"] for item in output["Objective_Breakdown_Report"]["components"]),
                delta=1e-3,
            )
            self.assertGreater(output["Performance_Profile"]["total_seconds"], 0)
            self.assertIn("pipeline", output["Performance_Profile"])

            expected_artifacts = [
                "input_snapshot.json",
                "preprocessed_mip_input.json",
                "output_snapshot.json",
                "output_through_solution_status.json",
                "run_metadata.json",
                "solve_metadata.json",
                "validation_report.json",
                "dispatch_instructions.json",
                "reserve_monitoring_report.json",
                "res_curtailment_report.json",
                "thermal_cost_curve_audit.json",
                "thermal_cost_curve_generation.json",
                "thermal_cost_report.json",
                "penalty_hierarchy_audit.json",
                "objective_breakdown_report.json",
                "slack_penalty_report.json",
                "time_resolution_report.json",
                "warning_report.json",
                "diagnostics_report.json",
                "performance_profile.json",
                "run_events.jsonl",
                "run_log.txt",
                "solver_log.txt",
                "example_model.mps",
            ]
            for filename in expected_artifacts:
                with self.subTest(artifact=filename):
                    self.assertTrue((artifact_dir / filename).exists())

            with (artifact_dir / "preprocessed_mip_input.json").open(encoding="utf-8") as f:
                preprocessed_input = json.load(f)
            self.assertIn("Time_Resolution_Report", preprocessed_input)
            self.assertIn("Generating_Units", preprocessed_input)
            with (artifact_dir / "input_snapshot.json").open(encoding="utf-8") as f:
                raw_input = json.load(f)
            self.assertNotIn("Time_Resolution_Report", raw_input)
            self.assertIn("preprocessed_input_sha256", output["Run_Metadata"])

            with (artifact_dir / "run_events.jsonl").open(encoding="utf-8") as f:
                event_names = [json.loads(line)["event"] for line in f if line.strip()]
            self.assertIn("run_started", event_names)
            self.assertIn("solver_log_configured", event_names)
            self.assertIn("optimization_finished", event_names)
            self.assertIn("validation_finished", event_names)

            solver_log = (artifact_dir / "solver_log.txt").read_text(encoding="utf-8")
            self.assertIn("Running HiGHS", solver_log)


if __name__ == "__main__":
    unittest.main()
