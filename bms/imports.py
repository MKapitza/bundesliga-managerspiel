from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .storage import (
    EvidenceArtifact,
    RawObservation,
    store_evidence,
    store_raw_observation,
)


class FixtureValidationError(ValueError):
    """Raised when archived source bytes do not satisfy their fixture contract."""


@dataclass(frozen=True)
class ImportEnvelope:
    raw_record_id: str
    import_batch_id: str
    source_record_id: str | None
    published_at: str | None
    effective_from: str | None
    effective_to: str | None
    season_id_ref: str | None
    season_label_raw: str | None
    gameweek_raw: str | None
    match_ref_raw: str | None
    external_player_id: str | None
    external_club_id: str | None
    player_name_raw: str | None
    club_name_raw: str | None
    data_type: str
    raw_label: str
    raw_value: str | None
    mapping_status: str
    check_status: str
    information_status: str
    conflict_status: str
    transformation_log_ref: str | None
    target_object_type: str
    import_method: str
    assertion_status: str | None
    created_at: str


@dataclass(frozen=True)
class FixtureImport:
    contract: dict[str, Any]
    source_path: Path
    source_bytes: bytes
    parsed_source: dict[str, Any]
    evidence: EvidenceArtifact
    raw_observation: RawObservation
    envelope: ImportEnvelope


def _created_at() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z"
    )


def _json_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise FixtureValidationError(f"fixture file not found: {path}") from exc
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise FixtureValidationError(f"invalid UTF-8 JSON: {path}") from exc
    if not isinstance(value, dict):
        raise FixtureValidationError(f"JSON root must be an object: {path}")
    return value


def _path_value(value: Any, dotted_path: str) -> Any:
    current = value
    for component in dotted_path.split("."):
        if not isinstance(current, dict) or component not in current:
            raise FixtureValidationError(f"missing expected JSON path: {dotted_path}")
        current = current[component]
    return current


def validate_fixture(fixture_dir: Path) -> dict[str, Any]:
    contract_path = fixture_dir / "fixture_contract.json"
    contract = _json_object(contract_path)
    if contract.get("schema") != "bms.w2-pilot-fixture-contract":
        raise FixtureValidationError("unexpected fixture contract schema")
    if contract.get("schema_version") != "0.1":
        raise FixtureValidationError("unexpected fixture contract schema_version")
    source_file = contract.get("source_file")
    if not isinstance(source_file, str) or not source_file:
        raise FixtureValidationError("source_file must be a non-empty string")
    source_path = fixture_dir / source_file
    try:
        source_bytes = source_path.read_bytes()
    except FileNotFoundError as exc:
        raise FixtureValidationError(f"fixture source not found: {source_path}") from exc
    actual_hash = hashlib.sha256(source_bytes).hexdigest()
    actual_length = len(source_bytes)
    if actual_hash != contract.get("sha256"):
        raise FixtureValidationError("fixture SHA-256 does not match contract")
    if actual_length != contract.get("byte_length"):
        raise FixtureValidationError("fixture byte length does not match contract")
    try:
        parsed = json.loads(source_bytes.decode(contract.get("encoding", "UTF-8")))
    except (LookupError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise FixtureValidationError("fixture source is not valid contract-encoded JSON") from exc
    structure = contract.get("expected_structure")
    if not isinstance(structure, dict) or structure.get("root_type") != "object":
        raise FixtureValidationError("unsupported or missing expected_structure")
    if not isinstance(parsed, dict):
        raise FixtureValidationError("fixture JSON root is not an object")
    path = structure.get("entity_id_path")
    if not isinstance(path, str) or _path_value(parsed, path) != structure.get(
        "entity_id_expected"
    ):
        raise FixtureValidationError("fixture entity identity does not match expected_structure")
    return {
        "contract": contract,
        "contract_path": contract_path,
        "source_path": source_path,
        "source_bytes": source_bytes,
        "parsed_source": parsed,
        "sha256": actual_hash,
        "byte_length": actual_length,
    }


def store_import_envelope(
    connection: sqlite3.Connection,
    *,
    raw_record_id: str,
    import_batch_id: str,
    contract: dict[str, Any],
) -> ImportEnvelope:
    values = {
        "raw_record_id": raw_record_id,
        "import_batch_id": import_batch_id,
        "source_record_id": contract.get("source_record_id"),
        "published_at": contract.get("published_at"),
        "effective_from": contract.get("effective_from"),
        "effective_to": contract.get("effective_to"),
        "season_id_ref": contract.get("season_id_ref"),
        "season_label_raw": contract.get("season_label_raw"),
        "gameweek_raw": contract.get("gameweek_raw"),
        "match_ref_raw": contract.get("match_ref_raw"),
        "external_player_id": contract.get("external_player_id"),
        "external_club_id": contract.get("external_club_id"),
        "player_name_raw": contract.get("player_name_raw"),
        "club_name_raw": contract.get("club_name_raw"),
        "data_type": contract["data_type"],
        "raw_label": contract["raw_label"],
        "raw_value": contract.get("raw_value"),
        "mapping_status": contract["mapping_status"],
        "check_status": contract["check_status"],
        "information_status": contract["information_status"],
        "conflict_status": contract["conflict_status"],
        "transformation_log_ref": contract.get("transformation_log_ref"),
        "target_object_type": contract["target_object_type"],
        "import_method": contract["import_method"],
        "assertion_status": contract.get("assertion_status"),
        "created_at": _created_at(),
    }
    columns = tuple(values)
    connection.execute(
        f"INSERT INTO import_envelope ({','.join(columns)}) VALUES ({','.join('?' for _ in columns)})",
        tuple(values[column] for column in columns),
    )
    return ImportEnvelope(**values)


def read_import_envelope(
    connection: sqlite3.Connection, raw_record_id: str
) -> ImportEnvelope:
    row = connection.execute(
        "SELECT * FROM import_envelope WHERE raw_record_id = ?", (raw_record_id,)
    ).fetchone()
    if row is None:
        raise KeyError(f"unknown import envelope raw_record_id: {raw_record_id}")
    return ImportEnvelope(**dict(row))


def import_fixture(
    connection: sqlite3.Connection, *, fixture_dir: Path, run_id: str
) -> FixtureImport:
    validated = validate_fixture(fixture_dir)
    contract = validated["contract"]
    import_batch_id = str(uuid.uuid4())
    evidence = store_evidence(
        connection,
        content=validated["source_bytes"],
        run_id=run_id,
        media_type=contract["media_type"],
    )
    raw = store_raw_observation(
        connection,
        source_system=contract["source_system"],
        source_reference=contract["source_reference"],
        retrieved_at=contract["retrieved_at"],
        observed_at=contract["observed_at"],
        raw_payload_ref=evidence.evidence_id,
        run_id=run_id,
    )
    envelope = store_import_envelope(
        connection,
        raw_record_id=raw.raw_record_id,
        import_batch_id=import_batch_id,
        contract=contract,
    )
    return FixtureImport(
        contract=contract,
        source_path=validated["source_path"],
        source_bytes=validated["source_bytes"],
        parsed_source=validated["parsed_source"],
        evidence=evidence,
        raw_observation=raw,
        envelope=envelope,
    )
