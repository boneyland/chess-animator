"""
animator_metrics.py

Draws the metrics strip at the bottom of the chess video frame: one
full-width plot of Stockfish's evaluation, revealed one move at a time as
the game is animated.

The evaluation is plotted as White's win-probability advantage in [-1, +1]
(Lichess's centipawn -> win-chance curve), so large evals and forced mates
bend towards the edge instead of being clipped.  Segments are green while
White is better and red while Black is better.

The plot is built from individual Manim Line segments rather than a
parametric function, which lets us add exactly one segment per move inside
the animation loop with no re-rendering of earlier data.

Public API (used by animator_game.py)
--------------------------------------
    panel = MetricPlotPanel(all_moves)   # construct once
    scene.add(panel.get_mobject())       # add static elements to scene
    anim  = panel.advance_to_move(idx)   # call inside the animation loop
    scene.play(anim, ...)
"""

from __future__ import annotations

import math
from typing import List

from manim import *

from animator_layout import (
    COLORS, FONTS,
    METRICS_TOP_Y, METRICS_BOTTOM_Y, METRICS_CENTER_X,
    METRICS_LEFT_X, METRICS_WIDTH,
    get_metrics_rect,
)

# Import MoveData type for annotations only (avoid circular import at runtime)
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from animator_game import MoveData


# =============================================================================
# Layout constants local to this module
# =============================================================================

_PLOT_TOP_MARGIN    = 0.22   # space above the axes for the label
_PLOT_BOTTOM_MARGIN = 0.18   # breathing room below the curve
_PLOT_H_MARGIN      = 0.15   # horizontal inset inside the strip

_PLOT_HEIGHT = (METRICS_TOP_Y - METRICS_BOTTOM_Y
                - _PLOT_TOP_MARGIN - _PLOT_BOTTOM_MARGIN)
_PLOT_DRAW_TOP    = METRICS_TOP_Y    - _PLOT_TOP_MARGIN
_PLOT_DRAW_BOTTOM = METRICS_BOTTOM_Y + _PLOT_BOTTOM_MARGIN
_PLOT_DRAW_LEFT   = METRICS_LEFT_X + _PLOT_H_MARGIN
_PLOT_DRAW_WIDTH  = METRICS_WIDTH - 2 * _PLOT_H_MARGIN

_EVAL_WIN_K = 0.00368208   # Lichess logistic coefficient (per centipawn)

# Stroke widths
_LINE_WIDTH   = 1.5   # data series
_ZERO_WIDTH   = 0.8   # zero reference line
_CURSOR_WIDTH = 1.0   # vertical cursor


# =============================================================================
# Coordinate helpers
# =============================================================================

def _x_coord(move_idx: int, total_moves: int) -> float:
    """
    Map a move index (0-based) to an x-coordinate.
    move_idx == 0 → left edge;  move_idx == total_moves-1 → right edge.
    """
    if total_moves <= 1:
        return _PLOT_DRAW_LEFT
    return _PLOT_DRAW_LEFT + move_idx / (total_moves - 1) * _PLOT_DRAW_WIDTH


def _y_coord(value: float) -> float:
    """Map a win advantage in [-1, +1] to a y-coordinate in the drawing area."""
    value = max(-1.0, min(1.0, value))
    return _PLOT_DRAW_BOTTOM + (value + 1.0) / 2.0 * _PLOT_HEIGHT


def _win_advantage(eval_cp: float) -> float:
    """
    Map a centipawn eval (White's POV) to White's win-probability advantage
    in [-1, +1]:  0 cp → 0,  ±100 cp → ±0.18,  ±300 cp → ±0.50,
    ±500 cp → ±0.73,  ±1000 cp → ±0.95,  forced mate → ±1.
    """
    return 2.0 / (1.0 + math.exp(-_EVAL_WIN_K * eval_cp)) - 1.0


# =============================================================================
# MetricPlotPanel  (public API)
# =============================================================================

