from __future__ import annotations

import ast
import hashlib
import json
import sqlite3
import sys
import tomllib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .control_events import ControlEvent, read_control_event, store_control_event
from .imports import FixtureImport, import_fixture, read_import_envelope, validate_fixture
from .manifests import build_run_manifest
from .persistence import apply_migrations, connect_database
from .storage import read_evidence, read_raw_observation

REQUIRED_K0_CONTROLS = (
    "CTL-K0-001",
    "CTL-K0-002",
    "CTL-K0-003",
    "CTL-K0-004",
    "CTL-K0-005",
    "CTL-K0-008",
)
EXPECTED_TABLES = {
    "schema_migrations",
    "evidence_artifact",
    "raw_observation",
    "control_event",
    "import_envelope",
}
FORBIDDEN_TABLE_FRAGMENTS = {
    "mapping",
    "identity",
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
}
FORBIDDEN_MODULES = {
    "mapping",
    "identity_matching",
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


class W2C1Error(RuntimeError):
    """Raised when C1 evidence cannot be produced from a fresh local fixture run."""


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z"
    )


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _aware_time(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None and parsed.utcoffset() is not None else None


def _event(
    connection: sqlite3.Connection,
    *,
    control_id: str,
    passed: bool,
    evidence_id: str,
    object_refs: list[str],
    expected: str,
    observed: str,
    description: str,
    trace_refs: list[str],
    severity: str,
    failure_effect: str,
    failure_process: str,
) -> ControlEvent:
    return store_control_event(
        connection,
        control_id=control_id,
        checked_at=_now(),
        object_refs=object_refs,
        control_point="K0",
        severity=severity,
        check_status="CHECK_PASSED" if passed else "CHECK_FAILED",
        observed_status=observed,
        expected_status=expected,
        description=description,
        trace_refs=[*trace_refs, "DOC-015 v0.4"],
        block_effect="NONE" if passed else failure_effect,
        blocked_process=None if passed else failure_process,
        owner_level="Rohdaten",
        resolution_status="RESOLVED" if passed else "OPEN",
        evidence_ref=evidence_id,
    )


def run_k0(
    connection: sqlite3.Connection,
    *,
    contract: dict[str, Any],
    run_id: str,
    import_batch_id: str,
    raw_record_id: str,
) -> list[ControlEvent]:
    raw = read_raw_observation(connection, raw_record_id)
    evidence = read_evidence(connection, raw.raw_payload_ref)
    envelope = read_import_envelope(connection, raw_record_id)
    refs = [
        f"run:{run_id}",
        f"import_batch:{import_batch_id}",
        f"raw_record:{raw_record_id}",
        f"evidence:{evidence.evidence_id}",
    ]
    events: list[ControlEvent] = []

    source_ok = (
        bool(raw.source_system)
        and bool(raw.source_reference)
        and raw.source_system == contract.get("source_system")
        and raw.source_reference == contract.get("source_reference")
        and envelope.source_record_id == contract.get("source_record_id")
    )
    events.append(
        _event(
            connection,
            control_id="CTL-K0-001",
            passed=source_ok,
            evidence_id=evidence.evidence_id,
            object_refs=refs,
            expected="Quelle/Nachweis vorhanden und konsistent",
            observed=(
                f"source_system={raw.source_system}; source_reference={raw.source_reference}"
            ),
            description="Quellenidentität und source_reference wurden gegen den Fixture-Contract geprüft.",
            trace_refs=["DEC-019", "REQ-NFR-007"],
            severity="CRITICAL",
            failure_effect="RELEASE_BLOCK",
            failure_process="G1 Rohdatenbatch",
        )
    )

    retrieved = _aware_time(raw.retrieved_at)
    observed = _aware_time(raw.observed_at)
    published = _aware_time(envelope.published_at) if envelope.published_at else None
    time_ok = (
        retrieved is not None
        and observed is not None
        and observed <= retrieved
        and (envelope.published_at is None or (published is not None and published <= retrieved))
        and raw.retrieved_at == contract.get("retrieved_at")
        and raw.observed_at == contract.get("observed_at")
    )
    events.append(
        _event(
            connection,
            control_id="CTL-K0-002",
            passed=time_ok,
            evidence_id=evidence.evidence_id,
            object_refs=refs,
            expected="timezone-aware Zeitbezug vorhanden und plausibel",
            observed=f"retrieved_at={raw.retrieved_at}; observed_at={raw.observed_at}",
            description="Abruf- und Beobachtungszeit wurden syntaktisch und chronologisch geprüft.",
            trace_refs=["DEC-019", "DEC-029", "TP-02"],
            severity="CRITICAL",
            failure_effect="RELEASE_BLOCK",
            failure_process="G1 Rohdatenbatch",
        )
    )

    actual_hash = hashlib.sha256(evidence.content_blob).hexdigest()
    evidence_ok = (
        raw.raw_payload_ref == evidence.evidence_id
        and raw.run_id == run_id
        and evidence.run_id == run_id
        and evidence.byte_length == len(evidence.content_blob)
        and evidence.content_sha256 == actual_hash
        and actual_hash == contract.get("sha256")
        and evidence.byte_length == contract.get("byte_length")
        and envelope.raw_value == contract.get("raw_value")
    )
    events.append(
        _event(
            connection,
            control_id="CTL-K0-003",
            passed=evidence_ok,
            evidence_id=evidence.evidence_id,
            object_refs=refs,
            expected=f"sha256={contract.get('sha256')}; byte_length={contract.get('byte_length')}",
            observed=f"sha256={actual_hash}; byte_length={len(evidence.content_blob)}",
            description="Persistierte Originalbytes, Hash, Länge, Raw-/Run-Verweise und Rohwert wurden geprüft.",
            trace_refs=["DEC-019", "TP-03"],
            severity="CRITICAL",
            failure_effect="PROCESS_BLOCK",
            failure_process=f"Rohdatenverarbeitung raw_record_id={raw_record_id}",
        )
    )

    structure_ok = False
    structure_observed = "JSON-Struktur nicht lesbar"
    try:
        parsed = json.loads(evidence.content_blob.decode(contract.get("encoding", "UTF-8")))
        structure = contract["expected_structure"]
        current: Any = parsed
        for part in structure["entity_id_path"].split("."):
            current = current[part]
        structure_ok = (
            isinstance(parsed, dict)
            and current == structure["entity_id_expected"]
            and envelope.data_type == contract.get("data_type")
        )
        structure_observed = f"{structure['entity_id_path']}={current}; data_type={envelope.data_type}"
    except (KeyError, TypeError, UnicodeDecodeError, json.JSONDecodeError, LookupError):
        pass
    events.append(
        _event(
            connection,
            control_id="CTL-K0-004",
            passed=structure_ok,
            evidence_id=evidence.evidence_id,
            object_refs=refs,
            expected=(
                f"{contract.get('expected_structure', {}).get('entity_id_path')}="
                f"{contract.get('expected_structure', {}).get('entity_id_expected')}; "
                f"data_type={contract.get('data_type')}"
            ),
            observed=structure_observed,
            description="Technische JSON-Struktur, Identitätswert und Datentyp wurden geprüft.",
            trace_refs=["REQ-DAT-001", "REQ-CTL-003"],
            severity="CRITICAL",
            failure_effect="PROCESS_BLOCK",
            failure_process=f"Importbatch import_batch_id={import_batch_id}",
        )
    )

    rows = connection.execute(
        """
        SELECT r.source_system, e.external_player_id
        FROM import_envelope e
        JOIN raw_observation r ON r.raw_record_id = e.raw_record_id
        WHERE e.import_batch_id = ?
        ORDER BY e.raw_record_id
        """,
        (import_batch_id,),
    ).fetchall()
    keys = [f"{row['source_system']}:{row['external_player_id']}" for row in rows]
    expected_keys = contract.get("critical_expected_record_keys")
    count_ok = (
        len(rows) == contract.get("critical_expected_record_count")
        and keys == expected_keys
    )
    events.append(
        _event(
            connection,
            control_id="CTL-K0-005",
            passed=count_ok,
            evidence_id=evidence.evidence_id,
            object_refs=refs,
            expected=(
                f"count={contract.get('critical_expected_record_count')}; keys={expected_keys}"
            ),
            observed=f"count={len(rows)}; keys={keys}",
            description="Kritische Sollmenge und kritische Identitätsschlüssel wurden verglichen.",
            trace_refs=["DEC-015", "REQ-CTL-001"],
            severity="CRITICAL",
            failure_effect="RELEASE_BLOCK",
            failure_process="G1 Rohdatenbatch",
        )
    )

    required_fallback_controls = {
        "CTL-K0-001",
        "CTL-K0-002",
        "CTL-K0-003",
        "CTL-K0-004",
        "CTL-K0-005",
    }
    required_fallback_refs = set(refs)
    executed_fallback_controls = {event.control_id for event in events}
    fallback_events_persisted = all(
        read_control_event(connection, event.control_event_id) == event for event in events
    )
    fallback_refs_complete = all(
        required_fallback_refs.issubset(event.object_refs)
        and event.evidence_ref == evidence.evidence_id
        for event in events
    )
    fallback_ok = (
        envelope.import_method == "SAVED_SOURCE"
        and executed_fallback_controls == required_fallback_controls
        and fallback_events_persisted
        and fallback_refs_complete
    )
    events.append(
        _event(
            connection,
            control_id="CTL-K0-008",
            passed=fallback_ok,
            evidence_id=evidence.evidence_id,
            object_refs=refs,
            expected="SAVED_SOURCE mit gleichwertigem Quellen-, Zeit-, Typ-, Evidence- und Vollständigkeitsnachweis",
            observed=(
                f"import_method={envelope.import_method}; "
                f"executed_controls={sorted(executed_fallback_controls)}; "
                f"persisted={fallback_events_persisted}; refs_complete={fallback_refs_complete}"
            ),
            description="Der dateibasierte Fallback wurde anhand der tatsächlich ausgeführten K0-Nachweise geprüft.",
            trace_refs=["DEC-019", "CON-002"],
            severity="CRITICAL",
            failure_effect="RELEASE_BLOCK",
            failure_process="G1 Rohdatenbatch",
        )
    )
    return events


def derive_g1(
    connection: sqlite3.Connection,
    *,
    run_id: str,
    import_batch_id: str,
    control_event_ids: list[str],
    raw_record_ids: list[str],
    evidence_ids: list[str],
) -> dict[str, Any]:
    events = [read_control_event(connection, event_id) for event_id in control_event_ids]
    controls = {event.control_id: event for event in events}
    complete = set(controls) == set(REQUIRED_K0_CONTROLS) and len(events) == len(
        REQUIRED_K0_CONTROLS
    )
    required_object_refs = {
        f"run:{run_id}",
        f"import_batch:{import_batch_id}",
        *(f"raw_record:{raw_id}" for raw_id in raw_record_ids),
        *(f"evidence:{evidence_id}" for evidence_id in evidence_ids),
    }
    controls_match_context = complete and all(
        event.control_point == "K0"
        and required_object_refs.issubset(event.object_refs)
        and event.evidence_ref in evidence_ids
        for event in events
    )
    all_passed = complete and all(
        controls[control_id].check_status == "CHECK_PASSED"
        for control_id in REQUIRED_K0_CONTROLS
    )
    no_critical_open_failure = not any(
        event.severity == "CRITICAL"
        and event.check_status in {"CHECK_PENDING", "CHECK_FAILED", "NOT_CHECKED"}
        for event in events
    )
    released = (
        complete and controls_match_context and all_passed and no_critical_open_failure
    )
    return {
        "schema": "bms.w2-c1-g1-decision",
        "schema_version": "0.1",
        "run_id": run_id,
        "import_batch_id": import_batch_id,
        "decision": "RELEASED_FOR_MAPPING" if released else "BLOCKED",
        "evaluated_control_event_ids": control_event_ids,
        "raw_record_ids": raw_record_ids,
        "evidence_ids": evidence_ids,
        "derivation": {
            "required_control_ids": list(REQUIRED_K0_CONTROLS),
            "required_controls_complete": complete,
            "controls_match_run_import_raw_and_evidence": controls_match_context,
            "all_required_controls_passed": all_passed,
            "no_open_critical_k0_deviation": no_critical_open_failure,
            "reason": (
                "Alle einschlägigen Pflicht-K0 sind vollständig persistiert und bestanden."
                if released
                else "Mindestens ein Pflicht-K0 fehlt, ist nicht bestanden oder kritisch offen."
            ),
        },
    }


def _scope_guard(connection: sqlite3.Connection, repo_root: Path) -> dict[str, Any]:
    tables = {
        row["name"]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        )
    }
    modules = {path.stem for path in (repo_root / "bms").glob("*.py")}
    imports: set[str] = set()
    for path in (repo_root / "bms").glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.update(alias.name.split(".", 1)[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                imports.add(node.module.split(".", 1)[0])
    migrations = sorted(path.name for path in (repo_root / "migrations").glob("*.sql"))
    dependencies = tomllib.loads((repo_root / "pyproject.toml").read_text(encoding="utf-8"))[
        "project"
    ].get("dependencies", [])
    forbidden_tables = sorted(
        table
        for table in tables
        if table != "import_envelope"
        and any(fragment in table for fragment in FORBIDDEN_TABLE_FRAGMENTS)
    )
    checks = {
        "productive_tables_exact": tables == EXPECTED_TABLES,
        "migrations_exact": migrations
        == [
            "0001_raw_evidence.sql",
            "0002_control_event.sql",
            "0003_import_envelope.sql",
        ],
        "no_migration_0004": not any(name.startswith("0004_") for name in migrations),
        "forbidden_tables_absent": not forbidden_tables,
        "forbidden_modules_absent": FORBIDDEN_MODULES.isdisjoint(modules),
        "network_imports_absent": NETWORK_IMPORT_ROOTS.isdisjoint(imports),
        "stdlib_only": not (imports - sys.stdlib_module_names) and dependencies == [],
    }
    return {
        "schema": "bms.w2-c1-scope-guard",
        "schema_version": "0.1",
        "status": "PASS" if all(checks.values()) else "FAIL",
        "checks": checks,
        "productive_tables": sorted(tables),
        "productive_migrations": migrations,
        "forbidden_tables_present": forbidden_tables,
        "forbidden_modules_present": sorted(FORBIDDEN_MODULES & modules),
    }


def _prepare_output(output_dir: Path) -> None:
    if output_dir.exists() and not output_dir.is_dir():
        raise W2C1Error(f"output path is not a directory: {output_dir}")
    if output_dir.exists() and any(output_dir.iterdir()):
        raise W2C1Error(f"output directory is not empty and will not be reused: {output_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)


def run_w2_c1_smoke(
    fixture_dir: Path, output_dir: Path, *, repo_root: Path
) -> dict[str, Any]:
    _prepare_output(output_dir)
    validated = validate_fixture(fixture_dir)
    database_path = output_dir / "w2-c1.sqlite3"
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
        expected_migrations = [
            "0001_raw_evidence",
            "0002_control_event",
            "0003_import_envelope",
        ]
        migration_report = {
            "schema": "bms.w2-c1-migration-report",
            "schema_version": "0.1",
            "status": "PASS" if applied == expected_migrations else "FAIL",
            "fresh_database": True,
            "applied_migrations": [dict(row) for row in migration_rows],
        }
        imported: FixtureImport = import_fixture(
            connection, fixture_dir=fixture_dir, run_id=base_manifest["run_id"]
        )
        events = run_k0(
            connection,
            contract=imported.contract,
            run_id=base_manifest["run_id"],
            import_batch_id=imported.envelope.import_batch_id,
            raw_record_id=imported.raw_observation.raw_record_id,
        )
        event_ids = [event.control_event_id for event in events]
        g1 = derive_g1(
            connection,
            run_id=base_manifest["run_id"],
            import_batch_id=imported.envelope.import_batch_id,
            control_event_ids=event_ids,
            raw_record_ids=[imported.raw_observation.raw_record_id],
            evidence_ids=[imported.evidence.evidence_id],
        )
        loaded_raw = read_raw_observation(connection, imported.raw_observation.raw_record_id)
        loaded_evidence = read_evidence(connection, imported.evidence.evidence_id)
        loaded_envelope = read_import_envelope(connection, loaded_raw.raw_record_id)
        traceability = {
            "raw_to_evidence": loaded_raw.raw_payload_ref == loaded_evidence.evidence_id,
            "raw_to_run": loaded_raw.run_id == base_manifest["run_id"],
            "evidence_to_run": loaded_evidence.run_id == base_manifest["run_id"],
            "envelope_to_raw": loaded_envelope.raw_record_id == loaded_raw.raw_record_id,
            "controls_to_evidence": all(
                event.evidence_ref == loaded_evidence.evidence_id for event in events
            ),
            "controls_persisted": all(
                read_control_event(connection, event.control_event_id) == event for event in events
            ),
        }
        scope = _scope_guard(connection, repo_root)
        fixture_report = {
            "schema": "bms.w2-c1-fixture-validation",
            "schema_version": "0.1",
            "status": "PASS",
            "fixture_id": imported.contract["fixture_id"],
            "source_file": imported.contract["source_file"],
            "sha256": validated["sha256"],
            "byte_length": validated["byte_length"],
            "expected_structure": imported.contract["expected_structure"],
        }
        import_report = {
            "schema": "bms.w2-c1-import-report",
            "schema_version": "0.1",
            "status": "PASS" if all(traceability.values()) else "FAIL",
            "run_id": base_manifest["run_id"],
            "fixture_id": imported.contract["fixture_id"],
            "import_batch_id": imported.envelope.import_batch_id,
            "evidence_id": imported.evidence.evidence_id,
            "raw_record_ids": [imported.raw_observation.raw_record_id],
            "mapping_status": imported.envelope.mapping_status,
            "check_status": imported.envelope.check_status,
            "information_status": imported.envelope.information_status,
            "conflict_status": imported.envelope.conflict_status,
            "assertion_status": imported.envelope.assertion_status,
            "traceability": traceability,
        }
        k0_report = {
            "schema": "bms.w2-c1-k0-control-report",
            "schema_version": "0.1",
            "status": (
                "PASS" if all(e.check_status == "CHECK_PASSED" for e in events) else "FAIL"
            ),
            "run_id": base_manifest["run_id"],
            "import_batch_id": imported.envelope.import_batch_id,
            "controls": [
                {
                    "control_event_id": event.control_event_id,
                    "control_id": event.control_id,
                    "check_status": event.check_status,
                    "severity": event.severity,
                    "block_effect": event.block_effect,
                    "observed_status": event.observed_status,
                    "expected_status": event.expected_status,
                    "evidence_ref": event.evidence_ref,
                    "object_refs": list(event.object_refs),
                    "trace_refs": list(event.trace_refs),
                }
                for event in events
            ],
        }
        run_manifest = {
            "schema": "bms.w2-c1-run-manifest",
            "schema_version": "0.1",
            **{key: base_manifest[key] for key in (
                "run_id", "run_at", "execution_status", "git_commit", "git_dirty",
                "specification_manifest",
            )},
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
            "control_event_ids": event_ids,
            "g1_decision": g1["decision"],
        }
        smoke_checks = {
            "migration_report_pass": migration_report["status"] == "PASS",
            "fixture_validation_pass": fixture_report["status"] == "PASS",
            "import_traceability_pass": import_report["status"] == "PASS",
            "all_required_k0_executed": [event.control_id for event in events]
            == list(REQUIRED_K0_CONTROLS),
            "k0_pass": k0_report["status"] == "PASS",
            "g1_released_for_mapping": g1["decision"] == "RELEASED_FOR_MAPPING",
            "scope_guard_pass": scope["status"] == "PASS",
            "mapping_not_executed": imported.envelope.mapping_status == "UNMAPPED",
            "status_dimensions_preserved": (
                imported.envelope.check_status == "CHECK_PENDING"
                and imported.envelope.conflict_status == "NOT_CHECKED"
                and imported.envelope.assertion_status is None
            ),
        }
        smoke = {
            "schema": "bms.w2-c1-smoke-report",
            "schema_version": "0.1",
            "status": "PASS" if all(smoke_checks.values()) else "FAIL",
            "run_id": base_manifest["run_id"],
            "checks": smoke_checks,
        }

        reports = {
            "fixture-validation.json": fixture_report,
            "import-report.json": import_report,
            "k0-control-report.json": k0_report,
            "g1-decision.json": g1,
            "run-manifest.json": run_manifest,
            "migration-report.json": migration_report,
            "scope-guard.json": scope,
            "smoke-report.json": smoke,
        }
        for name, report in reports.items():
            _write_json(output_dir / name, report)
        index_artifacts = []
        for name in reports:
            content = (output_dir / name).read_bytes()
            index_artifacts.append(
                {"path": name, "sha256": hashlib.sha256(content).hexdigest()}
            )
        index = {
            "schema": "bms.w2-c1-evidence-index",
            "schema_version": "0.1",
            "status": "PASS" if smoke["status"] == "PASS" else "FAIL",
            "run_id": base_manifest["run_id"],
            "artifacts": index_artifacts,
        }
        _write_json(output_dir / "evidence-index.json", index)
        if smoke["status"] != "PASS":
            raise W2C1Error(f"W2-C1 smoke checks failed: {smoke_checks}")
        return smoke
    finally:
        connection.close()
