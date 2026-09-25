# Chess Animator

## Commands
- `.venv/bin/python -m unittest discover tests` - test suite (unittest, no pytest; system python has no manim)
- `PATH=.venv/bin:$PATH python run_animator.py sample_game --no-preview` - render; run_animator calls `manim` from PATH
- `PATH=.venv/bin:$PATH python run_animator.py sample_game --analyze` - regenerate `sample_game_analysis.json` (depth 20, 1 thread: ~4 min)
- `.venv/bin/manim -ql -s animator_initial_frame.py LayoutDebug` - still of the frame layout; `animator_metrics.py MetricsDebug` for the eval plot
- `ffmpeg -ss T -i media/videos/animator_game/480p15/AnimatedGame.mp4 -frames:v 1 f.png` - check a render; ply N starts at ~5.6 s + Σ(0.4 + hold), hold = max(1.2, len(comment)/15)
- `python chess_game_analyzer.py game.pgn -o x.tex [--book]` - LaTeX report (no LaTeX installed here, so it can't be compiled; check structure only)

## Gotchas
- Everything shown about a move comes from Stockfish; board-counting metrics (space/mobility/king safety/FTI) were deliberately removed, don't reintroduce them
- Fixed-depth search: 1 thread is fastest (7 threads measured up to 30x slower); threads only help with `--time-limit`. Benchmark before changing engine defaults
- Header/title/end card read from the PGN; re-run `--analyze` only when the moves change
- Fonts are Courier New (monospace): text capacity comes from `char_width()`; Manim `Text` drops leading spaces from its width, so move-list rows are anchored on an invisible `|`
- `chess_plotting.py` doesn't exist; the report has no plots
- `sample_game.pgn` is annotated Byrne–Fischer 1956; commentary comes from PGN comments/NAGs plus `{game}_notes.txt` (notes file wins)
