from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Sequence


EVIDENCE_SCHEMA = "bms.w1-ig1-candidate-evidence"
EVIDENCE_SCHEMA_VERSION = "0.1"
VALIDATION_SCHEMA = "bms.w1-ig1-evidence-validation"
VALIDATION_SCHEMA_VERSION = "0.1"

W1_REQUIRED_ARTIFACTS = (
    "w1-smoke/migration-report.json",
    "w1-smoke/scope-guard.json",
    "w1-smoke/replay-a/run-manifest.json",
    "w1-smoke/replay-a/smoke-report.json",
    "w1-smoke/replay-a/artifact-sample.json",
    "w1-smoke/replay-b/run-manifest.json",
    "w1-smoke/replay-b/smoke-report.json",
    "w1-smoke/replay-b/artifact-sample.json",
    "w1-smoke/replay-comparison.json",
    "w1-smoke/fresh-rebuild-report.json",
    "w1-smoke/ig1-evidence-index.json",
)
REQUIRED_ARTIFACTS = (
    "preflight-state.json",
    "preflight-smoke.json",
    "preflight-smoke-command.json",
    "final-tests.txt",
    "final-tests-exit-code.json",
    "git-diff-check.txt",
    "git-diff-check-status.json",
    "git-status.txt",
    "w1-smoke-command.json",
    *W1_REQUIRED_ARTIFACTS,
    "evidence-validation.json",
)


class W1IG1EvidenceError(RuntimeError):
    """Raised when candidate evidence cannot be produced safely."""


@dataclass(frozen=True)
class CommandResult:
    returncode: int
    stdout: str
    stderr: str


CommandRunner = Callable[[Sequence[str], Path], CommandResult]


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _read_json(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"expected JSON object: {path}")
    return data


def _run_command(arguments: Sequence[str], cwd: Path) -> CommandResult:
    completed = subprocess.run(
        list(arguments),
        cwd=cwd,
        check=False,
        capture_output=True,
        text=True,
    )
    return CommandResult(completed.returncode, completed.stdout, completed.stderr)


def _successful_stdout(
    arguments: Sequence[str], *, repo_root: Path, command_runner: CommandRunner
) -> str:
    result = command_runner(arguments, repo_root)
    if result.returncode != 0:
        command = " ".join(arguments)
        raise W1IG1EvidenceError(
            f"repository inspection command failed ({command}): {result.stderr.strip()}"
        )
    return result.stdout.strip()


def capture_preflight_state(
    repo_root: Path, *, command_runner: CommandRunner = _run_command
) -> dict[str, Any]:
    repository_path = _successful_stdout(
        ("git", "rev-parse", "--show-toplevel"),
        repo_root=repo_root,
        command_runner=command_runner,
    )
    branch = _successful_stdout(
        ("git", "rev-parse", "--abbrev-ref", "HEAD"),
        repo_root=repo_root,
        command_runner=command_runner,
    )
    head = _successful_stdout(
        ("git", "rev-parse", "HEAD"),
        repo_root=repo_root,
        command_runner=command_runner,
    )
    tags_text = _successful_stdout(
        ("git", "tag", "--points-at", "HEAD"),
        repo_root=repo_root,
        command_runner=command_runner,
    )
    status_text = _successful_stdout(
        ("git", "status", "--porcelain"),
        repo_root=repo_root,
        command_runner=command_runner,
    )
    return {
        "schema": "bms.w1-ig1-preflight-state",
        "schema_version": "0.1",
        "repository_path": repository_path,
        "branch": branch,
        "head_commit": head,
        "tags_at_head": tags_text.splitlines() if tags_text else [],
        "python_version": sys.version.split()[0],
        "git_dirty": bool(status_text),
    }


def _prepare_output_directory(output_dir: Path) -> None:
    if output_dir.exists() and not output_dir.is_dir():
        raise W1IG1EvidenceError(f"output path is not a directory: {output_dir}")
    if output_dir.exists() and any(output_dir.iterdir()):
        raise W1IG1EvidenceError(
            f"managed evidence output is not empty and will not be reused: {output_dir}"
        )
    output_dir.mkdir(parents=True, exist_ok=True)


