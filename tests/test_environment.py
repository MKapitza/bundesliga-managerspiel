from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


class EnvironmentTests(unittest.TestCase):
    def test_python_minor_version_matches_i1_environment(self) -> None:
        self.assertEqual(
            sys.version_info[:2],
            (3, 13),
            msg=f"Python 3.13 required, got {sys.version.split()[0]}",
        )

    def test_git_repository_is_available(self) -> None:
        result = subprocess.run(
            ["git", "rev-parse", "--is-inside-work-tree"],
            cwd=REPO_ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertEqual(result.stdout.strip(), "true")


if __name__ == "__main__":
    unittest.main()
