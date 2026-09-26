"""
chess_openings.py

Names the opening of a game from Lichess's chess-openings data set
(https://github.com/lichess-org/chess-openings), copied into openings/*.tsv.
The data is in the public domain (CC0); to update it, replace those files.

Positions are matched rather than move orders, so a game that transposes into
a named line still gets its name.  A position that isn't named itself takes
the name of the last named position before it on its line (see from_rows).
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

import chess

OPENINGS_DIR = Path(__file__).resolve().parent / "openings"


@dataclass(frozen=True)
class Opening:
    eco: str
    name: str


class OpeningBook:
    """The opening of every position on the way to a named one ("book")."""

    def __init__(self, openings: Dict[str, Opening]):
        self.openings = openings

    @classmethod
    def from_rows(cls, rows: Iterable[Tuple[str, str, str]]) -> "OpeningBook":
        """
        Build from (eco, name, pgn) rows, e.g. ("C60", "Ruy Lopez", "1. e4 e5 2. Nf3 Nc6 3. Bb5").

        A position that isn't named takes the name of the last named position
        before it on its line, so a game that reaches it by another move order
        still gets it.  When it's on several lines, the name nearest the end
        of its line wins (the deepest), and between equally deep names, the
        first in the data.
        """
        lines: List[List[str]] = []
        named: Dict[str, Opening] = {}
        for eco, name, pgn in rows:
            board = chess.Board()
            line = []
            for token in pgn.split():
                if not token[0].isdigit():   # skip move numbers such as "1."
                    board.push_san(token)
                    line.append(board.epd())
            lines.append(line)
            named[line[-1]] = Opening(eco, name)

        deepest: Dict[str, Tuple[int, Opening]] = {}
        for line in lines:
            last = None   # (ply, opening) of the last named position so far
            for ply, epd in enumerate(line, 1):
                if epd in named:
                    last = (ply, named[epd])
                if last and (epd not in deepest or last[0] > deepest[epd][0]):
                    deepest[epd] = last
        return cls({epd: opening for epd, (_, opening) in deepest.items()})

    @classmethod
    def load(cls, directory: Path = OPENINGS_DIR) -> "OpeningBook":
        """Read the Lichess TSV files (eco, name, pgn, with a header row)."""
        rows = []
        for path in sorted(directory.glob("*.tsv")):
            lines = path.read_text(encoding="utf-8").splitlines()[1:]
            rows += [tuple(line.split("\t")) for line in lines if line]
        return cls.from_rows(rows)

    def _positions(self, moves_uci: List[str]) -> List[Optional[str]]:
        """The position (EPD) after each move from the start; None from the first illegal one."""
        board = chess.Board()
        positions: List[Optional[str]] = []
        for uci in moves_uci:
            try:
                board.push_uci(uci)
            except ValueError:
                break
            positions.append(board.epd())
        return positions + [None] * (len(moves_uci) - len(positions))

    def openings_by_ply(self, moves_uci: List[str]) -> List[Optional[Opening]]:
        """For each move, the opening of the position after it; None out of book."""
        return [self.openings.get(epd) for epd in self._positions(moves_uci)]

    def identify(self, moves_uci: List[str]) -> Optional[Opening]:
        """The game's opening: that of its last position in book, if any."""
        found = [o for o in self.openings_by_ply(moves_uci) if o]
        return found[-1] if found else None
