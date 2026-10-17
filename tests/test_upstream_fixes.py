"""
Tests for upstream_fixes.py, the local patch for manim-chess
issue #3.

Needs the project's environment (manim, manim-chess). Run from the
repository root:
    .venv/bin/python -m unittest discover tests
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import manim_chess

import upstream_fixes  # noqa: F401  (applies the patches)


class BoardLabelTest(unittest.TestCase):
    """Labels on a1-h1 and a1-a8 stay put when squares change colour."""

    def setUp(self):
        self.board = manim_chess.Board()
        self.board.set_board_from_FEN()
        self.board.scale(0.74)  # BOARD_SCALE; the bug only shows on a resized board

    def labels(self, square):
        return [(round(float(m.get_x()), 4), round(float(m.get_y()), 4),
                 m[0].get_fill_color().to_hex())
                for m in self.board.squares[square].submobjects]

    def test_move_keeps_labels_in_place(self):
        g1, a1 = self.labels("g1"), self.labels("a1")
        self.board.move_piece("g1", "f3")  # highlights g1
        self.assertEqual(self.labels("g1"), g1)
        self.board.move_piece("g8", "f6")  # clears g1
        self.assertEqual(self.labels("g1"), g1)
        self.board.move_piece("a2", "a4")  # a-file: rank label on a4, a2
        self.board.move_piece("b8", "c6")
        self.assertEqual(self.labels("a1"), a1)
        self.assertEqual(len(self.labels("a4")), 1)

    def test_square_still_changes_colour(self):
        board = self.board
        board.highlight_square("g1")
        self.assertEqual(board.squares["g1"].get_fill_color(), board.color_highlight_dark)
        board.unmark_square("g1")
        self.assertEqual(board.squares["g1"].get_fill_color(), board.color_dark)
        board.mark_square("h1")
        self.assertEqual(board.squares["h1"].get_fill_color().to_hex(), "#EC7D6A")


if __name__ == "__main__":
    unittest.main()
