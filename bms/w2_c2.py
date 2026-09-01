from __future__ import annotations

import ast
import hashlib
import json
import sqlite3
import sys
import tomllib
from pathlib import Path
from typing import Any

from .control_events import read_control_event
from .imports import import_fixture, validate_fixture
from .manifests import build_run_manifest
from .mapping import (
    derive_g2,
    map_external_identity,
    read_mapping_record,
    run_applicable_k1,
)
from .persistence import apply_migrations, connect_database
from .storage import read_evidence, read_raw_observation
from .w2_c1 import REQUIRED_K0_CONTROLS, derive_g1, run_k0

EXPECTED_MIGRATIONS = (
    "0001_raw_evidence",
    "0002_control_event",
    "0003_import_envelope",
    "0004_mapping_review",
)
EXPECTED_TABLES = {
    "schema_migrations",
    "evidence_artifact",
    "raw_observation",
    "control_event",
    "import_envelope",
    "mapping_record",
}
FORBIDDEN_TABLE_FRAGMENTS = {
    "ssot",
    "monitoring",
    "eligibility",
    "prediction",
    "prognosis",
    "recommendation",
    "snapshot",
    "manager_decision",
    "result",
    "evaluation",
    "external_identity",
}
FORBIDDEN_MODULES = {
    "ssot",
    "monitoring",
    "eligibility",
    "prediction",
    "prognosis",
    "recommendation",
    "snapshot",
    "manager_decision",
    "result",
    "evaluation",
    "gate_engine",
}
NETWORK_IMPORT_ROOTS = {"http", "socket", "urllib", "requests"}


