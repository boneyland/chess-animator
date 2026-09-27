"""
convert_script_to_comment_dict.py

Reads your commentary for the animator from two sources: the PGN's own
comments and move marks (!, ?, !!, ??, !?, ?!), and a notes file of [KEY]
entries.  Commentary is keyed by ply as a string ("1" = White's first move),
plus "intro", "result" and "conclusion" for the title and end cards.
"""

import re
import os

import chess.pgn

# PGN move-mark NAGs ($1..$6) and the symbols they stand for
NAG_SYMBOLS = {
    chess.pgn.NAG_GOOD_MOVE: "!",
    chess.pgn.NAG_MISTAKE: "?",
    chess.pgn.NAG_BRILLIANT_MOVE: "!!",
    chess.pgn.NAG_BLUNDER: "??",
    chess.pgn.NAG_SPECULATIVE_MOVE: "!?",
    chess.pgn.NAG_DUBIOUS_MOVE: "?!",
}

# Embedded commands such as [%clk 0:03:00] or [%eval 0.2] in Lichess and
# Chess.com exports; they are data, not commentary.
_PGN_COMMAND = re.compile(r'\[%[^\]]*\]')


def _clean_pgn_comment(text):
    return " ".join(_PGN_COMMAND.sub(" ", text).split())


def parse_pgn_annotations(pgn_path):
    """
    Reads commentary and move marks from the first game in a PGN file.

    Returns (comments, marks):
        comments -- {ply: text} using the same keys as parse_comments_file:
                    the ply as a string ("1" = White's first move), plus
                    "intro" for a comment before the first move.
        marks    -- {ply: symbol} for moves marked !, ?, !!, ??, !? or ?!

    Only the main line is read; side variations are ignored.
    """
    with open(pgn_path, encoding="utf-8") as f:
        game = chess.pgn.read_game(f)

    comments, marks = {}, {}
    if game is None:
        return comments, marks

    intro = _clean_pgn_comment(game.comment)
    if intro:
        comments["intro"] = intro

    for node in game.mainline():
        ply = node.ply()
        text = _clean_pgn_comment(node.comment)
        if text:
            comments[str(ply)] = text
        for nag in node.nags:
            if nag in NAG_SYMBOLS:
                marks[ply] = NAG_SYMBOLS[nag]

    return comments, marks


# A notes-file key: [ply number], [INTRO], [RESULT] or [CONCLUSION] at the
# start of a line (any case, optionally indented)
_NOTES_KEY = re.compile(r'^[ \t]*\[(\d+|intro|result|conclusion)\]',
                        re.IGNORECASE | re.MULTILINE)


def parse_comments_file(file_path):
    """
    Parses a notes file into {key: text} for the chess animator.

    Format: [KEY] at the start of a line, followed by the comment text, where
    KEY is a ply number (1 = White's first move) or INTRO, RESULT or
    CONCLUSION.  A comment runs until the next key, so it may contain square
    brackets and span several lines.  Keys are lowercased, whitespace in the
    text collapses to single spaces, and text before the first key is ignored.
    """
    with open(file_path, encoding="utf-8") as f:
        content = f.read()

    keys = list(_NOTES_KEY.finditer(content))
    ends = [k.start() for k in keys[1:]] + [len(content)]
    return {key.group(1).lower(): " ".join(content[key.end():end].split())
            for key, end in zip(keys, ends)}

def load_commentary(pgn_path=None, notes_path=None):
    """
    Collects commentary for the animator from the PGN and the notes file.

    Returns (comments, marks) as parse_pgn_annotations does.  Either path may
    be None or missing.  Where both sources have an entry for the same key,
    the notes file wins.
    """
    comments, marks = {}, {}
    if pgn_path and os.path.exists(pgn_path):
        comments, marks = parse_pgn_annotations(pgn_path)
    if notes_path and os.path.exists(notes_path):
        comments.update(parse_comments_file(notes_path))
    return comments, marks

# Example Usage:
# COMMENTS = parse_comments_file("sample_game_notes.txt")
# COMMENTS, MARKS = load_commentary("sample_game.pgn", "sample_game_notes.txt")
