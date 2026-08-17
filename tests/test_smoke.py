from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from bms.manifests import validate_run_manifest

REPO_ROOT = Path(__file__).resolve().parents[1]


class SmokeTests(unittest.TestCase):
    def test_cli_smoke_passes_and_writes_valid_run_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "smoke-run.json"
            result = subprocess.run(
                [sys.executable, "-m", "bms", "smoke", "--output", str(output)],
                cwd=REPO_ROOT,
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, msg=result.stderr)
            self.assertIn("SMOKE PASS", result.stdout)
            data = json.loads(output.read_text(encoding="utf-8"))
            validate_run_manifest(data)


if __name__ == "__main__":
    unittest.main()
