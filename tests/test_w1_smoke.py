from __future__ import annotations

import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from bms.control_events import read_control_event
from bms.manifests import validate_w1_run_manifest
from bms.persistence import connect_database
from bms.storage import read_evidence, read_raw_observation
from bms.w1_smoke import W1SmokeError, compare_replays, run_w1_smoke

REPO_ROOT = Path(__file__).resolve().parents[1]
EXPECTED_TABLES = {
    "schema_migrations",
    "evidence_artifact",
    "raw_observation",
    "control_event",
}


class W1SmokeTests(unittest.TestCase):
    def output_path(self, temporary_directory: str, name: str = "w1-evidence") -> Path:
        return Path(temporary_directory) / name

    def load_json(self, path: Path):
        return json.loads(path.read_text(encoding="utf-8"))

    def load_run_result(self, output: Path, replay: str):
        replay_dir = output / replay
        return {
            "run_manifest": self.load_json(replay_dir / "run-manifest.json"),
            "smoke_report": self.load_json(replay_dir / "smoke-report.json"),
            "artifact_sample": self.load_json(replay_dir / "artifact-sample.json"),
        }

    def test_c4_t01_cli_creates_fresh_full_setup(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output = self.output_path(tmp)
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "bms",
                    "w1-smoke",
                    "--output-dir",
                    str(output),
                ],
                cwd=REPO_ROOT,
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, msg=result.stderr)
            self.assertIn("W1 SMOKE PASS", result.stdout)
            for replay in ("replay-a", "replay-b"):
                self.assertTrue((output / replay / "w1-smoke.sqlite3").is_file())
                manifest = self.load_json(output / replay / "run-manifest.json")
                self.assertEqual(
                    [
                        item["migration_id"]
                        for item in manifest["database_schema"]["applied_migrations"]
                    ],
                    ["0001_raw_evidence", "0002_control_event"],
                )

    def test_c4_t02_integrated_evidence_raw_control_run_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output = self.output_path(tmp)
            run_w1_smoke(output, repo_root=REPO_ROOT)
            manifest = self.load_json(output / "replay-a/run-manifest.json")
            connection = connect_database(output / "replay-a/w1-smoke.sqlite3")
            try:
                evidence = read_evidence(
                    connection, manifest["artifacts"]["evidence_id"]
                )
                raw = read_raw_observation(
                    connection, manifest["artifacts"]["raw_record_id"]
                )
                control = read_control_event(
                    connection, manifest["artifacts"]["control_event_id"]
                )
                self.assertEqual(raw.raw_payload_ref, evidence.evidence_id)
                self.assertEqual(raw.run_id, manifest["run_id"])
                self.assertEqual(evidence.run_id, manifest["run_id"])
                self.assertEqual(control.evidence_ref, evidence.evidence_id)
                self.assertEqual(
                    read_evidence(connection, control.evidence_ref).run_id,
                    manifest["run_id"],
                )
                self.assertNotIn(manifest["run_id"], control.trace_refs)
            finally:
                connection.close()

    def test_c4_t03_w1_run_manifest_is_complete_and_w1_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output = self.output_path(tmp)
            run_w1_smoke(output, repo_root=REPO_ROOT)
            manifest = self.load_json(output / "replay-a/run-manifest.json")
            validate_w1_run_manifest(manifest)
            self.assertEqual(
                set(manifest),
                {
                    "schema",
                    "schema_version",
                    "run_id",
                    "run_at",
                    "execution_status",
                    "git_commit",
                    "git_dirty",
                    "specification_manifest",
                    "specification_manifest_sha256",
                    "python_version",
                    "sqlite_version",
                    "persistence_backend",
                    "database_schema",
                    "artifacts",
                },
            )
            self.assertEqual(manifest["database_schema"]["latest_migration"], "0002_control_event")
            self.assertEqual(
                set(manifest["artifacts"]),
                {"evidence_id", "raw_record_id", "control_event_id"},
            )
            forbidden_fields = {
                "mapping_version",
                "ssot_version",
                "monitoring_version",
                "model_version",
                "policy_version",
                "snapshot",
                "manager_decision",
                "result_version",
                "evaluation_version",
            }
            self.assertTrue(forbidden_fields.isdisjoint(manifest))

    def test_c4_t04_manifest_reports_actual_git_commit_and_dirty_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output = self.output_path(tmp)
            run_w1_smoke(output, repo_root=REPO_ROOT)
            manifest = self.load_json(output / "replay-a/run-manifest.json")
            commit = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=REPO_ROOT,
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
            dirty = bool(
                subprocess.run(
                    ["git", "status", "--porcelain"],
                    cwd=REPO_ROOT,
                    check=True,
                    capture_output=True,
                    text=True,
                ).stdout.strip()
            )
            self.assertEqual(manifest["git_commit"], commit)
            self.assertEqual(manifest["git_dirty"], dirty)

    def test_c4_t05_two_isolated_fresh_replays_pass(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output = self.output_path(tmp)
            result = run_w1_smoke(output, repo_root=REPO_ROOT)
            self.assertEqual(result["status"], "PASS")
            first_db = output / "replay-a/w1-smoke.sqlite3"
            second_db = output / "replay-b/w1-smoke.sqlite3"
            self.assertNotEqual(first_db, second_db)
            self.assertEqual(
                self.load_json(output / "replay-a/smoke-report.json")["status"],
                "PASS",
            )
            self.assertEqual(
                self.load_json(output / "replay-b/smoke-report.json")["status"],
                "PASS",
            )
            rebuild = self.load_json(output / "fresh-rebuild-report.json")
            self.assertEqual(rebuild["status"], "PASS")
            self.assertTrue(rebuild["independent_database_paths"])
            self.assertTrue(all(not item["existed_before"] for item in rebuild["databases"]))

    def test_c4_t06_replay_comparison_passes_and_detects_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output = self.output_path(tmp)
            run_w1_smoke(output, repo_root=REPO_ROOT)
            first = self.load_run_result(output, "replay-a")
            second = self.load_run_result(output, "replay-b")
            self.assertEqual(compare_replays(first, second)["status"], "PASS")

            changed = copy.deepcopy(second)
            changed["smoke_report"]["fixture"]["content_sha256"] = "0" * 64
            comparison = compare_replays(first, changed)
            self.assertEqual(comparison["status"], "FAIL")
            self.assertTrue(comparison["differences"])
            self.assertIn("content_sha256", comparison["differences"][0]["path"])

    def test_c4_t07_c1_c3_foundation_remains_present(self) -> None:
        self.assertTrue((REPO_ROOT / "bms/persistence.py").is_file())
        self.assertTrue((REPO_ROOT / "bms/storage.py").is_file())
        self.assertTrue((REPO_ROOT / "bms/control_events.py").is_file())
        self.assertTrue((REPO_ROOT / "migrations/0001_raw_evidence.sql").is_file())
        self.assertTrue((REPO_ROOT / "migrations/0002_control_event.sql").is_file())

    def test_c4_t08_scope_guard_is_exact(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output = self.output_path(tmp)
            run_w1_smoke(output, repo_root=REPO_ROOT)
            scope = self.load_json(output / "scope-guard.json")
            self.assertEqual(scope["status"], "PASS")
            for replay in ("replay_a", "replay_b"):
                self.assertEqual(
                    set(scope[replay]["productive_tables"]), EXPECTED_TABLES
                )
                self.assertEqual(
                    scope[replay]["productive_migrations"],
                    ["0001_raw_evidence.sql", "0002_control_event.sql"],
                )
                self.assertEqual(scope[replay]["forbidden_modules_present"], [])

    def test_c4_t09_uses_only_stdlib_sqlite_and_no_external_runtime(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output = self.output_path(tmp)
            run_w1_smoke(output, repo_root=REPO_ROOT)
            scope = self.load_json(output / "scope-guard.json")["replay_a"]
            self.assertTrue(scope["checks"]["stdlib_only"])
            self.assertTrue(scope["checks"]["network_imports_absent"])
            self.assertTrue(scope["checks"]["docker_artifacts_absent"])
            self.assertTrue(scope["checks"]["sqlite_backend_only"])
            self.assertEqual(scope["declared_dependencies"], [])
            self.assertEqual(scope["persistence_backend"], "sqlite")

    def test_c4_t10_stale_database_is_not_deleted_or_reused(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output = self.output_path(tmp)
            replay_dir = output / "replay-a"
            replay_dir.mkdir(parents=True)
            stale_database = replay_dir / "w1-smoke.sqlite3"
            stale_database.write_bytes(b"stale-database-marker")
            with self.assertRaisesRegex(W1SmokeError, "will not be reused"):
                run_w1_smoke(output, repo_root=REPO_ROOT)
            self.assertEqual(stale_database.read_bytes(), b"stale-database-marker")


if __name__ == "__main__":
    unittest.main()
