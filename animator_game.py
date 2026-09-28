"""
animator_game.py

Animates a chess game with move-by-move analysis and commentary.
Integrates with chess_game_analyzer.py for Stockfish annotations.

Usage:
    # Set config path via environment variable, then run manim:
    export CHESS_ANIMATOR_CONFIG=game_animator_config.json
    manim -pql animator_game.py AnimatedGame

    # Or use run_animator.py which handles config setup automatically:
    python run_animator.py sample_game --quality low

    # Quick demo (no files needed):
    manim -pql animator_game.py QuickDemo

Requirements:
    - manim, manim-chess, chess
    - chess_game_analyzer.py (for analysis)
    - Stockfish (if running live analysis)
"""

import functools
import json
import math
import os
from pathlib import Path
from dataclasses import dataclass, asdict, field
from typing import Optional, List, Dict, Any, Tuple

from manim import *
import manim_chess
import upstream_fixes  # noqa: F401  (patches library bugs on import)
import chess
import chess.pgn

from animator_layout import (
    COLORS, FONTS, FRAME_WIDTH, FRAME_HEIGHT,
    BOARD_SCALE, BOARD_CENTER_X, BOARD_CENTER_Y,
    EVAL_BAR_SCALE, EVAL_BAR_OFFSET,
    PANEL_LEFT_X, PANEL_CENTER_X,
    MOVES_COLUMN_RIGHT_X, MOVES_COLUMN_CENTER_X, MOVES_COLUMN_PADDING,
    COMMENT_LEFT_X, COMMENT_RIGHT_X, ANALYSIS_LEFT_X, ANALYSIS_RIGHT_X,
    HEADER_CENTER_Y,
    MOVE_LIST_TOP_Y, MOVE_LIST_BOTTOM_Y,
    ANALYSIS_TOP_Y, ANALYSIS_BOTTOM_Y,
    ANNOTATION_COLORS,
    get_panel_rect, get_classification_color, format_player_display
)

from animator_initial_frame import GameInfo, create_header_panel


# =============================================================================
# Evaluation display helpers
# =============================================================================

# chess_game_analyzer encodes "mate in N" as ±(MATE_SCORE_CP - 10·N) centipawns,
# with N = 0 meaning checkmate is on the board.
MATE_SCORE_CP = 10000


def mate_in_moves(eval_cp: float) -> Optional[int]:
    """Moves to mate encoded in eval_cp (0 = checkmate), or None for a normal score."""
    if abs(eval_cp) < MATE_SCORE_CP - 1000:
        return None
    return round((MATE_SCORE_CP - abs(eval_cp)) / 10)


def format_eval(eval_cp: float) -> str:
    """Short eval label: '1.3', '-0.4', 'M3', or the result once mate is on the board."""
    mate_n = mate_in_moves(eval_cp)
    if mate_n is None:
        return f'{eval_cp / 100.0:.1f}'
    if mate_n == 0:
        return "1-0" if eval_cp > 0 else "0-1"
    return f"M{mate_n}"


# =============================================================================
# Scaled Evaluation Bar  (sigmoid fill, real eval label)
# =============================================================================

class ScaledEvaluationBar(manim_chess.EvaluationBar):
    """
    Subclass of manim_chess.EvaluationBar that takes centipawns, labels the
    bar with Stockfish's actual evaluation (or M<n> for a forced mate), and
    maps the eval to the fill with the same win-probability curve Lichess
    uses, so the bar approaches the ends without ever pinning.

    Behaviour:
        eval =   0 cp  →  white fills exactly half the bar
        eval = +100 cp →  ~59%      eval = +400 cp  →  ~81%
        eval = +1000cp →  ~98%      forced mate for white → full bar

    All heights are derived at runtime from self.black_rectangle.height
    (world units, after any scale() call) so the formula stays correct
    regardless of EVAL_BAR_SCALE or any other transform applied externally.
    """

    _SIGMOID_K = 0.00368208  # Lichess winning-chances coefficient (per cp)
    _BAR_MIN_FRAC = 0.008  # tiny floor fraction so rect never disappears

    def set_evaluation(self, eval_cp: float):
        """Animate the bar to eval_cp (centipawns, White's point of view)."""
        self.evaluation = eval_cp

        # .height/.width are the actual world dimensions, after any scale() call
        H = self.black_rectangle.height   # e.g. 6.4 * 0.72 = 4.608

        white_frac = 1.0 / (1.0 + math.exp(-self._SIGMOID_K * eval_cp))
        rect_height = min(max(self._BAR_MIN_FRAC * H, white_frac * H), H)
        pos = self.black_rectangle.get_bottom() + np.array([0, rect_height / 2, 0])
        W = self.black_rectangle.width
        new_rect = (
            Rectangle(width=W, height=rect_height,
                      stroke_color=self.WHITE, fill_opacity=1)
            .set_fill(self.WHITE)
            .move_to(pos)
        )

        text_offset = H * 0.045   # ~4.5% of bar height for text nudge
        text_val = format_eval(eval_cp)
        if eval_cp > 0:
            new_text = (
                Text(text_val, font="Arial")
                .move_to(self.black_rectangle.get_bottom() + np.array([0, text_offset, 0]))
                .set_fill(self.BLACK)
                .scale(0.2)
            )
        else:
            new_text = (
                Text(text_val, font="Arial")
                .move_to(self.black_rectangle.get_top() + np.array([0, -text_offset, 0]))
                .set_fill(self.WHITE)
                .scale(0.2)
            )

        return [Transform(self.white_rectangle, new_rect),
                Transform(self.bot_text, new_text)]

from convert_script_to_comment_dict import load_commentary
from chess_openings import OpeningBook
from animator_metrics import MetricPlotPanel

# =============================================================================
# Analysis Data Loading
# =============================================================================

@dataclass
class MoveData:
    """
    Simplified move data for animation.  Everything comes from Stockfish's
    analysis except book_opening, which comes from the Lichess opening data.
    """
    # Core move info
    ply: int
    move_san: str
    move_uci: str
    is_white_move: bool
    eval_before: float
    eval_after: float
    eval_loss: float
    classification: str
    best_move_san: str
    is_capture: bool
    is_check: bool
    pv_line: List[str]

    # Mate annotations from the analyzer (see EnhancedMoveAnalysis)
    mate_advice: str = ""
    mate_line: str = ""

    # Stockfish's best line from the position before the move (SAN), and what
    # the searches reached: depth before the move (with search_lines lines)
    # and after it.  Empty / 0 in analysis files made before these existed.
    best_line: List[str] = field(default_factory=list)
    search_depth: int = 0
    search_depth_after: int = 0
    search_lines: int = 0

    # Opening name from the Lichess opening data while the move is in book
    # (set when the analysis is loaded, see AnalysisData); "" once out of it
    book_opening: str = ""

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "MoveData":
        """
        Build a MoveData from a JSON-decoded dict.  Fields it doesn't know,
        such as the positional metrics in older analysis files, are ignored.
        """
        return cls(
            ply=d.get("ply", 0),
            move_san=d.get("move_san", ""),
            move_uci=d.get("move_uci", ""),
            is_white_move=d.get("is_white_move", True),
            eval_before=float(d.get("eval_before", 0.0)),
            eval_after=float(d.get("eval_after", 0.0)),
            eval_loss=float(d.get("eval_loss", 0.0)),
            classification=d.get("classification", ""),
            best_move_san=d.get("best_move_san", ""),
            is_capture=d.get("is_capture", False),
            is_check=d.get("is_check", False),
            pv_line=d.get("pv_line", []),
            mate_advice=d.get("mate_advice", ""),
            mate_line=d.get("mate_line", ""),
            best_line=list(d.get("best_line", [])),
            search_depth=int(d.get("search_depth", 0)),
            search_depth_after=int(d.get("search_depth_after", 0)),
            search_lines=int(d.get("search_lines", 0)),
        )


