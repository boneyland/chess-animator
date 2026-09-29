"""
Tests for reading commentary and move marks from PGN files and notes files.

Run from the repository root:
    python -m unittest discover tests
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from convert_script_to_comment_dict import (load_commentary, parse_comments_file,
                                            parse_pgn_annotations, parse_pgn_clocks)


def _write_temp(suffix: str, text: str) -> str:
    fd, path = tempfile.mkstemp(suffix=suffix)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(text)
    return path


def _write_pgn(movetext: str) -> str:
    """Write a minimal PGN with the given movetext to a temp file; return its path."""
    return _write_temp(".pgn", '[White "A"]\n[Black "B"]\n[Result "*"]\n\n' + movetext + " *\n")


class ParsePgnAnnotationsTest(unittest.TestCase):

    def parse(self, movetext):
        path = _write_pgn(movetext)
        self.addCleanup(os.remove, path)
        return parse_pgn_annotations(path)

    def test_comments_are_keyed_by_ply(self):
        comments, _ = self.parse("1. e4 {King's pawn.} e5 {Symmetrical.} 2. Nf3")
        self.assertEqual(comments, {"1": "King's pawn.", "2": "Symmetrical."})

    def test_comment_whitespace_is_collapsed(self):
        comments, _ = self.parse("1. e4 {A comment\n   spread over\nlines.}")
        self.assertEqual(comments["1"], "A comment spread over lines.")

    def test_clock_and_eval_tags_are_stripped(self):
        comments, _ = self.parse(
            "1. e4 { [%clk 0:03:00] } e5 { [%eval 0.2] [%clk 0:02:59] Solid. }")
        self.assertEqual(comments, {"2": "Solid."})

    def test_comment_before_first_move_is_the_intro(self):
        comments, _ = self.parse("{A famous game.} 1. e4 e5")
        self.assertEqual(comments, {"intro": "A famous game."})

    def test_side_variations_are_ignored(self):
        comments, marks = self.parse("1. e4 (1. d4! {Also good.}) 1... e5")
        self.assertEqual(comments, {})
        self.assertEqual(marks, {})

    def test_move_marks_are_keyed_by_ply(self):
        _, marks = self.parse("1. e4! e5? 2. Nf3!! Nc6?? 3. Bb5!? a6?! 4. Ba4 $10")
        self.assertEqual(marks, {1: "!", 2: "?", 3: "!!", 4: "??", 5: "!?", 6: "?!"})


class ParsePgnClocksTest(unittest.TestCase):

    def parse(self, movetext, headers=""):
        path = _write_temp(".pgn", headers + '[Result "*"]\n\n' + movetext + " *\n")
        self.addCleanup(os.remove, path)
        return parse_pgn_clocks(path)

    def test_clocks_are_keyed_by_ply_in_seconds(self):
        _, clocks = self.parse("1. e4 { [%clk 0:10:00] } e5 { [%clk 0:09:58.4] }")
        self.assertEqual(clocks, {1: 600.0, 2: 598.4})

    def test_start_time_comes_from_the_time_control(self):
        start, _ = self.parse("1. e4", '[TimeControl "600+5"]\n')
        self.assertEqual(start, 600)

    def test_unknown_or_missing_time_control_has_no_start_time(self):
        for headers in ("", '[TimeControl "-"]\n', '[TimeControl "40/7200:3600"]\n'):
            with self.subTest(headers=headers):
                self.assertIsNone(self.parse("1. e4", headers)[0])

    def test_moves_without_a_clock_are_left_out(self):
        _, clocks = self.parse("1. e4 { [%clk 0:03:00] } e5 2. Nf3 { [%clk 0:02:55] }")
        self.assertEqual(clocks, {1: 180.0, 3: 175.0})

    def test_game_without_clocks(self):
        self.assertEqual(self.parse("1. e4 {Best by test.} e5"), (None, {}))


class ParseCommentsFileTest(unittest.TestCase):

    def parse(self, text):
        path = _write_temp(".txt", text)
        self.addCleanup(os.remove, path)
        return parse_comments_file(path)

    def test_keys_are_plies_and_card_names(self):
        self.assertEqual(
            self.parse("[INTRO]\nA famous game.\n\n[21] Byrne moves\nthe bishop again.\n"
                       "[Result] 0-1\n[conclusion]\nA masterpiece.\n"),
            {"intro": "A famous game.", "21": "Byrne moves the bishop again.",
             "result": "0-1", "conclusion": "A masterpiece."})

    def test_square_brackets_inside_a_comment_are_text(self):
        self.assertEqual(
            self.parse("[34] Fischer leaves his queen en prise [see 18.Bxb6].\n"
                       "[35] Next [36] comment.\n"),
            {"34": "Fischer leaves his queen en prise [see 18.Bxb6].",
             "35": "Next [36] comment."})

    def test_a_bracket_starting_a_line_that_is_not_a_key_is_text(self):
        self.assertEqual(self.parse("[34] The queen sacrifice.\n[Diagram below]\n"),
                         {"34": "The queen sacrifice. [Diagram below]"})

    def test_text_before_the_first_key_is_ignored(self):
        self.assertEqual(self.parse("Notes for the sample game.\n[1] King's pawn.\n"),
                         {"1": "King's pawn."})

    def test_keys_may_be_indented(self):
        self.assertEqual(self.parse("  [1] King's pawn.\n\t[2] Symmetrical.\n"),
                         {"1": "King's pawn.", "2": "Symmetrical."})


class LoadCommentaryTest(unittest.TestCase):

    def temp(self, path):
        self.addCleanup(os.remove, path)
        return path

    def test_notes_file_overrides_pgn_comment_for_the_same_key(self):
        pgn = self.temp(_write_pgn("{PGN intro.} 1. e4! {From PGN.} e5 {Only in PGN.}"))
        notes = self.temp(_write_temp(".txt", "[INTRO]\nNotes intro.\n\n[1]\nFrom notes.\n"))
        comments, marks = load_commentary(pgn, notes)
        self.assertEqual(comments, {"intro": "Notes intro.", "1": "From notes.",
                                    "2": "Only in PGN."})
        self.assertEqual(marks, {1: "!"})

    def test_either_source_may_be_missing(self):
        pgn = self.temp(_write_pgn("1. e4 {From PGN.}"))
        notes = self.temp(_write_temp(".txt", "[1]\nFrom notes.\n"))
        self.assertEqual(load_commentary(pgn, None), ({"1": "From PGN."}, {}))
        self.assertEqual(load_commentary(None, notes), ({"1": "From notes."}, {}))
        self.assertEqual(load_commentary(None, "no_such_notes.txt"), ({}, {}))


class LaterGameTest(unittest.TestCase):
    """Commentary, marks and clocks come from the game asked for."""

    def setUp(self):
        self.path = _write_temp(".pgn",
            '[White "A"]\n\n1. e4! {First game.} { [%clk 0:05:00] } *\n\n'
            '[White "C"]\n[TimeControl "180+2"]\n\n'
            '1. d4?! {Second game.} { [%clk 0:02:59] } *\n')
        self.addCleanup(os.remove, self.path)

    def test_commentary_and_marks_of_the_second_game(self):
        self.assertEqual(load_commentary(self.path, None, 2),
                         ({"1": "Second game."}, {1: "?!"}))

    def test_clocks_of_the_second_game(self):
        self.assertEqual(parse_pgn_clocks(self.path, 2), (180, {1: 179.0}))

    def test_the_first_game_by_default(self):
        self.assertEqual(parse_pgn_annotations(self.path), ({"1": "First game."}, {1: "!"}))


if __name__ == "__main__":
    unittest.main()
