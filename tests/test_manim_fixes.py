"""
Tests for manim_fixes.py, the local patch for manim issue #5035.

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

import manim_fixes  # noqa: F401  (applies the patch)


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


if __name__ == "__main__":
    unittest.main()
