# Chess Game Animator

A Python pipeline that turns a PGN chess game into an annotated video using [Manim](https://www.manim.community/). Each move is animated on a live board alongside a Stockfish evaluation bar, a scrolling move list, a commentary panel, and a four-plot metrics strip showing positional trends across the whole game.

---

## Example Output

Rendered games are on [this YouTube playlist](https://www.youtube.com/watch?v=hScw3EaoxNk&list=PLSwHwWPf_04RVNjMkisroM9gFSEWDFMP4).

Each frame is laid out like this:

```
┌─────────────────────────────────────────────────────────┐
│  Eval │                    │  Header (players, event)   │
│  Bar  │   Chess Board      │  Move List                 │
│       │                    │  Commentary / Analysis     │
├─────────────────────────────────────────────────────────┤
│ Eval win chance │  Space  │  Mobility  │  King Safety  │
└─────────────────────────────────────────────────────────┘
```

- **Eval bar:** Stockfish's evaluation, shown as a number, as `M3` for a forced mate, or as `1-0` / `0-1` at checkmate. The fill uses Lichess's win-probability curve, so a big advantage fills most of the bar but only a forced mate fills all of it.
- **Move list:** scrolls as the game goes on. Each move is colored by quality, for example red for blunders and teal for brilliant moves.
- **Commentary:** your own notes if you've written any (see [Adding Your Own Commentary](#adding-your-own-commentary)), otherwise the engine's annotation.
- **Metrics strip:** four plots that extend by one point per move. Eval shows White's win chance from -1 to +1. Space, Mobility and King Safety scale to the range the game actually covers, and that range is printed next to each title.

Each move stays on screen for about 1.6 seconds.

---

## Requirements

| Dependency | Notes |
|---|---|
| Python 3.10+ | |
| [Manim Community](https://www.manim.community/) v0.20+ | `pip install manim` |
| [manim-chess](https://github.com/swoyer2/manim-chess) | Provides `Board` and `EvaluationBar` |
| [python-chess](https://python-chess.readthedocs.io/) | `pip install chess` |
| [Stockfish](https://stockfishchess.org/download/) | Binary on your system |

Install Python dependencies:

```bash
pip install manim chess
# install manim-chess per its own instructions
```

---

## File Overview

| File | Purpose |
|---|---|
| `run_animator.py` | **Start here.** CLI entry point — runs analysis and/or Manim. |
| `animator_game.py` | Main Manim scene (`AnimatedGame`). Move loop, panels, metrics. |
| `animator_layout.py` | All geometry constants, colors, and fonts in one place. |
| `animator_initial_frame.py` | Initial frame scene and `GameInfo` dataclass. |
| `animator_metrics.py` | Four-plot metrics strip (Eval, Space, Mobility, King Safety). |
| `chess_game_analyzer.py` | Stockfish wrapper — produces per-move positional metrics. |
| `convert_script_to_comment_dict.py` | Reads commentary from a `[KEY]` notes file and from PGN comments and move marks. |
| `evaluation_bar.py` | `EvaluationBar` Mobject (part of manim-chess). |

---

## Quick Start

The repository includes `sample_game.pgn` — Caruana vs. Nepomniachtchi, Round 5 of the 2024 Candidates Tournament (Toronto), an Italian Game ending in a draw by repetition after 32 moves. All examples below use this file.

### 1. Analyze and animate in one step

```bash
python run_animator.py sample_game --analyze --depth 20
```

This runs Stockfish at depth 20, saves `sample_game_analysis.json`, then renders a low-quality preview video. The `--analyze` flag is only needed the first time; subsequent renders reuse the saved JSON. While the analysis runs, a progress line shows how many moves are done and an estimate of the time left:

```
Analyzing move 23/63 (36%) · 1:12 elapsed · ~2:05 left
```

### 2. Re-render without re-analyzing

```bash
python run_animator.py sample_game
```

### 3. Quality and resolution

Manim's quality flag controls both resolution and frame rate together:

| Flag | Resolution | FPS | Use case |
|---|---|---|---|
| `--quality low` | 854 × 480 | 15 | Fast preview during development |
| `--quality medium` | 1280 × 720 | 30 | Draft review |
| `--quality high` | 1920 × 1080 | 60 | Final YouTube/Vimeo upload |
| `--quality ultra` | 3840 × 2160 | 60 | 4K archival render |

```bash
# Fast preview (default)
python run_animator.py sample_game --quality low

# 1080p final render, no auto-open
python run_animator.py sample_game --quality high --no-preview

# 4K archival render (slow — allow 30–60 min on a typical machine)
python run_animator.py sample_game --quality ultra --no-preview
```

### 4. Stockfish location

```bash
python run_animator.py sample_game --analyze --depth 22 \
    --stockfish /opt/homebrew/bin/stockfish
```

By default Stockfish is found automatically in this order: the `STOCKFISH_PATH` environment variable if set, then `stockfish` on your `PATH`, then any `stockfish*` executable on your `PATH` (so official release names like `stockfish-ubuntu-x86-64-avx2` work unrenamed). If Stockfish isn't on your `PATH`, set `STOCKFISH_PATH` or pass `--stockfish`.

### 5. Your own game

Replace `sample_game` with any base filename. The script looks for `{name}.pgn`, `{name}_analysis.json`, and optionally `{name}_notes.txt` in the current directory:

```bash
python run_animator.py my_game --analyze --depth 20
```

---

## Adding Your Own Commentary

There are two ways to add commentary, and you can use both.

### In the PGN

Comments in curly braces after a move are shown in the commentary panel when that move is played. A comment before the first move is shown on the title card. Move marks (`!`, `?`, `!!`, `??`, `!?`, `?!`) replace the engine's symbol for that move in the move list:

```
{Fischer, aged 13, against one of America's leading masters.}
1. Nf3 Nf6 2. c4 g6 ... 11. Bg5? {Moving the same piece twice.} 11... Na4!!
```

Only the main line is read; side variations are ignored. Clock and eval tags from Lichess or Chess.com exports, such as `[%clk 0:03:00]`, are ignored too, so downloaded games work as-is.

### In a notes file

Create a plain text file named `sample_game_notes.txt` (or `{game_id}_notes.txt` for your own game) in the same directory. Each entry is a ply number in square brackets — where ply 1 = White's first move, ply 2 = Black's first move, and so on — followed by your comment:

```
[1] Caruana opens with the King's Pawn, staking a central claim immediately.

[10] The Italian Game — one of the oldest and most deeply analyzed openings in chess.

[23] A key moment: after the exchange on e3, White's rook structure becomes more active.

[47] Repetition begins. White has a slight edge but Black holds the balance.
```

If the notes file and the PGN both have a comment for the same move, the notes file wins.

Comments are word-wrapped to fit the commentary panel, which shows 5 lines of about 30 characters. A comment that wraps to more lines is cut off, and the render prints a warning naming the move. Moves without a comment fall back to engine annotations: move classification, centipawn loss, current evaluation (or "White mates in 3" / "Checkmate - White wins"), and the best move after a mistake or blunder. Moves that create, lose, or delay a forced mate get Lichess-style mate advice instead, with the mating line the mover had, e.g. `Lost forced checkmate sequence. Mate in 2: Kg6 Kg8 Qb8#`.

---

## How the Analysis Works

`chess_game_analyzer.py` runs Stockfish on each position and also computes four positional metrics directly from the board using `python-chess`:

| Metric | What it measures |
|---|---|
| **Eval** | Stockfish evaluation, plotted as White's win-probability advantage in [-1, +1] (0 cp → 0, ±300 cp → ±0.5, forced mate → ±1) |
| **Space** | Control of central territory, weighted by piece count behind the pawn chain |
| **Mobility** | Legal moves per piece type, weighted and penalized for unsafe squares |
| **King Safety** | Pawn shield strength, king tropism, and attack units near the king |

The Eval plot uses a fixed scale, so large evals and forced mates bend toward the edge instead of being clipped. The other three plots auto-scale to the actual range of values in the game (with 15% padding) so variation is always visible regardless of the absolute values. The range is shown next to each plot title, e.g. `King Safety [-0.22, 1.7]`.

### Move classification

Moves are judged by how much they drop the mover's **winning chances** (Lichess's centipawn → win-chance curve, on a -1 to +1 scale) rather than by raw centipawn loss, so losing a pawn at +8 costs far less than losing one at 0:

| Classification | Rule |
|---|---|
| Book | Ply ≤ 12 and < 30 cp lost |
| Best | < 5 cp lost |
| Excellent | Win-chance drop < 0.04 |
| Good | < 0.10 |
| Inaccuracy | < 0.20 |
| Mistake | < 0.30 |
| Blunder | ≥ 0.30 |

Forced mates follow Lichess's rules, which override the table above:

- **Checkmate is now unavoidable** (walked into a forced mate): blunder, or mistake / inaccuracy if the mover was already losing badly (below -7 / -10 pawns).
- **Lost forced checkmate sequence** (had a forced mate, no longer does): blunder, or mistake / inaccuracy if still winning big (above +7 / +10 pawns).
- **Not the best checkmate sequence** (still mates, but more slowly): excellent.

The thresholds are constants near the top of `chess_game_analyzer.py` (`WIN_DROP_*`, `MATE_*`). Mate advice also appears in the LaTeX report.

---

## Testing Without a Game File

A `QuickDemo` scene is included that runs without any PGN or analysis file:

```bash
python run_animator.py --scene QuickDemo
# or directly:
manim -pql animator_game.py QuickDemo
```

The metrics strip can also be tested independently with synthetic sine-wave data:

```bash
manim -pql animator_metrics.py MetricsDebug
```

Unit tests for reading commentary use the standard library's `unittest`:

```bash
python -m unittest discover tests
```

---

## Customization

### Changing the eval bar sensitivity

The eval bar maps centipawns to fill with a logistic curve, `1 / (1 + e^(-k·cp))`. To change how quickly it fills, edit `ScaledEvaluationBar._SIGMOID_K` in `animator_game.py`:

```python
_SIGMOID_K = 0.00368208  # Lichess coefficient: +100 cp ≈ 59%, +400 cp ≈ 81%, +1000 cp ≈ 98%
```

A larger `k` fills the bar faster. The Eval plot has its own copy of this coefficient (`_EVAL_WIN_K` in `animator_metrics.py`), and move classification uses `WIN_CHANCES_K` in `chess_game_analyzer.py`; keep them in step if you want the bar, plot, and classifications to agree.

### Swapping the fourth metrics plot

The fourth plot is King Safety. To swap it for Threats (or FTI), edit the `_ks_w` / `_ks_b` extraction in `MetricPlotPanel.__init__` in `animator_metrics.py` and the corresponding `advance_to_move()` call. The fields available on each `MoveData` are: `space_white/black`, `mobility_white/black`, `king_safety_white/black`, `threats_white/black`, `fti1`, `fti2`, `fti3`.

### Colors and fonts

All colors and font sizes are in `animator_layout.py` — `ColorScheme` and `Typography` dataclasses at the top of the file.

---

## Data Flow

```
sample_game.pgn                          (included in repository)
    │
    ▼
chess_game_analyzer.py                   (--analyze flag, run once)
    │
    ├──► sample_game_analysis.json       (reused on subsequent renders)
    └──► sample_game_notes.txt           (optional, hand-written)

run_animator.py
    ├── writes sample_game_animator_config.json
    ├── sets CHESS_ANIMATOR_CONFIG environment variable
    └── calls: manim -pql animator_game.py AnimatedGame

AnimatedGame.construct()
    ├── loads analysis JSON  →  List[MoveData]
    ├── builds board, eval bar, header, move list, commentary, metrics strip
    └── for each move:
            animate board position
            update eval bar
            update move list (scrolling)
            update commentary
            reveal next metrics segment
```

---

## License

MIT License. See `LICENSE` for details.

---

## Author

David Joyner
