"""
run_animator.py

CLI coordinator for the chess game video animator.
Writes a small JSON config file, sets CHESS_ANIMATOR_CONFIG in the
environment, then delegates to Manim.

Usage:
    python run_animator.py <game_id> [options]

    <game_id> is the base filename without extension.  The script looks for:
        {game_id}.pgn              — required for live analysis fallback
        {game_id}_analysis.json   — pre-computed analysis (preferred)
        {game_id}_notes.txt       — optional human commentary

    If none of those files exist the script exits with a clear error rather
    than letting Manim fail cryptically.

Options:
    --quality   low | medium | high | ultra   (default: medium, 720p)
                Maps to Manim's -pql / -pqm / -pqh / -pqk flags.
    --scene     Manim scene class name         (default: AnimatedGame)
    --no-preview                               Don't open the video after render.
    --analyze   Run Stockfish analysis first, saving {game_id}_analysis.json,
                then animate.  Requires chess_game_analyzer.py on the path.
    --depth N   Stockfish search depth for --analyze  (default: 20)
    --time-limit SECONDS
                Stop each search after this long even if depth N isn't
                reached; speeds up slow machines (default: no limit)
    --threads N CPU threads for Stockfish  (default: 1, or all cores but
                one with --time-limit, where extra threads help)
    --hash MB   Stockfish hash table size  (default: 256)
    --lines N   Lines Stockfish searches before each move (default: 3);
                1 is several times faster, but loses the alternative
                moves and makes evals somewhat less accurate
    --stockfish PATH  Path to Stockfish binary  (default: auto-detect)

Examples:
    # 720p render (default quality)
    python run_animator.py sample_game

    # High-quality final render
    python run_animator.py sample_game --quality high

    # Analyze then animate in one step
    python run_animator.py sample_game --analyze --depth 22

    # Deep analysis, but at most 2 seconds per position
    python run_animator.py sample_game --analyze --depth 24 --time-limit 2

    # Render the QuickDemo scene (no game files needed)
    python run_animator.py --scene QuickDemo
"""

import argparse
import json
import os
import subprocess
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Optional

from chess_game_analyzer import (ANALYSIS_LINES, EnhancedGameAnalyzer, ProgressLine,
                                 positive_int)


# ---------------------------------------------------------------------------
# Quality flag mapping
# ---------------------------------------------------------------------------

QUALITY_FLAGS = {
    "low":   "-pql",
    "medium": "-pqm",
    "high":  "-pqh",
    "ultra": "-pqk",
}


# ---------------------------------------------------------------------------
# Analysis helper
# ---------------------------------------------------------------------------

def format_search_summary(moves: list, engine: dict) -> str:
    """How deep the searches actually got, and the engine settings used."""
    def spread(depths):
        depths = [d for d in depths if d]   # 0 = nothing to search (e.g. mate)
        if not depths:
            return "none"
        if min(depths) == max(depths):
            return str(depths[0])
        return f"{min(depths)}–{max(depths)}, average {round(sum(depths) / len(depths))},"

    before = spread(m["search_depth"] for m in moves)
    after = spread(m["search_depth_after"] for m in moves)
    threads = engine["threads"]
    return (f"Depth reached (asked for {engine['depth']}): {before} before each "
            f"move, {after} after it ({engine['lines']} lines). "
            f"{threads} thread{'s' if threads != 1 else ''}, {engine['hash_mb']} MB hash.")


