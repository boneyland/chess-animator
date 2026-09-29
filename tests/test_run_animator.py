"""
Tests for the run_animator.py command line.

Run from the repository root:
    python -m unittest discover tests
"""

import contextlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import run_animator


class SceneExitCodeTest(unittest.TestCase):

    def test_failed_scene_render_exits_with_manims_exit_code(self):
        failed = subprocess.CompletedProcess(args=[], returncode=3)
        with mock.patch.object(sys, "argv", ["run_animator.py", "--scene", "QuickDemo"]), \
             mock.patch.object(run_animator.subprocess, "run", return_value=failed), \
             mock.patch("builtins.print"):
            with self.assertRaises(SystemExit) as cm:
                run_animator.main()
        self.assertEqual(cm.exception.code, 3)

    def test_ctrl_c_during_render_exits_quietly_and_removes_the_config(self):
        # chdir out before the directory is removed: Windows can't delete the cwd
        with tempfile.TemporaryDirectory() as tmp, contextlib.chdir(tmp), \
             mock.patch.object(sys, "argv", ["run_animator.py", "game", "--no-preview"]), \
             mock.patch.object(run_animator.subprocess, "run", side_effect=KeyboardInterrupt), \
             mock.patch("builtins.print"):
            Path("game.pgn").write_text("1. e4 *\n")
            with self.assertRaises(SystemExit) as cm:
                run_animator.main()
            self.assertEqual(cm.exception.code, 130)
            self.assertFalse(Path("game_animator_config.json").exists())


class OutputNameTest(unittest.TestCase):

    def manim_command(self, argv):
        done = subprocess.CompletedProcess(args=[], returncode=0)
        with tempfile.TemporaryDirectory() as tmp, contextlib.chdir(tmp), \
             mock.patch.object(sys, "argv", ["run_animator.py", *argv]), \
             mock.patch.object(run_animator.subprocess, "run", return_value=done) as run, \
             mock.patch("builtins.print"):
            Path("game.pgn").write_text("1. e4 *\n")
            with self.assertRaises(SystemExit):
                run_animator.main()
        return run.call_args.args[0]

    def test_output_name_is_passed_to_manim(self):
        cmd = self.manim_command(["game", "--no-preview", "--output", "byrne_fischer"])
        self.assertEqual(cmd[-2:], ["-o", "byrne_fischer"])

    def test_output_name_applies_to_other_scenes(self):
        cmd = self.manim_command(["--scene", "QuickDemo", "-o", "demo"])
        self.assertEqual(cmd[-2:], ["-o", "demo"])

    def test_short_render_flags_match_the_long_ones(self):
        cmd = self.manim_command(["-S", "QuickDemo", "-q", "low", "-n", "-o", "demo"])
        self.assertEqual(cmd, ["manim", "-ql", "animator_game.py", "QuickDemo", "-o", "demo"])

    def test_no_output_name_leaves_manims_default(self):
        cmd = self.manim_command(["game", "--no-preview"])
        self.assertNotIn("-o", cmd)


TWO_GAMES = ('[White "Byrne"]\n[Black "Fischer"]\n\n1. Nf3 *\n\n'
             '[White "Kasparov"]\n[Black "Topalov"]\n\n1. e4 *\n')


class GameChoiceTest(unittest.TestCase):
    """A PGN with several games: the note, --game and the files it picks."""

    def run_main(self, argv, pgn=TWO_GAMES, files=()):
        """(exit code, printed text, config the scene was given)"""
        done = subprocess.CompletedProcess(args=[], returncode=0)
        config = {}

        def fake_manim(cmd, env):
            config.update(json.loads(Path(env["CHESS_ANIMATOR_CONFIG"]).read_text()))
            return done

        with tempfile.TemporaryDirectory() as tmp, contextlib.chdir(tmp), \
             mock.patch.object(sys, "argv", ["run_animator.py", *argv]), \
             mock.patch.object(run_animator.subprocess, "run", side_effect=fake_manim), \
             mock.patch("builtins.print") as printed:
            Path("t.pgn").write_text(pgn)
            for name in files:
                Path(name).write_text("{}")
            with self.assertRaises(SystemExit) as cm:
                run_animator.main()
        text = "\n".join(str(c.args[0]) for c in printed.call_args_list if c.args)
        return cm.exception.code, text, config

    def test_several_games_without_game_get_a_note_and_the_first(self):
        code, text, config = self.run_main(["t", "-n"])
        self.assertEqual(code, 0)
        self.assertIn("t.pgn has 2 games; animating game 1 (Byrne vs Fischer)", text)
        self.assertIn("--game N (1–2)", text)
        self.assertEqual(config["game_number"], 1)

    def test_game_picks_the_game_and_its_own_files(self):
        code, text, config = self.run_main(
            ["t", "-n", "--game", "2"],
            files=["t_analysis.json", "t_notes.txt",
                   "t_game2_analysis.json", "t_game2_notes.txt"])
        self.assertEqual(code, 0)
        self.assertIn("animating game 2 (Kasparov vs Topalov)", text)
        self.assertNotIn("--game N", text)
        self.assertEqual((config["game_number"], config["analysis_path"], config["comments_path"]),
                         (2, "t_game2_analysis.json", "t_game2_notes.txt"))

    def test_a_game_past_the_last_is_an_error(self):
        code, text, _ = self.run_main(["t", "-n", "-g", "3"])
        self.assertEqual(code, 1)
        self.assertIn("t.pgn has only 2 games; there is no game 3", text)

    def test_a_single_game_gets_no_note(self):
        code, text, _ = self.run_main(["t", "-n"], pgn="1. e4 *\n")
        self.assertEqual(code, 0)
        self.assertNotIn("games", text)


if __name__ == "__main__":
    unittest.main()
