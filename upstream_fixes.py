"""
upstream_fixes.py

Local patches for bugs in manim and manim-chess, applied on import.  Each
one is reported upstream; delete it (and this file and its imports, once
empty) when the fix is in a release.
"""

import manim_chess
from manim import ManimColor, SVGMobject


# =============================================================================
# manim: stroke="none" drawn as an opaque white stroke
# https://github.com/ManimCommunity/manim/issues/5035
#
# svgelements parses "none" as a Color with no value, set_style ignores None,
# and the default stroke (white, opaque) stays at whatever width applies.  In
# manim-chess this puts a white outline round the black knight's mane stripe,
# so the stripe covers the knight's black edge.
# =============================================================================

_apply_style_to_mobject = SVGMobject.apply_style_to_mobject


def _apply_style_hiding_stroke_none(mob, shape):
    mob = _apply_style_to_mobject(mob, shape)
    # Width rather than opacity: Text is an SVGMobject whose glyphs have
    # stroke="none", and Text(...).set_stroke(BLACK, 2) must still show.
    if shape.stroke is None or shape.stroke.value is None:
        mob.set_stroke(width=0)
    return mob


SVGMobject.apply_style_to_mobject = staticmethod(_apply_style_hiding_stroke_none)


# =============================================================================
# manim-chess: file/rank labels move off their square on a resized board
# https://github.com/swoyer2/manim_chess/issues/3
#
# highlight_square, unmark_square and mark_square recolour the square together
# with its labels, then add fresh labels placed with the unscaled cell_size.
# Recolouring only the square leaves the original labels where they are.
# =============================================================================

def _set_square_color(self, coordinate, color):
    self.squares[coordinate].set_fill(color, family=False)


def _mark_square(self, coordinate):
    self._set_square_color(coordinate, ManimColor('#EC7D6A'))


def _unmark_square(self, coordinate):
    light = self.is_light_square(coordinate)
    self._set_square_color(coordinate, self.color_light if light else self.color_dark)


def _highlight_square(self, coordinate):
    light = self.is_light_square(coordinate)
    self._set_square_color(coordinate, self.color_highlight_light if light
                           else self.color_highlight_dark)


manim_chess.Board._set_square_color = _set_square_color
manim_chess.Board.mark_square = _mark_square
manim_chess.Board.unmark_square = _unmark_square
manim_chess.Board.highlight_square = _highlight_square