def run_analysis(pgn_path: Path, output_path: Path,
                 stockfish: Optional[str], depth: int,
                 time_limit: Optional[float] = None,
                 threads: Optional[int] = None,
                 hash_mb: Optional[int] = None,
                 lines: int = ANALYSIS_LINES) -> bool:
    """
    Run chess_game_analyzer on pgn_path and save JSON to output_path.
    Returns True on success.

    Deliberately does NOT import anything from animator_game so that
    manim / manim_chess are never touched during the analysis step.
    """
    cap = f", max {time_limit:g}s per position" if time_limit else ""
    print(f"Running Stockfish analysis (depth {depth}{cap}) on {pgn_path} …")

    progress = ProgressLine()
    try:
        with EnhancedGameAnalyzer(stockfish, depth, time_limit,
                                  threads=threads, hash_mb=hash_mb,
                                  lines=lines) as analyzer:
            result = analyzer.analyze_game(str(pgn_path), progress=progress)
    except Exception as exc:
        progress.finish()   # end the progress line before the error
        print(f"Error during analysis: {exc}")
        return False
    finally:
        progress.finish()

    try:
        # Every field the analyzer records; the animator ignores ones it doesn't use
        moves_out = [asdict(m) for m in result.moves]

        data = {
            "white":        result.white,
            "black":        result.black,
            "white_elo":    str(result.white_elo or ""),
            "black_elo":    str(result.black_elo or ""),
            "event":        result.event or "",
            "site":         result.site or "",
            "date":         result.date or "",
            "round_num":    result.round_num or "",
            "result":       result.result or "",
            "opening_name": result.opening_name or "",
            "opening_eco":  result.opening_eco or "",
            "moves":        moves_out,
            "white_stats":  {"accuracy": result.white_stats.get("accuracy", 0.0)},
            "black_stats":  {"accuracy": result.black_stats.get("accuracy", 0.0)},
            "engine": {
                "name":       analyzer.engine_version,
                "depth":      depth,
                "time_limit": time_limit,
                "lines":      analyzer.lines,
                "threads":    analyzer.threads,
                "hash_mb":    analyzer.hash_mb,
            },
        }

        output_path.write_text(json.dumps(data, indent=2))
        print(format_search_summary(moves_out, data["engine"]))
        print(f"Analysis saved to {output_path}")
        return True

    except Exception as exc:
        print(f"Error saving analysis JSON: {exc}")
        return False


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Render a chess game animation via Manim.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    parser.add_argument(
        "game_id", nargs="?", default=None,
        help="Base filename without extension (e.g. 'my_game').",
    )
    parser.add_argument(
        "--quality", choices=QUALITY_FLAGS.keys(), default="medium",
        help="Render quality (default: medium, 720p).",
    )
    parser.add_argument(
        "--scene", default="AnimatedGame",
        help="Manim scene class to render (default: AnimatedGame).",
    )
    parser.add_argument(
        "--no-preview", action="store_true",
        help="Don't open the video after rendering.",
    )
    parser.add_argument(
        "--analyze", action="store_true",
        help="Run Stockfish analysis before animating.",
    )
    parser.add_argument(
        "--depth", type=int, default=20,
        help="Stockfish depth for --analyze (default: 20).",
    )
    parser.add_argument(
        "--time-limit", type=float, default=None, metavar="SECONDS",
        help="Stop each Stockfish search after this many seconds, even if "
             "--depth isn't reached yet (default: no limit).",
    )
    parser.add_argument(
        "--threads", type=positive_int, default=None, metavar="N",
        help="CPU threads for Stockfish (default: 1, or all cores but one "
             "with --time-limit).",
    )
    parser.add_argument(
        "--lines", type=positive_int, default=ANALYSIS_LINES, metavar="N",
        help="Lines (MultiPV) Stockfish searches before each move: the best "
             "move plus alternatives (default: 3). 1 is several times faster, "
             "but loses the alternatives and makes evals somewhat less accurate.",
    )
    parser.add_argument(
        "--hash", type=positive_int, default=None, metavar="MB", dest="hash_mb",
        help="Stockfish hash table size in MB (default: 256).",
    )
    parser.add_argument(
        "--stockfish", default=None,
        help="Path to Stockfish binary (default: auto-detect via STOCKFISH_PATH "
             "or PATH).",
    )

    args = parser.parse_args()

    # ------------------------------------------------------------------
    # Special case: scene that needs no game files (e.g. QuickDemo)
    # ------------------------------------------------------------------
    if args.scene != "AnimatedGame":
        quality_flag = QUALITY_FLAGS[args.quality]
        if args.no_preview:
            quality_flag = quality_flag.replace("-p", "-")  # drop preview flag
        cmd = ["manim", quality_flag, "animator_game.py", args.scene]
        print(f"Running: {' '.join(cmd)}")
        sys.exit(subprocess.run(cmd).returncode)

    # ------------------------------------------------------------------
    # AnimatedGame requires a game_id
    # ------------------------------------------------------------------
    if not args.game_id:
        parser.error("game_id is required when rendering AnimatedGame.")

    game_id = args.game_id
    pgn_path      = Path(f"{game_id}.pgn")
    analysis_path = Path(f"{game_id}_analysis.json")
    notes_path    = Path(f"{game_id}_notes.txt")

    # ------------------------------------------------------------------
    # Optional: run analysis first
    # ------------------------------------------------------------------
    if args.analyze:
        if not pgn_path.exists():
            print(f"Error: {pgn_path} not found — cannot run analysis.")
            sys.exit(1)
        ok = run_analysis(pgn_path, analysis_path, args.stockfish, args.depth,
                          time_limit=args.time_limit, threads=args.threads,
                          hash_mb=args.hash_mb, lines=args.lines)
        if not ok:
            sys.exit(1)

    # ------------------------------------------------------------------
    # Validate that at least one data source exists
    # ------------------------------------------------------------------
    has_analysis = analysis_path.exists()
    has_pgn      = pgn_path.exists()

    if not has_analysis and not has_pgn:
        print(f"Error: neither {analysis_path} nor {pgn_path} found.")
        print("       Run with --analyze to generate the analysis JSON first,")
        print("       or place the PGN in the current directory.")
        sys.exit(1)

    if not has_analysis:
        print(f"Note: {analysis_path} not found — AnimatedGame will run live "
              f"Stockfish analysis from {pgn_path}.")
        print("      This is slow. Consider running with --analyze first.")

    # ------------------------------------------------------------------
    # Write the config JSON and set the environment variable
    # ------------------------------------------------------------------
    config = {
        "pgn_path":      str(pgn_path)      if has_pgn      else None,
        "analysis_path": str(analysis_path) if has_analysis else None,
        "comments_path": str(notes_path)    if notes_path.exists() else None,
        "stockfish_path": args.stockfish,
    }

    config_file = Path(f"{game_id}_animator_config.json")
    config_file.write_text(json.dumps(config, indent=2))
    print(f"Config written to {config_file}")

    # Pass the config path to AnimatedGame via environment variable
    env = os.environ.copy()
    env["CHESS_ANIMATOR_CONFIG"] = str(config_file)

    # ------------------------------------------------------------------
    # Build and run the Manim command
    # ------------------------------------------------------------------
    quality_flag = QUALITY_FLAGS[args.quality]
    if args.no_preview:
        quality_flag = quality_flag.replace("-p", "-")

    cmd = ["manim", quality_flag, "animator_game.py", args.scene]
    print(f"Running: {' '.join(cmd)}")
    print(f"  CHESS_ANIMATOR_CONFIG={config_file}")
    print()

    # Ctrl+C reaches manim too, which stops on its own ("Aborted!"); exit
    # with the usual status for an interrupt rather than a traceback
    try:
        returncode = subprocess.run(cmd, env=env).returncode
    except KeyboardInterrupt:
        returncode = 130
    finally:
        # Clean up the ephemeral config file
        try:
            config_file.unlink()
        except OSError:
            pass  # non-fatal

    sys.exit(returncode)


if __name__ == "__main__":
    main()
