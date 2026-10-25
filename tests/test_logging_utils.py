"""Tests for console tee logging and structured JSON event logging."""

import json
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

from mms.logging_utils import JsonEventLogger, tee_output


class LoggingUtilsTests(unittest.TestCase):
    """Covers console tee output and JSON event logging utilities."""
    def test_tee_output_writes_console_text_to_log_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            log_path = Path(tmp) / "run_log.txt"

            with redirect_stdout(StringIO()):
                with tee_output(log_path):
                    print("hello from run")

            self.assertIn("hello from run", log_path.read_text(encoding="utf-8"))

    def test_json_event_logger_writes_json_lines(self):
        with tempfile.TemporaryDirectory() as tmp:
            event_path = Path(tmp) / "run_events.jsonl"
            logger = JsonEventLogger(event_path)

            logger.event("started", solver="highs")
            logger.event("finished", status="Optimal")

            events = [
                json.loads(line)
                for line in event_path.read_text(encoding="utf-8").splitlines()
            ]
            self.assertEqual(["started", "finished"], [event["event"] for event in events])
            self.assertEqual("highs", events[0]["solver"])
            self.assertEqual("Optimal", events[1]["status"])


if __name__ == "__main__":
    unittest.main()
