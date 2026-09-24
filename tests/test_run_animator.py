"""
Tests for the run_animator.py command line.

Run from the repository root:
    python -m unittest discover tests
"""

import subprocess
import sys
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


if __name__ == "__main__":
    unittest.main()
