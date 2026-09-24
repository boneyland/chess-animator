"""
Tests for reading commentary and move marks from PGN files.

Run from the repository root:
    python -m unittest discover tests
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from convert_script_to_comment_dict import load_commentary, parse_pgn_annotations


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


if __name__ == "__main__":
    unittest.main()
