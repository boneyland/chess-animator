"""
Tests for Stockfish settings and the search details recorded per move.

Run from the repository root:
    python -m unittest discover tests
"""

import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import chess.engine

from chess_game_analyzer import ANALYSIS_LINES, EnhancedGameAnalyzer, default_threads

STOCKFISH = shutil.which("stockfish")
SHORT_GAME = '[Result "*"]\n\n1. e4 e5 2. Nf3 Nc6 *\n'


class DefaultThreadsTest(unittest.TestCase):

    def test_leaves_one_core_free(self):
        with mock.patch("os.cpu_count", return_value=8):
            self.assertEqual(default_threads(), 7)

    def test_uses_at_least_one_thread(self):
        for cores in (1, None):
            with mock.patch("os.cpu_count", return_value=cores):
                self.assertEqual(default_threads(), 1)


@unittest.skipUnless(STOCKFISH, "Stockfish not found on PATH")
class EngineSettingsTest(unittest.TestCase):

    def configured_options(self, **kwargs):
        """The options the analyzer sends to Stockfish when it starts."""
        sent = {}
        real_configure = chess.engine.SimpleEngine.configure

        def spy(engine, options):
            sent.update(options)
            return real_configure(engine, options)

        with mock.patch.object(chess.engine.SimpleEngine, "configure", spy):
            with EnhancedGameAnalyzer(STOCKFISH, depth=1, **kwargs):
                pass
        return sent

    def test_threads_and_hash_are_sent_to_stockfish(self):
        self.assertEqual(self.configured_options(threads=2, hash_mb=64),
                         {"Threads": 2, "Hash": 64})

    def test_depth_only_search_defaults_to_one_thread(self):
        # At a fixed depth, extra threads widen the search instead of
        # finishing sooner: measured up to 30x slower with 7 threads
        with mock.patch("os.cpu_count", return_value=4):
            self.assertEqual(self.configured_options(), {"Threads": 1, "Hash": 256})

    def test_time_limited_search_defaults_to_all_cores_but_one(self):
        with mock.patch("os.cpu_count", return_value=4):
            self.assertEqual(self.configured_options(time_limit=0.1),
                             {"Threads": 3, "Hash": 256})


@unittest.skipUnless(STOCKFISH, "Stockfish not found on PATH")
class SearchDetailsTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        with EnhancedGameAnalyzer(STOCKFISH, depth=6, threads=1, hash_mb=16) as analyzer:
            cls.result = analyzer.analyze_game(SHORT_GAME)

    def test_depth_reached_is_recorded_for_both_searches(self):
        for m in self.result.moves:
            self.assertGreaterEqual(m.search_depth, 6)
            self.assertGreaterEqual(m.search_depth_after, 6)

    def test_number_of_lines_searched_is_recorded(self):
        self.assertTrue(all(m.search_lines == ANALYSIS_LINES for m in self.result.moves))

    def test_best_line_starts_with_the_best_move(self):
        for m in self.result.moves:
            self.assertGreater(len(m.best_line), 1)
            self.assertEqual(m.best_line[0], m.best_move_san)


class SearchSummaryTest(unittest.TestCase):

    def test_summarises_depth_reached_lines_and_settings(self):
        from run_animator import format_search_summary

        moves = [{"search_depth": 14, "search_depth_after": 20, "search_lines": 3},
                 {"search_depth": 18, "search_depth_after": 22, "search_lines": 3},
                 # final checkmate: nothing left to search
                 {"search_depth": 16, "search_depth_after": 0, "search_lines": 3}]
        engine = {"depth": 30, "threads": 7, "hash_mb": 256, "lines": 3}
        self.assertEqual(
            format_search_summary(moves, engine),
            "Depth reached (asked for 30): 14–18, average 16, before each move "
            "(3 lines); 20–22, average 21, after it (1 line). "
            "7 threads, 256 MB hash.")


    def test_uniform_depth_and_one_thread_read_naturally(self):
        from run_animator import format_search_summary

        moves = [{"search_depth": 20, "search_depth_after": 20, "search_lines": 3}] * 2
        engine = {"depth": 20, "threads": 1, "hash_mb": 256, "lines": 3}
        self.assertEqual(
            format_search_summary(moves, engine),
            "Depth reached (asked for 20): 20 before each move (3 lines); "
            "20 after it (1 line). 1 thread, 256 MB hash.")


@unittest.skipUnless(STOCKFISH, "Stockfish not found on PATH")
class LinesTest(unittest.TestCase):

    def test_lines_sets_how_many_lines_are_searched_before_each_move(self):
        with EnhancedGameAnalyzer(STOCKFISH, depth=4, threads=1, hash_mb=16,
                                  lines=1) as analyzer:
            result = analyzer.analyze_game(SHORT_GAME)
        self.assertTrue(all(m.search_lines == 1 for m in result.moves))
        self.assertTrue(all(m.best_line for m in result.moves))

    def test_lines_flag_is_passed_to_the_analysis(self):
        import run_animator

        argv = ["run_animator.py", "sample_game", "--analyze", "--lines", "1"]
        with mock.patch.object(sys, "argv", argv), \
             mock.patch.object(run_animator, "run_analysis", return_value=False) as run, \
             mock.patch("builtins.print"):
            with self.assertRaises(SystemExit):
                run_animator.main()
        self.assertEqual(run.call_args.kwargs.get("lines"), 1)


@unittest.skipUnless(STOCKFISH, "Stockfish not found on PATH")
class AnalysisJsonTest(unittest.TestCase):

    def test_json_records_search_details_and_engine_settings(self):
        import run_animator

        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp)
        pgn, out = Path(tmp, "g.pgn"), Path(tmp, "g_analysis.json")
        pgn.write_text(SHORT_GAME)
        with mock.patch("builtins.print"):
            ok = run_animator.run_analysis(pgn, out, STOCKFISH, 4,
                                           threads=1, hash_mb=32, lines=2)
        self.assertTrue(ok)
        data = json.loads(out.read_text())
        move = data["moves"][0]
        for key in ("search_depth", "search_depth_after", "search_lines", "best_line"):
            self.assertIn(key, move)
        engine = data["engine"]
        self.assertEqual((engine["threads"], engine["hash_mb"], engine["depth"],
                          engine["lines"]), (1, 32, 4, 2))
        self.assertEqual(move["search_lines"], 2)
        self.assertTrue(engine["name"].startswith("Stockfish"))


if __name__ == "__main__":
    unittest.main()
