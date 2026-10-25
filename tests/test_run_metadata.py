"""Tests for run metadata hashing and reproducibility helpers."""

import unittest

from run_metadata import input_hash


class RunMetadataTests(unittest.TestCase):
    """Covers stable input hashing and run metadata helpers."""
    def test_input_hash_is_order_stable(self):
        left = {"b": 1, "a": [2, 3]}
        right = {"a": [2, 3], "b": 1}
        self.assertEqual(input_hash(left), input_hash(right))


if __name__ == "__main__":
    unittest.main()