# What the opening name holds when it isn't known ("Unknown" is the
# analyzer's placeholder when the PGN has no Opening header)
MISSING_OPENING = ("", "?", "Unknown")


@functools.lru_cache(maxsize=None)
def _opening_book() -> OpeningBook:
    return OpeningBook.load()


@dataclass
class AnalysisData:
    """Container for game analysis data."""
    game_info: GameInfo
    moves: List[MoveData]
    white_accuracy: float
    black_accuracy: float
    # Engine settings from the analysis file ({} in older files)
    engine: Dict[str, Any] = field(default_factory=dict)

    def name_opening(self) -> "AnalysisData":
        """
        Tag the moves that are in book with their opening, and name the game's
        opening from its moves when the PGN has no Opening header.
        """
        book = _opening_book()
        ucis = [m.move_uci for m in self.moves]
        for move, opening in zip(self.moves, book.openings_by_ply(ucis)):
            move.book_opening = opening.name if opening else ""
        info = self.game_info
        if info.opening in MISSING_OPENING:
            opening = book.identify(ucis)
            if opening:
                info.eco, info.opening = opening.eco, opening.name
        return self

    def engine_summary(self) -> str:
        """
        e.g. "Stockfish 19 · depth 14–245 · 4s per position · 1 line · 7 threads"
        for a search by time, or "Stockfish 19 · depth 20 · 1 line · 1 thread".
        """
        e = self.engine
        if not e:
            return ""
        parts = [e.get("name", "Stockfish")]
        reached = [m.search_depth for m in self.moves if m.search_depth]
        asked = e.get("depth")
        if asked is None:   # searched by time only: give the depth reached
            low, high = (min(reached), max(reached)) if reached else ("?", "?")
            depth = f"depth {low}" if low == high else f"depth {low}–{high}"
        else:
            depth = f"depth {asked}"
            if reached and (min(reached), max(reached)) != (asked,) * 2:
                depth += f" (reached {min(reached)}–{max(reached)})"
        parts.append(depth)
        if e.get("time_limit"):
            parts.append(f"{e['time_limit']:g}s per position")
        lines = e.get("lines")
        parts.append(f"{lines} line{'s' if lines != 1 else ''}")
        threads = e.get("threads")
        parts.append(f"{threads} thread{'s' if threads != 1 else ''}")
        return " · ".join(parts)

    @classmethod
    def from_json_file(cls, json_path: Path,
                       pgn_path: Optional[Path] = None) -> "AnalysisData":
        """
        Load analysis from a JSON file written by run_animator.py --analyze.

        If pgn_path exists, the game details (players, event, opening...)
        are read from its headers, so editing them doesn't need a fresh
        analysis; otherwise they come from the JSON.
        """
        with open(json_path) as f:
            data = json.load(f)

        if pgn_path and Path(pgn_path).exists():
            game_info = GameInfo.from_pgn(Path(pgn_path))
        else:
            game_info = GameInfo(
                white=data.get("white", "White"),
                black=data.get("black", "Black"),
                white_elo=str(data.get("white_elo", "") or ""),
                black_elo=str(data.get("black_elo", "") or ""),
                event=data.get("event", ""),
                site=data.get("site", ""),
                date=data.get("date", ""),
                round=data.get("round_num", ""),
                result=data.get("result", "*"),
                opening=data.get("opening_name", ""),
                eco=data.get("opening_eco", ""),
            )

        moves = [MoveData.from_dict(m) for m in data.get("moves", [])]

        white_stats = data.get("white_stats", {})
        black_stats = data.get("black_stats", {})

        return cls(
            game_info=game_info,
            moves=moves,
            white_accuracy=float(white_stats.get("accuracy", 0.0)),
            black_accuracy=float(black_stats.get("accuracy", 0.0)),
            engine=data.get("engine", {}),
        ).name_opening()

    @classmethod
    def from_analyzer(cls, pgn_path: Path,
                      stockfish_path: Optional[str] = None,
                      depth: Optional[int] = None,
                      time_limit: Optional[float] = None,
                      lines: Optional[int] = None,
                      threads: Optional[int] = None,
                      hash_mb: Optional[int] = None) -> "AnalysisData":
        """
        Run live analysis using chess_game_analyzer.py, with the video's
        defaults: see video_search (lines=None: VIDEO_LINES).
        Prefer pre-computed JSON (from_json_file) for iteration speed.
        """
        try:
            from chess_game_analyzer import VIDEO_LINES, EnhancedGameAnalyzer, video_search
        except ImportError:
            raise ImportError("chess_game_analyzer.py must be in the Python path")

        depth, time_limit = video_search(depth, time_limit)
        with EnhancedGameAnalyzer(stockfish_path, depth, time_limit,
                                  threads=threads, hash_mb=hash_mb,
                                  lines=VIDEO_LINES if lines is None else lines) as analyzer:
            result = analyzer.analyze_game(str(pgn_path))

        game_info = GameInfo(
            white=result.white,
            black=result.black,
            white_elo=str(result.white_elo) if result.white_elo else "",
            black_elo=str(result.black_elo) if result.black_elo else "",
            event=result.event,
            site=result.site,
            date=result.date,
            round=result.round_num,
            result=result.result,
            opening=result.opening_name,
            eco=result.opening_eco,
        )

        moves = [MoveData.from_dict(asdict(m)) for m in result.moves]

        return cls(
            game_info=game_info,
            moves=moves,
            white_accuracy=result.white_stats.get("accuracy", 0.0),
            black_accuracy=result.black_stats.get("accuracy", 0.0),
            engine={"name": analyzer.engine_version, "depth": analyzer.depth,
                    "time_limit": analyzer.time_limit, "lines": analyzer.lines,
                    "threads": analyzer.threads, "hash_mb": analyzer.hash_mb},
        ).name_opening()


# =============================================================================
# Dynamic Panel Components
# =============================================================================

# The symbol for each engine rating that gets one
RATING_SYMBOLS = {
    "blunder":    "??",
    "mistake":    "?",
    "inaccuracy": "?!",
}


