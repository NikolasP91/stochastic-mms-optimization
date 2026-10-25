"""Atomic JSON artifacts and reproducibility metadata for stochastic runs."""

from datetime import datetime, timezone
import hashlib
from importlib.metadata import PackageNotFoundError, version
import json
import os
from pathlib import Path
import platform
import tempfile


def canonical_hash(value):
    serialized = json.dumps(value, sort_keys=True, separators=(",", ":"),
                            ensure_ascii=False, allow_nan=False)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def write_json(path, value):
    """Serialize before touching the destination; replace only a complete file."""
    content = json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                         prefix=f".{path.name}.", suffix=".tmp", delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


def run_metadata(data, solver, time_limit, fixed_first_stage):
    root = Path(__file__).resolve().parents[2]
    sources = sorted([*root.glob("mms/**/*.py"), root / "mip_utils.py",
                      root / "input_validation.py", root / "stochastic_main.py"])
    hashes = {str(path.relative_to(root)).replace("\\", "/"):
              hashlib.sha256(path.read_bytes()).hexdigest() for path in sources}
    packages = {}
    for name in ("pulp", "highspy", "numpy", "pandas"):
        try:
            packages[name] = version(name)
        except PackageNotFoundError:
            packages[name] = None
    return {"created_at_utc": datetime.now(timezone.utc).isoformat(),
            "python": platform.python_version(), "platform": platform.platform(), "package_versions": packages,
            "input_sha256": canonical_hash(data),
            "fixed_first_stage_sha256": canonical_hash(fixed_first_stage or {}),
            "source_sha256": canonical_hash(hashes), "source_files": hashes,
            "solver": solver, "solver_settings": {"time_limit_seconds": time_limit,
            "relative_mip_gap": 0, "threads": 1}}
