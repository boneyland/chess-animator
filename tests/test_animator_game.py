"""
Tests for animator_game.py loading and display helpers.

Needs the project's environment (manim, manim-chess). Run from the
repository root:
    .venv/bin/python -m unittest discover tests
"""

import sys
import unittest
import warnings
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from animator_game import ScaledEvaluationBar


class EvalBarTest(unittest.TestCase):

    def test_updating_the_bar_raises_no_deprecation_warnings(self):
        bar = ScaledEvaluationBar()
        bar.scale(0.72)
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            bar.set_evaluation(150)
        self.assertEqual([str(w.message) for w in caught
                          if issubclass(w.category, DeprecationWarning)], [])


if __name__ == "__main__":
    unittest.main()
