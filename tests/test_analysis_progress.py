"""
Tests for the progress line shown while Stockfish analyses a game, from
run_animator.py --analyze or chess_game_analyzer.py.

Run from the repository root:
    python -m unittest discover tests
"""

import io
import shutil
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from chess_game_analyzer import ProgressLine, format_progress

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


class FakeTerminal(io.StringIO):
    def isatty(self):
        return True


class ProgressLineTest(unittest.TestCase):

    def run_progress(self, stdout, calls, clock):
        """Output of a ProgressLine given (done, total) calls, one clock reading each."""
        with mock.patch("sys.stdout", stdout), \
             mock.patch("chess_game_analyzer.time.monotonic", side_effect=clock):
            progress = ProgressLine()
            for done, total in calls:
                progress(done, total)
            progress.finish()
        return stdout.getvalue()

    def test_piped_output_gets_one_plain_line_per_call(self):
        out = self.run_progress(io.StringIO(), [(0, 2), (1, 2), (2, 2)], [0, 0, 5, 10])
        self.assertEqual(out.splitlines(), [
            "Analyzing move 0/2 (0%) · 0:00 elapsed",
            "Analyzing move 1/2 (50%) · 0:05 elapsed · ~0:05 left",
            "Analyzing move 2/2 (100%) · 0:10 elapsed",
        ])

    def test_terminal_output_redraws_one_line_and_ends_it_when_done(self):
        out = self.run_progress(FakeTerminal(), [(0, 2), (1, 2), (2, 2)], [0, 0, 5, 10])
        self.assertEqual(out.count("\n"), 1)
        self.assertTrue(out.endswith("\n"))
        # Padded with spaces over the longer line it redraws
        self.assertEqual(out.split("\r")[-1].rstrip(),
                         "Analyzing move 2/2 (100%) · 0:10 elapsed")

    def test_finish_ends_a_line_left_open_by_an_interrupted_analysis(self):
        out = self.run_progress(FakeTerminal(), [(0, 2), (1, 2)], [0, 0, 5])
        self.assertTrue(out.endswith("~0:05 left\n"))

    def test_clock_restarts_for_each_game(self):
        # Second game starts at t=100; its first move is done at t=103
        out = self.run_progress(io.StringIO(), [(0, 1), (1, 1), (0, 2), (1, 2)],
                                [0, 0, 7, 100, 103])
        self.assertEqual(out.splitlines()[-1],
                         "Analyzing move 1/2 (50%) · 0:03 elapsed · ~0:03 left")


class AnalyzerCommandLineTest(unittest.TestCase):

    def run_main(self, *flags, method="analyze_game"):
        """The EnhancedGameAnalyzer call chess_game_analyzer.py makes, and its
        call of the analyzer's method."""
        import chess_game_analyzer

        engine_cls = mock.MagicMock()
        analyzer = engine_cls.return_value.__enter__.return_value
        getattr(analyzer, method).side_effect = RuntimeError("stop after the call")
        argv = ["chess_game_analyzer.py", "sample_game.pgn", *flags]
        with mock.patch.object(sys, "argv", argv), \
             mock.patch.object(chess_game_analyzer, "EnhancedGameAnalyzer", engine_cls), \
             mock.patch("builtins.print"):
            with self.assertRaises(RuntimeError):
                chess_game_analyzer.main()
        return engine_cls.call_args, getattr(analyzer, method).call_args

    def test_engine_flags_are_passed_to_the_analyzer(self):
        engine_call, _ = self.run_main("--threads", "3", "--hash", "512",
                                       "--time-limit", "2.5", "--lines", "1")
        self.assertEqual(engine_call.args[2], 2.5)
        self.assertEqual(engine_call.kwargs,
                         {"threads": 3, "hash_mb": 512, "lines": 1})

    def test_progress_is_shown_unless_quiet(self):
        _, game_call = self.run_main()
        self.assertIsInstance(game_call.kwargs.get("progress"), ProgressLine)
        _, game_call = self.run_main("-q")
        self.assertIsNone(game_call.kwargs.get("progress"))

    def test_book_mode_shows_progress_and_takes_engine_flags(self):
        engine_call, games_call = self.run_main("--book", "--threads", "2",
                                                method="analyze_all_games")
        self.assertEqual(engine_call.kwargs["threads"], 2)
        self.assertIsInstance(games_call.kwargs.get("progress"), ProgressLine)


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
