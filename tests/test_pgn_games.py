"""
Tests for picking one game out of a PGN file with several.

Run from the repository root:
    python -m unittest discover tests
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pgn_games import count_games, game_file, open_game

THREE_GAMES = """[White "A"]\n[Black "B"]\n\n1. e4 *\n
[White "C"]\n[Black "D"]\n\n1. d4 {Queen's pawn.} *\n
[White "E"]\n[Black "F"]\n\n1. c4 *\n"""


def _write_pgn(text: str) -> str:
    fd, path = tempfile.mkstemp(suffix=".pgn")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(text)
    return path


class OpenGameTest(unittest.TestCase):

    def setUp(self):
        self.path = _write_pgn(THREE_GAMES)
        self.addCleanup(os.remove, self.path)

    def test_games_are_numbered_from_one_in_file_order(self):
        whites = [open_game(self.path, n).headers["White"] for n in (1, 2, 3)]
        self.assertEqual(whites, ["A", "C", "E"])

    def test_the_first_game_by_default(self):
        self.assertEqual(open_game(self.path).headers["White"], "A")

    def test_the_game_is_read_in_full(self):
        game = open_game(self.path, 2)
        self.assertEqual(game.next().san(), "d4")
        self.assertEqual(game.next().comment, "Queen's pawn.")

    def test_no_game_past_the_last(self):
        self.assertIsNone(open_game(self.path, 4))


class CountGamesTest(unittest.TestCase):

    def count(self, text):
        path = _write_pgn(text)
        self.addCleanup(os.remove, path)
        return count_games(path)

    def test_counts_every_game(self):
        self.assertEqual(self.count(THREE_GAMES), 3)

    def test_a_game_without_headers_counts(self):
        self.assertEqual(self.count("1. e4 *\n"), 1)

    def test_an_empty_file_has_none(self):
        self.assertEqual(self.count(""), 0)


class GameFileTest(unittest.TestCase):

    def test_the_first_game_keeps_the_pgns_name(self):
        self.assertEqual(game_file("games/x.pgn", "_analysis.json"),
                         Path("games/x_analysis.json"))
        self.assertEqual(game_file("games/x.pgn", "_notes.txt", 1),
                         Path("games/x_notes.txt"))

    def test_later_games_are_numbered(self):
        self.assertEqual(game_file("games/x.pgn", "_analysis.json", 3),
                         Path("games/x_game3_analysis.json"))


if __name__ == "__main__":
    unittest.main()