class MetricPlotPanel:
    """
    Full-width strip with the evaluation plot.

    Usage in animator_game.py::

        # Construction (once, before the animation loop)
        metric_panel = MetricPlotPanel(analysis.moves)
        self.add(metric_panel.get_mobject())

        # Inside the loop
        anim = metric_panel.advance_to_move(idx)
        self.play(..., anim, run_time=0.4)
    """

    def __init__(self, all_moves: "List[MoveData]"):
        self.total_moves = len(all_moves)
        self._values = [_win_advantage(m.eval_after) for m in all_moves]
        self._prev_y = _y_coord(self._values[0]) if self._values else None

        self._segments = VGroup()
        self._cursor = Line(
            start=[_PLOT_DRAW_LEFT, _PLOT_DRAW_BOTTOM, 0],
            end=[_PLOT_DRAW_LEFT, _PLOT_DRAW_TOP, 0],
            stroke_color=COLORS.plot_cursor,
            stroke_width=_CURSOR_WIDTH,
            stroke_opacity=0.5,
        )
        self._static = self._build_static()

    def _build_static(self) -> VGroup:
        """Strip background, zero line and label."""
        zero_y = _y_coord(0.0)
        zero_line = Line(
            start=[_PLOT_DRAW_LEFT, zero_y, 0],
            end=[_PLOT_DRAW_LEFT + _PLOT_DRAW_WIDTH, zero_y, 0],
            stroke_color=COLORS.plot_zero_line,
            stroke_width=_ZERO_WIDTH,
        )
        label = Text("Eval", font=FONTS.body_font,
                     font_size=FONTS.metric_label_size,
                     color=COLORS.text_secondary)
        range_text = Text("White's win chance", font=FONTS.body_font,
                          font_size=FONTS.metric_label_size - 2,
                          color=COLORS.text_secondary)
        header = VGroup(label, range_text).arrange(RIGHT, buff=0.08)
        header.move_to([METRICS_CENTER_X, METRICS_TOP_Y - _PLOT_TOP_MARGIN / 2, 0])
        return VGroup(get_metrics_rect(), zero_line, header)

    def get_mobject(self) -> VGroup:
        """
        Return the complete VGroup for the metrics strip.
        Add this to the Manim scene once before the animation loop.
        """
        return VGroup(self._static, self._segments, self._cursor)

    def advance_to_move(self, idx: int) -> Animation:
        """
        Extend the plot by one segment to include move number `idx`
        (0-based), and slide the cursor to the new position.

        Returns an animation that can be played in parallel with the board
        move and panel updates.
        """
        # idx == 0 is the starting point; there is no segment to draw yet.
        if idx == 0 or idx >= self.total_moves:
            return Wait(0)

        n = self.total_moves
        value = self._values[idx]
        x_new, x_old = _x_coord(idx, n), _x_coord(idx - 1, n)
        y_new = _y_coord(value)
        segment = Line(
            start=[x_old, self._prev_y, 0],
            end=[x_new, y_new, 0],
            stroke_color=COLORS.plot_net_pos if value >= 0 else COLORS.plot_net_neg,
            stroke_width=_LINE_WIDTH,
        )
        self._segments.add(segment)
        self._prev_y = y_new

        # The cursor is repositioned in place, so it needs no animation
        self._cursor.put_start_and_end_on([x_new, _PLOT_DRAW_BOTTOM, 0],
                                          [x_new, _PLOT_DRAW_TOP, 0])
        return FadeIn(segment, run_time=0.0)


# =============================================================================
# Standalone debug scene
# =============================================================================

class MetricsDebug(Scene):
    """
    Renders the metrics strip with a synthetic evaluation so you can check
    layout and colors without needing a real game analysis file.

    Run with:
        manim -pql animator_metrics.py MetricsDebug
    """

    def construct(self):
        self.camera.background_color = COLORS.background

        N = 40

        class _FakeMove:
            def __init__(self, i):
                self.eval_after = 300 * math.sin(2 * math.pi * i / N)

        panel = MetricPlotPanel([_FakeMove(i) for i in range(N)])
        self.add(panel.get_mobject())
        self.wait(0.5)

        for idx in range(1, N):
            self.play(panel.advance_to_move(idx), run_time=0.08)

        self.wait(2)
