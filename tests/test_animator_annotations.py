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
                           MoveListPanel, PlayerBars, format_clock,
                           material_imbalance, move_mark, play_move)
from animator_layout import ANNOTATION_COLORS, COLORS


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


class FormatClockTest(unittest.TestCase):

    def test_minutes_and_seconds(self):
        self.assertEqual(format_clock(603), "10:03")
        self.assertEqual(format_clock(65), "1:05")

    def test_hours(self):
        self.assertEqual(format_clock(3600), "1:00:00")
        self.assertEqual(format_clock(5405), "1:30:05")

    def test_tenths_when_low(self):
        self.assertEqual(format_clock(8.4), "0:08.4")
        self.assertEqual(format_clock(19.96), "0:19.9")
        self.assertEqual(format_clock(0), "0:00.0")
        self.assertEqual(format_clock(20), "0:20")

    def test_unknown(self):
        self.assertEqual(format_clock(None), "–:––")


class MaterialImbalanceTest(unittest.TestCase):

    def after(self, *sans):
        position = chess.Board()
        for san in sans:
            position.push_san(san)
        return material_imbalance(position)

    def test_start_position_is_level(self):
        self.assertEqual(self.after(), ([], [], 0))

    def test_a_capture_puts_the_capturer_ahead(self):
        self.assertEqual(self.after("e4", "d5", "exd5"), ([chess.PAWN], [], 1))

    def test_equal_trades_cancel(self):
        self.assertEqual(self.after("e4", "d5", "exd5", "Qxd5"), ([], [], 0))

    def test_each_side_shows_the_pieces_it_is_up(self):
        # Late in Byrne–Fischer: White has a queen for Black's rook, two
        # bishops and three pawns
        position = chess.Board("1Q6/5pk1/2p3p1/1pbbN2p/4n2P/8/r5P1/6K1 w - - 0 1")
        self.assertEqual(material_imbalance(position),
                         ([chess.QUEEN],
                          [chess.PAWN] * 3 + [chess.BISHOP] * 2 + [chess.ROOK], -5))

    def test_a_promoted_pawn_counts_as_its_new_piece(self):
        position = chess.Board("rnbqkbnr/pppppppp/8/8/8/Q7/1PPPPPPP/RNBQKBNR b KQkq - 0 1")
        self.assertEqual(material_imbalance(position), ([chess.QUEEN], [chess.PAWN], 8))


class PlayerBarsTest(unittest.TestCase):

    def setUp(self):
        self.board = manim_chess.Board()
        self.board.set_board_from_FEN()
        self.board.scale(0.74)

    def bars(self, start=600, clocks=None, names=("boneyland (1845)", "Futur_ist (1224)")):
        return PlayerBars(self.board, names, start,
                          {1: 603.0} if clocks is None else clocks)

    def test_before_the_first_move_both_clocks_show_the_start_time(self):
        bars = self.bars(clocks={1: 603.0, 2: 598.0})
        self.assertEqual(bars.times(0), (600, 600))

    def test_only_the_mover_clock_changes(self):
        bars = self.bars(clocks={1: 603.0, 2: 598.0, 3: 590.0})
        self.assertEqual(bars.times(1), (603.0, 600))
        self.assertEqual(bars.times(2), (603.0, 598.0))
        self.assertEqual(bars.times(3), (590.0, 598.0))

    def test_a_missing_clock_keeps_the_last_known_time(self):
        bars = self.bars(start=None, clocks={1: 180.0, 3: 175.0})
        self.assertEqual(bars.times(2), (180.0, None))
        self.assertEqual(bars.times(4), (175.0, None))

    def test_black_above_and_white_below_the_board(self):
        bars = self.bars()
        for (clock, name), above in zip(zip(bars.clock_labels(0), bars.name_labels),
                                        (False, True)):
            for label in (clock, name):
                if above:
                    self.assertGreater(label.get_bottom()[1], self.board.get_top()[1])
                else:
                    self.assertLess(label.get_top()[1], self.board.get_bottom()[1])
            self.assertAlmostEqual(clock.get_right()[0], self.board.get_right()[0])
            self.assertAlmostEqual(name.get_left()[0], self.board.get_left()[0])

    def test_side_to_move_clock_is_emphasised(self):
        bars = self.bars()
        primary = ManimColor(COLORS.text_primary)
        secondary = ManimColor(COLORS.text_secondary)
        white, black = bars.clock_labels(0)
        self.assertEqual((white[0].get_fill_color(), black[0].get_fill_color()),
                         (primary, secondary))
        white, black = bars.clock_labels(1)
        self.assertEqual((white[0].get_fill_color(), black[0].get_fill_color()),
                         (secondary, primary))
        self.assertLess(white[0].get_fill_opacity(), black[0].get_fill_opacity())

    def test_no_clocks_without_clock_times(self):
        self.assertEqual(self.bars(start=None, clocks={}).clock_labels(0), ())

    def test_names_that_fit_the_bar_are_not_cut(self):
        bars = self.bars(names=("Carlsen, Magnus (2803)", "Nepomniachtchi, Ian (2729)"))
        self.assertEqual([n.text for n in bars.name_labels],
                         ["Carlsen,Magnus(2803)", "Nepomniachtchi,Ian(2729)"])

    def test_long_names_are_cut_clear_of_the_clock(self):
        bars = self.bars(names=("x" * 80, "Byrne"))
        white, black = bars.name_labels
        self.assertTrue(white.text.endswith("…"))
        self.assertEqual(black.text, "Byrne")
        clock = bars.clock_labels(0)[0]
        self.assertLess(white.get_right()[0], clock.get_left()[0] - 0.5)

    def test_material_follows_the_name_with_the_lead(self):
        bars = self.bars()
        position = chess.Board()
        for san in ("e4", "d5", "exd5"):
            position.push_san(san)
        white, black = bars.material_items(position)
        self.assertEqual(len(black), 0)
        icon, lead = white
        self.assertEqual(lead.text, "+1")
        name = bars.name_labels[0]
        self.assertGreater(icon.get_left()[0], name.get_right()[0])
        self.assertGreater(lead.get_left()[0], icon.get_right()[0])
        self.assertAlmostEqual(icon.get_center()[1], name.get_center()[1], places=2)


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
