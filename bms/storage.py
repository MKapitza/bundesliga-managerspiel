from __future__ import annotations

import hashlib
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone


@dataclass(frozen=True)
class EvidenceArtifact:
    evidence_id: str
    run_id: str
    content_blob: bytes
    content_sha256: str
    byte_length: int
    media_type: str | None
    created_at: str


@dataclass(frozen=True)
class RawObservation:
    raw_record_id: str
    source_system: str
    source_reference: str
    retrieved_at: str
    observed_at: str
    raw_payload_ref: str
    run_id: str
    created_at: str
    predecessor_raw_record_id: str | None


def _created_at() -> str:
    """Return technical creation time as UTC ISO-8601 seconds with a Z suffix."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z"
    )


def _validate_aware_iso8601(value: str, field_name: str) -> None:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{field_name} must be a valid ISO-8601 timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field_name} must include a timezone offset")


def store_evidence(
    connection: sqlite3.Connection,
    *,
    content: bytes,
    run_id: str,
    media_type: str | None = None,
) -> EvidenceArtifact:
    if not isinstance(content, bytes):
        raise TypeError("content must be bytes")
    evidence = EvidenceArtifact(
        evidence_id=str(uuid.uuid4()),
        run_id=run_id,
        content_blob=content,
        content_sha256=hashlib.sha256(content).hexdigest(),
        byte_length=len(content),
        media_type=media_type,
        created_at=_created_at(),
    )
    connection.execute(
        """
        INSERT INTO evidence_artifact (
            evidence_id,
            run_id,
            content_blob,
            content_sha256,
            byte_length,
            media_type,
            created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            evidence.evidence_id,
            evidence.run_id,
            evidence.content_blob,
            evidence.content_sha256,
            evidence.byte_length,
            evidence.media_type,
            evidence.created_at,
        ),
    )
    return evidence


def read_evidence(
    connection: sqlite3.Connection, evidence_id: str
) -> EvidenceArtifact:
    row = connection.execute(
        """
        SELECT
            evidence_id,
            run_id,
            content_blob,
            content_sha256,
            byte_length,
            media_type,
            created_at
        FROM evidence_artifact
        WHERE evidence_id = ?
        """,
        (evidence_id,),
    ).fetchone()
    if row is None:
        raise KeyError(f"unknown evidence_id: {evidence_id}")
    return EvidenceArtifact(
        evidence_id=row["evidence_id"],
        run_id=row["run_id"],
        content_blob=bytes(row["content_blob"]),
        content_sha256=row["content_sha256"],
        byte_length=row["byte_length"],
        media_type=row["media_type"],
        created_at=row["created_at"],
    )


def verify_evidence(connection: sqlite3.Connection, evidence_id: str) -> bool:
    evidence = read_evidence(connection, evidence_id)
    return (
        evidence.byte_length == len(evidence.content_blob)
        and evidence.content_sha256
        == hashlib.sha256(evidence.content_blob).hexdigest()
    )


def store_raw_observation(
    connection: sqlite3.Connection,
    *,
    source_system: str,
    source_reference: str,
    retrieved_at: str,
    observed_at: str,
    raw_payload_ref: str,
    run_id: str,
    predecessor_raw_record_id: str | None = None,
) -> RawObservation:
    _validate_aware_iso8601(retrieved_at, "retrieved_at")
    _validate_aware_iso8601(observed_at, "observed_at")
    observation = RawObservation(
        raw_record_id=str(uuid.uuid4()),
        source_system=source_system,
        source_reference=source_reference,
        retrieved_at=retrieved_at,
        observed_at=observed_at,
        raw_payload_ref=raw_payload_ref,
        run_id=run_id,
        created_at=_created_at(),
        predecessor_raw_record_id=predecessor_raw_record_id,
    )
    connection.execute(
        """
        INSERT INTO raw_observation (
            raw_record_id,
            source_system,
            source_reference,
            retrieved_at,
            observed_at,
            raw_payload_ref,
            run_id,
            created_at,
            predecessor_raw_record_id
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            observation.raw_record_id,
            observation.source_system,
            observation.source_reference,
            observation.retrieved_at,
            observation.observed_at,
            observation.raw_payload_ref,
            observation.run_id,
            observation.created_at,
            observation.predecessor_raw_record_id,
        ),
    )
    return observation


def read_raw_observation(
    connection: sqlite3.Connection, raw_record_id: str
) -> RawObservation:
    row = connection.execute(
        """
        SELECT
            raw_record_id,
            source_system,
            source_reference,
            retrieved_at,
            observed_at,
            raw_payload_ref,
            run_id,
            created_at,
            predecessor_raw_record_id
        FROM raw_observation
        WHERE raw_record_id = ?
        """,
        (raw_record_id,),
    ).fetchone()
    if row is None:
        raise KeyError(f"unknown raw_record_id: {raw_record_id}")
    return RawObservation(
        raw_record_id=row["raw_record_id"],
        source_system=row["source_system"],
        source_reference=row["source_reference"],
        retrieved_at=row["retrieved_at"],
        observed_at=row["observed_at"],
        raw_payload_ref=row["raw_payload_ref"],
        run_id=row["run_id"],
        created_at=row["created_at"],
        predecessor_raw_record_id=row["predecessor_raw_record_id"],
    )
