"""
Tests for the run_animator.py command line.

Run from the repository root:
    python -m unittest discover tests
"""

import os
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
        with tempfile.TemporaryDirectory() as tmp, \
             mock.patch.object(sys, "argv", ["run_animator.py", "game", "--no-preview"]), \
             mock.patch.object(run_animator.subprocess, "run", side_effect=KeyboardInterrupt), \
             mock.patch("builtins.print"):
            cwd = os.getcwd()
            os.chdir(tmp)
            self.addCleanup(os.chdir, cwd)
            Path("game.pgn").write_text("1. e4 *\n")
            with self.assertRaises(SystemExit) as cm:
                run_animator.main()
            self.assertEqual(cm.exception.code, 130)
            self.assertFalse(Path("game_animator_config.json").exists())


if __name__ == "__main__":
    unittest.main()
