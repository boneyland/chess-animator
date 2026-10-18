"""
A search stopped by its time limit can end on a fail-high/low report: its
score is only a bound and its pv is cut to a move or two. The analysis keeps
the last exact report instead (it once showed 22... Bxa5 23. Rxb7 as the
whole best line).
"""
import sys
import unittest
from pathlib import Path

import chess
import chess.engine

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from chess_game_analyzer import EnhancedGameAnalyzer


class FakeAnalysis:
    """What engine.analysis() yields: the reports in order, then the merged lines."""

    def __init__(self, infos):
        self.infos = infos
        merged = {}
        for info in infos:
            merged.setdefault(info.get("multipv", 1), {}).update(info)
        self.multipv = [merged[k] for k in sorted(merged)]

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def __iter__(self):
        return iter(self.infos)


def search(infos):
    analyzer = EnhancedGameAnalyzer.__new__(EnhancedGameAnalyzer)
    analyzer.depth, analyzer.time_limit, analyzer.lines = None, 4.0, len({i.get("multipv", 1) for i in infos})
    analyzer.engine = type("Engine", (), {"analysis": lambda self, *a, **k: FakeAnalysis(infos)})()
    return analyzer._search(chess.Board())


def pov(cp):
    return chess.engine.PovScore(chess.engine.Cp(cp), chess.WHITE)


LONG = [chess.Move.from_uci(u) for u in "e2e4 e7e5 g1f3 b8c6 f1b5 a7a6".split()]
SHORT = LONG[:2]


class BoundReportTest(unittest.TestCase):

    def test_a_bound_report_at_the_end_does_not_replace_the_last_exact_one(self):
        info, = search([
            {"depth": 23, "score": pov(140), "pv": LONG},
            {"depth": 24, "score": pov(152), "pv": SHORT, "upperbound": True},
        ])
        self.assertEqual((info["depth"], info["score"], info["pv"]), (23, pov(140), LONG))

    def test_a_lowerbound_report_is_skipped_too(self):
        info, = search([
            {"depth": 23, "score": pov(140), "pv": LONG},
            {"depth": 24, "score": pov(120), "pv": SHORT, "lowerbound": True},
        ])
        self.assertEqual(info["pv"], LONG)

    def test_each_line_keeps_its_own_last_exact_report(self):
        other = [chess.Move.from_uci(u) for u in "d2d4 d7d5 c2c4".split()]
        infos = search([
            {"multipv": 1, "depth": 20, "score": pov(30), "pv": LONG},
            {"multipv": 2, "depth": 20, "score": pov(20), "pv": other},
            {"multipv": 1, "depth": 21, "score": pov(40), "pv": SHORT, "lowerbound": True},
        ])
        self.assertEqual([i["pv"] for i in infos], [LONG, other])

    def test_a_line_with_no_exact_report_keeps_the_merged_one(self):
        # a finished game: Stockfish reports depth 0 and a mate score, no pv
        mated = chess.engine.PovScore(chess.engine.Mate(0), chess.WHITE)
        info, = search([{"depth": 0, "score": mated, "upperbound": True}])
        self.assertEqual(info["score"], mated)


if __name__ == "__main__":
    unittest.main()
