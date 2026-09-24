import re
import json
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


def parse_comments_file(file_path):
    """
    Parses a text file into a dictionary for the chess animator.
    Format: [KEY] followed by the comment text.
    """
    with open(file_path, 'r') as f:
        content = f.read()

    # Regex to find [KEY] and the text following it until the next [KEY]
    pattern = r'\[(.*?)\]\s*(.*?)(?=\s*\[|$)'
    matches = re.findall(pattern, content, re.DOTALL)

    comments_dict = {}
    for key, text in matches:
        # Clean up the key and the text
        clean_key = key.strip().lower()
        clean_text = " ".join(text.split()) # Removes newlines/extra spaces
        
        # Store in dictionary
        comments_dict[clean_key] = clean_text

    return comments_dict


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
# COMMENTS = parse_comments_file("game_notes.txt")
# COMMENTS, MARKS = load_commentary("game.pgn", "game_notes.txt")
