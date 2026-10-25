"""Tables with CSV download, and error/issue presentation."""

from __future__ import annotations

import traceback

import pandas as pd
import streamlit as st


def table(frame: pd.DataFrame, filename: str, key: str, height: int | str = "auto",
          column_config: dict | None = None, caption: str = "") -> None:
    """Read-only table with a CSV download button."""
    if frame is None or frame.empty:
        st.caption("No rows.")
        return
    st.dataframe(frame, hide_index=True, height=height, column_config=column_config)
    cols = st.columns([1, 4])
    with cols[0]:
        st.download_button("⬇ CSV", frame.to_csv(index=False).encode("utf-8"), file_name=f"{filename}.csv",
                           mime="text/csv", key=f"dl_{key}", help="Download this table as CSV.")
    if caption:
        with cols[1]:
            st.caption(caption)


def issues_list(issues, max_rows: int = 200) -> None:
    """Show validation issues as a table pointing to unit / field."""
    if not issues:
        st.success("No issues found: the input passes the GUI checks and the engine's validator.", icon="✅")
        return
    errors = [i for i in issues if i.severity == "error"]
    warnings = [i for i in issues if i.severity == "warning"]
    if errors:
        st.error(f"{len(errors)} error(s) must be fixed before solving.", icon="🛑")
    if warnings:
        st.warning(f"{len(warnings)} warning(s): the run is allowed, but check them.", icon="⚠️")
    frame = pd.DataFrame([{"Severity": "🛑 error" if i.severity == "error" else "⚠️ warning",
                           "Where": i.location, "Problem": i.message} for i in issues[:max_rows]])
    st.dataframe(frame, hide_index=True, column_config={
        "Where": st.column_config.TextColumn(width="medium"),
        "Problem": st.column_config.TextColumn(width="large")})


def error_box(title: str, message: str, details: str | None = None) -> None:
    """Friendly error with the technical text hidden in a 'Details' expander."""
    st.error(f"**{title}**  \n{message}", icon="🛑")
    if details:
        with st.expander("Details"):
            st.code(details, language="text")


def guarded(fn, *args, title: str = "Something went wrong", **kwargs):
    """Run ``fn``; on failure show a friendly box instead of a raw traceback."""
    try:
        return fn(*args, **kwargs)
    except Exception as exc:  # noqa: BLE001 - the GUI must never show a raw traceback
        error_box(title, f"{type(exc).__name__}: {exc}", traceback.format_exc())
        return None
