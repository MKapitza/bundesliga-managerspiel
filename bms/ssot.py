from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .mapping import MappingRecord, read_mapping_record, store_mapping_record
from .storage import EvidenceArtifact, read_evidence, read_raw_observation, store_evidence


@dataclass(frozen=True)
class IdentityLegitimation:
    legitimation_ref: str
    run_id: str
    object_type: str
    decision_status: str
    decided_at: str
    authorized_by: str
    resulting_internal_object_id: str
    evidence_refs: tuple[str, ...]
    created_at: str


@dataclass(frozen=True)
class SSOTPlayer:
    player_id: str
    display_name: str
    given_name: str | None
    family_name: str | None
    identity_status: str
    legitimation_ref: str
    legitimized_at: str
    created_at: str


@dataclass(frozen=True)
class SSOTClub:
    club_id: str
    club_name: str
    short_name: str | None
    identity_status: str
    legitimation_ref: str
    legitimized_at: str
    created_at: str


@dataclass(frozen=True)
class SSOTVersion:
    ssot_version_id: str
    run_id: str
    data_as_of: str
    released_at: str | None
    predecessor_ssot_version_id: str | None
    change_ref: str
    release_evidence_ref: str | None
    state: dict[str, Any]
    created_at: str


@dataclass(frozen=True)
class AuthorizedPlayerBootstrap:
    legitimation: IdentityLegitimation
    player: SSOTPlayer
    mapping: MappingRecord


@dataclass(frozen=True)
class EvidenceReference:
    evidence_ref: str
    evidence_id: str
    artifact_path: str
    manifest_sha256: str
    manifest_byte_length: int
    media_type: str
    source_reference: str
    representation_type: str
    created_at: str


class IdentityLegitimationConflictError(ValueError):
    """Raised when an existing legitimation reference is reused inconsistently."""


class EvidenceManifestError(ValueError):
    """Raised when evidence provenance cannot be reproduced from its manifest."""


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z"
    )


def _validate_time(value: str, field_name: str) -> None:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{field_name} must be a valid ISO-8601 timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field_name} must include a timezone offset")


def _nonempty(value: str, field_name: str) -> None:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    if not value:
        raise ValueError(f"{field_name} must be non-empty")


def read_evidence_reference(
    connection: sqlite3.Connection, evidence_ref: str
) -> EvidenceReference:
    row = connection.execute(
        "SELECT * FROM ssot_evidence_reference WHERE evidence_ref = ?",
        (evidence_ref,),
    ).fetchone()
    if row is None:
        raise KeyError(f"unknown evidence_ref: {evidence_ref}")
    return EvidenceReference(**dict(row))


def resolve_evidence_reference(
    connection: sqlite3.Connection, evidence_ref: str
) -> EvidenceArtifact:
    binding = connection.execute(
        """
        SELECT evidence_id, manifest_sha256, manifest_byte_length
        FROM ssot_evidence_reference WHERE evidence_ref = ?
        """,
        (evidence_ref,),
    ).fetchone()
    evidence_id = binding["evidence_id"] if binding is not None else evidence_ref
    try:
        artifact = read_evidence(connection, evidence_id)
    except KeyError as exc:
        raise EvidenceManifestError(
            f"unresolved evidence_ref: {evidence_ref}"
        ) from exc
    actual_hash = hashlib.sha256(artifact.content_blob).hexdigest()
    if actual_hash != artifact.content_sha256 or len(artifact.content_blob) != artifact.byte_length:
        raise EvidenceManifestError(f"stored evidence artifact is inconsistent: {evidence_ref}")
    if binding is not None and (
        binding["manifest_sha256"] != actual_hash
        or binding["manifest_byte_length"] != len(artifact.content_blob)
    ):
        raise EvidenceManifestError(
            f"evidence artifact does not match manifest: {evidence_ref}"
        )
    return artifact