def _command_evidence(arguments: Sequence[str], result: CommandResult) -> dict[str, Any]:
    return {
        "command": list(arguments),
        "stdout": result.stdout,
        "stderr": result.stderr,
        "exit_code": result.returncode,
    }


def _combined_output(result: CommandResult) -> str:
    return result.stdout + result.stderr


def _reported_cli_status(result: CommandResult) -> str | None:
    for line in reversed(result.stdout.splitlines()):
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict) and isinstance(payload.get("status"), str):
            return payload["status"]
    return None


def write_complete_evidence_index(output_dir: Path) -> dict[str, Any]:
    indexed = set(REQUIRED_ARTIFACTS)
    indexed.update(
        path.relative_to(output_dir).as_posix()
        for path in output_dir.rglob("*")
        if path.is_file() and path.name != "ig1-evidence-index.json"
    )
    index = {
        "schema": EVIDENCE_SCHEMA,
        "schema_version": EVIDENCE_SCHEMA_VERSION,
        "status": "CANDIDATE_EVIDENCE_GENERATED",
        "ig1_decision": "NOT_MADE",
        "candidate_only": True,
        "artifacts": sorted(indexed),
    }
    _write_json(output_dir / "ig1-evidence-index.json", index)
    return index


def _exit_code(output_dir: Path, relative_path: str) -> int | None:
    try:
        value = _read_json(output_dir / relative_path)["exit_code"]
    except (OSError, ValueError, KeyError, json.JSONDecodeError):
        return None
    return value if isinstance(value, int) else None


def _status(output_dir: Path, relative_path: str) -> str | None:
    try:
        value = _read_json(output_dir / relative_path)["status"]
    except (OSError, ValueError, KeyError, json.JSONDecodeError):
        return None
    return value if isinstance(value, str) else None


def _preflight_dirty(output_dir: Path) -> bool | None:
    try:
        value = _read_json(output_dir / "preflight-state.json")["git_dirty"]
    except (OSError, ValueError, KeyError, json.JSONDecodeError):
        return None
    return value if isinstance(value, bool) else None


def _inner_candidate_state(output_dir: Path) -> tuple[str | None, bool | None]:
    try:
        index = _read_json(output_dir / "w1-smoke/ig1-evidence-index.json")
    except (OSError, ValueError, json.JSONDecodeError):
        return None, None
    decision = index.get("ig1_decision")
    candidate_only = index.get("candidate_only")
    return (
        decision if isinstance(decision, str) else None,
        candidate_only if isinstance(candidate_only, bool) else None,
    )


def validate_evidence(output_dir: Path, *, require_clean: bool = False) -> dict[str, Any]:
    missing = sorted(
        relative_path
        for relative_path in REQUIRED_ARTIFACTS
        if not (output_dir / relative_path).is_file()
    )
    dirty = _preflight_dirty(output_dir)
    inner_decision, inner_candidate_only = _inner_candidate_state(output_dir)
    checks = {
        "required_artifacts_present": not missing,
        "full_test_exit_code_zero": _exit_code(
            output_dir, "final-tests-exit-code.json"
        )
        == 0,
        "lightweight_smoke_exit_code_zero": _exit_code(
            output_dir, "preflight-smoke-command.json"
        )
        == 0,
        "git_diff_check_exit_code_zero": _exit_code(
            output_dir, "git-diff-check-status.json"
        )
        == 0,
        "integrated_w1_smoke_exit_code_zero": _exit_code(
            output_dir, "w1-smoke-command.json"
        )
        == 0,
        "integrated_w1_smoke_pass": _status(
            output_dir, "w1-smoke-command.json"
        )
        == "PASS",
        "replay_comparison_pass": _status(
            output_dir, "w1-smoke/replay-comparison.json"
        )
        == "PASS",
        "scope_guard_pass": _status(output_dir, "w1-smoke/scope-guard.json")
        == "PASS",
        "migration_report_pass": _status(
            output_dir, "w1-smoke/migration-report.json"
        )
        == "PASS",
        "fresh_rebuild_pass": _status(
            output_dir, "w1-smoke/fresh-rebuild-report.json"
        )
        == "PASS",
        "replay_a_smoke_pass": _status(
            output_dir, "w1-smoke/replay-a/smoke-report.json"
        )
        == "PASS",
        "replay_b_smoke_pass": _status(
            output_dir, "w1-smoke/replay-b/smoke-report.json"
        )
        == "PASS",
        "inner_evidence_index_pass": _status(
            output_dir, "w1-smoke/ig1-evidence-index.json"
        )
        == "PASS",
        "ig1_decision_not_made": inner_decision == "NOT_MADE",
        "candidate_only": inner_candidate_only is True,
        "git_dirty_state_recorded": dirty is not None,
        "clean_requirement_satisfied": dirty is False if require_clean else True,
    }
    failed_checks = sorted(name for name, passed in checks.items() if not passed)
    return {
        "schema": VALIDATION_SCHEMA,
        "schema_version": VALIDATION_SCHEMA_VERSION,
        "status": "PASS" if not failed_checks else "FAIL",
        "ig1_decision": "NOT_MADE",
        "candidate_only": True,
        "require_clean": require_clean,
        "recorded_git_dirty": dirty,
        "checks": checks,
        "missing_artifacts": missing,
        "failed_checks": failed_checks,
    }


