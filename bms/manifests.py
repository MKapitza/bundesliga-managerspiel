from __future__ import annotations

import json
import re
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SPEC_SCHEMA = "bms.specification-manifest"
SPEC_SCHEMA_VERSION = "1.0"
RUN_SCHEMA = "bms.run-manifest"
RUN_SCHEMA_VERSION = "0.1"
RUN_STATUSES = {"RUNNING", "SUCCEEDED", "FAILED"}
RUN_ID_RE = re.compile(r"^run-\d{8}T\d{6}Z-[0-9a-f]{12}$")


class ManifestError(ValueError):
    """Raised when a manifest is structurally invalid."""


def _load_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ManifestError(f"manifest not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ManifestError(f"invalid JSON in {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ManifestError(f"manifest root must be an object: {path}")
    return data


def validate_specification_manifest(path: Path) -> dict[str, Any]:
    data = _load_json(path)
    if data.get("schema") != SPEC_SCHEMA:
        raise ManifestError(f"unexpected specification schema: {data.get('schema')!r}")
    if data.get("schema_version") != SPEC_SCHEMA_VERSION:
        raise ManifestError(
            f"unexpected specification schema_version: {data.get('schema_version')!r}"
        )
    if data.get("requires_explicit_update_on_document_register_change") is not True:
        raise ManifestError("explicit DOC-REG-001 update requirement must be true")

    created_at = data.get("created_at")
    if not isinstance(created_at, str) or not created_at.endswith("Z"):
        raise ManifestError("created_at must be a UTC timestamp ending in Z")

    specifications = data.get("specifications")
    if not isinstance(specifications, dict) or not specifications:
        raise ManifestError("specifications must be a non-empty object")
    for doc_id, version in specifications.items():
        if not isinstance(doc_id, str) or not doc_id:
            raise ManifestError("specification IDs must be non-empty strings")
        if not isinstance(version, str) or not version:
            raise ManifestError(f"version for {doc_id!r} must be a non-empty string")
    if "DOC-REG-001" not in specifications:
        raise ManifestError("DOC-REG-001 must be present in specifications")
    return data


def _git_commit(repo_root: Path) -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo_root,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        return result.stdout.strip()
    return "UNBORN"


def _git_dirty(repo_root: Path) -> bool:
    result = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=repo_root,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise ManifestError("repository is not a readable Git worktree")
    return bool(result.stdout.strip())


def build_run_manifest(
    *,
    repo_root: Path,
    specification_manifest: Path,
    execution_status: str = "SUCCEEDED",
) -> dict[str, Any]:
    validate_specification_manifest(specification_manifest)
    if execution_status not in RUN_STATUSES:
        raise ManifestError(f"unsupported execution_status: {execution_status!r}")

    now = datetime.now(timezone.utc).replace(microsecond=0)
    timestamp = now.strftime("%Y%m%dT%H%M%SZ")
    run_id = f"run-{timestamp}-{uuid.uuid4().hex[:12]}"
    try:
        spec_ref = specification_manifest.resolve().relative_to(repo_root.resolve()).as_posix()
    except ValueError as exc:
        raise ManifestError("specification manifest must live inside the repository") from exc

    return {
        "schema": RUN_SCHEMA,
        "schema_version": RUN_SCHEMA_VERSION,
        "run_id": run_id,
        "run_at": now.isoformat().replace("+00:00", "Z"),
        "git_commit": _git_commit(repo_root),
        "git_dirty": _git_dirty(repo_root),
        "specification_manifest": spec_ref,
        "execution_status": execution_status,
    }


def validate_run_manifest(data: dict[str, Any]) -> None:
    if data.get("schema") != RUN_SCHEMA:
        raise ManifestError(f"unexpected run schema: {data.get('schema')!r}")
    if data.get("schema_version") != RUN_SCHEMA_VERSION:
        raise ManifestError(f"unexpected run schema_version: {data.get('schema_version')!r}")
    run_id = data.get("run_id")
    if not isinstance(run_id, str) or RUN_ID_RE.fullmatch(run_id) is None:
        raise ManifestError(f"invalid run_id: {run_id!r}")
    run_at = data.get("run_at")
    if not isinstance(run_at, str) or not run_at.endswith("Z"):
        raise ManifestError("run_at must be a UTC timestamp ending in Z")
    git_commit = data.get("git_commit")
    if not isinstance(git_commit, str) or not git_commit:
        raise ManifestError("git_commit must be a non-empty technical version reference")
    if not isinstance(data.get("git_dirty"), bool):
        raise ManifestError("git_dirty must be boolean")
    spec_ref = data.get("specification_manifest")
    if not isinstance(spec_ref, str) or not spec_ref:
        raise ManifestError("specification_manifest must be a non-empty repository path")
    if data.get("execution_status") not in RUN_STATUSES:
        raise ManifestError(f"invalid execution_status: {data.get('execution_status')!r}")


def write_run_manifest(
    output_path: Path,
    *,
    repo_root: Path,
    specification_manifest: Path,
    execution_status: str = "SUCCEEDED",
) -> dict[str, Any]:
    data = build_run_manifest(
        repo_root=repo_root,
        specification_manifest=specification_manifest,
        execution_status=execution_status,
    )
    validate_run_manifest(data)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return data
