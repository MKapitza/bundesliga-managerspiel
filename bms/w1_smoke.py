from __future__ import annotations

import ast
import hashlib
import json
import sqlite3
import sys
import tomllib
from pathlib import Path
from typing import Any

from .control_events import read_control_event, store_control_event
from .manifests import build_run_manifest, write_w1_run_manifest
from .persistence import apply_migrations, connect_database, schema_version
from .storage import (
    read_evidence,
    read_raw_observation,
    store_evidence,
    store_raw_observation,
    verify_evidence,
)

W1_SMOKE_SCHEMA = "bms.w1-smoke-report"
W1_SMOKE_SCHEMA_VERSION = "0.1"
REPLAY_COMPARISON_SCHEMA = "bms.w1-replay-comparison"
REPLAY_COMPARISON_SCHEMA_VERSION = "0.1"

FIXTURE_BYTES = b"BMS-W1-SMOKE-FIXTURE\x00\xff\x10"
FIXTURE_SOURCE_SYSTEM = "synthetic-technical-w1-smoke"
FIXTURE_SOURCE_REFERENCE = "fixture://technical-w1-smoke/raw-observation"
FIXTURE_RETRIEVED_AT = "2026-01-01T00:00:00.123456+00:00"
FIXTURE_OBSERVED_AT = "2026-01-01T00:00:00Z"
FIXTURE_CHECKED_AT = "2026-01-01T00:00:01.500000+00:00"

EXPECTED_MIGRATIONS = ("0001_raw_evidence", "0002_control_event")
EXPECTED_TABLES = {
    "schema_migrations",
    "evidence_artifact",
    "raw_observation",
    "control_event",
}
FORBIDDEN_PRODUCTION_MODULES = {
    "mapping",
    "identity_matching",
    "ssot",
    "monitoring",
    "eligibility",
    "prognosis",
    "prediction",
    "recommendation",
    "snapshot",
    "result",
    "evaluation",
    "gate_engine",
    "release_engine",
    "control_engine",
    "control_runner",
    "control_executor",
}
NETWORK_IMPORT_ROOTS = {"http", "socket", "urllib", "requests"}
MANAGED_OUTPUTS = {
    "replay-a",
    "replay-b",
    "migration-report.json",
    "scope-guard.json",
    "replay-comparison.json",
    "fresh-rebuild-report.json",
    "ig1-evidence-index.json",
}
IGNORED_VOLATILE_FIELDS = [
    "run_manifest.run_id",
    "run_manifest.run_at",
    "run_manifest.artifacts.*",
    "artifact_sample.*_id",
    "artifact_sample.run_id",
    "artifact_sample.created_at",
    "smoke_report.run_id",
    "temporary/output paths",
    "schema_migrations.applied_at",
]
COMPARED_STRUCTURAL_FIELDS = [
    "git commit/state",
    "Specification Manifest path/hash",
    "Python runtime basis",
    "SQLite runtime basis",
    "persistence backend",
    "migration IDs/order/checksums",
    "table/schema structure",
    "fixture bytes/hash",
    "evidence SHA-256/byte length",
    "artifact counts/types",
    "Raw -> Evidence relationship shape",
    "Evidence -> Run relationship shape",
    "Control -> Evidence relationship shape",
    "Control -> Run reconstruction shape",
    "nonvolatile Control Event fixture properties",
    "scope guard result",
    "execution status",
]


class W1SmokeError(RuntimeError):
    """Raised when integrated W1 smoke evidence cannot be produced safely."""


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _database_schema(connection: sqlite3.Connection) -> dict[str, Any]:
    latest_migration, _ = schema_version(connection)
    migrations = [
        {
            "migration_id": row["migration_id"],
            "checksum_sha256": row["checksum_sha256"],
        }
        for row in connection.execute(
            """
            SELECT migration_id, checksum_sha256
            FROM schema_migrations
            ORDER BY migration_id
            """
        )
    ]
    return {
        "latest_migration": latest_migration,
        "applied_migrations": migrations,
    }


def _schema_structure(connection: sqlite3.Connection) -> list[dict[str, Any]]:
    return [
        {"type": row["type"], "name": row["name"], "sql": row["sql"]}
        for row in connection.execute(
            """
            SELECT type, name, sql
            FROM sqlite_master
            WHERE name NOT LIKE 'sqlite_%'
            ORDER BY type, name
            """
        )
    ]