def register_evidence_manifest(
    connection: sqlite3.Connection, *, manifest_path: Path, run_id: str
) -> tuple[EvidenceReference, ...]:
    """Verify and persist an immutable ref-to-artifact binding."""
    _nonempty(run_id, "run_id")
    try:
        manifest = json.loads(manifest_path.read_bytes())
    except FileNotFoundError as exc:
        raise EvidenceManifestError(f"evidence manifest not found: {manifest_path}") from exc
    except json.JSONDecodeError as exc:
        raise EvidenceManifestError("evidence manifest is not valid JSON") from exc
    if not isinstance(manifest, dict) or manifest.get("schema") != "bms.seed-evidence-manifest":
        raise EvidenceManifestError("unexpected evidence manifest schema")
    if manifest.get("schema_version") != "1.0":
        raise EvidenceManifestError("unexpected evidence manifest schema_version")
    entries = manifest.get("evidence")
    if not isinstance(entries, list) or not entries:
        raise EvidenceManifestError("evidence manifest must contain entries")

    root = manifest_path.parent.resolve()
    verified: list[tuple[dict[str, Any], bytes]] = []
    refs: set[str] = set()
    paths: set[str] = set()
    for entry in entries:
        if not isinstance(entry, dict):
            raise EvidenceManifestError("evidence manifest entry must be an object")
        for field in (
            "evidence_ref", "artifact_path", "sha256", "media_type",
            "source_reference", "representation_type", "representation_status",
            "confirmation",
        ):
            if not isinstance(entry.get(field), str) or not entry[field]:
                raise EvidenceManifestError(f"evidence manifest field is invalid: {field}")
        if not isinstance(entry.get("byte_length"), int) or entry["byte_length"] < 0:
            raise EvidenceManifestError("evidence manifest byte_length is invalid")
        if entry["representation_status"] != "CONFIRMED":
            raise EvidenceManifestError("evidence representation is not confirmed")
        if entry["evidence_ref"] not in entry["confirmation"]:
            raise EvidenceManifestError("manifest confirmation does not match evidence_ref")
        if entry["evidence_ref"] in refs:
            raise EvidenceManifestError("evidence_ref is not unique")
        if entry["artifact_path"] in paths:
            raise EvidenceManifestError("artifact_path is not unique")
        refs.add(entry["evidence_ref"])
        paths.add(entry["artifact_path"])

        artifact_path = (root / entry["artifact_path"]).resolve()
        if not artifact_path.is_relative_to(root):
            raise EvidenceManifestError("artifact_path escapes evidence package")
        try:
            content = artifact_path.read_bytes()
        except FileNotFoundError as exc:
            raise EvidenceManifestError(
                f"evidence artifact not found: {entry['artifact_path']}"
            ) from exc
        if hashlib.sha256(content).hexdigest() != entry["sha256"]:
            raise EvidenceManifestError(
                f"evidence artifact SHA-256 mismatch: {entry['evidence_ref']}"
            )
        if len(content) != entry["byte_length"]:
            raise EvidenceManifestError(
                f"evidence artifact byte length mismatch: {entry['evidence_ref']}"
            )
        if entry["representation_type"] == "CANONICAL_MANUAL_WEB_EVIDENCE_RECORD":
            try:
                canonical_record = json.loads(content)
            except json.JSONDecodeError as exc:
                raise EvidenceManifestError("canonical evidence record is not valid JSON") from exc
            if not isinstance(canonical_record, dict) or canonical_record.get(
                "evidence_ref"
            ) != entry["evidence_ref"]:
                raise EvidenceManifestError(
                    "canonical evidence record does not match evidence_ref"
                )
        verified.append((entry, content))

    connection.execute("SAVEPOINT register_evidence_manifest")
    try:
        result: list[EvidenceReference] = []
        for entry, content in verified:
            existing = connection.execute(
                "SELECT * FROM ssot_evidence_reference WHERE evidence_ref = ?",
                (entry["evidence_ref"],),
            ).fetchone()
            if existing is not None:
                binding = EvidenceReference(**dict(existing))
                basis = {
                    "artifact_path": entry["artifact_path"],
                    "manifest_sha256": entry["sha256"],
                    "manifest_byte_length": entry["byte_length"],
                    "media_type": entry["media_type"],
                    "source_reference": entry["source_reference"],
                    "representation_type": entry["representation_type"],
                }
                if any(getattr(binding, field) != value for field, value in basis.items()):
                    raise EvidenceManifestError(
                        f"evidence_ref is already bound differently: {entry['evidence_ref']}"
                    )
                resolve_evidence_reference(connection, entry["evidence_ref"])
                result.append(binding)
                continue

            candidates = connection.execute(
                """
                SELECT evidence_id FROM evidence_artifact
                WHERE content_sha256 = ? AND byte_length = ? AND media_type = ?
                  AND content_blob = ?
                ORDER BY created_at, evidence_id
                """,
                (entry["sha256"], entry["byte_length"], entry["media_type"], content),
            ).fetchall()
            if candidates:
                artifact = read_evidence(connection, candidates[0]["evidence_id"])
            else:
                artifact = store_evidence(
                    connection, content=content, run_id=run_id,
                    media_type=entry["media_type"],
                )
            binding = EvidenceReference(
                evidence_ref=entry["evidence_ref"],
                evidence_id=artifact.evidence_id,
                artifact_path=entry["artifact_path"],
                manifest_sha256=entry["sha256"],
                manifest_byte_length=entry["byte_length"],
                media_type=entry["media_type"],
                source_reference=entry["source_reference"],
                representation_type=entry["representation_type"],
                created_at=_now(),
            )
            connection.execute(
                "INSERT INTO ssot_evidence_reference VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                tuple(binding.__dict__.values()),
            )
            result.append(binding)
        connection.execute("RELEASE register_evidence_manifest")
        return tuple(result)
    except Exception:
        connection.execute("ROLLBACK TO register_evidence_manifest")
        connection.execute("RELEASE register_evidence_manifest")
        raise


