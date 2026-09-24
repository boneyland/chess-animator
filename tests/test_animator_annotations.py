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

from animator_game import CommentPanel, MoveData, MoveListPanel

_Z = dict(space_white=0, space_black=0, mobility_white=0, mobility_black=0,
          king_safety_white=0, king_safety_black=0, threats_white=0,
          threats_black=0, fti1=0, fti2=0, fti3=0)


def _move(ply, san, classification):
    return MoveData(ply, san, "a1a2", ply % 2 == 1, 0, 0, 0, classification,
                    san, False, False, [], **_Z)


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


class MoveListRowsTest(unittest.TestCase):

    def rows(self, moves):
        panel = MoveListPanel()
        panel.moves.extend(moves)
        return [(n, w and w.move_san, b and b.move_san) for n, w, b in panel.rows()]

    def test_white_and_black_share_a_row_even_for_blunders(self):
        moves = [_move(1, "e4", "book"), _move(2, "e5", "book"),
                 _move(3, "Bg5", "blunder"), _move(4, "Na4", "brilliant"),
                 _move(5, "Qa3", "mistake")]
        self.assertEqual(self.rows(moves),
                         [(1, "e4", "e5"), (2, "Bg5", "Na4"), (3, "Qa3", None)])

    def test_a_game_starting_with_black_leaves_the_white_cell_empty(self):
        self.assertEqual(self.rows([_move(2, "e5", "book"), _move(3, "Nf3", "best")]),
                         [(1, None, "e5"), (2, "Nf3", None)])


class OverlongCommentsTest(unittest.TestCase):

    def test_reports_move_comments_longer_than_the_panel(self):
        long_text = "word " * 200
        comments = {"34": "Short enough.", "35": long_text, "intro": long_text}
        self.assertEqual(CommentPanel.overlong_comments(comments),
                         [("35", len(CommentPanel.wrap_comment(long_text)))])


if __name__ == "__main__":
    unittest.main()
