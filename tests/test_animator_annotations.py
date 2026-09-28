"""
Tests for how PGN annotations are shown by the animator panels.

Needs the project's environment (manim, manim-chess). Run from the
repository root:
    .venv/bin/python -m unittest discover tests
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import chess
import manim_chess
from manim import ManimColor, interpolate_color

from animator_game import (BoardAnnotation, CheckGlow, CommentPanel, MoveData,
                           MoveListPanel, move_mark, play_move)
from animator_layout import ANNOTATION_COLORS


def _move(ply, san, classification):
    return MoveData(ply, san, "a1a2", ply % 2 == 1, 0, 0, 0, classification,
                    san, False, False, [])


class MoveListMarksTest(unittest.TestCase):

    def test_pgn_mark_is_shown_on_an_unmarked_engine_move(self):
        panel = MoveListPanel(marks={34: "!!"})
        self.assertEqual(panel._format_move_text(_move(34, "Be6", "best")), "Be6!!")

    def test_pgn_mark_replaces_the_engine_symbol(self):
        panel = MoveListPanel(marks={35: "!?"})
        self.assertEqual(panel._format_move_text(_move(35, "Bxb6", "mistake")), "Bxb6!?")

    def test_engine_symbol_is_kept_without_a_pgn_mark(self):
        panel = MoveListPanel(marks={34: "!!"})
        self.assertEqual(panel._format_move_text(_move(35, "Bxb6", "mistake")), "Bxb6?")


class MoveMarkTest(unittest.TestCase):

    def test_pgn_mark_wins_over_the_engine_rating(self):
        self.assertEqual(move_mark(_move(35, "Bxb6", "mistake"), {35: "!?"}), "!?")

    def test_engine_rating_without_a_pgn_mark(self):
        self.assertEqual(move_mark(_move(35, "Bxb6", "inaccuracy"), {}), "?!")

    def test_no_mark_for_an_unremarkable_move(self):
        self.assertEqual(move_mark(_move(35, "Bxb6", "best"), {}), "")


class BoardAnnotationTest(unittest.TestCase):

    def setUp(self):
        self.board = manim_chess.Board()
        self.board.set_board_from_FEN()
        self.board.scale(0.74)
        self.position = chess.Board()
        self.annotation = BoardAnnotation(self.board)

    def play(self, uci, symbol):
        play_move(self.board, self.position, uci)
        return self.annotation.update(uci, symbol)

    def fill(self, square):
        return self.board.squares[square].get_fill_color().to_hex().lower()

    def test_marked_move_tints_both_squares_with_its_colour(self):
        self.play("e2e4", "?")
        tint = ManimColor(ANNOTATION_COLORS["?"][0])
        for square, base in (("e2", self.board.color_light),
                             ("e4", self.board.color_light)):
            expected = interpolate_color(base, tint, BoardAnnotation.TINT)
            self.assertEqual(self.fill(square), expected.to_hex().lower())

    def test_badge_sits_on_the_destination_squares_top_right_corner(self):
        self.play("g1f3", "!!")
        square = self.board.squares["f3"]
        badge = self.annotation.get_mobject()
        self.assertGreater(len(badge.submobjects), 0)
        x, y = badge.get_center()[:2]
        right, top = square.get_right()[0], square.get_top()[1]
        self.assertAlmostEqual(x, right - 0.1 * square.width, delta=0.02)
        self.assertAlmostEqual(y, top - 0.045 * square.width, delta=0.03)

    def test_unmarked_move_keeps_the_plain_highlight_and_has_no_badge(self):
        self.play("e2e4", "")
        self.assertEqual(self.fill("e4"),
                         self.board.color_highlight_light.to_hex().lower())
        self.assertEqual(len(self.annotation.get_mobject().submobjects), 0)

    def test_next_move_removes_the_previous_badge_and_tint(self):
        self.play("e2e4", "??")
        self.play("e7e5", "")
        self.assertEqual(len(self.annotation.get_mobject().submobjects), 0)
        self.assertEqual(self.fill("e4"), self.board.color_light.to_hex().lower())


class CheckGlowTest(unittest.TestCase):

    def setUp(self):
        self.board = manim_chess.Board()
        self.board.set_board_from_FEN()
        self.board.scale(0.74)
        self.position = chess.Board()
        self.glow = CheckGlow(self.board)

    def play(self, *ucis):
        for uci in ucis:
            play_move(self.board, self.position, uci)
            self.glow.update(self.position)

    def glowing_squares(self):
        return [name for name, square in self.board.squares.items()
                if self.glow.get_mobject() in square.submobjects]

    def test_king_in_check_glows_between_its_square_and_the_king(self):
        self.play("e2e4", "f7f6", "d1h5")
        self.assertEqual(self.glowing_squares(), ["e8"])
        family = self.board.get_family()
        glow = self.glow.get_mobject()
        self.assertLess(family.index(self.board.squares["e8"]), family.index(glow))
        self.assertLess(family.index(glow), family.index(self.board.pieces["e8"]))

    def test_glow_stays_inside_the_square(self):
        self.play("e2e4", "f7f6", "d1h5")
        square, glow = self.board.squares["e8"], self.glow.get_mobject()
        self.assertGreater(len(glow.submobjects), 0)
        self.assertLessEqual(glow.width, square.width + 1e-6)
        self.assertLessEqual(glow.height, square.height + 1e-6)
        self.assertTrue(all(abs(a - b) < 1e-6 for a, b in
                            zip(glow.get_center(), square.get_center())))

    def test_glow_goes_once_the_check_is_answered(self):
        self.play("e2e4", "f7f6", "d1h5", "g7g6")
        self.assertEqual(self.glowing_squares(), [])

    def test_no_glow_without_check(self):
        self.play("e2e4")
        self.assertEqual(self.glowing_squares(), [])


class MoveListRowsTest(unittest.TestCase):

    def rows(self, moves):
        panel = MoveListPanel()
        panel.moves.extend(moves)
        return [(n, w and w.move_san, b and b.move_san) for n, w, b in panel.rows()]

    def test_white_and_black_share_a_row_even_for_blunders(self):
        moves = [_move(1, "e4", "best"), _move(2, "e5", "best"),
                 _move(3, "Bg5", "blunder"), _move(4, "Na4", "brilliant"),
                 _move(5, "Qa3", "mistake")]
        self.assertEqual(self.rows(moves),
                         [(1, "e4", "e5"), (2, "Bg5", "Na4"), (3, "Qa3", None)])

    def test_a_game_starting_with_black_leaves_the_white_cell_empty(self):
        self.assertEqual(self.rows([_move(2, "e5", "best"), _move(3, "Nf3", "best")]),
                         [(1, None, "e5"), (2, "Nf3", None)])


class OverlongCommentsTest(unittest.TestCase):

    def test_reports_move_comments_longer_than_the_panel(self):
        long_text = "word " * 200
        comments = {"34": "Short enough.", "35": long_text, "intro": long_text}
        self.assertEqual(CommentPanel.overlong_comments(comments),
                         [("35", len(CommentPanel.wrap_comment(long_text)))])


if __name__ == "__main__":
    unittest.main()
