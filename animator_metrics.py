"""
animator_metrics.py

Draws the metrics strip at the bottom of the chess video frame: one
full-width plot of Stockfish's evaluation, revealed one move at a time as
the game is animated.

The evaluation is plotted as White's win-probability advantage in [-1, +1]
(Lichess's centipawn -> win-chance curve), so large evals and forced mates
bend towards the edge instead of being clipped.  The plot starts from the
starting position's eval, and is green while White is better and red while
Black is better; a segment that crosses zero changes colour where it crosses.

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

from chess_game_analyzer import winning_chances
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

# Stroke widths
_LINE_WIDTH   = 1.5   # data series
_ZERO_WIDTH   = 0.8   # zero reference line
_CURSOR_WIDTH = 1.0   # vertical cursor


# =============================================================================
# Coordinate helpers
# =============================================================================

def _x_coord(point_idx: int, total_points: int) -> float:
    """
    Map a point index (0-based) to an x-coordinate.
    point_idx == 0 → left edge;  point_idx == total_points-1 → right edge.
    """
    if total_points <= 1:
        return _PLOT_DRAW_LEFT
    return _PLOT_DRAW_LEFT + point_idx / (total_points - 1) * _PLOT_DRAW_WIDTH


def _y_coord(value: float) -> float:
    """Map a win advantage in [-1, +1] to a y-coordinate in the drawing area."""
    value = max(-1.0, min(1.0, value))
    return _PLOT_DRAW_BOTTOM + (value + 1.0) / 2.0 * _PLOT_HEIGHT


def _segment_lines(x0: float, v0: float, x1: float, v1: float) -> List[Line]:
    """
    The plot between two points: one line, or two when it crosses zero, so
    each part is coloured by the side that is better along it.
    """
    points = [(x0, v0), (x1, v1)]
    if (v0 > 0 > v1) or (v0 < 0 < v1):
        x_zero = x0 + (x1 - x0) * v0 / (v0 - v1)
        points.insert(1, (x_zero, 0.0))
    lines = []
    for (xa, va), (xb, vb) in zip(points, points[1:]):
        lines.append(Line(
            start=[xa, _y_coord(va), 0],
            end=[xb, _y_coord(vb), 0],
            stroke_color=COLORS.plot_net_pos if va + vb >= 0 else COLORS.plot_net_neg,
            stroke_width=_LINE_WIDTH,
        ))
    return lines


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
        # One point for the starting position, then one after each move
        self._values = ([winning_chances(all_moves[0].eval_before)] if all_moves else [])
        self._values += [winning_chances(m.eval_after) for m in all_moves]

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
        Extend the plot by one segment, from the position before move `idx`
        (0-based) to the position after it, and move the cursor there.

        Returns an animation that can be played in parallel with the board
        move and panel updates.
        """
        if not 0 <= idx < self.total_moves:
            return Wait(0)

        n = len(self._values)
        x_old, x_new = _x_coord(idx, n), _x_coord(idx + 1, n)
        segment = VGroup(*_segment_lines(x_old, self._values[idx],
                                         x_new, self._values[idx + 1]))
        self._segments.add(segment)

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
                self.eval_before = 300 * math.sin(2 * math.pi * (i - 1) / N)
                self.eval_after = 300 * math.sin(2 * math.pi * i / N)

        panel = MetricPlotPanel([_FakeMove(i) for i in range(N)])
        self.add(panel.get_mobject())
        self.wait(0.5)

        for idx in range(N):
            self.play(panel.advance_to_move(idx), run_time=0.08)

        self.wait(2)