class W2C2Error(RuntimeError):
    """Raised when the integrated C1-to-C2 smoke cannot complete safely."""


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _prepare_output(output_dir: Path) -> None:
    if output_dir.exists() and not output_dir.is_dir():
        raise W2C2Error(f"output path is not a directory: {output_dir}")
    if output_dir.exists() and any(output_dir.iterdir()):
        raise W2C2Error(f"output directory is not empty and will not be reused: {output_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)


def _scope_guard(connection: sqlite3.Connection, repo_root: Path) -> dict[str, Any]:
    tables = {
        row["name"]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        )
    }
    migrations = sorted(path.name for path in (repo_root / "migrations").glob("*.sql"))
    modules = {path.stem for path in (repo_root / "bms").glob("*.py")}
    import_roots: set[str] = set()
    for path in (repo_root / "bms").glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                import_roots.update(alias.name.split(".", 1)[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                import_roots.add(node.module.split(".", 1)[0])
    dependencies = tomllib.loads((repo_root / "pyproject.toml").read_text(encoding="utf-8"))[
        "project"
    ].get("dependencies", [])
    forbidden_tables = sorted(
        table
        for table in tables
        if any(fragment in table for fragment in FORBIDDEN_TABLE_FRAGMENTS)
    )
    checks = {
        "productive_tables_exact": tables == EXPECTED_TABLES,
        "migrations_exact": migrations
        == [
            "0001_raw_evidence.sql",
            "0002_control_event.sql",
            "0003_import_envelope.sql",
            "0004_mapping_review.sql",
        ],
        "no_migration_0005": not any(name.startswith("0005_") for name in migrations),
        "forbidden_tables_absent": not forbidden_tables,
        "forbidden_modules_absent": FORBIDDEN_MODULES.isdisjoint(modules),
        "network_imports_absent": NETWORK_IMPORT_ROOTS.isdisjoint(import_roots),
        "stdlib_only": not (import_roots - sys.stdlib_module_names) and dependencies == [],
    }
    return {
        "schema": "bms.w2-c2-scope-guard",
        "schema_version": "0.1",
        "status": "PASS" if all(checks.values()) else "FAIL",
        "checks": checks,
        "productive_tables": sorted(tables),
        "productive_migrations": migrations,
        "forbidden_tables_present": forbidden_tables,
        "forbidden_modules_present": sorted(FORBIDDEN_MODULES & modules),
    }


def run_w2_c2_smoke(
    fixture_dir: Path, output_dir: Path, *, repo_root: Path
) -> dict[str, Any]:
    _prepare_output(output_dir)
    validated = validate_fixture(fixture_dir)
    database_path = output_dir / "w2-c2.sqlite3"
    base_manifest = build_run_manifest(
        repo_root=repo_root,
        specification_manifest=repo_root / "spec/specification-manifest.json",
    )
    connection = connect_database(database_path)
    try:
        applied = apply_migrations(connection, repo_root / "migrations")
        migration_rows = connection.execute(
            "SELECT migration_id, checksum_sha256 FROM schema_migrations ORDER BY migration_id"
        ).fetchall()
        migration_report = {
            "schema": "bms.w2-c2-migration-report",
            "schema_version": "0.1",
            "status": "PASS" if applied == list(EXPECTED_MIGRATIONS) else "FAIL",
            "fresh_database": True,
            "applied_migrations": [dict(row) for row in migration_rows],
        }
        imported = import_fixture(
            connection, fixture_dir=fixture_dir, run_id=base_manifest["run_id"]
        )
        k0_events = run_k0(
            connection,
            contract=imported.contract,
            run_id=base_manifest["run_id"],
            import_batch_id=imported.envelope.import_batch_id,
            raw_record_id=imported.raw_observation.raw_record_id,
        )
        g1 = derive_g1(
            connection,
            run_id=base_manifest["run_id"],
            import_batch_id=imported.envelope.import_batch_id,
            control_event_ids=[event.control_event_id for event in k0_events],
            raw_record_ids=[imported.raw_observation.raw_record_id],
            evidence_ids=[imported.evidence.evidence_id],
        )
        fixture_report = {
            "schema": "bms.w2-c2-fixture-validation",
            "schema_version": "0.1",
            "status": "PASS",
            "fixture_id": imported.contract["fixture_id"],
            "sha256": validated["sha256"],
            "byte_length": validated["byte_length"],
            "expected_structure": imported.contract["expected_structure"],
        }
        k0_report = {
            "schema": "bms.w2-c2-k0-control-report",
            "schema_version": "0.1",
            "status": (
                "PASS"
                if [event.control_id for event in k0_events]
                == list(REQUIRED_K0_CONTROLS)
                and all(event.check_status == "CHECK_PASSED" for event in k0_events)
                else "FAIL"
            ),
            "controls": [
                {
                    "control_event_id": event.control_event_id,
                    "control_id": event.control_id,
                    "check_status": event.check_status,
                    "block_effect": event.block_effect,
                }
                for event in k0_events
            ],
        }
        reports: dict[str, dict[str, Any]] = {
            "fixture-validation.json": fixture_report,
            "migration-report.json": migration_report,
            "k0-control-report.json": k0_report,
            "g1-decision.json": g1,
        }
        if g1["decision"] != "RELEASED_FOR_MAPPING":
            smoke = {
                "schema": "bms.w2-c2-smoke-report",
                "schema_version": "0.1",
                "status": "FAIL",
                "run_id": base_manifest["run_id"],
                "stopped_after": "G1",
                "reason": "G1 blockiert; Mapping und G2 wurden nicht ausgeführt.",
            }
            reports["smoke-report.json"] = smoke
            for name, report in reports.items():
                _write_json(output_dir / name, report)
            raise W2C2Error("G1 blocked; mapping and G2 were not executed")

        mapping = map_external_identity(
            connection,
            raw_record_id=imported.raw_observation.raw_record_id,
            run_id=base_manifest["run_id"],
            source_system=imported.raw_observation.source_system,
            external_id=imported.envelope.external_player_id,
            object_type="PLAYER",
            criticality="CRITICAL",
        )
        k1_events = run_applicable_k1(connection, mapping.mapping_record_id)
        g2 = derive_g2(
            connection,
            mapping_record_ids=[mapping.mapping_record_id],
            control_event_ids=[event.control_event_id for event in k1_events],
        )
        persisted_mapping = read_mapping_record(connection, mapping.mapping_record_id)
        raw = read_raw_observation(connection, mapping.raw_record_id)
        evidence = read_evidence(connection, raw.raw_payload_ref)
        persisted_k1 = [
            read_control_event(connection, event.control_event_id) for event in k1_events
        ]
        k1_traceability = all(
            event == persisted
            and f"mapping_record:{mapping.mapping_record_id}" in persisted.object_refs
            and f"raw_record:{raw.raw_record_id}" in persisted.object_refs
            and f"evidence:{evidence.evidence_id}" in persisted.object_refs
            and f"run:{base_manifest['run_id']}" in persisted.object_refs
            and persisted.evidence_ref == evidence.evidence_id
            for event, persisted in zip(k1_events, persisted_k1, strict=True)
        )
        pilot_k1_expected = (
            len(k1_events) == 1
            and k1_events[0].control_id == "CTL-K1-001"
            and k1_events[0].check_status == "CHECK_PASSED"
            and k1_events[0].block_effect == "PARTIAL_BLOCK"
        )
        mapping_report = {
            "schema": "bms.w2-c2-mapping-review-report",
            "schema_version": "0.1",
            "status": "PASS",
            "run_id": base_manifest["run_id"],
            "mapping_record_id": persisted_mapping.mapping_record_id,
            "raw_record_id": persisted_mapping.raw_record_id,
            "source_system": persisted_mapping.source_system,
            "external_id": persisted_mapping.external_id,
            "object_type": persisted_mapping.object_type,
            "internal_object_id": persisted_mapping.internal_object_id,
            "mapping_status": persisted_mapping.mapping_status,
            "conflict_status": persisted_mapping.conflict_status,
            "criticality": persisted_mapping.criticality,
            "candidate_refs": list(persisted_mapping.candidate_refs),
            "review_reason": persisted_mapping.review_reason,
            "ssot_identity_created": False,
        }
        k1_report = {
            "schema": "bms.w2-c2-k1-control-report",
            "schema_version": "0.1",
            "status": (
                "PASS"
                if pilot_k1_expected and k1_traceability
                else "FAIL"
            ),
            "run_id": base_manifest["run_id"],
            "mapping_record_id": mapping.mapping_record_id,
            "controls": [
                {
                    "control_event_id": event.control_event_id,
                    "control_id": event.control_id,
                    "check_status": event.check_status,
                    "severity": event.severity,
                    "block_effect": event.block_effect,
                    "blocked_process": event.blocked_process,
                    "object_refs": list(event.object_refs),
                    "evidence_ref": event.evidence_ref,
                    "trace_refs": list(event.trace_refs),
                }
                for event in k1_events
            ],
            "traceability_pass": k1_traceability,
        }
        scope = _scope_guard(connection, repo_root)
        ssot_production_absent = (
            scope["checks"]["productive_tables_exact"]
            and scope["checks"]["forbidden_tables_absent"]
        )
        k2_events_absent = connection.execute(
            "SELECT COUNT(*) FROM control_event WHERE control_point = 'K2'"
        ).fetchone()[0] == 0
        g3_evidence_absent = not any(
            "g3" in artifact_name.lower()
            for artifact_name in (
                *reports.keys(),
                *(path.name for path in output_dir.iterdir()),
            )
        )
        smoke_checks = {
            "fixture_validation_pass": fixture_report["status"] == "PASS",
            "migration_report_pass": migration_report["status"] == "PASS",
            "k0_pass": k0_report["status"] == "PASS",
            "g1_released_for_mapping": g1["decision"] == "RELEASED_FOR_MAPPING",
            "mapping_executed": persisted_mapping.mapping_record_id == mapping.mapping_record_id,
            "mapping_review_required": persisted_mapping.mapping_status
            == "REVIEW_REQUIRED",
            "g2_expected_blocked": g2["decision"] == "BLOCKED",
            "no_automatic_ssot_identity": persisted_mapping.internal_object_id is None,
            "ssot_not_executed": ssot_production_absent,
            "k2_g3_not_executed": k2_events_absent and g3_evidence_absent,
            "only_applicable_k1_executed": [event.control_id for event in k1_events]
            == ["CTL-K1-001"],
            "k1_report_pass": k1_report["status"] == "PASS",
            "k1_traceability_pass": k1_traceability,
            "scope_guard_pass": scope["status"] == "PASS",
        }
        smoke = {
            "schema": "bms.w2-c2-smoke-report",
            "schema_version": "0.1",
            "status": "PASS" if all(smoke_checks.values()) else "FAIL",
            "run_id": base_manifest["run_id"],
            "checks": smoke_checks,
            "execution_result": "SUCCEEDED",
            "g2_gate_result": g2["decision"],
        }
        run_manifest = {
            "schema": "bms.w2-c2-run-manifest",
            "schema_version": "0.1",
            **{
                key: base_manifest[key]
                for key in (
                    "run_id",
                    "run_at",
                    "execution_status",
                    "git_commit",
                    "git_dirty",
                    "specification_manifest",
                )
            },
            "specifications": {
                "DOC-REG-001": "3.6",
                "DOC-013": "0.1",
                "DOC-014": "0.5",
                "DOC-015": "0.4",
                "DOC-016": "0.2",
            },
            "python_version": sys.version.split()[0],
            "sqlite_version": sqlite3.sqlite_version,
            "schema_migrations": [dict(row) for row in migration_rows],
            "fixture_id": imported.contract["fixture_id"],
            "fixture_sha256": imported.evidence.content_sha256,
            "import_batch_id": imported.envelope.import_batch_id,
            "evidence_id": imported.evidence.evidence_id,
            "raw_record_ids": [imported.raw_observation.raw_record_id],
            "mapping_record_ids": [mapping.mapping_record_id],
            "k0_control_event_ids": [event.control_event_id for event in k0_events],
            "k1_control_event_ids": [event.control_event_id for event in k1_events],
            "g1_decision": g1["decision"],
            "g2_decision": g2["decision"],
        }
        reports.update(
            {
                "mapping-review-report.json": mapping_report,
                "k1-control-report.json": k1_report,
                "g2-decision.json": g2,
                "scope-guard.json": scope,
                "smoke-report.json": smoke,
                "run-manifest.json": run_manifest,
            }
        )
        for name, report in reports.items():
            _write_json(output_dir / name, report)
        artifacts = []
        for name in reports:
            content = (output_dir / name).read_bytes()
            artifacts.append(
                {"path": name, "sha256": hashlib.sha256(content).hexdigest()}
            )
        evidence_index = {
            "schema": "bms.w2-c2-evidence-index",
            "schema_version": "0.1",
            "status": smoke["status"],
            "run_id": base_manifest["run_id"],
            "artifacts": artifacts,
        }
        _write_json(output_dir / "evidence-index.json", evidence_index)
        if smoke["status"] != "PASS":
            raise W2C2Error(f"W2-C2 smoke checks failed: {smoke_checks}")
        return smoke
    finally:
        connection.close()
