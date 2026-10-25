"""Run metadata and reproducibility hash helpers."""

import hashlib
import json
import platform
import subprocess
import sys
from datetime import datetime, timezone


def _module_version(module_name):
    """Read an installed package version for run metadata."""
    try:
        module = __import__(module_name)
    except Exception:
        return None
    return getattr(module, "__version__", "unknown")


def _git_value(args):
    """Run a small git command and return its text value for metadata."""
    try:
        result = subprocess.run(
            ["git", *args],
            check=True,
            capture_output=True,
            text=True,
        )
    except Exception:
        return None
    return result.stdout.strip() or None


def input_hash(input_data):
    """Return a stable hash of the input payload for reproducibility tracking."""
    canonical = json.dumps(input_data, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def build_run_metadata(input_data, config_path, output_path, solver_name, preprocessed_input_data=None):
    """Build reproducibility metadata for the current optimization run."""
    metadata = {
        "run_started_at_utc": datetime.now(timezone.utc).isoformat(),
        "config_path": str(config_path),
        "output_path": str(output_path),
        "input_sha256": input_hash(input_data),
        "git_commit": _git_value(["rev-parse", "HEAD"]),
        "git_branch": _git_value(["branch", "--show-current"]),
        "git_dirty": bool(_git_value(["status", "--short"])),
        "python_version": sys.version,
        "platform": platform.platform(),
        "solver": solver_name,
        "package_versions": {
            "pulp": _module_version("pulp"),
            "highspy": _module_version("highspy"),
            "numpy": _module_version("numpy"),
            "pandas": _module_version("pandas"),
        },
    }
    if preprocessed_input_data is not None:
        metadata["preprocessed_input_sha256"] = input_hash(preprocessed_input_data)
    return metadata
