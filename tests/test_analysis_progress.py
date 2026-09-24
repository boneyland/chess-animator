"""
Tests for the progress line shown while --analyze runs.

Run from the repository root:
    python -m unittest discover tests
"""

import shutil
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from run_animator import format_progress

STOCKFISH = shutil.which("stockfish")


class FormatProgressTest(unittest.TestCase):

    def test_shows_count_percent_elapsed_and_time_left(self):
        self.assertEqual(format_progress(23, 82, 72),
                         "Analyzing move 23/82 (28%) · 1:12 elapsed · ~3:05 left")

    def test_no_estimate_before_the_first_move_is_done(self):
        self.assertEqual(format_progress(0, 82, 3),
                         "Analyzing move 0/82 (0%) · 0:03 elapsed")

    def test_no_estimate_once_every_move_is_done(self):
        self.assertEqual(format_progress(82, 82, 250),
                         "Analyzing move 82/82 (100%) · 4:10 elapsed")

    def test_hours_are_shown_for_long_runs(self):
        self.assertEqual(format_progress(10, 40, 3725),
                         "Analyzing move 10/40 (25%) · 1:02:05 elapsed · ~3:06:15 left")


@unittest.skipUnless(STOCKFISH, "Stockfish not found on PATH")
class AnalyzeGameProgressTest(unittest.TestCase):

    def test_progress_is_reported_before_and_after_each_move(self):
        from chess_game_analyzer import EnhancedGameAnalyzer

        calls = []
        with EnhancedGameAnalyzer(STOCKFISH, depth=1) as analyzer:
            analyzer.analyze_game('[Result "*"]\n\n1. e4 e5 2. Nf3 *\n',
                                  progress=lambda done, total: calls.append((done, total)))
        self.assertEqual(calls, [(0, 3), (1, 3), (2, 3), (3, 3)])


if __name__ == "__main__":
    unittest.main()
