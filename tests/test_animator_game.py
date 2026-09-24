"""
Tests for animator_game.py loading and display helpers.

Needs the project's environment (manim, manim-chess). Run from the
repository root:
    .venv/bin/python -m unittest discover tests
"""

import json
import os
import sys
import tempfile
import unittest
import warnings
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from animator_game import (AnalysisData, AnalysisPanel, CommentPanel, MoveData,
                           ScaledEvaluationBar, comment_hold_seconds,
                           default_notes_path, format_line)

_Z = dict(space_white=0, space_black=0, mobility_white=0, mobility_black=0,
          king_safety_white=0, king_safety_black=0, threats_white=0,
          threats_black=0, fti1=0, fti2=0, fti3=0)


def _move(ply, san, classification, best_san, best_line=(), eval_after=21,
          eval_loss=38, **extra):
    return MoveData(ply, san, "a1a2", ply % 2 == 1, 0, eval_after, eval_loss,
                    classification, best_san, False, False, [],
                    best_line=list(best_line), **_Z, **extra)


class FormatLineTest(unittest.TestCase):

    def test_numbers_a_line_starting_with_white(self):
        self.assertEqual(format_line(["Be2", "Nfd7", "O-O", "e5"], ply=21),
                         "11.Be2 Nfd7 12.O-O e5")

    def test_numbers_a_line_starting_with_black(self):
        self.assertEqual(format_line(["Qb5", "Bd3", "Nd5", "Kg1"], ply=34),
                         "17...Qb5 18.Bd3 Nd5 19.Kg1")

    def test_stops_after_max_plies(self):
        line = ["Be2", "Nfd7", "O-O", "e5", "dxe5", "Qe8", "Bd2", "Nxe5"]
        self.assertEqual(format_line(line, ply=21, max_plies=6),
                         "11.Be2 Nfd7 12.O-O e5 13.dxe5 Qe8")


class AnalysisPanelTest(unittest.TestCase):

    def test_headline_has_rating_loss_and_eval(self):
        move = _move(21, "Bg5", "inaccuracy", "Be2", ["Be2", "Nfd7"])
        self.assertEqual(AnalysisPanel.headline(move),
                         ("Inaccuracy (38cp lost)", "Eval +0.21"))

    def test_non_best_move_shows_six_plies_of_the_best_line(self):
        move = _move(21, "Bg5", "good", "Be2",
                     ["Be2", "Nfd7", "O-O", "e5", "dxe5", "Qe8", "Bd2"])
        self.assertIn("Best line: 11.Be2 Nfd7 12.O-O e5 13.dxe5 Qe8",
                      " ".join(AnalysisPanel.body_lines(move)))

    def test_best_move_shows_no_best_line(self):
        move = _move(34, "Be6", "best", "Be6", ["Be6", "Bxb6", "Bxc4+"], eval_loss=0)
        self.assertEqual(AnalysisPanel.body_lines(move), [])

    def test_move_rated_best_shows_no_best_line_even_if_engine_chose_another(self):
        # 41...Rc2# is as good as the engine's 41...Ba3#
        move = _move(82, "Rc2#", "best", "Ba3#", ["Ba3#"], eval_loss=0)
        self.assertEqual(AnalysisPanel.body_lines(move), [])

    def test_book_move_shows_no_best_line(self):
        move = _move(7, "Nc3", "book", "d4", ["d4", "d5"], eval_loss=12)
        self.assertEqual(AnalysisPanel.body_lines(move), [])

    def test_analysis_without_a_best_line_falls_back_to_the_best_move(self):
        move = _move(21, "Bg5", "mistake", "Be2", [])
        self.assertEqual(AnalysisPanel.body_lines(move), ["Best: 11.Be2"])

    def test_footer_reports_depth_and_lines_searched(self):
        move = _move(21, "Bg5", "good", "Be2", ["Be2"], search_depth=18,
                     search_depth_after=23, search_lines=3)
        self.assertEqual(AnalysisPanel.footer(move),
                         "Search depth 18 (3 lines), 23 after the move")

    def test_footer_is_empty_for_old_analysis_files(self):
        self.assertEqual(AnalysisPanel.footer(_move(21, "Bg5", "good", "Be2")), "")


class CommentPanelTest(unittest.TestCase):

    def test_comment_column_is_wider_than_the_old_panel(self):
        self.assertGreater(CommentPanel.chars_per_line(), 30)

    def test_only_moves_with_a_comment_get_lines(self):
        panel = CommentPanel({"34": "The move that made the game famous."})
        self.assertEqual(panel.comment_lines(_move(34, "Be6", "best", "Be6")),
                         ["The move that made the game famous."])
        self.assertEqual(panel.comment_lines(_move(35, "Bxb6", "best", "Bxb6")), [])