def _production_import_roots(repo_root: Path) -> set[str]:
    roots: set[str] = set()
    for path in (repo_root / "bms").glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                roots.update(alias.name.split(".", 1)[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                roots.add(node.module.split(".", 1)[0])
    return roots


def build_scope_guard(
    connection: sqlite3.Connection, *, repo_root: Path
) -> dict[str, Any]:
    tables = {
        row["name"]
        for row in connection.execute(
            """
            SELECT name FROM sqlite_master
            WHERE type = 'table' AND name NOT LIKE 'sqlite_%'
            """
        )
    }
    migrations = sorted(path.name for path in (repo_root / "migrations").glob("*.sql"))
    modules = {path.stem for path in (repo_root / "bms").glob("*.py")}
    import_roots = _production_import_roots(repo_root)
    non_stdlib_imports = sorted(import_roots - sys.stdlib_module_names)
    project = tomllib.loads((repo_root / "pyproject.toml").read_text(encoding="utf-8"))
    dependencies = project.get("project", {}).get("dependencies", [])
    docker_artifacts = sorted(
        path.name
        for pattern in ("Dockerfile*", "docker-compose*", "compose*.yaml", "compose*.yml")
        for path in repo_root.glob(pattern)
    )
    checks = {
        "productive_tables_exact": tables == EXPECTED_TABLES,
        "productive_migrations_exact": migrations
        == ["0001_raw_evidence.sql", "0002_control_event.sql"],
        "no_0003_migration": not any(name.startswith("0003_") for name in migrations),
        "forbidden_modules_absent": FORBIDDEN_PRODUCTION_MODULES.isdisjoint(modules),
        "stdlib_only": not non_stdlib_imports and dependencies == [],
        "network_imports_absent": NETWORK_IMPORT_ROOTS.isdisjoint(import_roots),
        "docker_artifacts_absent": not docker_artifacts,
        "sqlite_backend_only": True,
    }
    return {
        "schema": "bms.w1-scope-guard",
        "schema_version": "0.1",
        "status": "PASS" if all(checks.values()) else "FAIL",
        "checks": checks,
        "productive_tables": sorted(tables),
        "productive_migrations": migrations,
        "production_modules": sorted(modules),
        "forbidden_modules_present": sorted(FORBIDDEN_PRODUCTION_MODULES & modules),
        "import_roots": sorted(import_roots),
        "non_stdlib_imports": non_stdlib_imports,
        "declared_dependencies": dependencies,
        "docker_artifacts": docker_artifacts,
        "persistence_backend": "sqlite",
    }


def _artifact_sample(evidence: Any, raw: Any, control_event: Any) -> dict[str, Any]:
    return {
        "schema": "bms.w1-artifact-sample",
        "schema_version": "0.1",
        "evidence": {
            "evidence_id": evidence.evidence_id,
            "run_id": evidence.run_id,
            "content_sha256": evidence.content_sha256,
            "byte_length": evidence.byte_length,
            "media_type": evidence.media_type,
            "created_at": evidence.created_at,
        },
        "raw_observation": {
            "raw_record_id": raw.raw_record_id,
            "raw_payload_ref": raw.raw_payload_ref,
            "run_id": raw.run_id,
            "source_system": raw.source_system,
            "source_reference": raw.source_reference,
            "retrieved_at": raw.retrieved_at,
            "observed_at": raw.observed_at,
            "created_at": raw.created_at,
        },
        "control_event": {
            "control_event_id": control_event.control_event_id,
            "control_id": control_event.control_id,
            "checked_at": control_event.checked_at,
            "object_refs": list(control_event.object_refs),
            "control_point": control_event.control_point,
            "severity": control_event.severity,
            "check_status": control_event.check_status,
            "trace_refs": list(control_event.trace_refs),
            "block_effect": control_event.block_effect,
            "owner_level": control_event.owner_level,
            "resolution_status": control_event.resolution_status,
            "evidence_ref": control_event.evidence_ref,
            "created_at": control_event.created_at,
        },
    }


def _run_replay(run_dir: Path, *, repo_root: Path) -> dict[str, Any]:
    if run_dir.exists():
        raise W1SmokeError(f"replay output already exists and will not be reused: {run_dir}")
    run_dir.mkdir(parents=True)
    database_path = run_dir / "w1-smoke.sqlite3"
    if database_path.exists():
        raise W1SmokeError(f"smoke database already exists: {database_path}")

    specification_manifest = repo_root / "spec/specification-manifest.json"
    base_manifest = build_run_manifest(
        repo_root=repo_root,
        specification_manifest=specification_manifest,
    )
    connection = connect_database(database_path)
    try:
        newly_applied = apply_migrations(connection, repo_root / "migrations")
        database_schema = _database_schema(connection)
        if newly_applied != list(EXPECTED_MIGRATIONS):
            raise W1SmokeError(f"unexpected fresh migration order: {newly_applied!r}")
        if database_schema["latest_migration"] != "0002_control_event":
            raise W1SmokeError("latest migration must be 0002_control_event")

        evidence = store_evidence(
            connection,
            content=FIXTURE_BYTES,
            run_id=base_manifest["run_id"],
            media_type="application/octet-stream",
        )
        raw = store_raw_observation(
            connection,
            source_system=FIXTURE_SOURCE_SYSTEM,
            source_reference=FIXTURE_SOURCE_REFERENCE,
            retrieved_at=FIXTURE_RETRIEVED_AT,
            observed_at=FIXTURE_OBSERVED_AT,
            raw_payload_ref=evidence.evidence_id,
            run_id=base_manifest["run_id"],
        )
        control_event = store_control_event(
            connection,
            control_id="CTL-K0-001",
            checked_at=FIXTURE_CHECKED_AT,
            object_refs=["fixture-object:technical-w1-smoke"],
            control_point="K0",
            severity="CRITICAL",
            check_status="NOT_CHECKED",
            trace_refs=["DOC-015"],
            block_effect="NONE",
            owner_level="technical-w1-smoke",
            resolution_status="OPEN",
            evidence_ref=evidence.evidence_id,
        )

        loaded_evidence = read_evidence(connection, evidence.evidence_id)
        loaded_raw = read_raw_observation(connection, raw.raw_record_id)
        loaded_control = read_control_event(connection, control_event.control_event_id)
        control_run_id = read_evidence(
            connection, loaded_control.evidence_ref
        ).run_id
        relationships = {
            "raw_to_evidence": loaded_raw.raw_payload_ref == loaded_evidence.evidence_id,
            "raw_to_run": loaded_raw.run_id == base_manifest["run_id"],
            "evidence_to_run": loaded_evidence.run_id == base_manifest["run_id"],
            "control_to_evidence": loaded_control.evidence_ref
            == loaded_evidence.evidence_id,
            "control_to_run_via_evidence": control_run_id == base_manifest["run_id"],
        }
        counts = {
            table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in ("evidence_artifact", "raw_observation", "control_event")
        }
        scope_guard = build_scope_guard(connection, repo_root=repo_root)
        checks = {
            "fresh_database_created": database_path.is_file(),
            "migrations_0001_0002_applied": [
                item["migration_id"] for item in database_schema["applied_migrations"]
            ]
            == list(EXPECTED_MIGRATIONS),
            "evidence_roundtrip": loaded_evidence == evidence,
            "evidence_integrity_verified": verify_evidence(
                connection, evidence.evidence_id
            ),
            "raw_roundtrip": loaded_raw == raw,
            "control_event_roundtrip": loaded_control == control_event,
            "relationships_valid": all(relationships.values()),
            "artifact_counts_valid": counts
            == {"evidence_artifact": 1, "raw_observation": 1, "control_event": 1},
            "scope_guard_pass": scope_guard["status"] == "PASS",
        }
        if not all(checks.values()):
            raise W1SmokeError(f"integrated W1 checks failed: {checks!r}")

        run_manifest = write_w1_run_manifest(
            run_dir / "run-manifest.json",
            base_manifest=base_manifest,
            specification_manifest=specification_manifest,
            python_version=sys.version.split()[0],
            sqlite_version=sqlite3.sqlite_version,
            database_schema=database_schema,
            artifacts={
                "evidence_id": evidence.evidence_id,
                "raw_record_id": raw.raw_record_id,
                "control_event_id": control_event.control_event_id,
            },
        )
        artifact_sample = _artifact_sample(evidence, raw, control_event)
        schema_structure = _schema_structure(connection)
        smoke_report = {
            "schema": W1_SMOKE_SCHEMA,
            "schema_version": W1_SMOKE_SCHEMA_VERSION,
            "status": "PASS",
            "execution_status": "SUCCEEDED",
            "run_id": base_manifest["run_id"],
            "fixture": {
                "kind": "synthetic-technical-w1-smoke",
                "real_source_claimed": False,
                "content_hex": FIXTURE_BYTES.hex(),
                "content_sha256": hashlib.sha256(FIXTURE_BYTES).hexdigest(),
                "byte_length": len(FIXTURE_BYTES),
                "source_system": FIXTURE_SOURCE_SYSTEM,
                "source_reference": FIXTURE_SOURCE_REFERENCE,
                "retrieved_at": FIXTURE_RETRIEVED_AT,
                "observed_at": FIXTURE_OBSERVED_AT,
            },
            "checks": checks,
            "artifact_counts": counts,
            "artifact_types": ["evidence_artifact", "raw_observation", "control_event"],
            "relationships": relationships,
            "control_event_fixture": {
                "control_id": control_event.control_id,
                "checked_at": control_event.checked_at,
                "object_refs": list(control_event.object_refs),
                "control_point": control_event.control_point,
                "severity": control_event.severity,
                "check_status": control_event.check_status,
                "trace_refs": list(control_event.trace_refs),
                "block_effect": control_event.block_effect,
                "owner_level": control_event.owner_level,
                "resolution_status": control_event.resolution_status,
                "control_rule_executed": False,
                "gate_decision_made": False,
            },
            "database_schema": database_schema,
            "schema_structure": schema_structure,
            "scope_guard": scope_guard,
        }
        _write_json(run_dir / "artifact-sample.json", artifact_sample)
        _write_json(run_dir / "smoke-report.json", smoke_report)
        return {
            "run_manifest": run_manifest,
            "smoke_report": smoke_report,
            "artifact_sample": artifact_sample,
            "scope_guard": scope_guard,
            "database_path": str(database_path),
            "database_existed_before": False,
        }
    finally:
        connection.close()


def normalize_replay(run_result: dict[str, Any]) -> dict[str, Any]:
    manifest = run_result["run_manifest"]
    report = run_result["smoke_report"]
    return {
        "runtime_and_version_basis": {
            "git_commit": manifest["git_commit"],
            "git_dirty": manifest["git_dirty"],
            "specification_manifest": manifest["specification_manifest"],
            "specification_manifest_sha256": manifest[
                "specification_manifest_sha256"
            ],
            "python_version": manifest["python_version"],
            "sqlite_version": manifest["sqlite_version"],
            "persistence_backend": manifest["persistence_backend"],
        },
        "database_schema": manifest["database_schema"],
        "schema_structure": report["schema_structure"],
        "fixture": report["fixture"],
        "artifact_counts": report["artifact_counts"],
        "artifact_types": report["artifact_types"],
        "relationships": report["relationships"],
        "control_event_fixture": report["control_event_fixture"],
        "scope_guard": report["scope_guard"],
        "execution_status": manifest["execution_status"],
    }


def _differences(left: Any, right: Any, path: str = "$") -> list[dict[str, Any]]:
    if type(left) is not type(right):
        return [{"path": path, "left": left, "right": right}]
    if isinstance(left, dict):
        differences: list[dict[str, Any]] = []
        for key in sorted(set(left) | set(right)):
            if key not in left or key not in right:
                differences.append(
                    {"path": f"{path}.{key}", "left": left.get(key), "right": right.get(key)}
                )
            else:
                differences.extend(_differences(left[key], right[key], f"{path}.{key}"))
        return differences
    if isinstance(left, list):
        if len(left) != len(right):
            return [{"path": path, "left": left, "right": right}]
        differences = []
        for index, (left_item, right_item) in enumerate(zip(left, right, strict=True)):
            differences.extend(_differences(left_item, right_item, f"{path}[{index}]"))
        return differences
    if left != right:
        return [{"path": path, "left": left, "right": right}]
    return []


def compare_replays(
    first: dict[str, Any], second: dict[str, Any]
) -> dict[str, Any]:
    differences = _differences(normalize_replay(first), normalize_replay(second))
    return {
        "schema": REPLAY_COMPARISON_SCHEMA,
        "schema_version": REPLAY_COMPARISON_SCHEMA_VERSION,
        "status": "PASS" if not differences else "FAIL",
        "ignored_volatile_field_list": IGNORED_VOLATILE_FIELDS,
        "compared_structural_field_list": COMPARED_STRUCTURAL_FIELDS,
        "differences": differences,
    }


def _prepare_output_directory(output_dir: Path) -> None:
    if output_dir.exists() and not output_dir.is_dir():
        raise W1SmokeError(f"output path is not a directory: {output_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)
    conflicts = sorted(name for name in MANAGED_OUTPUTS if (output_dir / name).exists())
    if conflicts:
        raise W1SmokeError(
            "managed W1 smoke output already exists and will not be reused: "
            + ", ".join(conflicts)
        )


def run_w1_smoke(output_dir: Path, *, repo_root: Path) -> dict[str, Any]:
    _prepare_output_directory(output_dir)
    first = _run_replay(output_dir / "replay-a", repo_root=repo_root)
    second = _run_replay(output_dir / "replay-b", repo_root=repo_root)
    comparison = compare_replays(first, second)

    first_migrations = first["run_manifest"]["database_schema"]["applied_migrations"]
    second_migrations = second["run_manifest"]["database_schema"]["applied_migrations"]
    migration_files = {
        path.stem: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted((repo_root / "migrations").glob("*.sql"))
    }
    migration_checks = [
        {
            "migration_id": first_item["migration_id"],
            "file_checksum_sha256": migration_files[first_item["migration_id"]],
            "replay_a_checksum_sha256": first_item["checksum_sha256"],
            "replay_b_checksum_sha256": second_item["checksum_sha256"],
            "checksums_match": migration_files[first_item["migration_id"]]
            == first_item["checksum_sha256"]
            == second_item["checksum_sha256"],
        }
        for first_item, second_item in zip(
            first_migrations, second_migrations, strict=True
        )
    ]
    migration_report = {
        "schema": "bms.w1-migration-report",
        "schema_version": "0.1",
        "status": "PASS"
        if first["run_manifest"]["database_schema"]
        == second["run_manifest"]["database_schema"]
        and all(item["checksums_match"] for item in migration_checks)
        else "FAIL",
        "replay_a": first["run_manifest"]["database_schema"],
        "replay_b": second["run_manifest"]["database_schema"],
        "migrations": migration_checks,
    }
    scope_guard = {
        "schema": "bms.w1-integrated-scope-guard",
        "schema_version": "0.1",
        "status": "PASS"
        if first["scope_guard"] == second["scope_guard"]
        and first["scope_guard"]["status"] == "PASS"
        else "FAIL",
        "replay_a": first["scope_guard"],
        "replay_b": second["scope_guard"],
    }
    fresh_rebuild_report = {
        "schema": "bms.w1-fresh-rebuild-report",
        "schema_version": "0.1",
        "status": "PASS"
        if not first["database_existed_before"]
        and not second["database_existed_before"]
        and first["database_path"] != second["database_path"]
        else "FAIL",
        "databases": [
            {
                "replay": "a",
                "path": first["database_path"],
                "existed_before": first["database_existed_before"],
            },
            {
                "replay": "b",
                "path": second["database_path"],
                "existed_before": second["database_existed_before"],
            },
        ],
        "independent_database_paths": first["database_path"]
        != second["database_path"],
    }
    _write_json(output_dir / "migration-report.json", migration_report)
    _write_json(output_dir / "scope-guard.json", scope_guard)
    _write_json(output_dir / "replay-comparison.json", comparison)
    _write_json(output_dir / "fresh-rebuild-report.json", fresh_rebuild_report)

    overall_pass = all(
        report["status"] == "PASS"
        for report in (
            migration_report,
            scope_guard,
            comparison,
            fresh_rebuild_report,
        )
    )
    evidence_index = {
        "schema": "bms.w1-ig1-evidence-index",
        "schema_version": "0.1",
        "status": "PASS" if overall_pass else "FAIL",
        "ig1_decision": "NOT_MADE",
        "candidate_only": True,
        "artifacts": [
            "migration-report.json",
            "scope-guard.json",
            "replay-a/run-manifest.json",
            "replay-a/smoke-report.json",
            "replay-a/artifact-sample.json",
            "replay-b/run-manifest.json",
            "replay-b/smoke-report.json",
            "replay-b/artifact-sample.json",
            "replay-comparison.json",
            "fresh-rebuild-report.json",
        ],
    }
    _write_json(output_dir / "ig1-evidence-index.json", evidence_index)
    if not overall_pass:
        raise W1SmokeError("integrated W1 smoke or replay comparison failed")
    return {
        "status": "PASS",
        "ig1_decision": "NOT_MADE",
        "output_dir": str(output_dir),
        "replay_a_run_id": first["run_manifest"]["run_id"],
        "replay_b_run_id": second["run_manifest"]["run_id"],
        "replay_comparison": comparison["status"],
        "scope_guard": scope_guard["status"],
    }
