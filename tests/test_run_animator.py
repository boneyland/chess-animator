"""
Tests for the run_animator.py command line.

Run from the repository root:
    python -m unittest discover tests
"""

import contextlib
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


if __name__ == "__main__":
    unittest.main()
