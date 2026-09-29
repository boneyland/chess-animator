"""
run_animator.py

CLI coordinator for the chess game video animator.
Writes a small JSON config file, sets CHESS_ANIMATOR_CONFIG in the
environment, then delegates to Manim.  Run with --help for the options.
"""

import argparse
import json
import os
import statistics
import subprocess
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Optional

from chess_game_analyzer import (VIDEO_LINES, VIDEO_TIME_LIMIT, EnhancedGameAnalyzer,
                                 ProgressLine, describe_search, positive_int,
                                 search_depth, video_search)


HELP_EPILOG = """\
Files, for a game_id:
    {game_id}.pgn             — the game: moves for --analyze, headers,
                                commentary and move marks for the video
    {game_id}_analysis.json   — Stockfish's analysis, written by --analyze
    {game_id}_notes.txt       — optional commentary (see the README)

    With neither the PGN nor the analysis the script exits with an error.
    With a PGN but no analysis, the video analyzes it live, which is slow.

Examples:
    # 720p render (default quality)
    python run_animator.py sample_game

    # High-quality final render
    python run_animator.py sample_game --quality high

    # Save as byrne_fischer.mp4 instead of AnimatedGame.mp4
    python run_animator.py sample_game --output byrne_fischer

    # Analyze then animate in one step (4 seconds per position)
    python run_animator.py sample_game --analyze

    # 10 seconds per position, as deep as that gets
    python run_animator.py sample_game --analyze --time-limit 10

    # Depth 20 on 1 thread: the same analysis on every run
    python run_animator.py sample_game --analyze --depth 20

    # Render the QuickDemo scene (no game files needed)
    python run_animator.py --scene QuickDemo
"""

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
        # The median, as a forced mate is searched to Stockfish's maximum (245)
        return f"{min(depths)}–{max(depths)}, median {round(statistics.median(depths))},"

    before = spread(m["search_depth"] for m in moves)
    after = spread(m["search_depth_after"] for m in moves)
    threads = engine["threads"]
    asked = (f"asked for {engine['depth']}" if engine["depth"] is not None
             else f"{engine['time_limit']:g}s per position")
    return (f"Depth reached ({asked}): {before} before each "
            f"move, {after} after it ({engine['lines']} line{'s' if engine['lines'] != 1 else ''}). "
            f"{threads} thread{'s' if threads != 1 else ''}, {engine['hash_mb']} MB hash.")


def run_analysis(pgn_path: Path, output_path: Path,
                 stockfish: Optional[str], depth: Optional[int],
                 time_limit: Optional[float] = None,
                 threads: Optional[int] = None,
                 hash_mb: Optional[int] = None,
                 lines: int = VIDEO_LINES) -> bool:
    """
    Run chess_game_analyzer on pgn_path and save JSON to output_path; with
    neither depth nor time_limit, each position is searched for
    VIDEO_TIME_LIMIT seconds (see video_search).  Returns True on success.

    Deliberately does NOT import anything from animator_game so that
    manim / manim_chess are never touched during the analysis step.
    """
    depth, time_limit = video_search(depth, time_limit)
    search = describe_search(search_depth(depth, time_limit), time_limit)
    print(f"Running Stockfish analysis ({search}) on {pgn_path} …")

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
                "depth":      analyzer.depth,
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

def manim_command(quality_flag: str, args) -> list:
    """The manim command line for args.scene, named by --output if given."""
    cmd = ["manim", quality_flag, "animator_game.py", args.scene]
    if args.output:
        cmd += ["-o", args.output]
    return cmd


def main():
    parser = argparse.ArgumentParser(
        description="Render a chess game animation via Manim.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=HELP_EPILOG,
    )

    parser.add_argument(
        "game_id", nargs="?", default=None,
        help="Base filename without extension (e.g. 'my_game').",
    )
    parser.add_argument(
        "-q", "--quality", choices=QUALITY_FLAGS.keys(), default="medium",
        help="Render quality (default: medium, 720p).",
    )
    parser.add_argument(
        "-S", "--scene", default="AnimatedGame",
        help="Manim scene class to render (default: AnimatedGame).",
    )
    parser.add_argument(
        "-n", "--no-preview", action="store_true",
        help="Don't open the video after rendering.",
    )
    parser.add_argument(
        "-o", "--output", default=None, metavar="NAME",
        help="File name for the video, saved in Manim's usual video folder "
             "(default: the scene name, e.g. AnimatedGame.mp4).",
    )
    parser.add_argument(
        "-a", "--analyze", action="store_true",
        help="Run Stockfish analysis before animating.",
    )
    parser.add_argument(
        "-t", "--time-limit", type=float, default=None, metavar="SECONDS",
        help="Seconds Stockfish searches each position for --analyze, going as "
             f"deep as that allows (default: {VIDEO_TIME_LIMIT:g}).",
    )
    parser.add_argument(
        "-d", "--depth", type=int, default=None,
        help="Search to this depth instead. With --time-limit as well, each "
             "search stops at whichever comes first; alone, on 1 thread, it "
             "gives the same result on every run.",
    )
    parser.add_argument(
        "-j", "--threads", type=positive_int, default=None, metavar="N",
        help="CPU threads for Stockfish (default: all cores but one with a "
             "time limit, 1 for a depth alone).",
    )
    parser.add_argument(
        "-l", "--lines", type=positive_int, default=VIDEO_LINES, metavar="N",
        help=f"Lines (MultiPV) Stockfish searches in each position (default: "
             f"{VIDEO_LINES}, the best line, which is all the video shows). More "
             "lines make a multi-threaded search much shallower.",
    )
    parser.add_argument(
        "-m", "--hash", type=positive_int, default=None, metavar="MB", dest="hash_mb",
        help="Stockfish hash table size in MB (default: 256).",
    )
    parser.add_argument(
        "-s", "--stockfish", default=None,
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
        cmd = manim_command(quality_flag, args)
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

    cmd = manim_command(quality_flag, args)
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
