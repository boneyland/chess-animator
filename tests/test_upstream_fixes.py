"""
Tests for upstream_fixes.py, the local patches for manim issue #5035
and manim-chess issue #3.

Needs the project's environment (manim, manim-chess). Run from the
repository root:
    .venv/bin/python -m unittest discover tests
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import manim_chess
from manim import BLACK, SVGMobject, Text

import upstream_fixes  # noqa: F401  (applies the patches)


SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">
  <g stroke="#000" stroke-width="4">
    <rect x="10" y="10" width="80" height="80" fill="#000"/>
    <rect x="30" y="30" width="40" height="40" fill="#00f" stroke="none"/>
  </g>
</svg>
"""


class StrokeNoneTest(unittest.TestCase):
    def setUp(self):
        fd, self.path = tempfile.mkstemp(suffix=".svg")
        with os.fdopen(fd, "w") as f:
            f.write(SVG)
        self.addCleanup(os.remove, self.path)

    def test_stroke_none_has_no_visible_stroke(self):
        inner = SVGMobject(self.path, use_svg_cache=False)[1]
        self.assertEqual(inner.get_stroke_width(), 0)

    def test_text_outline_still_shows(self):
        glyph = Text("Nf3").set_stroke(BLACK, 2)[0]
        self.assertEqual(glyph.get_stroke_width(), 2)
        self.assertEqual(glyph.get_stroke_opacity(), 1)

    def test_inherited_stroke_is_kept(self):
        outer = SVGMobject(self.path, use_svg_cache=False)[0]
        self.assertEqual(outer.get_stroke_color().to_hex(), "#000000")
        self.assertEqual(outer.get_stroke_opacity(), 1)
        self.assertEqual(outer.get_stroke_width(), 4)

    def test_black_knight_mane_stripe_has_no_stroke(self):
        # The stripe is the last path in bN.svg and the only one with
        # stroke="none"; the body and head keep their black outline.
        knight = manim_chess.Knight(is_white=False)[0]
        self.assertEqual(knight[3].get_stroke_width(), 0)
        self.assertGreater(knight[0].get_stroke_width(), 0)


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
