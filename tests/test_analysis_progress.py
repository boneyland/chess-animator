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


@unittest.skipUnless(STOCKFISH, "Stockfish not found on PATH")
class TimeLimitTest(unittest.TestCase):

    def search_limits(self, **kwargs):
        """The chess.engine.Limit of every Stockfish search for a short game."""
        from chess_game_analyzer import EnhancedGameAnalyzer

        limits = []
        with EnhancedGameAnalyzer(STOCKFISH, depth=1, **kwargs) as analyzer:
            real_analyse = analyzer.engine.analyse

            def spy(board, limit, *args, **kw):
                limits.append(limit)
                return real_analyse(board, limit, *args, **kw)

            analyzer.engine.analyse = spy
            analyzer.analyze_game('[Result "*"]\n\n1. e4 e5 *\n')
        return limits

    def test_each_position_is_searched_once(self):
        # The start, after 1. e4 and after 1... e5: the search after a move
        # is reused as the search before the next
        self.assertEqual(len(self.search_limits()), 3)

    def test_searches_have_no_time_cap_by_default(self):
        self.assertTrue(all(l.depth == 1 and l.time is None for l in self.search_limits()))

    def test_time_limit_caps_every_search(self):
        limits = self.search_limits(time_limit=0.5)
        self.assertTrue(limits)
        self.assertTrue(all(l.depth == 1 and l.time == 0.5 for l in limits))


class TimeLimitFlagTest(unittest.TestCase):

    def test_time_limit_flag_is_passed_to_the_analysis(self):
        from unittest import mock
        import run_animator

        argv = ["run_animator.py", "sample_game", "--analyze", "--time-limit", "2.5"]
        with mock.patch.object(sys, "argv", argv), \
             mock.patch.object(run_animator, "run_analysis", return_value=False) as run, \
             mock.patch("builtins.print"):
            with self.assertRaises(SystemExit):
                run_animator.main()
        self.assertEqual(run.call_args.kwargs.get("time_limit"), 2.5)


if __name__ == "__main__":
    unittest.main()
