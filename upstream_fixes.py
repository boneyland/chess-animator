"""
upstream_fixes.py

Local patches for bugs in manim-chess, applied on import.  Each
one is reported upstream; delete it (and this file and its imports, once
empty) when the fix is in a release.
"""

import manim_chess
from manim import ManimColor


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
