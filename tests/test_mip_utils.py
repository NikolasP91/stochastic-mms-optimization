"""Tests for MIP utility helpers such as constraint naming."""

import unittest
import warnings

import pulp as pl

from mip_utils import ConstraintBuildTracker, name_auto_constraints


class ConstraintBuildTrackerTests(unittest.TestCase):
    """Checks constraint naming and build-tracking helpers."""
    def test_tracker_names_anonymous_constraints_by_section(self):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            prob = pl.LpProblem("tracker_test", pl.LpMinimize)
            x = pl.LpVariable("x", lowBound=0)
            tracker = ConstraintBuildTracker(prob)

            with tracker.section("Load Balance"):
                prob += x >= 1

            self.assertIn("mms_load_balance_000001", prob.constraints)
            self.assertEqual(0, name_auto_constraints(prob))
        self.assertEqual(
            [
                {
                    "section": "load_balance",
                    "constraints_added": 1,
                    "variables_added": 1,
                    "anonymous_constraints_named": 1,
                    "build_seconds": tracker.summary()[0]["build_seconds"],
                }
            ],
            tracker.summary(),
        )


if __name__ == "__main__":
    unittest.main()