class EngineSummaryTest(unittest.TestCase):

    def analysis(self, engine, depths):
        moves = [_move(i + 1, "e4", "best", "e4", search_depth=d) for i, d in enumerate(depths)]
        return AnalysisData(game_info=None, moves=moves, white_accuracy=0,
                            black_accuracy=0, engine=engine)

    def test_names_engine_settings_and_depth_reached(self):
        engine = {"name": "Stockfish 17.1", "depth": 20, "lines": 3,
                  "threads": 7, "hash_mb": 256, "time_limit": None}
        self.assertEqual(self.analysis(engine, [16, 20, 0, 18]).engine_summary(),
                         "Stockfish 17.1 · depth 20 (reached 16–20) · 3 lines · 7 threads")

    def test_says_nothing_extra_when_every_search_reached_the_depth(self):
        engine = {"name": "Stockfish 19", "depth": 20, "lines": 3,
                  "threads": 1, "hash_mb": 256, "time_limit": None}
        self.assertEqual(self.analysis(engine, [20, 20, 0]).engine_summary(),
                         "Stockfish 19 · depth 20 · 3 lines · 1 thread")

    def test_mentions_a_time_limit(self):
        engine = {"name": "Stockfish 17.1", "depth": 30, "lines": 3,
                  "threads": 7, "hash_mb": 256, "time_limit": 0.2}
        self.assertEqual(self.analysis(engine, [14, 17]).engine_summary(),
                         "Stockfish 17.1 · depth 30 (reached 14–17) · 0.2s per position"
                         " · 3 lines · 7 threads")

    def test_empty_for_older_analysis_files(self):
        self.assertEqual(self.analysis({}, [0, 0]).engine_summary(), "")


class CommentHoldTest(unittest.TestCase):

    def test_moves_without_a_comment_keep_the_normal_hold(self):
        self.assertEqual(comment_hold_seconds(None), 1.2)

    def test_short_comments_keep_the_normal_hold(self):
        self.assertEqual(comment_hold_seconds("Best."), 1.2)

    def test_longer_comments_hold_long_enough_to_read(self):
        self.assertEqual(comment_hold_seconds("x" * 300), 20.0)   # 15 chars/s


class MoveDataFieldsTest(unittest.TestCase):

    def test_search_details_and_best_line_are_read_from_json(self):
        d = {"ply": 21, "move_san": "Bg5", "move_uci": "f4g5", "is_white_move": True,
             "eval_before": 0, "eval_after": 21, "eval_loss": 38,
             "classification": "good", "best_move_san": "Be2",
             "best_line": ["Be2", "Nfd7"], "search_depth": 18,
             "search_depth_after": 23, "search_lines": 3}
        m = MoveData.from_dict(d)
        self.assertEqual((m.best_line, m.search_depth, m.search_depth_after, m.search_lines),
                         (["Be2", "Nfd7"], 18, 23, 3))

    def test_older_json_without_them_still_loads(self):
        d = {"ply": 1, "move_san": "e4", "move_uci": "e2e4", "is_white_move": True,
             "eval_before": 0, "eval_after": 30, "eval_loss": 0,
             "classification": "book", "best_move_san": "e4"}
        m = MoveData.from_dict(d)
        self.assertEqual((m.best_line, m.search_depth, m.search_lines), ([], 0, 0))


def _write_temp(suffix: str, text: str) -> str:
    fd, path = tempfile.mkstemp(suffix=suffix)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(text)
    return path


class GameInfoSourceTest(unittest.TestCase):

    def setUp(self):
        self.json_path = _write_temp(".json", json.dumps(
            {"white": "Old White", "event": "Old Event", "date": "????.??.??", "moves": []}))
        self.addCleanup(os.remove, self.json_path)

    def test_header_comes_from_the_pgn_when_given(self):
        pgn = _write_temp(".pgn", '[Event "Third Rosenwald Trophy"]\n[White "Donald Byrne"]\n'
                                  '[Date "1956.10.17"]\n[Opening "Grünfeld Defense"]\n\n1. Nf3 *\n')
        self.addCleanup(os.remove, pgn)
        info = AnalysisData.from_json_file(Path(self.json_path), pgn_path=Path(pgn)).game_info
        self.assertEqual((info.white, info.event, info.date, info.opening),
                         ("Donald Byrne", "Third Rosenwald Trophy", "1956.10.17", "Grünfeld Defense"))

    def test_header_comes_from_the_json_without_a_pgn(self):
        info = AnalysisData.from_json_file(Path(self.json_path)).game_info
        self.assertEqual((info.white, info.event), ("Old White", "Old Event"))


class DefaultNotesPathTest(unittest.TestCase):

    def test_notes_file_sits_next_to_the_pgn(self):
        self.assertEqual(default_notes_path("games/fischer.pgn"),
                         Path("games/fischer_notes.txt"))


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
