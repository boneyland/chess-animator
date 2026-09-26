#!/usr/bin/env python3
"""
Chess Game Analyzer
===================

Analyzes chess games with Stockfish and reports, for every move:

- the evaluation before and after it, and the centipawns lost;
- a rating (best, excellent, good, inaccuracy, mistake, blunder), judged
  by the drop in the mover's winning chances using Lichess's thresholds;
- Lichess-style advice when a move creates, loses or delays a forced mate;
- Stockfish's best line and playable alternatives (MultiPV);
- the depth each search actually reached.

It also detects sacrifices and critical positions, and computes each player's
accuracy.  Evaluations and ratings come from Stockfish, with one board-based
exception: a sacrifice is a move that gives up material (by piece values)
without losing evaluation.

Used as a library by run_animator.py (for the video), or on its own to write a
LaTeX report of a game, or a LaTeX book of every game in a PGN:

    python chess_game_analyzer.py game.pgn -o analysis.tex
    python chess_game_analyzer.py games.pgn -o book.tex --book
    python chess_game_analyzer.py --help

Author: Generated for David Joyner's chess analysis pipeline, 2026-01-27
distribution license: either modified BSD or MIT license, user's choice.
"""

import argparse
import chess
import chess.pgn
import chess.engine
import io
import json
import math
import os
import shutil
import sys
import time
from dataclasses import asdict, dataclass, field
from typing import Callable, Optional, List, Dict, Tuple, Union
from pathlib import Path


def find_stockfish(stockfish_path: Optional[str] = None) -> str:
    """
    Locate the Stockfish executable.

    Resolution order:
      1. ``stockfish_path`` if given (a full path, or a command name on PATH)
      2. The ``STOCKFISH_PATH`` environment variable
      3. ``stockfish`` / ``stockfish.exe`` on PATH
      4. Any other ``stockfish*`` executable on PATH
         (e.g. official release names like ``stockfish-ubuntu-x86-64-avx2``)

    Raises:
        FileNotFoundError: if no executable can be found.
    """
    explicit = stockfish_path or os.environ.get("STOCKFISH_PATH")
    if explicit:
        expanded = os.path.expanduser(explicit)
        found = shutil.which(expanded)
        if found:
            return found
        raise FileNotFoundError(f"Stockfish not found or not executable at {explicit}")

    names = ["stockfish.exe", "stockfish"] if sys.platform == "win32" else ["stockfish"]
    for name in names:
        found = shutil.which(name)
        if found:
            return found

    # Official release binaries keep names like stockfish-ubuntu-x86-64-avx2
    for directory in os.environ.get("PATH", "").split(os.pathsep):
        if not directory:
            continue
        try:
            entries = sorted(Path(directory).glob("stockfish*"))
        except OSError:
            continue
        for entry in entries:
            if sys.platform == "win32" and entry.suffix.lower() != ".exe":
                continue
            if entry.is_file() and os.access(entry, os.X_OK):
                return str(entry)

    raise FileNotFoundError(
        "Stockfish not found. Install it (https://stockfishchess.org/download/), "
        "add it to PATH, set STOCKFISH_PATH, or pass its path explicitly."
    )

# =============================================================================
# PIECE VALUES (centipawns)
# =============================================================================

PIECE_VALUES = {
    chess.PAWN: 100,
    chess.KNIGHT: 320,
    chess.BISHOP: 330,
    chess.ROOK: 500,
    chess.QUEEN: 900,
    chess.KING: 0
}

# Move classification by drop in winning chances (-1..+1, the mover's point of
# view).  Inaccuracy / mistake / blunder use Lichess's thresholds; excellent and
# good match Chess.com's 0.02 / 0.05 expected-points bands (half this scale).
WIN_CHANCES_K = 0.00368208   # Lichess centipawn -> winning chances coefficient
WIN_DROP_EXCELLENT = 0.04
WIN_DROP_GOOD = 0.10
WIN_DROP_INACCURACY = 0.20
WIN_DROP_MISTAKE = 0.30


def winning_chances(eval_cp: float) -> float:
    """White's winning chances in [-1, +1] for a centipawn eval (Lichess's curve)."""
    return 2.0 / (1.0 + math.exp(-WIN_CHANCES_K * eval_cp)) - 1.0


# Threshold (in centipawns) for considering alternative moves as "playable"
# Moves within this threshold of the best move will be suggested as alternatives
PLAYABLE_THRESHOLD = 50

# Default Stockfish lines (MultiPV) searched in each position: the best move,
# plus alternatives to suggest.  Each extra line costs search time: at depth
# 20, 3 lines took about 4.5x as long as 1.  Fewer lines lose the alternatives,
# and the first line's eval gets less accurate too: a multi-line search is also
# a more thorough one (on 16 sample positions, eval error vs a much deeper
# search rose from 40 to 57 cp at depth 20 with 1 line instead of 3).
# Each position is searched once, for the move played from it and the move
# that led to it; that was 7% faster on the sample game than an extra
# one-line search after each move.
ANALYSIS_LINES = 3

# Stockfish transposition-table size in MB (Stockfish's own default is 16)
DEFAULT_HASH_MB = 256

# Longest best line (in plies) stored per move
BEST_LINE_MAX_PLIES = 12


def positive_int(text: str) -> int:
    """argparse type for counts that must be at least 1, such as --lines."""
    try:
        value = int(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"invalid int value: {text!r}")
    if value < 1:
        raise argparse.ArgumentTypeError(f"must be at least 1, got {value}")
    return value


def default_threads() -> int:
    """All CPU cores but one, so the machine stays usable; at least one."""
    return max(1, (os.cpu_count() or 1) - 1)


def default_search_threads(time_limit: Optional[float]) -> int:
    """
    Stockfish threads for a search.  At a fixed depth, extra threads widen the
    search rather than reaching the depth sooner (on a 4-core laptop, depth 20
    took up to 30x longer with 7 threads than with 1), so a depth-only search
    uses one thread, which is also reproducible.  With a time limit, more
    threads search more positions in the same time, so it uses
    default_threads().
    """
    return 1 if time_limit is None else default_threads()