def move_mark(move: MoveData, marks: Dict[int, str]) -> str:
    """The move's mark: the PGN's ({ply: "!!"}) if it has one, else its rating's."""
    if move.ply in marks:
        return marks[move.ply]
    return RATING_SYMBOLS.get(move.classification, "")


class MoveListPanel:
    """
    Manages the move list: the left-hand column of the moves panel.
    Each row holds a move number, White's move and Black's move in aligned
    columns, each move coloured by its rating, scrolling as the game goes on.
    """

    def __init__(self, max_visible_lines: int = 8,
                 marks: Optional[Dict[int, str]] = None):
        self.max_visible_lines = max_visible_lines
        # Move marks from the PGN ({ply: "!!"}); they replace the engine's symbol
        self.marks = marks or {}
        self.moves: List[MoveData] = []
        self.panel_group = VGroup()
        self.moves_group = VGroup()
        self._create_panel()

    def _create_panel(self):
        bg = get_panel_rect(MOVE_LIST_TOP_Y, MOVE_LIST_BOTTOM_Y)
        self.panel_group.add(bg)

        title = Text(
            "Moves",
            font=FONTS.heading_font, weight=FONTS.weight,
            font_size=FONTS.subtitle_size,
            color=COLORS.text_secondary
        )
        title.move_to([MOVES_COLUMN_CENTER_X, MOVE_LIST_TOP_Y - 0.25, 0])
        self.panel_group.add(title)

        # Divider between the move list and the commentary column
        divider = Line([MOVES_COLUMN_RIGHT_X, MOVE_LIST_TOP_Y - 0.15, 0],
                       [MOVES_COLUMN_RIGHT_X, MOVE_LIST_BOTTOM_Y + 0.15, 0],
                       stroke_width=1, color=COLORS.text_secondary,
                       stroke_opacity=0.4)
        self.panel_group.add(divider)
        self.panel_group.add(self.moves_group)

    def get_mobject(self) -> VGroup:
        return self.panel_group

    def _format_move_text(self, move: MoveData) -> str:
        return move.move_san + move_mark(move, self.marks)

    def rows(self) -> List[Tuple[int, Optional[MoveData], Optional[MoveData]]]:
        """(move number, White's move, Black's move) for every move so far."""
        rows: Dict[int, List[Optional[MoveData]]] = {}
        for move in self.moves:
            cells = rows.setdefault((move.ply + 1) // 2, [None, None])
            cells[0 if move.is_white_move else 1] = move
        return [(n, w, b) for n, (w, b) in rows.items()]

    # Characters per field: "100." then White's move then Black's move
    NUMBER_WIDTH = 4
    MOVE_WIDTH   = 10   # longest SAN plus mark, e.g. "exd8=Q+??", and a space

    def _row_text(self, number: int, white: Optional[MoveData],
                  black: Optional[MoveData], y: float) -> Text:
        """
        One row as a single monospaced Text, so every row lines up in columns
        and shares a baseline.  It starts with an invisible "|" that the row
        is positioned by, because leading spaces don't count towards a Text's
        width.
        """
        white_text = self._format_move_text(white) if white else "..."
        black_text = self._format_move_text(black) if black else ""
        num = f"{number}."
        row = f"|{num:>{self.NUMBER_WIDTH}} {white_text:<{self.MOVE_WIDTH}}{black_text}"

        white_at = 1 + self.NUMBER_WIDTH + 1
        black_at = white_at + self.MOVE_WIDTH
        t2c = {f"[1:{1 + self.NUMBER_WIDTH}]": COLORS.text_secondary,
               f"[{white_at}:{white_at + len(white_text)}]":
                   get_classification_color(white.classification) if white
                   else COLORS.text_secondary}
        if black:
            t2c[f"[{black_at}:{black_at + len(black_text)}]"] = \
                get_classification_color(black.classification)

        t = Text(row, font=FONTS.mono_font, weight=FONTS.weight, font_size=FONTS.move_size,
                 color=COLORS.text_primary, t2c=t2c)
        anchor = t.submobjects[0]
        anchor.set_opacity(0)
        x_left = PANEL_LEFT_X + MOVES_COLUMN_PADDING - char_width(FONTS.move_size)
        t.shift([x_left - anchor.get_left()[0], y - anchor.get_center()[1], 0])
        return t

    def _render_lines(self) -> VGroup:
        """
        Build and return a fresh VGroup with the most recent rows.  Does NOT
        mutate self.moves_group; the caller decides what to do with the old
        and new groups.
        """
        title_height  = 0.5   # room for the "Moves" title at the top
        bottom_margin = 0.15  # breathing room above the panel bottom edge
        usable_height = (MOVE_LIST_TOP_Y - MOVE_LIST_BOTTOM_Y
                         - title_height - bottom_margin)
        line_height = usable_height / max(1, self.max_visible_lines)
        content_top = MOVE_LIST_TOP_Y - title_height

        group = VGroup()
        visible = self.rows()[-self.max_visible_lines:]
        for i, (number, white, black) in enumerate(visible):
            group.add(self._row_text(number, white, black,
                                     content_top - (i + 0.5) * line_height))
        return group

    def add_move(self, move: MoveData) -> Animation:
        """Append a move and return the Manim animation for the panel update."""
        self.moves.append(move)

        new_group = self._render_lines()

        # Replace the old content in moves_group with the new content.
        # We do this by building the animation against the old state, then
        # swapping the children so the scene always holds the live objects.
        old_children = list(self.moves_group.submobjects)
        old_group    = VGroup(*[c.copy() for c in old_children])

        # Swap children into moves_group so the scene tracks the new objects
        self.moves_group.remove(*old_children)
        for obj in new_group.submobjects:
            self.moves_group.add(obj)

        if not old_children:
            return FadeIn(self.moves_group)
        return FadeTransform(old_group, self.moves_group)


def format_line(sans: List[str], ply: int, max_plies: int = 6) -> str:
    """
    Number a line of SAN moves that starts at `ply` (1 = White's first move):
    ["Be2", "Nfd7", "O-O"] at ply 21 -> "11.Be2 Nfd7 12.O-O",
    ["Qb5", "Bd3"] at ply 34 -> "17...Qb5 18.Bd3".
    """
    parts = []
    for i, san in enumerate(sans[:max_plies]):
        p = ply + i
        number = (p + 1) // 2
        if p % 2 == 1:
            parts.append(f"{number}.{san}")
        elif i == 0:
            parts.append(f"{number}...{san}")
        else:
            parts.append(san)
    return " ".join(parts)


@functools.lru_cache(maxsize=None)
def char_width(font_size: int) -> float:
    """Width of one character of the body font, which is monospaced."""
    sample = "M" * 20
    return Text(sample, font=FONTS.body_font, weight=FONTS.weight, font_size=font_size).width / len(sample)


def wrap_text(text: str, width: int) -> List[str]:
    """Word-wrap text into lines of fewer than `width` characters."""
    lines, current = [], ""
    for word in text.split():
        if not current or len(current) + len(word) < width:
            current += word + " "
        else:
            lines.append(current.strip())
            current = word + " "
    if current.strip():
        lines.append(current.strip())
    return lines


def _left_text(text: str, x_left: float, y: float, **kwargs) -> Text:
    t = Text(text, **kwargs)
    t.move_to([x_left + t.width / 2, y, 0])
    return t


def _swap_content(group: VGroup, new_items: List[Mobject]) -> Optional[Animation]:
    """
    Replace the children of `group` (which the scene holds) with new_items and
    return the transition, or None when there was nothing before or after.
    """
    old_children = list(group.submobjects)
    old_group = VGroup(*[c.copy() for c in old_children])
    group.remove(*old_children)
    for obj in new_items:
        group.add(obj)

    if not old_children and not new_items:
        return None
    if not old_children:
        return FadeIn(group)
    if not new_items:
        return FadeOut(old_group)
    return FadeTransform(old_group, group)


class CommentPanel:
    """
    Your commentary (PGN comments and the notes file), shown in the right-hand
    column of the moves panel, on the move it belongs to.
    """

    LINE_HEIGHT   = 0.23
    TITLE_HEIGHT  = 0.5
    BOTTOM_MARGIN = 0.15

    def __init__(self, custom_comments: dict = None):
        self.custom_comments = custom_comments or {}
        self.content_group = VGroup()
        title = Text("Commentary", font=FONTS.heading_font, weight=FONTS.weight,
                     font_size=FONTS.subtitle_size, color=COLORS.text_secondary)
        title.move_to([(COMMENT_LEFT_X + COMMENT_RIGHT_X) / 2,
                       MOVE_LIST_TOP_Y - 0.25, 0])
        self.panel_group = VGroup(title, self.content_group)

    def get_mobject(self) -> VGroup:
        return self.panel_group

    @classmethod
    def max_lines(cls) -> int:
        usable = (MOVE_LIST_TOP_Y - MOVE_LIST_BOTTOM_Y
                  - cls.TITLE_HEIGHT - cls.BOTTOM_MARGIN)
        return int(usable / cls.LINE_HEIGHT)

    @staticmethod
    def chars_per_line() -> int:
        return int((COMMENT_RIGHT_X - COMMENT_LEFT_X) / char_width(FONTS.commentary_size))

    @classmethod
    def wrap_comment(cls, text: str) -> List[str]:
        return wrap_text(text, cls.chars_per_line())

    @classmethod
    def overlong_comments(cls, comments: Dict[str, str]) -> List[Tuple[str, int]]:
        """(ply key, line count) for each move comment too long for the column."""
        limit = cls.max_lines()
        return [(key, len(cls.wrap_comment(text)))
                for key, text in comments.items()
                if key.isdigit() and len(cls.wrap_comment(text)) > limit]

    def comment_lines(self, move: MoveData) -> List[str]:
        text = self.custom_comments.get(str(move.ply))
        return self.wrap_comment(text) if text else []

    def update(self, move: MoveData) -> Optional[Animation]:
        """Show this move's comment (or nothing) and return the transition."""
        content_top = MOVE_LIST_TOP_Y - self.TITLE_HEIGHT
        texts = [
            _left_text(line, COMMENT_LEFT_X,
                       content_top - (i + 0.5) * self.LINE_HEIGHT,
                       font=FONTS.body_font, weight=FONTS.weight, font_size=FONTS.commentary_size,
                       color=COLORS.text_primary)
            for i, line in enumerate(self.comment_lines(move)[:self.max_lines()])
        ]
        return _swap_content(self.content_group, texts)


class AnalysisPanel:
    """
    Stockfish's view of each move: rating, evaluation, the best line when the
    move wasn't the engine's choice, Lichess-style mate advice, and how deep
    the search went.
    """

    LINE_HEIGHT   = 0.23
    TITLE_HEIGHT  = 0.45
    BOTTOM_MARGIN = 0.1
    BEST_LINE_PLIES = 6

    def __init__(self):
        self.content_group = VGroup()
        bg = get_panel_rect(ANALYSIS_TOP_Y, ANALYSIS_BOTTOM_Y)
        title = Text("Analysis", font=FONTS.heading_font, weight=FONTS.weight,
                     font_size=FONTS.subtitle_size, color=COLORS.text_secondary)
        title.move_to([PANEL_CENTER_X, ANALYSIS_TOP_Y - 0.25, 0])
        self.panel_group = VGroup(bg, title, self.content_group)

    def get_mobject(self) -> VGroup:
        return self.panel_group

    @classmethod
    def max_lines(cls) -> int:
        usable = (ANALYSIS_TOP_Y - ANALYSIS_BOTTOM_Y
                  - cls.TITLE_HEIGHT - cls.BOTTOM_MARGIN)
        return int(usable / cls.LINE_HEIGHT)

    @staticmethod
    def chars_per_line() -> int:
        return int((ANALYSIS_RIGHT_X - ANALYSIS_LEFT_X) / char_width(FONTS.commentary_size))

    @staticmethod
    def headline(move: MoveData) -> Tuple[str, str]:
        """(rating with centipawns lost, evaluation after the move)."""
        rating = ""
        if move.classification:
            # A centipawn loss means little when a forced mate appears or vanishes
            loss = (f" ({move.eval_loss:.0f}cp lost)"
                    if move.eval_loss > 10 and not move.mate_advice else "")
            rating = f"{move.classification.capitalize()}{loss}"

        eval_val = move.eval_after / 100.0
        mate_n = mate_in_moves(move.eval_after)
        winner = "White" if eval_val > 0 else "Black"
        if mate_n == 0:
            evaluation = f"Checkmate - {winner} wins"
        elif mate_n is not None:
            evaluation = f"{winner} mates in {mate_n}"
        else:
            evaluation = f"Eval {eval_val:+.2f}"
        return rating, evaluation

    @classmethod
    def body_lines(cls, move: MoveData) -> List[str]:
        """
        The opening while the move is in book, mate advice, and the best line
        when the move wasn't the engine's choice.
        """
        width = cls.chars_per_line()
        lines = []
        if move.book_opening:
            lines += wrap_text(f"Book: {move.book_opening}", width)
        if move.mate_advice:
            lines += wrap_text(move.mate_advice + ".", width)
        if move.mate_line:
            lines += wrap_text(move.mate_line, width)
        elif (move.best_move_san and move.move_san != move.best_move_san
                and move.classification != "best"):
            if move.best_line:
                best = format_line(move.best_line, move.ply, cls.BEST_LINE_PLIES)
                lines += wrap_text(f"Best line: {best}", width)
            else:   # analysis made before best lines were saved
                lines.append(f"Best: {format_line([move.best_move_san], move.ply)}")
        return lines

    @staticmethod
    def footer(move: MoveData) -> str:
        """How deep Stockfish got for this move, if the analysis recorded it."""
        if not move.search_depth:
            return ""
        n = move.search_lines
        text = f"Search depth {move.search_depth} ({n} line{'s' if n != 1 else ''})"
        if move.search_depth_after:
            text += f", {move.search_depth_after} after the move"
        return text

    def update(self, move: MoveData) -> Optional[Animation]:
        """Show this move's analysis and return the transition."""
        content_top = ANALYSIS_TOP_Y - self.TITLE_HEIGHT
        max_lines = self.max_lines()
        items: List[Mobject] = []

        def y_of(row):
            return content_top - (row + 0.5) * self.LINE_HEIGHT

        rating, evaluation = self.headline(move)
        eval_text = Text(evaluation, font=FONTS.body_font, weight=FONTS.weight,
                         font_size=FONTS.commentary_size, color=COLORS.text_primary)
        if rating:
            rating_text = _left_text(rating, ANALYSIS_LEFT_X, y_of(0),
                                     font=FONTS.body_font, weight=FONTS.weight,
                                     font_size=FONTS.commentary_size,
                                     color=get_classification_color(move.classification))
            eval_text.next_to(rating_text, RIGHT, buff=0.35)
            items.append(rating_text)
        else:
            eval_text.move_to([ANALYSIS_LEFT_X + eval_text.width / 2, y_of(0), 0])
        items.append(eval_text)

        footer = self.footer(move)
        body_rows = max_lines - 1 - (1 if footer else 0)
        for i, line in enumerate(self.body_lines(move)[:body_rows]):
            items.append(_left_text(line, ANALYSIS_LEFT_X, y_of(i + 1),
                                    font=FONTS.body_font, weight=FONTS.weight,
                                    font_size=FONTS.commentary_size,
                                    color=COLORS.text_primary))
        if footer:
            items.append(_left_text(footer, ANALYSIS_LEFT_X, y_of(max_lines - 1),
                                    font=FONTS.body_font, weight=FONTS.weight,
                                    font_size=FONTS.commentary_size - 2,
                                    color=COLORS.text_secondary))
        return _swap_content(self.content_group, items)


# =============================================================================
# Configuration Loading
# =============================================================================

def _load_animator_config() -> Dict[str, str]:
    """
    Load animator config from the JSON file whose path is in the
    CHESS_ANIMATOR_CONFIG environment variable.

    Returns a dict with optional keys:
        pgn_path, analysis_path, comments_path, stockfish_path
    """
    config_path = os.environ.get("CHESS_ANIMATOR_CONFIG", "")
    if config_path and Path(config_path).exists():
        with open(config_path) as f:
            return json.load(f)
    return {}


# Seconds each move stays on screen after its animation, and how fast a
# comment is assumed to be read when deciding how long to hold its move
BASE_HOLD_SECONDS = 1.2
READING_CHARS_PER_SECOND = 15


def comment_hold_seconds(comment: Optional[str]) -> float:
    """How long to hold a move: longer when it has a comment to read."""
    if not comment:
        return BASE_HOLD_SECONDS
    return max(BASE_HOLD_SECONDS, len(comment) / READING_CHARS_PER_SECOND)


def default_notes_path(pgn_path) -> Path:
    """The notes file that goes with a PGN: games/x.pgn -> games/x_notes.txt."""
    pgn_path = Path(pgn_path)
    return pgn_path.with_name(pgn_path.stem + "_notes.txt")


def analysis_sources(pgn_path, analysis_path) -> Tuple[List[Path], List[Path]]:
    """
    Where to look for a game's analysis: (JSON files, PGNs to analyse live),
    each in order of preference.

    Once a game is named, only its own files count, so a game without an
    analysis is analysed live rather than shown with another game's moves.
    The default files are for running the scene without a config.
    """
    if not pgn_path and not analysis_path:
        return ([Path("game_analysis.json"), Path("sample_game_analysis.json")],
                [Path("game.pgn"), Path("sample_game.pgn")])
    jsons = [Path(analysis_path)] if analysis_path else []
    pgns = []
    if pgn_path:
        pgn_path = Path(pgn_path)
        jsons.append(pgn_path.with_name(pgn_path.stem + "_analysis.json"))
        pgns.append(pgn_path)
    return jsons, pgns


# =============================================================================
# Board moves
# =============================================================================

def play_move(board: manim_chess.Board, position: chess.Board, uci: str) -> None:
    """
    Apply one move to the manim board instantly.

    Unlike manim_chess.play_game, this doesn't pause for a second afterwards,
    so the panels describing the move can update together with it.
    `position` tracks the game with python-chess to recognise castling,
    en passant and promotion; it is advanced by the move.
    """
    move = chess.Move.from_uci(uci)
    from_sq = chess.square_name(move.from_square)
    to_sq = chess.square_name(move.to_square)

    if position.is_en_passant(move):
        board.remove_piece(to_sq[0] + from_sq[1])
    elif position.is_castling(move):
        rank = from_sq[1]
        if position.is_kingside_castling(move):
            board.move_piece(f"h{rank}", f"f{rank}")
        else:
            board.move_piece(f"a{rank}", f"d{rank}")

    board.move_piece(from_sq, to_sq)
    if move.promotion:
        board.promote_piece(to_sq, chess.piece_symbol(move.promotion))
    position.push(move)


class BoardAnnotation:
    """
    The last move's mark (!!, !, !?, ?!, ?, ??) shown on the board the way
    en-croissant shows it: the move's two squares take on the mark's colour,
    and a round badge with the symbol sits on the destination square's
    top-right corner.  Moves without a mark keep the board's own highlight.
    """

    TINT = 0.4           # share of the mark's colour mixed into each square
    BADGE_SIZE = 0.45    # badge diameter, in squares
    BADGE_X = 0.9        # badge centre from the square's left edge, in squares
    BADGE_Y = 0.045      # ... and below its top edge (raised 40% of its size)
    SHADOW = 1 / 48      # drop shadow offset, in badge diameters (1px of 48)
    GLYPH_HEIGHT = 0.62  # symbol height, in badge diameters
    GLYPH_WIDTH = 0.72   # widest a two-character symbol may be

    def __init__(self, board: manim_chess.Board):
        self.board = board
        self.layer = VGroup()   # added after the board, so it's drawn on top

    def get_mobject(self) -> VGroup:
        return self.layer

    def update(self, move_uci: str, symbol: str) -> Optional[Animation]:
        """
        Mark the move just played on the board; call after play_move, whose
        highlight this recolours.  Returns the badge's entrance, or None.
        """
        self.layer.remove(*self.layer.submobjects)
        colors = ANNOTATION_COLORS.get(symbol)
        if not colors:
            return None
        tint, badge_color = colors

        board = self.board
        for coordinate in board.highlighted_squares:
            base = (board.color_light if board.is_light_square(coordinate)
                    else board.color_dark)
            board.squares[coordinate].set_fill(
                interpolate_color(base, ManimColor(tint), self.TINT), family=False)

        to_sq = chess.square_name(chess.Move.from_uci(move_uci).to_square)
        square = board.squares[to_sq]
        size = square.width
        diameter = self.BADGE_SIZE * size
        center = square.get_corner(UL) + np.array([self.BADGE_X * size,
                                                   -self.BADGE_Y * size, 0])

        shadow = Circle(radius=diameter / 2, stroke_width=0,
                        fill_color=BLACK, fill_opacity=0.3)
        shadow.move_to(center + DOWN * self.SHADOW * diameter)
        disc = Circle(radius=diameter / 2, stroke_width=0,
                      fill_color=badge_color, fill_opacity=1).move_to(center)
        glyph = Text(symbol, font="Noto Sans", weight=ULTRABOLD, color=WHITE)
        glyph.scale_to_fit_height(self.GLYPH_HEIGHT * diameter)
        if glyph.width > self.GLYPH_WIDTH * diameter:
            glyph.scale_to_fit_width(self.GLYPH_WIDTH * diameter)
        glyph.move_to(center)

        self.layer.add(shadow, disc, glyph)
        return FadeIn(self.layer, scale=0.5)


class CheckGlow:
    """
    A red glow on the square of a king in check, as en-croissant draws it:
    chessground's radial gradient, opaque red out to a quarter of the way to
    the square's corners, then fading out by 89%.  The glow sits under the
    king and the square's coordinate label, like a background.
    """

    # chessground's cg-board square.check stops: (radius as a share of the
    # centre-to-corner distance, colour, opacity)
    STOPS = [(0.0, "#FF0000", 1.0), (0.25, "#E70000", 1.0), (0.89, "#A90000", 0.0)]
    RINGS = 24   # discs approximating each part of the gradient

    def __init__(self, board: manim_chess.Board):
        self.board = board
        self.layer = VGroup()
        self.square: Optional[Mobject] = None   # the square holding the glow

    def get_mobject(self) -> VGroup:
        return self.layer

    def update(self, position: chess.Board) -> None:
        """
        Show the glow if the side to move in `position` is in check; call
        after play_move.  Instant, like the move itself.
        """
        if self.square is not None:
            self.square.remove(self.layer)
            self.square = None
        self.layer.remove(*self.layer.submobjects)
        if not position.is_check():
            return

        square = self.board.squares[chess.square_name(position.king(position.turn))]
        self.layer.add(*self._discs(square))
        # First among the square's submobjects: drawn after its fill, before
        # its label, and before the pieces, which the board adds after squares.
        square.submobjects.insert(0, self.layer)
        self.square = square

    @classmethod
    def _discs(cls, square: Mobject) -> List[VMobject]:
        """
        Concentric discs, largest first, clipped to the square.  Each band
        between two radii is covered by every disc from its outer edge out,
        so a disc's opacity is set to bring the stack to the gradient's
        opacity at the middle of its band.
        """
        size = square.width
        corner = size / math.sqrt(2)
        clip = Square(side_length=size).move_to(square.get_center())
        discs = []
        stacked = 0.0   # opacity of the discs already drawn
        for (t0, c0, a0), (t1, c1, a1) in reversed(list(zip(cls.STOPS, cls.STOPS[1:]))):
            for k in range(cls.RINGS, 0, -1):
                outer = t0 + (t1 - t0) * k / cls.RINGS
                mid = (k - 0.5) / cls.RINGS
                target = a0 + (a1 - a0) * mid
                if target <= 0:
                    continue
                opacity = 1.0 if target >= 1 else 1 - (1 - target) / (1 - stacked)
                stacked = target
                color = interpolate_color(ManimColor(c0), ManimColor(c1), mid)
                disc = Circle(radius=outer * corner).move_to(square.get_center())
                if outer * corner > size / 2:
                    disc = Intersection(disc, clip)
                disc.set_fill(color, opacity=opacity).set_stroke(width=0)
                discs.append(disc)
        return discs


# =============================================================================
# Main Animated Scene
# =============================================================================

class AnimatedGame(Scene):
    """
    Main scene that animates a complete chess game with
    engine analysis and optional human commentary.

    Config is read from the JSON file at CHESS_ANIMATOR_CONFIG env var.
    See run_animator.py for how to set this up.
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        cfg = _load_animator_config()
        self.pgn_path      = cfg.get("pgn_path")
        self.analysis_path = cfg.get("analysis_path")
        self.comments_path = cfg.get("comments_path")
        self.stockfish_path = cfg.get("stockfish_path")
        self.custom_comments: Dict[str, str] = {}
        self.pgn_marks: Dict[int, str] = {}

    def _load_analysis(self) -> AnalysisData:
        """
        Load game analysis.  Priority order:
        1. Pre-computed JSON  (analysis_path or <game>_analysis.json)
        2. Live Stockfish run (pgn_path)
        3. Hard error
        """
        candidates, pgn_candidates = analysis_sources(self.pgn_path, self.analysis_path)

        # Try analysis JSON first
        for path in candidates:
            if path.exists():
                print(f"Loading analysis from {path}")
                return AnalysisData.from_json_file(path, self.pgn_path)

        # Fall back to live analysis
        for path in pgn_candidates:
            if path.exists():
                print(f"Running live Stockfish analysis on {path}…")
                return AnalysisData.from_analyzer(path, self.stockfish_path)

        raise FileNotFoundError(
            "No analysis JSON or PGN found. "
            "Set CHESS_ANIMATOR_CONFIG or place game.pgn in the working directory."
        )

    def _load_custom_comments(self):
        """
        Load commentary into self.custom_comments and move marks into
        self.pgn_marks, from the PGN's annotations and the [KEY]-based notes
        file.  The notes file wins where both have an entry.
        """
        txt_path = self.comments_path
        if not txt_path and self.pgn_path:
            candidate = default_notes_path(self.pgn_path)
            if candidate.exists():
                txt_path = str(candidate)

        self.custom_comments, self.pgn_marks = load_commentary(self.pgn_path, txt_path)
        sources = [p for p in (self.pgn_path, txt_path) if p and Path(p).exists()]
        if self.custom_comments or self.pgn_marks:
            print(f"Loaded {len(self.custom_comments)} comments and "
                  f"{len(self.pgn_marks)} move marks from {', '.join(sources)}")
        else:
            print("No commentary found — using engine-only mode.")

        for key, n_lines in CommentPanel.overlong_comments(self.custom_comments):
            print(f"Warning: comment for ply {key} wraps to {n_lines} lines; "
                  f"only the first {CommentPanel.max_lines()} will be shown.")

    def _make_title_card(self, info: "GameInfo") -> VGroup:
        """
        Build the opening title card as a VGroup of Text objects.

        Displays: event/site, date, White vs Black with Elos, opening name,
        result, and an optional intro from self.custom_comments["intro"]
        (the PGN's comment before the first move, or the notes file's
        [INTRO] entry).

        Every text item is clamped to MAX_WIDTH so nothing bleeds horizontally.
        arrange(DOWN, buff=0.40) provides enough vertical breathing room to
        prevent lines from bleeding into each other at low resolution.
        """
        MAX_WIDTH = FRAME_WIDTH - 2.0

        def _t(text, font_size, color, bold=False):
            t = Text(text, font=FONTS.heading_font,
                     font_size=font_size, color=color,
                     weight=BOLD if bold else FONTS.weight)
            if t.width > MAX_WIDTH:
                t.set_width(MAX_WIDTH)
            return t

        gi    = info
        items = []

        # ── Title line: event or "Chess Game" fallback ───────────────────────
        event_str = gi.event if gi.event and gi.event not in ("?", "") else "Chess Game"
        items.append(_t(event_str, 28, COLORS.text_accent, bold=True))

        # ── Site · Date ───────────────────────────────────────────────────────
        site_date_parts = [p for p in (gi.site, gi.date)
                           if p and p not in ("?", "", "????.??.??")]
        if site_date_parts:
            items.append(_t("  ·  ".join(site_date_parts), 16, COLORS.text_secondary))

        # ── Players ───────────────────────────────────────────────────────────
        white_str = format_player_display(gi.white, gi.white_elo)
        black_str = format_player_display(gi.black, gi.black_elo)
        items.append(_t(f"{white_str}  vs  {black_str}", 22, COLORS.text_primary, bold=True))

        # ── Opening ───────────────────────────────────────────────────────────
        if gi.opening and gi.opening not in ("?", ""):
            eco_prefix = f"{gi.eco}  " if gi.eco and gi.eco not in ("?", "") else ""
            items.append(_t(f"{eco_prefix}{gi.opening}", 14, COLORS.text_secondary))

        # ── Result ────────────────────────────────────────────────────────────
        result_str = gi.result if gi.result and gi.result not in ("?", "*", "") else ""
        if result_str:
            items.append(_t(result_str, 18, COLORS.text_primary))

        # ── Intro (PGN comment before move 1, or notes file [INTRO]) ─────────
        if "intro" in self.custom_comments:
            items.append(_t(self.custom_comments["intro"], 14, COLORS.text_primary))

        card = VGroup(*items)
        card.arrange(DOWN, buff=0.40, center=True)

        # Safety: scale down if card is taller than the frame
        if card.height > FRAME_HEIGHT - 1.0:
            card.scale((FRAME_HEIGHT - 1.0) / card.height)

        card.move_to(ORIGIN)
        return card

    def _make_end_card(self, analysis: "AnalysisData") -> VGroup:
        """
        Build the closing end card as a VGroup of Text objects.

        Shows: result (the notes file's [RESULT] if given), players,
        accuracy statistics, move counts by classification, the notes
        file's [CONCLUSION], and a credits block listing the engine and
        search settings, Manim, manim-chess, and Claude.

        Every text item is clamped to MAX_WIDTH so nothing bleeds horizontally.
        arrange(DOWN, buff=0.30) provides enough vertical breathing room to
        prevent lines from bleeding into each other at low resolution.
        """
        MAX_WIDTH = FRAME_WIDTH - 2.0

        def _t(text, font_size, color, bold=False):
            t = Text(text, font=FONTS.heading_font,
                     font_size=font_size, color=color,
                     weight=BOLD if bold else FONTS.weight)
            if t.width > MAX_WIDTH:
                t.set_width(MAX_WIDTH)
            return t

        gi    = analysis.game_info
        items = []

        # ── Result headline ───────────────────────────────────────────────────
        result_str = self.custom_comments.get("result", gi.result) or "*"
        items.append(_t(result_str, 32, COLORS.text_accent, bold=True))

        # ── Players ───────────────────────────────────────────────────────────
        white_str = format_player_display(gi.white, gi.white_elo)
        black_str = format_player_display(gi.black, gi.black_elo)
        items.append(_t(f"{white_str}  vs  {black_str}", 18, COLORS.text_primary))

        # ── Accuracy ─────────────────────────────────────────────────────────
        items.append(_t(
            f"Accuracy:  {gi.white} {analysis.white_accuracy:.1f}%"
            f"   {gi.black} {analysis.black_accuracy:.1f}%",
            14, COLORS.text_secondary,
        ))

        # ── Move classification counts (two rows) ─────────────────────────────
        counts: Dict[str, int] = {}
        for m in analysis.moves:
            counts[m.classification] = counts.get(m.classification, 0) + 1

        order = ["best", "inaccuracy", "mistake", "blunder"]
        stat_parts = [f"{c.capitalize()}: {counts[c]}"
                      for c in order if c in counts]
        if stat_parts:
            mid = (len(stat_parts) + 1) // 2
            items.append(_t("  ·  ".join(stat_parts[:mid]),  12, COLORS.text_secondary))
            items.append(_t("  ·  ".join(stat_parts[mid:]),  12, COLORS.text_secondary))

        # ── Custom conclusion ─────────────────────────────────────────────────
        if "conclusion" in self.custom_comments:
            items.append(_t(self.custom_comments["conclusion"], 14, COLORS.text_primary))

        # ── Thanks / Credits ──────────────────────────────────────────────────
        items.append(_t("— Thanks for watching —", 16, COLORS.text_accent, bold=True))

        for line in [
            (f"Analysis engine: {analysis.engine_summary()}"
             if analysis.engine else
             "Analysis engine: Stockfish  (stockfishchess.org)"),
            "Animation:       Manim Community  (manim.community)",
            "Chess rendering: manim-chess",
            "AI assistance:   Claude (Anthropic)",
        ]:
            items.append(_t(line, 11, COLORS.text_secondary))

        card = VGroup(*items)
        card.arrange(DOWN, buff=0.30, center=True)

        # Safety: scale down if card is taller than the frame
        if card.height > FRAME_HEIGHT - 0.8:
            card.scale((FRAME_HEIGHT - 0.8) / card.height)

        card.move_to(ORIGIN)
        return card

    def construct(self):
        # ── 1. Initialise ────────────────────────────────────────────────────
        self.camera.background_color = COLORS.background
        analysis = self._load_analysis()
        self._load_custom_comments()

        # ── 2. Title card ────────────────────────────────────────────────────
        title_card = self._make_title_card(analysis.game_info)
        self.play(FadeIn(title_card), run_time=1.0)
        self.wait(3)
        self.play(FadeOut(title_card), run_time=0.8)
        self.wait(0.3)

        # ── 3. Board & eval bar ──────────────────────────────────────────────
        board = manim_chess.Board()
        board.set_board_from_FEN()
        board.scale(BOARD_SCALE)
        board.move_to([BOARD_CENTER_X, BOARD_CENTER_Y, 0])

        eval_bar = ScaledEvaluationBar()
        eval_bar.scale(EVAL_BAR_SCALE)
        eval_bar.next_to(board, LEFT, buff=EVAL_BAR_OFFSET)
        board_annotation = BoardAnnotation(board)
        check_glow = CheckGlow(board)

        # ── 4. Side panels ───────────────────────────────────────────────────
        header_panel = create_header_panel(analysis.game_info)
        move_list    = MoveListPanel(marks=self.pgn_marks)
        comments     = CommentPanel(custom_comments=self.custom_comments)
        analysis_box = AnalysisPanel()

        # ── 5. Eval plot ─────────────────────────────────────────────────────
        metric_panel = MetricPlotPanel(analysis.moves)

        # Add all persistent objects
        objects_to_add = [board, board_annotation.get_mobject(), eval_bar,
                          header_panel, move_list.get_mobject(),
                          comments.get_mobject(), analysis_box.get_mobject(),
                          metric_panel.get_mobject()]
        self.add(*objects_to_add)

        # ── 6. Animation loop ────────────────────────────────────────────────
        position = chess.Board()
        for idx, move in enumerate(analysis.moves):
            play_move(board, position, move.move_uci)
            check_glow.update(position)

            panel_anims = [
                board_annotation.update(move.move_uci,
                                        move_mark(move, self.pgn_marks)),
                eval_bar.set_evaluation(move.eval_after),
                move_list.add_move(move),
                comments.update(move),
                analysis_box.update(move),
                metric_panel.advance_to_ply(idx),
            ]
            panel_anims = [a for a in panel_anims if a is not None]

            self.play(*panel_anims, run_time=0.4)
            # Hold on the analysed position, longer when there's a comment to read
            self.wait(comment_hold_seconds(self.custom_comments.get(str(move.ply))))

        # ── 7. End card ──────────────────────────────────────────────────────
        self.wait(1)

        # Fade out the board area, keep side panels a moment then clear all
        game_objects = Group(board, board_annotation.get_mobject(), eval_bar)
        self.play(FadeOut(game_objects), run_time=0.8)
        self.play(FadeOut(Group(*objects_to_add)), run_time=0.5)

        end_card = self._make_end_card(analysis)
        self.play(FadeIn(end_card), run_time=1.0)
        self.wait(5)
        self.play(FadeOut(end_card), run_time=1.0)


# =============================================================================
# Quick Demo Scene (self-contained, no external files needed)
# =============================================================================

class QuickDemo(Scene):
    """
    Quick demo using hard-coded moves.
    Tests the full animation pipeline — board, eval bar, move list,
    analysis — without requiring any external files.
    """

    def construct(self):
        self.camera.background_color = COLORS.background

        board = manim_chess.Board()
        board.set_board_from_FEN()
        board.scale(BOARD_SCALE)
        board.move_to([BOARD_CENTER_X, BOARD_CENTER_Y, 0])

        eval_bar = ScaledEvaluationBar()
        eval_bar.scale(EVAL_BAR_SCALE)
        eval_bar.next_to(board, LEFT, buff=EVAL_BAR_OFFSET)

        title = Text(
            "Quick Demo",
            font=FONTS.heading_font, weight=FONTS.weight,
            font_size=FONTS.title_size,
            color=COLORS.text_primary
        ).move_to([PANEL_CENTER_X, HEADER_CENTER_Y, 0])

        board_annotation = BoardAnnotation(board)
        check_glow = CheckGlow(board)
        move_list    = MoveListPanel()
        comments     = CommentPanel()
        analysis_box = AnalysisPanel()

        self.add(board, board_annotation.get_mobject(), eval_bar, title,
                 move_list.get_mobject(),
                 comments.get_mobject(), analysis_box.get_mobject())
        self.wait(1)

        # (ply, san, uci, is_white, ev_before, ev_after, ev_loss,
        #  classif, best_san, is_capture, is_check, pv_line)

        demo_moves = [
            MoveData(1,  "e4",    "e2e4", True,   0,   30,   0, "best",    "e4",  False, False, []),
            MoveData(2,  "e5",    "e7e5", False,  30,   25,   5, "best",    "e5",  False, False, []),
            MoveData(3,  "Nf3",   "g1f3", True,   25,   35,   0, "best",    "Nf3", False, False, []),
            MoveData(4,  "Nc6",   "b8c6", False,  35,   30,   5, "",        "Nc6", False, False, []),
            MoveData(5,  "Bb5",   "f1b5", True,   30,   40,   0, "best",    "Bb5", False, False, []),
            MoveData(6,  "a6",    "a7a6", False,  40,   35,   5, "",        "a6",  False, False, []),
            MoveData(7,  "Ba4",   "b5a4", True,   35,   40,   0, "best",    "Ba4", False, False, []),
            MoveData(8,  "Nf6",   "g8f6", False,  40,   35,   5, "best",    "Nf6", False, False, []),
            MoveData(9,  "O-O",   "e1g1", True,   35,   40,   0, "best",    "O-O", False, False, []),
            MoveData(10, "Be7",   "f8e7", False,  40,   35,   5, "",        "Be7", False, False, []),
            MoveData(11, "Re1",   "f1e1", True,   35,   45,   0, "best",    "Re1", False, False, []),
            MoveData(12, "b5",    "b7b5", False,  45,   40,   5, "",        "b5",  False, False, []),
            MoveData(13, "Bb3",   "a4b3", True,   40,   50,   0, "best",    "Bb3", False, False, []),
            MoveData(14, "d6",    "d7d6", False,  50,   45,   5, "",        "d6",  False, False, []),
            MoveData(15, "c3",    "c2c3", True,   45,   55,   0, "best",    "c3",  False, False, []),
            MoveData(16, "O-O",   "e8g8", False,  55,   50,   5, "",        "O-O", False, False, []),
            MoveData(17, "h3",    "h2h3", True,   50,   60,   0, "best",    "h3",  False, False, []),
            MoveData(18, "Na5",   "c6a5", False,  60,  180, 140, "blunder", "Nb8", False, False, []),
        ]

        position = chess.Board()
        for move in demo_moves:
            play_move(board, position, move.move_uci)
            check_glow.update(position)
            badge = board_annotation.update(move.move_uci, move_mark(move, {}))

            self.play(eval_bar.set_evaluation(move.eval_after),
                      *[badge] if badge else [], run_time=0.3)
            self.play(move_list.add_move(move), run_time=0.3)
            self.play(analysis_box.update(move), run_time=0.3)
            self.wait(1.3)

        self.wait(2)


# =============================================================================
# Command Line Interface
# =============================================================================

if __name__ == "__main__":
    print("Chess Game Animator")
    print("=" * 50)
    print()
    print("Scenes available:")
    print("  AnimatedGame  — full game animation")
    print("                  (needs CHESS_ANIMATOR_CONFIG env var)")
    print("  QuickDemo     — self-contained demo, no files needed")
    print()
    print("Run via Manim:")
    print("  manim -pql animator_game.py QuickDemo")
    print("  CHESS_ANIMATOR_CONFIG=my_config.json manim -pql animator_game.py AnimatedGame")
    print()
    print("Or analyze and render a game in one step:")
    print("  python run_animator.py my_game --analyze")
    print()
    print("Config JSON format:")
    print('  {"pgn_path": "game.pgn",')
    print('   "analysis_path": "game_analysis.json",')
    print('   "comments_path": "game_notes.txt",')
    print('   "stockfish_path": null}')
