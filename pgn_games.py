"""
pgn_games.py

Picking one game out of a PGN file that holds several (a Lichess study,
a tournament download), and naming the files that go with it.  Games are
numbered from 1, in the order they appear in the file.
"""

from pathlib import Path
from typing import Optional, TextIO

import chess.pgn


def read_game(handle: TextIO, game_number: int = 1) -> Optional[chess.pgn.Game]:
    """Game game_number from an open PGN, or None if it has fewer games."""
    for _ in range(game_number - 1):
        if not chess.pgn.skip_game(handle):
            return None
    return chess.pgn.read_game(handle)


def open_game(pgn_path, game_number: int = 1) -> Optional[chess.pgn.Game]:
    """Game game_number from the PGN file at pgn_path, or None."""
    with open(pgn_path, encoding="utf-8") as f:
        return read_game(f, game_number)


def count_games(pgn_path) -> int:
    """How many games the PGN file holds, without parsing their moves."""
    count = 0
    with open(pgn_path, encoding="utf-8") as f:
        while chess.pgn.skip_game(f):
            count += 1
    return count


def game_file(pgn_path, suffix: str, game_number: int = 1) -> Path:
    """
    A file that goes with one game of a PGN, next to it: for games/x.pgn and
    "_analysis.json", games/x_analysis.json for the first game and
    games/x_game3_analysis.json for the third.
    """
    pgn_path = Path(pgn_path)
    stem = pgn_path.stem if game_number == 1 else f"{pgn_path.stem}_game{game_number}"
    return pgn_path.with_name(stem + suffix)
