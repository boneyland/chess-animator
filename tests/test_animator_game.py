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

from animator_game import AnalysisData, ScaledEvaluationBar, default_notes_path


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