def run_w1_ig1_evidence(
    output_dir: Path,
    *,
    repo_root: Path,
    require_clean: bool = False,
    command_runner: CommandRunner = _run_command,
) -> dict[str, Any]:
    _prepare_output_directory(output_dir)
    preflight = capture_preflight_state(repo_root, command_runner=command_runner)
    _write_json(output_dir / "preflight-state.json", preflight)

    smoke_arguments = (
        sys.executable,
        "-m",
        "bms",
        "smoke",
        "--output",
        str(output_dir / "preflight-smoke.json"),
    )
    smoke_result = command_runner(smoke_arguments, repo_root)
    _write_json(
        output_dir / "preflight-smoke-command.json",
        _command_evidence(smoke_arguments, smoke_result),
    )

    test_arguments = (
        sys.executable,
        "-m",
        "unittest",
        "discover",
        "-s",
        "tests",
        "-v",
    )
    test_result = command_runner(test_arguments, repo_root)
    (output_dir / "final-tests.txt").write_text(
        _combined_output(test_result), encoding="utf-8"
    )
    _write_json(
        output_dir / "final-tests-exit-code.json",
        {"command": list(test_arguments), "exit_code": test_result.returncode},
    )

    diff_arguments = ("git", "diff", "--check")
    diff_result = command_runner(diff_arguments, repo_root)
    (output_dir / "git-diff-check.txt").write_text(
        _combined_output(diff_result), encoding="utf-8"
    )
    _write_json(
        output_dir / "git-diff-check-status.json",
        {"command": list(diff_arguments), "exit_code": diff_result.returncode},
    )

    status_arguments = ("git", "status", "--short")
    status_result = command_runner(status_arguments, repo_root)
    if status_result.returncode != 0:
        raise W1IG1EvidenceError(
            f"git status failed: {status_result.stderr.strip()}"
        )
    (output_dir / "git-status.txt").write_text(status_result.stdout, encoding="utf-8")

    w1_arguments = (
        sys.executable,
        "-m",
        "bms",
        "w1-smoke",
        "--output-dir",
        str(output_dir / "w1-smoke"),
    )
    w1_result = command_runner(w1_arguments, repo_root)
    w1_command_evidence = _command_evidence(w1_arguments, w1_result)
    w1_command_evidence["status"] = _reported_cli_status(w1_result)
    _write_json(
        output_dir / "w1-smoke-command.json",
        w1_command_evidence,
    )

    _write_json(
        output_dir / "evidence-validation.json",
        {
            "schema": VALIDATION_SCHEMA,
            "schema_version": VALIDATION_SCHEMA_VERSION,
            "status": "PENDING_TECHNICAL_VALIDATION",
            "ig1_decision": "NOT_MADE",
            "candidate_only": True,
        },
    )
    index = write_complete_evidence_index(output_dir)
    validation = validate_evidence(output_dir, require_clean=require_clean)
    _write_json(output_dir / "evidence-validation.json", validation)
    return {
        "status": validation["status"],
        "ig1_decision": "NOT_MADE",
        "candidate_only": True,
        "output_dir": str(output_dir),
        "evidence_index": index["status"],
        "validation": validation,
    }