def _format_duration(seconds: float) -> str:
    """m:ss, or h:mm:ss from one hour up."""
    seconds = round(seconds)
    h, rest = divmod(seconds, 3600)
    m, s = divmod(rest, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def format_progress(done: int, total: int, elapsed: float) -> str:
    """One-line analysis progress, with a time estimate while moves remain."""
    pct = done * 100 // total if total else 100
    line = f"Analyzing move {done}/{total} ({pct}%) · {_format_duration(elapsed)} elapsed"
    if 0 < done < total:
        line += f" · ~{_format_duration(elapsed / done * (total - done))} left"
    return line


class ProgressLine:
    """
    A progress(done, total) callback for analyze_game that prints
    format_progress().  In a terminal it redraws one line in place; when
    piped it prints plain lines.  The clock restarts at progress(0, total),
    so one ProgressLine can follow each game of a multi-game analysis.
    """

    def __init__(self):
        self.interactive = sys.stdout.isatty()
        self.start = time.monotonic()
        self.open_len = 0   # length of the line being redrawn; 0 = none open

    def __call__(self, done: int, total: int) -> None:
        now = time.monotonic()
        if done == 0:
            self.start = now
        line = format_progress(done, total, now - self.start)
        if not self.interactive:
            print(line, flush=True)
            return
        # Pad over any leftover characters from a longer previous line
        finished = done == total
        print("\r" + line.ljust(self.open_len), end="\n" if finished else "",
              flush=True)
        self.open_len = 0 if finished else len(line)

    def finish(self) -> None:
        """End a line left open by an interrupted analysis, e.g. before an error."""
        if self.open_len:
            print()
            self.open_len = 0

# Maximum eval_loss to count towards accuracy calculations (in centipawns)
# This prevents mate score transitions from producing absurd values (8000+ cp)
# that would completely distort accuracy statistics. A cap of 1500cp (15 pawns)
# still represents a catastrophic blunder but won't ruin the entire game's stats.
MAX_EVAL_LOSS_FOR_ACCURACY = 1500

# Mate scores are encoded by _eval_to_cp as ±(MATE_SCORE_CP - MATE_STEP_CP·N)
# for "mate in N"; anything within MATE_BAND_CP of ±MATE_SCORE_CP is a mate.
MATE_SCORE_CP = 10000
MATE_STEP_CP = 10
MATE_BAND_CP = 1000

# Lichess's descriptions for moves that change a forced mate
MATE_CREATED = "Checkmate is now unavoidable"
MATE_LOST = "Lost forced checkmate sequence"
MATE_DELAYED = "Not the best checkmate sequence"

# Longest mating line (in plies) written into a mate annotation
MATE_LINE_MAX_PLIES = 9


def mate_advice(best_eval: float, current_eval: float,
                is_white_move: bool) -> Tuple[Optional[str], str]:
    """
    Lichess's mate rules for one move, judged from the mover's point of view.

    best_eval is the position before the move, current_eval the position after
    it (both centipawns from White's point of view, mates encoded as above).

    Returns (classification, advice).  classification replaces the
    centipawn-based one when it is not None:
      - MATE_CREATED (walked into a forced mate): inaccuracy if the mover was
        already below -10 pawns, mistake below -7, otherwise blunder.
      - MATE_LOST (had a forced mate, no longer has): inaccuracy if still
        above +10 pawns, mistake above +7, otherwise blunder.
      - MATE_DELAYED (still mates, but more slowly than the best move):
        Lichess gives no judgement; we call it excellent, as Chess.com does.
    """
    sign = 1 if is_white_move else -1
    before, after = sign * best_eval, sign * current_eval
    mate_zone = MATE_SCORE_CP - MATE_BAND_CP
    had_mate, has_mate = before >= mate_zone, after >= mate_zone
    was_mated, is_mated = before <= -mate_zone, after <= -mate_zone

    if had_mate and not has_mate:
        judgement = ("inaccuracy" if after > 999 else
                     "mistake" if after > 700 else "blunder")
        return judgement, MATE_LOST
    if is_mated and not (had_mate or was_mated):
        judgement = ("inaccuracy" if before < -999 else
                     "mistake" if before < -700 else "blunder")
        return judgement, MATE_CREATED
    # The best move turns mate-in-N into mate-in-(N-1), one MATE_STEP_CP closer
    if had_mate and has_mate and after < before + MATE_STEP_CP:
        return "excellent", MATE_DELAYED
    return None, ""


def parse_elo(elo_str: str) -> Optional[int]:
    """
    Safely parse an ELO rating from a PGN header value.
    
    Handles common non-numeric values like "?", "*", "", "-", "N/A", etc.
    Returns None if the value cannot be parsed as a valid ELO rating.
    """
    if not elo_str:
        return None
    elo_str = elo_str.strip()
    if not elo_str or elo_str in ("?", "*", "-", "N/A", "n/a", "unknown", "Unknown"):
        return None
    try:
        elo = int(elo_str)
        # Sanity check: valid ELO ratings are typically between 100 and 4000
        if 100 <= elo <= 4000:
            return elo
        elif elo == 0:
            return None  # 0 often means "unknown"
        else:
            return elo  # Return anyway if outside typical range but parseable
    except ValueError:
        return None


# =============================================================================
# ANALYSIS DATA CLASSES
# =============================================================================


@dataclass
class EnhancedMoveAnalysis:
    """Stockfish's analysis of a single move."""
    ply: int
    move_san: str
    move_uci: str
    is_white_move: bool
    eval_before: float
    eval_after: float
    best_move_san: str
    best_move_uci: str
    best_eval: float
    eval_loss: float
    classification: str
    is_capture: bool
    is_check: bool
    material_balance: int
    fen_after: str
    pv_line: List[str]

    # Alternative moves: list of (san, eval_cp) tuples for playable alternatives
    # Only includes moves within PLAYABLE_THRESHOLD of the best move
    alternative_moves: List[Tuple[str, float]] = field(default_factory=list)

    # Mate annotations, empty unless the move created, lost or delayed a forced
    # mate: Lichess's description (MATE_CREATED / MATE_LOST / MATE_DELAYED) and,
    # like Scid's missed-mate annotation, the mate the mover had,
    # e.g. "Mate in 2: Kg6 Kg8 Qb8#".
    mate_advice: str = ""
    mate_line: str = ""

    # What the searches actually reached: depth of the search before the move
    # and after it (each of ANALYSIS_LINES lines; the one after is also the
    # next move's search before), and how many lines the search before the
    # move returned.  With a time limit, depth can fall short of the
    # requested depth.
    search_depth: int = 0
    search_depth_after: int = 0
    search_lines: int = 0

    # Stockfish's best line from the position before the move, in SAN,
    # starting with the best move
    best_line: List[str] = field(default_factory=list)


@dataclass
class BrilliantSacrifice:
    """Details of a detected brilliant sacrifice."""
    ply: int
    move_san: str
    player: str
    piece_type: str
    material_lost: int
    eval_before: float
    eval_after: float
    eval_improvement: float
    is_sound: bool


@dataclass
class CriticalPosition:
    """A critical position worth showing a diagram for."""
    ply: int
    fen: str
    move_san: str
    eval_score: float
    reason: str
    best_continuation: List[str]
    is_biggest_swing: bool = False  # True if this is a top-N biggest evaluation swing
    eval_swing: float = 0.0  # Magnitude of the evaluation change
    alternative_moves: List[Tuple[str, float]] = field(default_factory=list)
    best_move_san: str = ""  # The best move instead of the played move

@dataclass
class EnhancedGameAnalysisResult:
    """Complete analysis result for one game."""
    # Game metadata
    white: str
    black: str
    white_elo: Optional[int]
    black_elo: Optional[int]
    result: str
    date: str
    event: str
    site: str
    round_num: str
    opening_eco: str
    opening_name: str
    
    # Analysis data
    moves: List[EnhancedMoveAnalysis]
    brilliant_sacrifices: List[BrilliantSacrifice]
    critical_positions: List[CriticalPosition]
    
    # Statistics
    white_stats: Dict
    black_stats: Dict

    # Metadata
    analysis_depth: int = 20
    analysis_time: float = 0.0
    engine_version: str = "Stockfish"


# =============================================================================
# ENHANCED ANALYZER
# =============================================================================


class EnhancedGameAnalyzer:
    def __init__(self, stockfish_path: Optional[str] = None,
                 depth: int = 20, time_limit: Optional[float] = None,
                 threads: Optional[int] = None,
                 hash_mb: Optional[int] = None,
                 lines: int = ANALYSIS_LINES):
        self.stockfish_path = find_stockfish(stockfish_path)
        self.depth = depth
        self.threads = threads or default_search_threads(time_limit)
        self.hash_mb = hash_mb or DEFAULT_HASH_MB
        if lines < 1:
            raise ValueError(f"lines must be at least 1, got {lines}")
        self.lines = lines
        # Seconds per search, on top of depth; None = no time cap
        self.time_limit = time_limit
        self.engine = None
        self.engine_version = "Unknown"

    def __enter__(self):
        """Protocol to support 'with' statement."""
        self.engine = chess.engine.SimpleEngine.popen_uci(self.stockfish_path)
        self.engine_version = self.engine.id.get('name', 'Stockfish')
        self.engine.configure({"Threads": self.threads, "Hash": self.hash_mb})
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Ensures the engine quits properly."""
        if self.engine:
            self.engine.quit()

    def _eval_to_cp(self, score: chess.engine.PovScore) -> float:
        white_score = score.white()
        if white_score.is_mate():
            # On a checkmated board mate() is 0 for both colours, so the sign of
            # mate() can't say who won; compare the score against zero instead.
            mate_in = abs(white_score.mate())
            return 10000 - mate_in * 10 if white_score > chess.engine.Cp(0) else -10000 + mate_in * 10
        return float(white_score.score() or 0)

    def _search(self, board: chess.Board) -> List[dict]:
        """Stockfish's best lines (up to self.lines) for board, best first."""
        infos = self.engine.analyse(
            board, chess.engine.Limit(depth=self.depth, time=self.time_limit),
            multipv=self.lines)
        # Handle both single dict (multipv=1) and list (multipv>1) returns
        return [infos] if isinstance(infos, dict) else infos

    def analyze_game(self, pgn_source: Union[str, io.StringIO], 
                     min_diagram_spacing: int = 6,
                     top_n_swings: int = 2,
                     progress: Optional[Callable[[int, int], None]] = None
                     ) -> EnhancedGameAnalysisResult:
        """
        Analyze every move of the first game in pgn_source with Stockfish.
        
        Args:
            pgn_source: PGN file path, PGN string, or StringIO object
            min_diagram_spacing: Minimum ply distance between critical position diagrams
            top_n_swings: Number of "biggest swing" positions to always include (default: 2)
            progress: Optional callback, called as progress(moves_done, total_moves)
                      before the first move and after each move is analyzed
        """
        # --- 1. Fix NameError: Initialize PGN Source ---
        if isinstance(pgn_source, str):
            if '\n' in pgn_source or pgn_source.startswith('['):
                pgn_io = io.StringIO(pgn_source)
            else:
                pgn_io = open(pgn_source, 'r')
        else:
            pgn_io = pgn_source
        
        try:
            game = chess.pgn.read_game(pgn_io)
            if not game:
                raise ValueError("Could not parse PGN")
            
            board = game.board()
            moves_analysis = []
            brilliant_sacrifices = []
            critical_positions = []
            
            # Collect all eval swings for top-N selection
            all_eval_swings = []
            
            start_time = time.time()
            prev_material = self._calculate_material(board)
            last_diagram_ply = -100
            
            total_moves = sum(1 for _ in game.mainline_moves())
            if progress:
                progress(0, total_moves)

            # Each position is searched once: the search after a move is also
            # the search before the next one
            info_before_list = self._search(board)
            prev_eval = self._eval_to_cp(info_before_list[0]['score'])

            # --- 2. Main Move Loop ---
            for node in game.mainline():
                ply = board.ply() + 1
                is_white_move = board.turn == chess.WHITE

                # A. The search BEFORE the move gives the best move and alternatives
                info_before = info_before_list[0]  # Best line
                best_move = info_before.get('pv', [None])[0]
                
                # Capture SAN strings while it's still the moving player's turn
                played_san = board.san(node.move)
                best_san = board.san(best_move) if best_move else "-"
                best_line = []
                line_board = board.copy()
                for pv_move in info_before.get('pv', [])[:BEST_LINE_MAX_PLIES]:
                    if pv_move not in line_board.legal_moves:
                        break
                    best_line.append(line_board.san(pv_move))
                    line_board.push(pv_move)
                is_capture = board.is_capture(node.move)
                best_eval = self._eval_to_cp(info_before['score'])
                
                # Extract playable alternative moves (within PLAYABLE_THRESHOLD of best)
                alternative_moves = []
                for alt_info in info_before_list[1:]:  # Skip the best move (index 0)
                    alt_move = alt_info.get('pv', [None])[0]
                    if alt_move and alt_move in board.legal_moves:
                        alt_eval = self._eval_to_cp(alt_info['score'])
                        eval_diff = abs(best_eval - alt_eval)
                        if eval_diff <= PLAYABLE_THRESHOLD:
                            alt_san = board.san(alt_move)
                            alternative_moves.append((alt_san, alt_eval))
                
                # B. Execute the move
                move = node.move
                board.push(move)
                
                # C. Analyze AFTER push
                info_after_list = self._search(board)
                info_after = info_after_list[0]
                current_eval = self._eval_to_cp(info_after['score'])
                current_material = self._calculate_material(board)
                
                # D. Calculate eval_loss properly
                # The key insight: eval_loss should measure how much WORSE the played move
                # is compared to the best move, from the perspective of the moving player.
                #
                # best_eval: evaluation if the best move was played (from White's perspective)
                # current_eval: evaluation after the actual move (from White's perspective)
                #
                # For White: a good move increases eval, so loss = best_eval - current_eval
                # For Black: a good move decreases eval, so loss = current_eval - best_eval
                #
                # When the mover has a forced mate, best_eval is "mate in N" measured
                # before the move, but the best move leaves "mate in N-1".  Compare
                # against that, or a move that keeps mate-in-N (wasting a move)
                # would show zero loss and be classified "best".
                best_eval_after = best_eval
                mover_sign = 1 if is_white_move else -1
                if mover_sign * best_eval >= MATE_SCORE_CP - MATE_BAND_CP:
                    best_eval_after += mover_sign * MATE_STEP_CP

                # We want loss >= 0 for bad moves, so:
                if is_white_move:
                    # White wants higher eval; if current < best, that's bad
                    raw_eval_loss = best_eval_after - current_eval
                else:
                    # Black wants lower eval; if current > best, that's bad
                    raw_eval_loss = current_eval - best_eval_after
                
                # Clamp negative values (move was better than engine's "best" - can happen 
                # due to search instability or horizon effects)
                raw_eval_loss = max(0, raw_eval_loss)
                
                # Cap eval_loss to avoid absurd values from mate score transitions
                # When positions swing between "mate" and "no mate", raw differences
                # can be 8000+ cp which distorts accuracy calculations.
                eval_loss = min(raw_eval_loss, MAX_EVAL_LOSS_FOR_ACCURACY)
                
                # Drop in the mover's winning chances, as Lichess measures mistakes
                win_drop = winning_chances(best_eval) - winning_chances(current_eval)
                if not is_white_move:
                    win_drop = -win_drop
                classification = self._classify_move(eval_loss, max(0.0, win_drop))
                
                # D. Fix AssertionError: Safely generate PV SAN line using a temp board
                temp_board = board.copy()
                pv_san = []
                for pv_move in info_after.get('pv', [])[:3]:
                    if pv_move in temp_board.legal_moves:
                        pv_san.append(temp_board.san(pv_move))
                        temp_board.push(pv_move)
                    else:
                        break

                # Lichess's mate rules override the centipawn judgement.  Skipped
                # for the engine's own move (a mate flip there is search noise)
                # and for checkmate itself.
                mate_class, mate_adv, mate_line = None, "", ""
                if move != best_move and not board.is_checkmate():
                    mate_class, mate_adv = mate_advice(best_eval, current_eval, is_white_move)
                if mate_class:
                    classification = mate_class
                if mate_adv in (MATE_LOST, MATE_DELAYED):
                    # Like Scid's missed-mate annotation, give the mate the mover had
                    mate_n = round((MATE_SCORE_CP - abs(best_eval)) / MATE_STEP_CP)
                    line_board = board.copy()
                    line_board.pop()
                    line_san = []
                    for pv_move in info_before.get('pv', [])[:min(2 * mate_n - 1, MATE_LINE_MAX_PLIES)]:
                        line_san.append(line_board.san(pv_move))
                        line_board.push(pv_move)
                    mate_line = f"Mate in {mate_n}: {' '.join(line_san)}"
                    if 2 * mate_n - 1 > MATE_LINE_MAX_PLIES:
                        mate_line += " ..."

                # E. Record Move Analysis
                move_analysis = EnhancedMoveAnalysis(
                    ply=ply, move_san=played_san, move_uci=move.uci(),
                    is_white_move=is_white_move, eval_before=prev_eval, eval_after=current_eval,
                    best_move_san=best_san, best_move_uci=best_move.uci() if best_move else "-",
                    best_eval=best_eval, eval_loss=eval_loss, classification=classification,
                    is_capture=is_capture, is_check=board.is_check(),
                    material_balance=current_material, fen_after=board.fen(),
                    pv_line=pv_san,
                    alternative_moves=alternative_moves,
                    mate_advice=mate_adv, mate_line=mate_line,
                    search_depth=info_before.get('depth', 0),
                    search_depth_after=info_after.get('depth', 0),
                    search_lines=len(info_before_list),
                    best_line=best_line
                )
                moves_analysis.append(move_analysis)
                
                # F. Detect Brilliant Sacrifices
                mat_diff = prev_material - current_material if is_white_move else current_material - prev_material
                if mat_diff >= 250:
                    eval_diff = current_eval - prev_eval if is_white_move else prev_eval - current_eval
                    if eval_diff >= -30:
                        brilliant_sacrifices.append(BrilliantSacrifice(
                            ply=ply, move_san=played_san, player="White" if is_white_move else "Black",
                            piece_type=self._classify_sacrifice_type(mat_diff),
                            material_lost=abs(mat_diff), eval_before=prev_eval, eval_after=current_eval,
                            eval_improvement=max(0, eval_diff), is_sound=eval_diff >= 0
                        ))

                # G. Detect Critical Positions (threshold-based)
                eval_swing = abs(current_eval - prev_eval)
                if eval_swing > 100 and ply - last_diagram_ply >= min_diagram_spacing:
                    critical_positions.append(CriticalPosition(
                        ply=ply, fen=board.fen(), move_san=played_san, eval_score=current_eval,
                        reason=self._get_critical_reason(prev_eval, current_eval, classification, is_white_move),
                        best_continuation=pv_san,
                        is_biggest_swing=False, eval_swing=eval_swing, alternative_moves=alternative_moves,
                        best_move_san=best_san
                    ))
                    last_diagram_ply = ply
                
                # H. Collect all eval swings for top-N selection (excluding already-added positions)
                all_eval_swings.append({
                    'ply': ply,
                    'fen': board.fen(),
                    'move_san': played_san,
                    'eval_score': current_eval,
                    'prev_eval': prev_eval,
                    'classification': classification,
                    'is_white_move': is_white_move,
                    'pv_san': pv_san,
                    'eval_swing': eval_swing,
                    'alternative_moves': alternative_moves,  # Include alternatives for biggest swing positions
                    'best_move_san': best_san  # Include best move for biggest swing positions
                })
                
                prev_eval = current_eval
                prev_material = current_material
                info_before_list = info_after_list

                if progress:
                    progress(len(moves_analysis), total_moves)

            # --- 3. Add Top-N Biggest Swings ---
            # Get plies already in critical_positions
            existing_plies = {cp.ply for cp in critical_positions}
            
            # Sort all swings by magnitude (descending)
            all_eval_swings.sort(key=lambda x: x['eval_swing'], reverse=True)
            
            # Select top-N swings that aren't already included and respect spacing
            selected_plies = list(existing_plies)
            biggest_swing_positions = []
            
            for swing_data in all_eval_swings:
                if swing_data['ply'] in existing_plies:
                    continue  # Already a critical position
                
                # Check minimum spacing from all selected positions
                if all(abs(swing_data['ply'] - p) >= min_diagram_spacing for p in selected_plies):
                    reason = f"Biggest evaluation swing(s) ({swing_data['eval_swing']:.0f}cp)"
                    biggest_swing_positions.append(CriticalPosition(
                        ply=swing_data['ply'],
                        fen=swing_data['fen'],
                        move_san=swing_data['move_san'],
                        eval_score=swing_data['eval_score'],
                        reason=reason,
                        best_continuation=swing_data['pv_san'],
                        is_biggest_swing=True,
                        eval_swing=swing_data['eval_swing'],
                        alternative_moves=swing_data.get('alternative_moves', []),
                        best_move_san=swing_data.get('best_move_san', '')
                    ))
                    selected_plies.append(swing_data['ply'])
                    
                    if len(biggest_swing_positions) >= top_n_swings:
                        break
            
            # Merge and sort all critical positions by ply
            critical_positions.extend(biggest_swing_positions)
            critical_positions.sort(key=lambda cp: cp.ply)

            # --- 4. Wrap Results ---
            white_moves = [m for m in moves_analysis if m.is_white_move]
            black_moves = [m for m in moves_analysis if not m.is_white_move]

            return EnhancedGameAnalysisResult(
                white=game.headers.get("White", "Unknown"),
                black=game.headers.get("Black", "Unknown"),
                white_elo=parse_elo(game.headers.get("WhiteElo", "")),
                black_elo=parse_elo(game.headers.get("BlackElo", "")),
                result=game.headers.get("Result", "*"),
                date=game.headers.get("Date", "????.??.??"),
                event=game.headers.get("Event", "Unknown"),
                site=game.headers.get("Site", "Unknown"),
                round_num=game.headers.get("Round", "?"),
                opening_eco=game.headers.get("ECO", "???"),
                opening_name=game.headers.get("Opening", "Unknown"),
                moves=moves_analysis,
                brilliant_sacrifices=brilliant_sacrifices,
                critical_positions=critical_positions,
                white_stats=self._calculate_player_stats(white_moves),
                black_stats=self._calculate_player_stats(black_moves),
                analysis_depth=self.depth,
                analysis_time=time.time() - start_time,
                engine_version=self.engine_version
            )
            
        finally:
            if isinstance(pgn_source, str) and not ('\n' in pgn_source or pgn_source.startswith('[')):
                pgn_io.close()

    def analyze_all_games(self, pgn_source: Union[str, io.StringIO],
                          min_diagram_spacing: int = 6,
                          top_n_swings: int = 2,
                          verbose: bool = True,
                          progress: Optional[Callable[[int, int], None]] = None
                          ) -> List[EnhancedGameAnalysisResult]:
        """
        Analyze all games in a PGN file.

        Args:
            pgn_source: PGN file path, PGN string, or StringIO object
            min_diagram_spacing: Minimum ply distance between critical position diagrams
            top_n_swings: Number of "biggest swing" positions to always include
            verbose: Print progress messages
            progress: Optional callback passed to analyze_game for each game

        Returns:
            List of EnhancedGameAnalysisResult objects, one per game
        """
        results = []
        
        # Open PGN source
        if isinstance(pgn_source, str):
            if '\n' in pgn_source or pgn_source.startswith('['):
                pgn_io = io.StringIO(pgn_source)
            else:
                pgn_io = open(pgn_source, 'r')
        else:
            pgn_io = pgn_source
        
        try:
            game_num = 0
            while True:
                game = chess.pgn.read_game(pgn_io)
                if game is None:
                    break
                
                game_num += 1
                if verbose:
                    white = game.headers.get("White", "Unknown")
                    black = game.headers.get("Black", "Unknown")
                    print(f"Analyzing game {game_num}: {white} vs {black}...")
                
                # Analyze this game using a StringIO of the game
                game_pgn = io.StringIO()
                exporter = chess.pgn.StringExporter()
                game_pgn.write(game.accept(exporter))
                game_pgn.seek(0)
                
                result = self.analyze_game(
                    game_pgn,
                    min_diagram_spacing=min_diagram_spacing,
                    top_n_swings=top_n_swings,
                    progress=progress
                )
                results.append(result)
                
                if verbose:
                    print(f"  Completed in {result.analysis_time:.1f}s")
            
            if verbose:
                print(f"Analyzed {len(results)} game(s) total.")
                
        finally:
            if isinstance(pgn_source, str) and not ('\n' in pgn_source or pgn_source.startswith('[')):
                pgn_io.close()
        
        return results

    def _calculate_material(self, board: chess.Board) -> int:
        """Calculates the material balance (positive = White ahead)."""
        material = 0
        for piece_type in [chess.PAWN, chess.KNIGHT, chess.BISHOP, chess.ROOK, chess.QUEEN]:
            white_count = len(board.pieces(piece_type, chess.WHITE))
            black_count = len(board.pieces(piece_type, chess.BLACK))
            material += (white_count - black_count) * PIECE_VALUES[piece_type]
        return material

    def _classify_move(self, eval_loss: float, win_drop: float) -> str:
        """
        Classifies a move.  best uses centipawn loss; the rest use
        win_drop, the drop in the mover's winning chances (see winning_chances),
        so a pawn lost at +8 costs far less than a pawn lost at 0.
        """
        if eval_loss < 5:
            return "best"
        elif win_drop < WIN_DROP_EXCELLENT:
            return "excellent"
        elif win_drop < WIN_DROP_GOOD:
            return "good"
        elif win_drop < WIN_DROP_INACCURACY:
            return "inaccuracy"
        elif win_drop < WIN_DROP_MISTAKE:
            return "mistake"
        else:
            return "blunder"

    def _classify_sacrifice_type(self, material: int) -> str:
        """Identifies what type of material was sacrificed."""
        if material >= 850: return "queen"
        elif material >= 450: return "rook"
        elif material >= 300: return "minor_piece"
        elif material >= 200: return "exchange"
        else: return "pawns"

    def _get_critical_reason(self, prev_eval: float, curr_eval: float,
                             classification: str, is_white: bool) -> str:
        """Generates a reason why a position is marked as critical."""
        swing = curr_eval - prev_eval
        if abs(curr_eval) >= 9900:
            return "Checkmate! " + ("White wins" if curr_eval > 0 else "Black wins")
        if classification == "blunder":
            player = "White" if is_white else "Black"
            return f"{player} blunders ({swing:+.0f}cp)"
        elif abs(swing) > 200:
            return "Position swings to " + ("White's" if swing > 0 else "Black's") + " favor"
        return "Critical moment"

    def _calculate_player_stats(self, moves: List[EnhancedMoveAnalysis]) -> Dict:
        """Calculates performance statistics for a specific player."""
        if not moves:
            return {
                'total_moves': 0,
                'accuracy': 0,
                'avg_centipawn_loss': 0,
                'best_moves': 0,
                'excellent_moves': 0,
                'good_moves': 0,
                'inaccuracies': 0,
                'mistakes': 0,
                'blunders': 0
            }
        
        avg_loss = sum(m.eval_loss for m in moves) / len(moves)
        accuracy = max(0, 100 * math.exp(-0.005 * avg_loss)) if avg_loss > 0 else 100.0
        
        counts = {'best': 0, 'excellent': 0, 'good': 0, 'inaccuracy': 0, 'mistake': 0, 'blunder': 0}
        for m in moves:
            if m.classification in counts: counts[m.classification] += 1
            
        return {
            'total_moves': len(moves),
            'avg_centipawn_loss': avg_loss,
            'accuracy': accuracy,
            'best_moves': counts['best'],
            'excellent_moves': counts['excellent'],
            'good_moves': counts['good'],
            'inaccuracies': counts['inaccuracy'],
            'mistakes': counts['mistake'],
            'blunders': counts['blunder']
        }


# =============================================================================
# ENHANCED LATEX REPORT GENERATOR
# =============================================================================

class EnhancedLaTeXReportGenerator:
    """Generates LaTeX reports from Stockfish's analysis of a game."""
    
    
    @staticmethod
    def _mate_comment(move: EnhancedMoveAnalysis) -> str:
        """LaTeX comment for a move with mate advice, e.g.
        "Lost forced checkmate sequence. Mate in 2: Kg6 Kg8 Qb8#"."""
        esc = EnhancedLaTeXReportGenerator._escape_latex
        comment = f"{esc(move.mate_advice)}."
        if move.mate_line:
            comment += f" {esc(move.mate_line)}"
        elif move.best_move_san and move.move_uci != move.best_move_uci:
            comment += f" Best was {esc(move.best_move_san)}."
        return comment

    @staticmethod
    def _escape_latex(text: str) -> str:
        """Escape special LaTeX characters."""
        if not text:
            return ""
        text = text.replace('#', r'\#')
        replacements = {
            '&': r'\&', '%': r'\%', '$': r'\$', '_': r'\_',
            '{': r'\{', '}': r'\}', '~': r'\textasciitilde{}', '^': r'\^{}'
        }
        for old, new in replacements.items():
            text = text.replace(old, new)
        return text
    
    @staticmethod
    def _preamble(document_class: str) -> List[str]:
        """Packages and colours shared by the report and the book."""
        return [
            rf"\documentclass[11pt]{{{document_class}}}",
            r"\usepackage[utf8]{inputenc}",
            r"\usepackage{xskak}",
            r"\usepackage{amsmath}",
            r"\usepackage{amssymb}",
            r"\usepackage{chessboard}",
            r"\usepackage[margin=1in]{geometry}",
            r"\usepackage{longtable}",
            r"\usepackage{booktabs}",
            r"\usepackage{hyperref}",
            r"\usepackage{xcolor}",
            r"",
            r"% Custom colors",
            r"\definecolor{brilliantcolor}{RGB}{0, 150, 150}",
            r"\definecolor{excellentcolor}{RGB}{0, 128, 0}",
            r"\definecolor{goodcolor}{RGB}{64, 160, 64}",
            r"\definecolor{inaccuracycolor}{RGB}{200, 180, 0}",
            r"\definecolor{mistakecolor}{RGB}{220, 120, 0}",
            r"\definecolor{blundercolor}{RGB}{200, 0, 0}",
            r"",
        ]

    @staticmethod
    def generate_report(analysis: EnhancedGameAnalysisResult,
                       include_diagrams: bool = True) -> str:
        """
        Generate a complete LaTeX report of a game's analysis.

        Args:
            analysis: EnhancedGameAnalysisResult from analyzer
            include_diagrams: Include chess board diagrams

        Returns:
            Complete LaTeX document as string
        """
        esc = EnhancedLaTeXReportGenerator._escape_latex
        lines = EnhancedLaTeXReportGenerator._preamble("article")
        lines.extend([
            r"\title{Chess Game Analysis\\",
            rf"{esc(analysis.white)} vs {esc(analysis.black)}}}",
            r"\author{Generated by " + esc(analysis.engine_version) + "}",
            r"\date{" + esc(analysis.date) + "}",
            r"",
            r"\begin{document}",
            r"\maketitle",
            r"\tableofcontents",
            r"\newpage",
            r"",
        ])
        lines.extend(EnhancedLaTeXReportGenerator._game_sections(
            analysis, include_diagrams=include_diagrams))
        lines.append(r"\end{document}")
        return "\n".join(lines)

    @staticmethod
    def generate_book_report(analyses: List[EnhancedGameAnalysisResult],
                             book_title: str = "Chess Game Collection Analysis",
                             author: str = None,
                             include_diagrams: bool = True) -> str:
        """
        Generate a LaTeX book with multiple games as chapters.

        Args:
            analyses: List of EnhancedGameAnalysisResult objects
            book_title: Title for the book
            author: Author name (defaults to engine version)
            include_diagrams: Include chess board diagrams

        Returns:
            Complete LaTeX book document as string
        """
        if not analyses:
            raise ValueError("No games to include in report")

        esc = EnhancedLaTeXReportGenerator._escape_latex
        lines = EnhancedLaTeXReportGenerator._preamble("book")

        # Determine author
        if author is None:
            author = f"Generated by {analyses[0].engine_version}"

        lines.extend([
            rf"\title{{{esc(book_title)}}}",
            rf"\author{{{esc(author)}}}",
            r"\date{\today}",
            r"",
            r"\begin{document}",
            r"\maketitle",
            r"\tableofcontents",
            r"",
        ])

        # Generate each game as a chapter
        for game_num, analysis in enumerate(analyses, 1):
            lines.extend(EnhancedLaTeXReportGenerator._generate_game_chapter(
                analysis, game_num=game_num, include_diagrams=include_diagrams))

        lines.append(r"\end{document}")
        return "\n".join(lines)

    @staticmethod
    def _game_sections(analysis: EnhancedGameAnalysisResult,
                       include_diagrams: bool = True) -> List[str]:
        """
        The sections describing one game, from Game Information to Analysis
        Information: the body of a report, or of a chapter in the book.
        """
        esc = EnhancedLaTeXReportGenerator._escape_latex
        lines = []

        # Game Information
        lines.extend([
            r"\section{Game Information}",
            r"\begin{tabular}{ll}",
            rf"\textbf{{Event}} & {esc(analysis.event)} \\",
            rf"\textbf{{Site}} & {esc(analysis.site)} \\",
            rf"\textbf{{Date}} & {esc(analysis.date)} \\",
            rf"\textbf{{Round}} & {esc(analysis.round_num)} \\",
        ])
        
        white_info = esc(analysis.white)
        if analysis.white_elo:
            white_info += f" ({analysis.white_elo})"
        black_info = esc(analysis.black)
        if analysis.black_elo:
            black_info += f" ({analysis.black_elo})"
        
        lines.extend([
            rf"\textbf{{White}} & {white_info} \\",
            rf"\textbf{{Black}} & {black_info} \\",
            rf"\textbf{{Result}} & {esc(analysis.result)} \\",
            rf"\textbf{{Opening}} & {esc(analysis.opening_eco)} -- {esc(analysis.opening_name)} \\",
            r"\end{tabular}",
            r"",
        ])
        
        # Player Statistics
        lines.extend([
            r"\section{Player Statistics}",
            r"",
            r"\subsection{" + esc(analysis.white) + " (White)}",
            r"\begin{itemize}",
            rf"\item Total moves: {analysis.white_stats['total_moves']}",
            rf"\item Accuracy: {analysis.white_stats['accuracy']:.1f}\%",
            rf"\item Average centipawn loss: {analysis.white_stats['avg_centipawn_loss']:.1f}",
            rf"\item Best/Excellent moves: {analysis.white_stats['best_moves']} / {analysis.white_stats['excellent_moves']}",
            rf"\item Good moves: {analysis.white_stats['good_moves']}",
            rf"\item Inaccuracies: {analysis.white_stats['inaccuracies']}",
            rf"\item Mistakes: {analysis.white_stats['mistakes']}",
            rf"\item Blunders: {analysis.white_stats['blunders']}",
            r"\end{itemize}",
            r"",
            r"\subsection{" + esc(analysis.black) + " (Black)}",
            r"\begin{itemize}",
            rf"\item Total moves: {analysis.black_stats['total_moves']}",
            rf"\item Accuracy: {analysis.black_stats['accuracy']:.1f}\%",
            rf"\item Average centipawn loss: {analysis.black_stats['avg_centipawn_loss']:.1f}",
            rf"\item Best/Excellent moves: {analysis.black_stats['best_moves']} / {analysis.black_stats['excellent_moves']}",
            rf"\item Good moves: {analysis.black_stats['good_moves']}",
            rf"\item Inaccuracies: {analysis.black_stats['inaccuracies']}",
            rf"\item Mistakes: {analysis.black_stats['mistakes']}",
            rf"\item Blunders: {analysis.black_stats['blunders']}",
            r"\end{itemize}",
            r"",
        ])

        # Brilliant Sacrifices
        if analysis.brilliant_sacrifices:
            lines.extend([
                r"\section{Brilliant Sacrifices}",
                r"",
                rf"This game features {len(analysis.brilliant_sacrifices)} brilliant sacrifice(s):",
                r"",
                r"\begin{itemize}",
            ])
            
            for sac in analysis.brilliant_sacrifices:
                move_num = (sac.ply + 1) // 2
                move_str = f"{move_num}. {sac.move_san}" if sac.player == "White" else f"{move_num}...{sac.move_san}"
                sound_str = "Sound sacrifice" if sac.is_sound else "Speculative sacrifice"
                
                lines.append(
                    rf"\item \textbf{{{esc(move_str)}}} -- {sac.player} sacrifices {sac.piece_type} "
                    rf"({sac.material_lost}cp). {sound_str}. "
                    rf"Evaluation: {sac.eval_before/100:+.2f} $\rightarrow$ {sac.eval_after/100:+.2f}"
                )
            
            lines.extend([r"\end{itemize}", r""])
        
        # Annotated Game
        lines.extend([
            r"\section{Annotated Game}",
            r"",
            r"\begin{quote}",
        ])
        
        current_line = ""
        for move in analysis.moves:
            move_num = (move.ply + 1) // 2
            
            if move.is_white_move:
                if current_line:
                    lines.append(current_line)
                current_line = f"{move_num}. {esc(move.move_san)}"
            else:
                if current_line:
                    current_line += f" {esc(move.move_san)}"
                else:
                    current_line = f"{move_num}...{esc(move.move_san)}"
            
            # NAG annotations
            if move.classification == "blunder":
                current_line += "??"
            elif move.classification == "mistake":
                current_line += "?"
            elif move.classification == "inaccuracy":
                current_line += "?!"
            elif move.classification == "best" and move.move_san == move.best_move_san:
                current_line += "!"
            
            # Comments for significant moves
            if move.mate_advice:
                lines.append(current_line)
                lines.append(rf"\textit{{{EnhancedLaTeXReportGenerator._mate_comment(move)}}}")
                lines.append("")
                current_line = ""
            elif move.classification in ["blunder", "mistake"]:
                lines.append(current_line)
                player = "White" if move.is_white_move else "Black"
                # Don't show alternatives when the played move equals the best move
                if move.move_san == move.best_move_san or move.move_uci == move.best_move_uci:
                    # Edge case: move classified as error but matches best move
                    comment = f"{player} loses {move.eval_loss:.0f}cp."
                else:
                    # Build list of moves to consider: best move + playable alternatives
                    moves_to_consider = [esc(move.best_move_san)]
                    for alt_san, alt_eval in move.alternative_moves:
                        if alt_san != move.best_move_san:  # Don't duplicate best move
                            moves_to_consider.append(esc(alt_san))
                    
                    if len(moves_to_consider) == 1:
                        comment = f"{player} loses {move.eval_loss:.0f}cp. Consider instead: {moves_to_consider[0]}."
                    else:
                        comment = f"{player} loses {move.eval_loss:.0f}cp. Consider instead: {', '.join(moves_to_consider)}."
                lines.append(rf"\textit{{{comment}}}")
                lines.append("")
                current_line = ""
        
        if current_line:
            lines.append(current_line)
        
        lines.extend([
            r"",
            esc(analysis.result),
            r"\end{quote}",
            r"",
        ])
        
        # Critical Positions
        if include_diagrams and analysis.critical_positions:
            lines.extend([
                r"\section{Critical Positions}",
                r"",
                r"This section highlights critical moments where the evaluation shifted substantially---either due to errors or missed opportunities. Each diagram shows the position \emph{after} the move was played.",
                r"",
                r"\begin{itemize}",
                r"\item \textbf{Instead of [move]}: The move(s) that should have been played instead.",
                r"\item \textbf{Best continuation}: The optimal sequence of moves from the diagrammed position.",
                r"\end{itemize}",
                r"",
                r"Positions marked with {\color{blue}$\bigstar$} represent the biggest evaluation swings in the game.",
                r"",
            ])
            
            for i, pos in enumerate(analysis.critical_positions, 1):
                move_num = (pos.ply + 1) // 2
                is_white = pos.ply % 2 == 1
                move_str = f"{move_num}. {pos.move_san}" if is_white else f"{move_num}...{pos.move_san}"
                
                if pos.is_biggest_swing:
                    subsection_title = rf"\subsection*{{\textcolor{{blue}}{{Position {i}: After {esc(move_str)} $\bigstar$}}}}"
                    reason_text = rf"\textit{{\textcolor{{blue}}{{{esc(pos.reason)}}}}}"
                else:
                    subsection_title = rf"\subsection*{{Position {i}: After {esc(move_str)}}}"
                    reason_text = rf"\textit{{{esc(pos.reason)}}}"
                
                lines.extend([
                    subsection_title,
                    reason_text,
                    r"",
                    rf"Evaluation: {pos.eval_score/100:+.2f}",
                    r"",
                    r"\chessboard[setfen=" + pos.fen + "]",
                    r"",
                ])

                # Add "Instead of" moves: best move + alternatives (if different from played move)
                instead_moves = []
                if pos.best_move_san and pos.best_move_san != pos.move_san:
                    instead_moves.append(esc(pos.best_move_san))
                for alt_san, alt_eval in pos.alternative_moves[:2]:  # Add up to 2 more alternatives
                    if alt_san != pos.move_san and esc(alt_san) not in instead_moves:
                        instead_moves.append(esc(alt_san))
                if instead_moves:
                    instead_str = ", ".join(instead_moves[:3])  # Cap at 3 total
                    lines.append(rf"Instead of {esc(pos.move_san)}: \hspace{{0.5em}} {instead_str}\hspace{{4em}}")
                
                if pos.best_continuation:
                    cont_str = " ".join(esc(m) for m in pos.best_continuation[:5])
                    lines.append(rf"\hspace{{0.5em}}Best continuation: {cont_str}")
                
                lines.append(r"")

        # Analysis Metadata
        lines.extend([
            r"\section{Analysis Information}",
            r"\begin{itemize}",
            rf"\item Engine: {esc(analysis.engine_version)}",
            rf"\item Depth: {analysis.analysis_depth}",
            rf"\item Analysis time: {analysis.analysis_time:.1f} seconds",
            r"\end{itemize}",
            r"",
        ])

        return lines


    @staticmethod
    def _generate_game_chapter(analysis: EnhancedGameAnalysisResult,
                               game_num: int,
                               include_diagrams: bool = True) -> List[str]:
        """Generate a chapter for a single game in the book."""
        esc = EnhancedLaTeXReportGenerator._escape_latex
        lines = [
            rf"\chapter{{{esc(analysis.white)} vs {esc(analysis.black)}}}",
            r"",
        ]
        lines.extend(EnhancedLaTeXReportGenerator._game_sections(
            analysis, include_diagrams=include_diagrams))
        return lines


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================

def analyze_game_to_report(
    pgn_source: Union[str, io.StringIO],
    output_path: Optional[str] = None,
    stockfish_path: Optional[str] = None,
    depth: int = 20,
    time_limit: Optional[float] = None,
    include_diagrams: bool = True,
    top_n_swings: int = 2,
    verbose: bool = True,
    lines: int = ANALYSIS_LINES,
    threads: Optional[int] = None,
    hash_mb: Optional[int] = None
) -> Union[str, EnhancedGameAnalysisResult]:
    """
    Analyze a chess game with Stockfish and write a LaTeX report.

    Args:
        pgn_source: Path to PGN file, or PGN string, or StringIO object
        output_path: Optional path to save LaTeX file (if None, returns result object)
        stockfish_path: Path to Stockfish executable (None: auto-detect)
        depth: Analysis depth (default 20)
        time_limit: Max seconds per position, on top of depth (default None: no cap)
        include_diagrams: Include chess board diagrams in report
        top_n_swings: Number of "biggest swing" positions to always include (default: 2)
        verbose: Print progress messages
        lines: Lines (MultiPV) searched before each move (default: ANALYSIS_LINES)
        threads: Stockfish threads (None: see default_search_threads)
        hash_mb: Stockfish hash size in MB (None: DEFAULT_HASH_MB)

    Returns:
        If output_path provided: LaTeX document as string
        If output_path is None: EnhancedGameAnalysisResult object

    Example:
        >>> analyze_game_to_report("game.pgn", output_path="analysis.tex")
    """
    if verbose:
        cap = f", max {time_limit}s per position" if time_limit else ""
        print(f"Starting analysis (depth={depth}{cap})...")

    with EnhancedGameAnalyzer(stockfish_path, depth, time_limit, threads=threads,
                              hash_mb=hash_mb, lines=lines) as analyzer:
        if verbose:
            print(f"Engine: {analyzer.engine_version}")

        progress = ProgressLine() if verbose else None
        try:
            analysis = analyzer.analyze_game(pgn_source, top_n_swings=top_n_swings,
                                             progress=progress)
        finally:
            if progress:
                progress.finish()

        if verbose:
            print(f"Analysis complete in {analysis.analysis_time:.1f}s")
            print(f"  {analysis.white} vs {analysis.black}")
            print(f"  Result: {analysis.result}")
            print(f"  White accuracy: {analysis.white_stats['accuracy']:.1f}%")
            print(f"  Black accuracy: {analysis.black_stats['accuracy']:.1f}%")
            if analysis.brilliant_sacrifices:
                print(f"  Brilliant sacrifices: {len(analysis.brilliant_sacrifices)}")

    if output_path is None:
        return analysis

    latex_content = EnhancedLaTeXReportGenerator.generate_report(
        analysis, include_diagrams=include_diagrams)

    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(latex_content)

    if verbose:
        print(f"LaTeX report saved to: {output_path}")

    return latex_content


def analyze_games_to_book(
    pgn_source: Union[str, io.StringIO],
    output_path: str,
    book_title: str = "Chess Game Collection Analysis",
    author: str = None,
    stockfish_path: Optional[str] = None,
    depth: int = 20,
    time_limit: Optional[float] = None,
    include_diagrams: bool = True,
    top_n_swings: int = 2,
    verbose: bool = True,
    lines: int = ANALYSIS_LINES,
    threads: Optional[int] = None,
    hash_mb: Optional[int] = None
) -> Tuple[str, List[EnhancedGameAnalysisResult]]:
    """
    Analyze all games in a PGN file and generate a LaTeX book with each game as a chapter.

    Args:
        pgn_source: Path to PGN file containing one or more games
        output_path: Path to save LaTeX book file
        book_title: Title for the book
        author: Author name (defaults to engine version)
        stockfish_path: Path to Stockfish executable (None: auto-detect)
        depth: Analysis depth (default 20)
        time_limit: Max seconds per position, on top of depth (default None: no cap)
        include_diagrams: Include chess board diagrams in report
        top_n_swings: Number of "biggest swing" positions per game (default: 2)
        verbose: Print progress messages
        lines: Lines (MultiPV) searched before each move (default: ANALYSIS_LINES)
        threads: Stockfish threads (None: see default_search_threads)
        hash_mb: Stockfish hash size in MB (None: DEFAULT_HASH_MB)

    Returns:
        Tuple of (LaTeX content as string, list of EnhancedGameAnalysisResult objects)

    Example:
        >>> latex, results = analyze_games_to_book(
        ...     "tournament_games.pgn",
        ...     "tournament_analysis.tex",
        ...     book_title="Club Championship 2026",
        ...     author="Chess Club Analysis Team"
        ... )
        >>> print(f"Analyzed {len(results)} games")
    """
    if verbose:
        cap = f", max {time_limit}s per position" if time_limit else ""
        print(f"Starting multi-game book analysis (depth={depth}{cap})...")

    with EnhancedGameAnalyzer(stockfish_path, depth, time_limit, threads=threads,
                              hash_mb=hash_mb, lines=lines) as analyzer:
        if verbose:
            print(f"Engine: {analyzer.engine_version}")

        progress = ProgressLine() if verbose else None
        try:
            analyses = analyzer.analyze_all_games(
                pgn_source,
                top_n_swings=top_n_swings,
                verbose=verbose,
                progress=progress
            )
        finally:
            if progress:
                progress.finish()

        if not analyses:
            raise ValueError("No games found in PGN file")

        if verbose:
            total_time = sum(a.analysis_time for a in analyses)
            print(f"All games analyzed in {total_time:.1f}s total")

    latex_content = EnhancedLaTeXReportGenerator.generate_book_report(
        analyses,
        book_title=book_title,
        author=author,
        include_diagrams=include_diagrams,
    )

    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(latex_content)

    if verbose:
        print(f"LaTeX book saved to: {output_path}")

    return latex_content, analyses


# =============================================================================
# COMMAND LINE INTERFACE
# =============================================================================

def write_json(path: str, analysis) -> None:
    """Save one analysis result, or a list of them, as JSON."""
    if isinstance(analysis, list):
        data = [asdict(a) for a in analysis]
    else:
        data = asdict(analysis)
    with open(path, 'w') as f:
        json.dump(data, f, indent=2)


def main():
    parser = argparse.ArgumentParser(
        description="Analyze chess games with Stockfish and write LaTeX reports",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Report for a single game
  python chess_game_analyzer.py game.pgn -o analysis.tex

  # Analyze all games in PGN as a book (multiple games)
  python chess_game_analyzer.py games.pgn -o analysis.tex --book --book-title "My Games"

  # Get just the raw analysis data (JSON output)
  python chess_game_analyzer.py game.pgn --json-output analysis.json
        """
    )
    
    parser.add_argument("pgn_file", help="Path to PGN file (can contain multiple games)")
    parser.add_argument("-o", "--output", help="Output LaTeX file")
    parser.add_argument("--json-output", help="Output raw analysis as JSON")
    parser.add_argument("-s", "--stockfish", default=None,
                       help="Path to Stockfish executable (default: auto-detect "
                            "via STOCKFISH_PATH or PATH)")
    parser.add_argument("-d", "--depth", type=int, default=20,
                       help="Analysis depth (default: 20)")
    parser.add_argument("-t", "--time", "--time-limit", type=float, default=None,
                       dest="time", metavar="SECONDS",
                       help="Max seconds per position, on top of --depth (default: no cap)")
    parser.add_argument("--lines", type=positive_int, default=ANALYSIS_LINES,
                       help=f"Lines (MultiPV) searched before each move (default: {ANALYSIS_LINES})")
    parser.add_argument("--threads", type=positive_int, default=None, metavar="N",
                       help="CPU threads for Stockfish (default: 1, or all cores but one "
                            "with --time, where extra threads help)")
    parser.add_argument("--hash", type=positive_int, default=None, metavar="MB",
                       dest="hash_mb",
                       help=f"Stockfish hash table size in MB (default: {DEFAULT_HASH_MB})")
    parser.add_argument("--no-diagrams", action="store_true",
                       help="Don't include position diagrams")
    parser.add_argument("-q", "--quiet", action="store_true",
                       help="Suppress progress messages")

    # Multi-game book options
    parser.add_argument("--book", action="store_true",
                       help="Analyze all games in PGN and generate a book (LaTeX book class)")
    parser.add_argument("--book-title", default="Chess Game Collection Analysis",
                       help="Title for the book (used with --book)")
    parser.add_argument("--book-author", default=None,
                       help="Author for the book (used with --book)")
    
    args = parser.parse_args()
    engine_args = (args.stockfish, args.depth, args.time)
    engine_kwargs = dict(threads=args.threads, hash_mb=args.hash_mb, lines=args.lines)
    progress = None if args.quiet else ProgressLine()

    if args.book:
        # Multi-game book mode
        with EnhancedGameAnalyzer(*engine_args, **engine_kwargs) as analyzer:
            if not args.quiet:
                print(f"Analyzing all games with {analyzer.engine_version}...")
            
            try:
                analyses = analyzer.analyze_all_games(args.pgn_file, verbose=not args.quiet,
                                                      progress=progress)
            finally:
                if progress:
                    progress.finish()
            
            if not analyses:
                print("No games found in PGN file")
                return
            
            if not args.quiet:
                total_time = sum(a.analysis_time for a in analyses)
                print(f"All {len(analyses)} games analyzed in {total_time:.1f}s total")
        
        # Output LaTeX book
        if args.output:
            latex_content = EnhancedLaTeXReportGenerator.generate_book_report(
                analyses,
                book_title=args.book_title,
                author=args.book_author,
                include_diagrams=not args.no_diagrams,
            )
            
            with open(args.output, 'w', encoding='utf-8') as f:
                f.write(latex_content)
            
            if not args.quiet:
                print(f"LaTeX book saved to: {args.output}")
        
        # Output JSON (list of all analyses)
        if args.json_output:
            write_json(args.json_output, analyses)
            
            if not args.quiet:
                print(f"JSON output saved to: {args.json_output}")
        
        if not args.output and not args.json_output:
            # Print summary to stdout
            print(f"\nAnalyzed {len(analyses)} games:")
            for i, analysis in enumerate(analyses, 1):
                print(f"\n  Game {i}: {analysis.white} vs {analysis.black}")
                print(f"    Result: {analysis.result}")
                print(f"    White accuracy: {analysis.white_stats['accuracy']:.1f}%")
                print(f"    Black accuracy: {analysis.black_stats['accuracy']:.1f}%")
    
    else:
        # Single game mode (original behavior)
        with EnhancedGameAnalyzer(*engine_args, **engine_kwargs) as analyzer:
            if not args.quiet:
                print(f"Analyzing with {analyzer.engine_version}...")
            
            try:
                analysis = analyzer.analyze_game(args.pgn_file, progress=progress)
            finally:
                if progress:
                    progress.finish()
            
            if not args.quiet:
                print(f"Analysis complete in {analysis.analysis_time:.1f}s")
        
        # Output LaTeX
        if args.output:
            latex_content = EnhancedLaTeXReportGenerator.generate_report(
                analysis,
                include_diagrams=not args.no_diagrams,
            )
            
            with open(args.output, 'w', encoding='utf-8') as f:
                f.write(latex_content)
            
            if not args.quiet:
                print(f"LaTeX report saved to: {args.output}")
        
        # Output JSON
        if args.json_output:
            write_json(args.json_output, analysis)
            
            if not args.quiet:
                print(f"JSON output saved to: {args.json_output}")
        
        if not args.output and not args.json_output:
            # Print summary to stdout
            print(f"\n{analysis.white} vs {analysis.black}")
            print(f"Result: {analysis.result}")
            print(f"\nWhite: {analysis.white_stats['accuracy']:.1f}% accuracy")
            print(f"Black: {analysis.black_stats['accuracy']:.1f}% accuracy")


if __name__ == "__main__":
    main()
