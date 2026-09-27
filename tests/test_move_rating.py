"""
Tests for how chess_game_analyzer rates a move against Stockfish's choice.

Stockfish is replaced by scripted search results, so the evaluations are
exactly the ones given here.  Run from the repository root:
    python -m unittest discover tests
"""

import shutil
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import chess
import chess.engine

from chess_game_analyzer import EnhancedGameAnalyzer

STOCKFISH = shutil.which("stockfish")


def _info(cp, pv):
    return {"score": chess.engine.PovScore(chess.engine.Cp(cp), chess.WHITE),
            "pv": [chess.Move.from_uci(m) for m in pv]}


@unittest.skipUnless(STOCKFISH, "Stockfish not found on PATH")
class EngineMoveRatingTest(unittest.TestCase):

    def analyse(self, pgn_moves, searches):
        """Analyse a game whose searches return `searches` (by FEN), in order."""
        analyzer = EnhancedGameAnalyzer(STOCKFISH, depth=1)
        analyzer._search = lambda board: [searches[board.board_fen()]]
        return analyzer.analyze_game(f'[Result "*"]\n\n{pgn_moves} *\n').moves

    def searches(self):
        # The search before 1.e4 rates e4 at +40; the search after it, only
        # +10, as separate searches of neighbouring positions do
        start = chess.Board()
        after_e4 = chess.Board(); after_e4.push_san("e4")
        after_d4 = chess.Board(); after_d4.push_san("d4")
        return {start.board_fen():    _info(40, ["e2e4", "e7e5"]),
                after_e4.board_fen(): _info(10, ["e7e5"]),
                after_d4.board_fen(): _info(10, ["d7d5"])}

    def test_engine_move_is_best_with_nothing_lost(self):
        move, = self.analyse("1. e4", self.searches())
        self.assertEqual((move.classification, move.eval_loss), ("best", 0))

    def test_other_move_with_the_same_evals_loses_the_difference(self):
        move, = self.analyse("1. d4", self.searches())
        self.assertEqual((move.classification, move.eval_loss), ("good", 30))


if __name__ == "__main__":
    unittest.main()
