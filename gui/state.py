"""Session state: the loaded case, the edited working copy, solver options and runs."""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

import streamlit as st

from gui import adapter

DEFAULT_SOLVER = {"solver": "highs", "time_limit": 0.0, "accept_incumbent": False, "compare": False,
                  "ds_hours": 4}
DEFAULT_CASE = "examples/small_tree_bess.json"


@st.cache_data(show_spinner=False)
def _read_case(path: str, mtime: float) -> dict:
    """Cached JSON read, invalidated when the file changes (mtime)."""
    return adapter.read_json(path)


@st.cache_data(show_spinner=False, max_entries=32)
def _results(run_dir: str, mtime: float) -> adapter.Results:
    return adapter.load_results(run_dir)


def init() -> None:
    ss = st.session_state
    ss.setdefault("ver", 0)
    ss.setdefault("mode", "RDAS")
    ss.setdefault("scenario_choice", adapter.EXPECTED_ID)
    ss.setdefault("solver_opts", dict(DEFAULT_SOLVER))
    ss.setdefault("run", None)
    ss.setdefault("result_dir", None)
    ss.setdefault("issues", None)
    if "work" not in ss:
        default = adapter.ROOT / DEFAULT_CASE
        cases = adapter.discover_cases()
        load_file(default if default.exists() else cases[0])


def load_file(path: Path) -> None:
    raw = _read_case(str(path), path.stat().st_mtime)
    _set_case(raw, adapter.case_label(path))


def load_uploaded(name: str, content: bytes) -> None:
    raw = json.loads(content.decode("utf-8-sig"))
    if not isinstance(raw, dict) or "Generating_Units" not in raw:
        raise ValueError("The uploaded JSON is not an MMS input (no 'Generating_Units').")
    _set_case(raw, f"upload: {name}")


def _set_case(raw: dict, label: str) -> None:
    ss = st.session_state
    data, notes = adapter.prepare_case(raw)
    ss.case_label = label
    ss.base = data                 # as loaded (plus a nominal scenario if absent)
    ss.work = deepcopy(data)       # edited by the Inputs / Parameters pages
    ss.case_notes = notes
    ss.issues = None
    ss.result_dir = None
    if ss.scenario_choice not in (adapter.EXPECTED_ID, adapter.ALL_ID) + tuple(adapter.scenario_ids(data)):
        ss.scenario_choice = adapter.EXPECTED_ID
    bump()


def bump() -> None:
    """Invalidate editor widgets (after reset / load) so they re-read the working copy."""
    st.session_state.ver = st.session_state.get("ver", 0) + 1


def work() -> dict:
    return st.session_state.work


def base() -> dict:
    return st.session_state.base


def reset_work() -> None:
    st.session_state.work = deepcopy(st.session_state.base)
    st.session_state.issues = None
    bump()


def editor_source(name: str, builder):
    """A data_editor source frame that stays fixed until the next ``bump``.

    Editors report edits relative to their source; keeping the source fixed
    while the working copy changes avoids applying edits twice.
    """
    key = f"_src_{name}_{st.session_state.ver}"
    if key not in st.session_state:
        st.session_state[key] = builder()
    return st.session_state[key]


def results() -> adapter.Results | None:
    """Results of the run currently shown (latest finished run, or one chosen from history)."""
    run_dir = st.session_state.get("result_dir")
    if not run_dir:
        return None
    path = Path(run_dir)
    marker = path / "status.json"
    mtime = marker.stat().st_mtime if marker.exists() else 0
    return _results(str(path), mtime)


def running() -> bool:
    run = st.session_state.get("run")
    return bool(run and run.process is not None and run.process.poll() is None)


def current_status() -> str:
    if running():
        return "Running"
    res = results()
    return res.status if res else "Not run"
