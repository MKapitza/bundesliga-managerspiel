from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from bms.w1_ig1_evidence import (
    REQUIRED_ARTIFACTS,
    CommandResult,
    W1IG1EvidenceError,
    _prepare_output_directory,
    capture_preflight_state,
    validate_evidence,
    write_complete_evidence_index,
)


class W1IG1EvidenceTests(unittest.TestCase):
    def write_json(self, path: Path, data: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data) + "\n", encoding="utf-8")

    def valid_evidence(self, output: Path, *, dirty: bool = True) -> None:
        for relative_path in REQUIRED_ARTIFACTS:
            path = output / relative_path
            path.parent.mkdir(parents=True, exist_ok=True)
            if path.suffix == ".json":
                self.write_json(path, {})
            else:
                path.write_text("captured evidence\n", encoding="utf-8")

        self.write_json(output / "preflight-state.json", {"git_dirty": dirty})
        for relative_path in (
            "preflight-smoke-command.json",
            "final-tests-exit-code.json",
            "git-diff-check-status.json",
        ):
            self.write_json(output / relative_path, {"exit_code": 0})
        self.write_json(
            output / "w1-smoke-command.json", {"exit_code": 0, "status": "PASS"}
        )
        for relative_path in (
            "w1-smoke/migration-report.json",
            "w1-smoke/scope-guard.json",
            "w1-smoke/replay-comparison.json",
            "w1-smoke/fresh-rebuild-report.json",
            "w1-smoke/replay-a/smoke-report.json",
            "w1-smoke/replay-b/smoke-report.json",
        ):
            self.write_json(output / relative_path, {"status": "PASS"})
        self.write_json(
            output / "w1-smoke/ig1-evidence-index.json",
            {
                "status": "PASS",
                "ig1_decision": "NOT_MADE",
                "candidate_only": True,
            },
        )

    def test_complete_required_evidence_index_is_generated(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp)
            self.valid_evidence(output)
            extra_inner_artifact = output / "w1-smoke/replay-a/w1-smoke.sqlite3"
            extra_inner_artifact.write_bytes(b"sqlite fixture")

            index = write_complete_evidence_index(output)

            self.assertTrue(set(REQUIRED_ARTIFACTS).issubset(index["artifacts"]))
            self.assertIn(
                "w1-smoke/replay-a/w1-smoke.sqlite3", index["artifacts"]
            )
            self.assertEqual(index["ig1_decision"], "NOT_MADE")
            self.assertTrue(index["candidate_only"])
            self.assertTrue((output / "ig1-evidence-index.json").is_file())

    def test_missing_required_evidence_fails_validation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp)
            self.valid_evidence(output)
            (output / "preflight-smoke.json").unlink()

            validation = validate_evidence(output)

            self.assertEqual(validation["status"], "FAIL")
            self.assertIn("preflight-smoke.json", validation["missing_artifacts"])

    def test_nonzero_test_exit_status_fails_validation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp)
            self.valid_evidence(output)
            self.write_json(output / "final-tests-exit-code.json", {"exit_code": 1})

            validation = validate_evidence(output)

            self.assertEqual(validation["status"], "FAIL")
            self.assertFalse(validation["checks"]["full_test_exit_code_zero"])

    def test_nonzero_git_diff_check_status_fails_validation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp)
            self.valid_evidence(output)
            self.write_json(output / "git-diff-check-status.json", {"exit_code": 2})

            validation = validate_evidence(output)

            self.assertEqual(validation["status"], "FAIL")
            self.assertFalse(validation["checks"]["git_diff_check_exit_code_zero"])

    def test_w1_report_failure_propagates_to_validation(self) -> None:
        reports = {
            "w1-smoke/replay-comparison.json": "replay_comparison_pass",
            "w1-smoke/scope-guard.json": "scope_guard_pass",
            "w1-smoke/migration-report.json": "migration_report_pass",
        }
        for relative_path, check_name in reports.items():
            with self.subTest(relative_path=relative_path):
                with tempfile.TemporaryDirectory() as tmp:
                    output = Path(tmp)
                    self.valid_evidence(output)
                    self.write_json(output / relative_path, {"status": "FAIL"})

                    validation = validate_evidence(output)

                    self.assertEqual(validation["status"], "FAIL")
                    self.assertFalse(validation["checks"][check_name])

    def test_normal_development_validation_records_dirty_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp)
            self.valid_evidence(output, dirty=True)

            validation = validate_evidence(output)

            self.assertEqual(validation["status"], "PASS")
            self.assertTrue(validation["recorded_git_dirty"])
            self.assertTrue(validation["checks"]["clean_requirement_satisfied"])

    def test_capture_preflight_records_reported_repository_state(self) -> None:
        responses = {
            ("git", "rev-parse", "--show-toplevel"): "/repo\n",
            ("git", "rev-parse", "--abbrev-ref", "HEAD"): "main\n",
            ("git", "rev-parse", "HEAD"): "abc123\n",
            ("git", "tag", "--points-at", "HEAD"): "tag-a\ntag-b\n",
            ("git", "status", "--porcelain"): " M README.md\n",
        }

        def runner(arguments, cwd):
            self.assertEqual(cwd, Path("/repo"))
            return CommandResult(0, responses[tuple(arguments)], "")

        state = capture_preflight_state(Path("/repo"), command_runner=runner)

        self.assertEqual(state["repository_path"], "/repo")
        self.assertEqual(state["branch"], "main")
        self.assertEqual(state["head_commit"], "abc123")
        self.assertEqual(state["tags_at_head"], ["tag-a", "tag-b"])
        self.assertTrue(state["git_dirty"])

    def test_clean_required_mode_rejects_dirty_repository_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp)
            self.valid_evidence(output, dirty=True)

            validation = validate_evidence(output, require_clean=True)

            self.assertEqual(validation["status"], "FAIL")
            self.assertFalse(validation["checks"]["clean_requirement_satisfied"])

    def test_evidence_metadata_adds_no_w2_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp)
            self.valid_evidence(output)
            index = write_complete_evidence_index(output)
            validation = validate_evidence(output)
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

            self.assertTrue(forbidden_fields.isdisjoint(index))
            self.assertTrue(forbidden_fields.isdisjoint(validation))
            self.assertEqual(validation["ig1_decision"], "NOT_MADE")
            self.assertTrue(validation["candidate_only"])

    def test_nonempty_managed_output_is_refused_without_removal(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "evidence"
            output.mkdir()
            marker = output / "keep.txt"
            marker.write_text("keep", encoding="utf-8")

            with self.assertRaisesRegex(W1IG1EvidenceError, "will not be reused"):
                _prepare_output_directory(output)

            self.assertEqual(marker.read_text(encoding="utf-8"), "keep")


if __name__ == "__main__":
    unittest.main()