def store_identity_legitimation(
    connection: sqlite3.Connection,
    *,
    run_id: str,
    object_type: str,
    decided_at: str,
    authorized_by: str,
    resulting_internal_object_id: str,
    evidence_refs: Sequence[str],
    legitimation_ref: str,
) -> IdentityLegitimation:
    _validate_time(decided_at, "decided_at")
    for value, name in (
        (run_id, "run_id"),
        (authorized_by, "authorized_by"),
        (resulting_internal_object_id, "resulting_internal_object_id"),
        (legitimation_ref, "legitimation_ref"),
    ):
        _nonempty(value, name)
    if isinstance(evidence_refs, (str, bytes, bytearray)) or not isinstance(
        evidence_refs, Sequence
    ):
        raise TypeError("evidence_refs must be a sequence of strings")
    supplied_evidence = tuple(evidence_refs)
    if not supplied_evidence or any(
        not isinstance(item, str) or not item for item in supplied_evidence
    ):
        raise ValueError("evidence_refs must contain non-empty strings")
    if len(set(supplied_evidence)) != len(supplied_evidence):
        raise ValueError("evidence_refs must not contain duplicates")
    for evidence_ref in supplied_evidence:
        resolve_evidence_reference(connection, evidence_ref)
    evidence = tuple(sorted(supplied_evidence))
    record = IdentityLegitimation(
        legitimation_ref=legitimation_ref,
        run_id=run_id,
        object_type=object_type,
        decision_status="IDENTITY_LEGITIMATED",
        decided_at=decided_at,
        authorized_by=authorized_by,
        resulting_internal_object_id=resulting_internal_object_id,
        evidence_refs=evidence,
        created_at=_now(),
    )
    existing_row = connection.execute(
        "SELECT 1 FROM ssot_identity_legitimation WHERE legitimation_ref = ?",
        (legitimation_ref,),
    ).fetchone()
    if existing_row is not None:
        existing = read_identity_legitimation(connection, legitimation_ref)
        replay_basis = (
            "object_type", "decision_status", "decided_at", "authorized_by",
            "resulting_internal_object_id", "evidence_refs",
        )
        if all(getattr(existing, field) == getattr(record, field) for field in replay_basis):
            return existing
        raise IdentityLegitimationConflictError(
            f"legitimation_ref is already used with a different decision basis: {legitimation_ref}"
        )
    evidence_json = json.dumps(evidence, ensure_ascii=False, separators=(",", ":"))
    connection.execute(
        """
        INSERT INTO ssot_identity_legitimation (
            legitimation_ref, run_id, object_type, decision_status, decided_at,
            authorized_by, evidence_refs_json, resulting_internal_object_id,
            created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            record.legitimation_ref, record.run_id, record.object_type,
            record.decision_status, record.decided_at, record.authorized_by,
            evidence_json, record.resulting_internal_object_id, record.created_at,
        ),
    )
    return record


def read_identity_legitimation(
    connection: sqlite3.Connection, legitimation_ref: str
) -> IdentityLegitimation:
    row = connection.execute(
        "SELECT * FROM ssot_identity_legitimation WHERE legitimation_ref = ?",
        (legitimation_ref,),
    ).fetchone()
    if row is None:
        raise KeyError(f"unknown legitimation_ref: {legitimation_ref}")
    values = dict(row)
    try:
        decoded_evidence = json.loads(values.pop("evidence_refs_json"))
    except (TypeError, json.JSONDecodeError) as exc:
        raise ValueError("stored legitimation evidence bundle is invalid") from exc
    if (
        not isinstance(decoded_evidence, list)
        or not decoded_evidence
        or any(not isinstance(item, str) or not item for item in decoded_evidence)
        or len(set(decoded_evidence)) != len(decoded_evidence)
    ):
        raise ValueError("stored legitimation evidence bundle is invalid")
    evidence = tuple(decoded_evidence)
    return IdentityLegitimation(**values, evidence_refs=evidence)


def store_ssot_player(
    connection: sqlite3.Connection,
    *,
    player_id: str,
    display_name: str,
    legitimation_ref: str,
    legitimized_at: str,
    given_name: str | None = None,
    family_name: str | None = None,
) -> SSOTPlayer:
    _validate_time(legitimized_at, "legitimized_at")
    for value, name in (
        (player_id, "player_id"),
        (display_name, "display_name"),
        (legitimation_ref, "legitimation_ref"),
    ):
        _nonempty(value, name)
    record = SSOTPlayer(
        player_id=player_id, display_name=display_name, given_name=given_name,
        family_name=family_name, identity_status="IDENTITY_LEGITIMATED",
        legitimation_ref=legitimation_ref, legitimized_at=legitimized_at,
        created_at=_now(),
    )
    existing_rows = connection.execute(
        "SELECT * FROM ssot_player WHERE player_id = ? OR legitimation_ref = ?",
        (player_id, legitimation_ref),
    ).fetchall()
    if existing_rows:
        if len(existing_rows) == 1:
            existing = SSOTPlayer(**dict(existing_rows[0]))
            replay_basis = (
                "player_id", "display_name", "given_name", "family_name",
                "identity_status", "legitimation_ref", "legitimized_at",
            )
            if all(getattr(existing, field) == getattr(record, field) for field in replay_basis):
                return existing
        raise IdentityLegitimationConflictError(
            f"player identity replay conflicts with persisted identity: {player_id}"
        )
    connection.execute(
        "INSERT INTO ssot_player VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        tuple(record.__dict__.values()),
    )
    return record


def read_ssot_player(connection: sqlite3.Connection, player_id: str) -> SSOTPlayer:
    row = connection.execute(
        "SELECT * FROM ssot_player WHERE player_id = ?", (player_id,)
    ).fetchone()
    if row is None:
        raise KeyError(f"unknown player_id: {player_id}")
    return SSOTPlayer(**dict(row))


def store_ssot_club(
    connection: sqlite3.Connection,
    *,
    club_id: str,
    club_name: str,
    legitimation_ref: str,
    legitimized_at: str,
    short_name: str | None = None,
) -> SSOTClub:
    _validate_time(legitimized_at, "legitimized_at")
    for value, name in (
        (club_id, "club_id"),
        (club_name, "club_name"),
        (legitimation_ref, "legitimation_ref"),
    ):
        _nonempty(value, name)
    record = SSOTClub(
        club_id=club_id, club_name=club_name, short_name=short_name,
        identity_status="IDENTITY_LEGITIMATED", legitimation_ref=legitimation_ref,
        legitimized_at=legitimized_at, created_at=_now(),
    )
    existing_rows = connection.execute(
        "SELECT * FROM ssot_club WHERE club_id = ? OR legitimation_ref = ?",
        (club_id, legitimation_ref),
    ).fetchall()
    if existing_rows:
        if len(existing_rows) == 1:
            existing = SSOTClub(**dict(existing_rows[0]))
            replay_basis = (
                "club_id", "club_name", "short_name", "identity_status",
                "legitimation_ref", "legitimized_at",
            )
            if all(getattr(existing, field) == getattr(record, field) for field in replay_basis):
                return existing
        raise IdentityLegitimationConflictError(
            f"club identity replay conflicts with persisted identity: {club_id}"
        )
    connection.execute(
        "INSERT INTO ssot_club VALUES (?, ?, ?, ?, ?, ?, ?)",
        tuple(record.__dict__.values()),
    )
    return record


def read_ssot_club(connection: sqlite3.Connection, club_id: str) -> SSOTClub:
    row = connection.execute(
        "SELECT * FROM ssot_club WHERE club_id = ?", (club_id,)
    ).fetchone()
    if row is None:
        raise KeyError(f"unknown club_id: {club_id}")
    return SSOTClub(**dict(row))


def store_authorized_player_bootstrap(
    connection: sqlite3.Connection,
    *,
    run_id: str,
    legitimation_ref: str,
    decided_at: str,
    authorized_by: str,
    player_id: str,
    display_name: str,
    evidence_refs: Sequence[str],
    raw_record_id: str,
    source_system: str,
    external_id: str,
    confirmation_evidence_ref: str,
    given_name: str | None = None,
    family_name: str | None = None,
) -> AuthorizedPlayerBootstrap:
    """Persist an already authorized positive player bootstrap atomically."""
    if confirmation_evidence_ref not in evidence_refs:
        raise ValueError("confirmation_evidence_ref must belong to the evidence bundle")
    raw = read_raw_observation(connection, raw_record_id)
    if raw.source_system != source_system:
        raise ValueError("source_system must match the referenced raw observation")
    confirmation_artifact = resolve_evidence_reference(
        connection, confirmation_evidence_ref
    )
    if confirmation_artifact.evidence_id != raw.raw_payload_ref:
        raise ValueError(
            "confirmation_evidence_ref must resolve to the mapped raw evidence artifact"
        )

    connection.execute("SAVEPOINT store_authorized_player_bootstrap")
    try:
        legitimation = store_identity_legitimation(
            connection,
            run_id=run_id,
            object_type="PLAYER",
            decided_at=decided_at,
            authorized_by=authorized_by,
            resulting_internal_object_id=player_id,
            evidence_refs=evidence_refs,
            legitimation_ref=legitimation_ref,
        )
        player = store_ssot_player(
            connection,
            player_id=player_id,
            display_name=display_name,
            given_name=given_name,
            family_name=family_name,
            legitimation_ref=legitimation_ref,
            legitimized_at=decided_at,
        )

        def mapping_matches_authorized_result(mapping: MappingRecord) -> bool:
            replay_basis = {
                "raw_record_id": raw_record_id,
                "source_system": source_system,
                "external_id": external_id,
                "object_type": "PLAYER",
                "internal_object_id": player_id,
                "mapping_status": "CONFIRMED",
                "conflict_status": "CLEAR",
                "criticality": "CRITICAL",
                "candidate_refs": (),
                "review_reason": None,
                "confirmation_evidence_ref": confirmation_evidence_ref,
                "valid_from": None,
                "valid_to": None,
                "predecessor_mapping_record_id": None,
            }
            return all(
                getattr(mapping, field) == expected
                for field, expected in replay_basis.items()
            )

        link = connection.execute(
            """
            SELECT mapping_record_id FROM ssot_legitimation_mapping
            WHERE legitimation_ref = ?
            """,
            (legitimation_ref,),
        ).fetchone()
        if link is not None:
            mapping = read_mapping_record(connection, link["mapping_record_id"])
            if not mapping_matches_authorized_result(mapping):
                raise IdentityLegitimationConflictError(
                    "persisted mapping conflicts with authorized bootstrap replay"
                )
        else:
            exact_matches = connection.execute(
                """
                SELECT mapping_record_id
                FROM mapping_record
                WHERE raw_record_id = ?
                  AND source_system = ?
                  AND external_id = ?
                  AND object_type = 'PLAYER'
                  AND internal_object_id = ?
                  AND mapping_status = 'CONFIRMED'
                  AND conflict_status = 'CLEAR'
                  AND confirmation_evidence_ref = ?
                ORDER BY mapping_record_id
                """,
                (
                    raw_record_id,
                    source_system,
                    external_id,
                    player_id,
                    confirmation_evidence_ref,
                ),
            ).fetchall()
            if len(exact_matches) > 1:
                raise IdentityLegitimationConflictError(
                    "multiple matching confirmed mappings already exist"
                )
            if exact_matches:
                mapping = read_mapping_record(
                    connection, exact_matches[0]["mapping_record_id"]
                )
                if not mapping_matches_authorized_result(mapping):
                    raise IdentityLegitimationConflictError(
                        "existing mapping conflicts with authorized bootstrap result"
                    )
            else:
                mapping = store_mapping_record(
                    connection,
                    raw_record_id=raw_record_id,
                    run_id=run_id,
                    source_system=source_system,
                    external_id=external_id,
                    object_type="PLAYER",
                    internal_object_id=player_id,
                    mapping_status="CONFIRMED",
                    conflict_status="CLEAR",
                    criticality="CRITICAL",
                    candidate_refs=[],
                    review_reason=None,
                    confirmation_evidence_ref=confirmation_evidence_ref,
                )
            connection.execute(
                """
                INSERT INTO ssot_legitimation_mapping (
                    legitimation_ref, mapping_record_id, created_at
                ) VALUES (?, ?, ?)
                """,
                (legitimation_ref, mapping.mapping_record_id, _now()),
            )
        connection.execute("RELEASE store_authorized_player_bootstrap")
    except Exception:
        connection.execute("ROLLBACK TO store_authorized_player_bootstrap")
        connection.execute("RELEASE store_authorized_player_bootstrap")
        raise
    return AuthorizedPlayerBootstrap(
        legitimation=legitimation,
        player=player,
        mapping=mapping,
    )


def store_ssot_version(
    connection: sqlite3.Connection,
    *,
    run_id: str,
    data_as_of: str,
    change_ref: str,
    state: Mapping[str, Any],
    released_at: str | None = None,
    release_evidence_ref: str | None = None,
    predecessor_ssot_version_id: str | None = None,
) -> SSOTVersion:
    _validate_time(data_as_of, "data_as_of")
    _nonempty(run_id, "run_id")
    _nonempty(change_ref, "change_ref")
    if released_at is not None:
        _validate_time(released_at, "released_at")
    if release_evidence_ref is not None:
        _nonempty(release_evidence_ref, "release_evidence_ref")
    if not isinstance(state, Mapping):
        raise TypeError("state must be a mapping")
    state_json = json.dumps(
        dict(state), ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    state_copy = json.loads(state_json)
    record = SSOTVersion(
        ssot_version_id=str(uuid.uuid4()), run_id=run_id,
        data_as_of=data_as_of,
        released_at=released_at,
        predecessor_ssot_version_id=predecessor_ssot_version_id,
        change_ref=change_ref, release_evidence_ref=release_evidence_ref,
        state=state_copy, created_at=_now(),
    )
    connection.execute(
        """
        INSERT INTO ssot_version (
            ssot_version_id, run_id, data_as_of, released_at,
            predecessor_ssot_version_id, change_ref, release_evidence_ref,
            state_json, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            record.ssot_version_id, record.run_id, record.data_as_of, record.released_at,
            record.predecessor_ssot_version_id, record.change_ref,
            record.release_evidence_ref, state_json, record.created_at,
        ),
    )
    return record


def read_ssot_version(
    connection: sqlite3.Connection, ssot_version_id: str
) -> SSOTVersion:
    row = connection.execute(
        "SELECT * FROM ssot_version WHERE ssot_version_id = ?", (ssot_version_id,)
    ).fetchone()
    if row is None:
        raise KeyError(f"unknown ssot_version_id: {ssot_version_id}")
    values = dict(row)
    try:
        state = json.loads(values.pop("state_json"))
    except (TypeError, json.JSONDecodeError) as exc:
        raise ValueError("stored state_json is not valid JSON") from exc
    if not isinstance(state, dict):
        raise ValueError("stored SSOT state must be a JSON object")
    return SSOTVersion(**values, state=state)
