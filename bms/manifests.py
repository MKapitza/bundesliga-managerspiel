from __future__ import annotations

import hashlib
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
W1_RUN_SCHEMA = "bms.w1-run-manifest"
W1_RUN_SCHEMA_VERSION = "0.1"
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


def build_w1_run_manifest(
    *,
    base_manifest: dict[str, Any],
    specification_manifest: Path,
    python_version: str,
    sqlite_version: str,
    database_schema: dict[str, Any],
    artifacts: dict[str, str],
) -> dict[str, Any]:
    validate_run_manifest(base_manifest)
    specification_sha256 = hashlib.sha256(specification_manifest.read_bytes()).hexdigest()
    data = {
        "schema": W1_RUN_SCHEMA,
        "schema_version": W1_RUN_SCHEMA_VERSION,
        "run_id": base_manifest["run_id"],
        "run_at": base_manifest["run_at"],
        "execution_status": base_manifest["execution_status"],
        "git_commit": base_manifest["git_commit"],
        "git_dirty": base_manifest["git_dirty"],
        "specification_manifest": base_manifest["specification_manifest"],
        "specification_manifest_sha256": specification_sha256,
        "python_version": python_version,
        "sqlite_version": sqlite_version,
        "persistence_backend": "sqlite",
        "database_schema": database_schema,
        "artifacts": artifacts,
    }
    validate_w1_run_manifest(data)
    return data


def validate_w1_run_manifest(data: dict[str, Any]) -> None:
    if data.get("schema") != W1_RUN_SCHEMA:
        raise ManifestError(f"unexpected W1 run schema: {data.get('schema')!r}")
    if data.get("schema_version") != W1_RUN_SCHEMA_VERSION:
        raise ManifestError(
            f"unexpected W1 run schema_version: {data.get('schema_version')!r}"
        )
    base_fields = {
        "schema": RUN_SCHEMA,
        "schema_version": RUN_SCHEMA_VERSION,
        "run_id": data.get("run_id"),
        "run_at": data.get("run_at"),
        "git_commit": data.get("git_commit"),
        "git_dirty": data.get("git_dirty"),
        "specification_manifest": data.get("specification_manifest"),
        "execution_status": data.get("execution_status"),
    }
    validate_run_manifest(base_fields)
    specification_sha256 = data.get("specification_manifest_sha256")
    if not isinstance(specification_sha256, str) or re.fullmatch(
        r"[0-9a-f]{64}", specification_sha256
    ) is None:
        raise ManifestError("specification_manifest_sha256 must be lowercase SHA-256")
    for field_name in ("python_version", "sqlite_version"):
        if not isinstance(data.get(field_name), str) or not data[field_name]:
            raise ManifestError(f"{field_name} must be a non-empty string")
    if data.get("persistence_backend") != "sqlite":
        raise ManifestError("persistence_backend must be sqlite")

    database_schema = data.get("database_schema")
    if not isinstance(database_schema, dict):
        raise ManifestError("database_schema must be an object")
    if not isinstance(database_schema.get("latest_migration"), str):
        raise ManifestError("database_schema.latest_migration must be a string")
    migrations = database_schema.get("applied_migrations")
    if not isinstance(migrations, list) or not migrations:
        raise ManifestError("database_schema.applied_migrations must be a non-empty array")
    for migration in migrations:
        if not isinstance(migration, dict) or set(migration) != {
            "migration_id",
            "checksum_sha256",
        }:
            raise ManifestError("each applied migration must contain ID and checksum")
        if not isinstance(migration["migration_id"], str) or not migration["migration_id"]:
            raise ManifestError("migration_id must be a non-empty string")
        checksum = migration["checksum_sha256"]
        if not isinstance(checksum, str) or re.fullmatch(r"[0-9a-f]{64}", checksum) is None:
            raise ManifestError("migration checksum must be lowercase SHA-256")

    artifacts = data.get("artifacts")
    expected_artifacts = {"evidence_id", "raw_record_id", "control_event_id"}
    if not isinstance(artifacts, dict) or set(artifacts) != expected_artifacts:
        raise ManifestError("artifacts must contain the three W1 technical IDs")
    for field_name, value in artifacts.items():
        if not isinstance(value, str) or not value:
            raise ManifestError(f"artifacts.{field_name} must be a non-empty string")


def write_w1_run_manifest(
    output_path: Path,
    *,
    base_manifest: dict[str, Any],
    specification_manifest: Path,
    python_version: str,
    sqlite_version: str,
    database_schema: dict[str, Any],
    artifacts: dict[str, str],
) -> dict[str, Any]:
    data = build_w1_run_manifest(
        base_manifest=base_manifest,
        specification_manifest=specification_manifest,
        python_version=python_version,
        sqlite_version=sqlite_version,
        database_schema=database_schema,
        artifacts=artifacts,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return data
