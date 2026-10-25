"""Logging utilities for mirrored console output and structured run events."""

import json
import sys
from contextlib import contextmanager, redirect_stderr, redirect_stdout
from datetime import datetime, timezone
from pathlib import Path


class TeeStream:
    """File-like stream that writes console output to multiple destinations."""
    def __init__(self, *streams):
        self.streams = streams

    def __getattr__(self, name):
        return getattr(self.streams[0], name)

    def write(self, text):
        for stream in self.streams:
            stream.write(text)
        return len(text)

    def flush(self):
        for stream in self.streams:
            stream.flush()


@contextmanager
def tee_output(log_path):
    """Handle tee output logic for logging utilities for mirrored console output and structured run events."""
    if not log_path:
        yield
        return

    path = Path(log_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as log_file:
        stdout = TeeStream(sys.stdout, log_file)
        stderr = TeeStream(sys.stderr, log_file)
        with redirect_stdout(stdout), redirect_stderr(stderr):
            yield


class JsonEventLogger:
    """Append-only JSONL logger for structured run milestone events."""
    def __init__(self, path):
        self.path = Path(path) if path else None
        if self.path is not None:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text("", encoding="utf-8")

    def event(self, name, **fields):
        if self.path is None:
            return
        record = {
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "event": name,
        }
        record.update(fields)
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")


def null_event_logger():
    """Handle null event logger logic for logging utilities for mirrored console output and structured run events."""
    return JsonEventLogger(None)
