"""
Tests for naming openings from the Lichess opening data.

Run from the repository root:
    python -m unittest discover tests
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from chess_openings import Opening, OpeningBook


# Byrne–Fischer 1956, the first 12 plies
BYRNE_FISCHER = ["g1f3", "g8f6", "c2c4", "g7g6", "b1c3", "f8g7",
                 "d2d4", "e8g8", "c1f4", "d7d5", "d1b3", "d5c4"]

SMALL_BOOK = OpeningBook.from_rows([
    ("C20", "King's Pawn Game", "1. e4 e5"),
    ("C44", "King's Knight Opening: Normal Variation", "1. e4 e5 2. Nf3 Nc6"),
    ("C60", "Ruy Lopez", "1. e4 e5 2. Nf3 Nc6 3. Bb5"),
])


class OpeningsByPlyTest(unittest.TestCase):

    def test_each_book_move_takes_the_last_name_on_its_line(self):
        # 1.e4 is only a step on the way to named positions, so has no name yet
        self.assertEqual(SMALL_BOOK.openings_by_ply(["e2e4", "e7e5", "g1f3", "b8c6"]),
                         [None,
                          Opening("C20", "King's Pawn Game"),
                          Opening("C20", "King's Pawn Game"),
                          Opening("C44", "King's Knight Opening: Normal Variation")])

    def test_a_position_the_game_reaches_by_another_move_order_takes_its_lines_name(self):
        book = OpeningBook.from_rows([
            ("C40", "King's Knight Opening", "1. e4 e5 2. Nf3"),
            ("C50", "Italian Game", "1. e4 e5 2. Nf3 Nc6 3. Bc4"),
        ])
        # 1.Nf3 Nc6 2.e4 e5 skips 1.e4 e5 2.Nf3, the named position before it
        self.assertEqual(book.openings_by_ply(["g1f3", "b8c6", "e2e4", "e7e5"])[3],
                         Opening("C40", "King's Knight Opening"))

    def test_a_position_on_several_lines_takes_the_deepest_name_before_it(self):
        book = OpeningBook.from_rows([
            ("C20", "King's Pawn Game", "1. e4 e5"),
            ("C20", "King's Pawn Game: Early Bb5", "1. e4 e5 2. Bb5 Nc6 3. Nf3 Nf6"),
            ("C44", "King's Knight Opening: Normal Variation", "1. e4 e5 2. Nf3 Nc6"),
            ("C60", "Ruy Lopez: Morphy Defense", "1. e4 e5 2. Nf3 Nc6 3. Bb5 a6 4. Ba4"),
        ])
        # 1.e4 e5 2.Bb5 Nc6 3.Nf3 is on two lines: the last name before it is
        # 1...e5 (ply 2) on the Early Bb5 line, 2...Nc6 (ply 4) on the Morphy one
        self.assertEqual(book.openings_by_ply(["e2e4", "e7e5", "f1b5", "b8c6", "g1f3"])[4],
                         Opening("C44", "King's Knight Opening: Normal Variation"))

    def test_between_equally_deep_names_the_first_in_the_data_wins(self):
        book = OpeningBook.from_rows([
            ("C20", "King's Pawn Game", "1. e4 e5"),
            ("C50", "Italian Game", "1. e4 e5 2. Nf3 Nc6 3. Bc4"),
            ("B00", "Nimzowitsch Defense", "1. e4 Nc6"),
            ("C50", "Italian Game", "1. e4 Nc6 2. Nf3 e5 3. Bc4"),
        ])
        self.assertEqual(book.openings_by_ply(["e2e4", "b8c6", "g1f3", "e7e5"])[3],
                         Opening("C20", "King's Pawn Game"))

    def test_a_move_out_of_book_has_no_opening(self):
        self.assertEqual(SMALL_BOOK.openings_by_ply(["e2e4", "e7e5", "d2d4"])[2], None)

    def test_moves_that_transpose_into_a_named_position_get_its_name(self):
        # 1.Nf3 Nc6 2.e4 e5 reaches the position of 1.e4 e5 2.Nf3 Nc6
        self.assertEqual(SMALL_BOOK.openings_by_ply(["g1f3", "b8c6", "e2e4", "e7e5"]),
                         [None, None, None,
                          Opening("C44", "King's Knight Opening: Normal Variation")])

    def test_moves_after_an_illegal_move_have_no_opening(self):
        self.assertEqual(SMALL_BOOK.openings_by_ply(["e2e4", "a1a2", "g1f3"]),
                         [None, None, None])


class IdentifyTest(unittest.TestCase):

    def test_the_game_is_named_after_its_last_named_position(self):
        moves = ["e2e4", "e7e5", "g1f3", "b8c6", "f1b5", "a7a6", "b5a4"]
        self.assertEqual(SMALL_BOOK.identify(moves), Opening("C60", "Ruy Lopez"))

    def test_a_game_that_never_reaches_a_named_position_is_unnamed(self):
        self.assertIsNone(SMALL_BOOK.identify(["d2d4", "d7d5"]))


class LichessDataTest(unittest.TestCase):
    """The data shipped in openings/, on the sample game."""

    @classmethod
    def setUpClass(cls):
        cls.book = OpeningBook.load()
        cls.openings = cls.book.openings_by_ply(BYRNE_FISCHER)

    def test_the_sample_game_is_named_after_the_grunfeld_it_transposes_to(self):
        # 5...d5 lies on 1.d4 Nf6 2.c4 g6 3.Nc3 d5 4.Nf3 Bg7 5.Bf4 O-O, a ply
        # after the Hungarian Attack, which the game's move order skips
        hungarian = Opening("D92", "Grünfeld Defense: Three Knights Variation, "
                                   "Hungarian Attack")
        self.assertEqual(self.openings[9], hungarian)
        self.assertEqual(self.book.identify(BYRNE_FISCHER), hungarian)

    def test_the_sample_game_leaves_book_at_5_bf4_and_returns_at_5_d5(self):
        in_book = [o is not None for o in self.openings]
        self.assertEqual(in_book, [True] * 8 + [False, True, False, False])
