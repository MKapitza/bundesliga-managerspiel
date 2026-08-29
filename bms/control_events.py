from __future__ import annotations

import json
import sqlite3
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timezone


@dataclass(frozen=True)
class ControlEvent:
    control_event_id: str
    control_id: str
    checked_at: str
    object_refs: tuple[str, ...]
    control_point: str
    severity: str
    check_status: str
    observed_status: str | None
    expected_status: str | None
    description: str | None
    trace_refs: tuple[str, ...]
    block_effect: str
    blocked_process: str | None
    owner_level: str
    resolution_status: str
    evidence_ref: str
    resolution_ref: str | None
    predecessor_event_ref: str | None
    created_at: str


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


def _serialize_refs(values: Sequence[str], field_name: str) -> tuple[str, tuple[str, ...]]:
    if isinstance(values, (str, bytes, bytearray)) or not isinstance(values, Sequence):
        raise TypeError(f"{field_name} must be a sequence of strings")
    refs = tuple(values)
    if not refs:
        raise ValueError(f"{field_name} must contain at least one reference")
    if any(not isinstance(value, str) for value in refs):
        raise TypeError(f"{field_name} entries must be strings")
    if any(not value for value in refs):
        raise ValueError(f"{field_name} entries must be non-empty")
    return json.dumps(refs, ensure_ascii=False, separators=(",", ":")), refs


def _deserialize_refs(value: str, field_name: str) -> tuple[str, ...]:
    try:
        decoded = json.loads(value)
    except (TypeError, json.JSONDecodeError) as exc:
        raise ValueError(f"stored {field_name} is not valid JSON") from exc
    if not isinstance(decoded, list) or not decoded:
        raise ValueError(f"stored {field_name} must be a non-empty JSON array")
    if any(not isinstance(item, str) or not item for item in decoded):
        raise ValueError(f"stored {field_name} entries must be non-empty strings")
    return tuple(decoded)


def store_control_event(
    connection: sqlite3.Connection,
    *,
    control_id: str,
    checked_at: str,
    object_refs: Sequence[str],
    control_point: str,
    severity: str,
    check_status: str,
    trace_refs: Sequence[str],
    block_effect: str,
    owner_level: str,
    resolution_status: str,
    evidence_ref: str,
    observed_status: str | None = None,
    expected_status: str | None = None,
    description: str | None = None,
    blocked_process: str | None = None,
    resolution_ref: str | None = None,
    predecessor_event_ref: str | None = None,
) -> ControlEvent:
    _validate_aware_iso8601(checked_at, "checked_at")
    object_refs_json, object_ref_values = _serialize_refs(object_refs, "object_refs")
    trace_refs_json, trace_ref_values = _serialize_refs(trace_refs, "trace_refs")
    event = ControlEvent(
        control_event_id=str(uuid.uuid4()),
        control_id=control_id,
        checked_at=checked_at,
        object_refs=object_ref_values,
        control_point=control_point,
        severity=severity,
        check_status=check_status,
        observed_status=observed_status,
        expected_status=expected_status,
        description=description,
        trace_refs=trace_ref_values,
        block_effect=block_effect,
        blocked_process=blocked_process,
        owner_level=owner_level,
        resolution_status=resolution_status,
        evidence_ref=evidence_ref,
        resolution_ref=resolution_ref,
        predecessor_event_ref=predecessor_event_ref,
        created_at=_created_at(),
    )
    connection.execute(
        """
        INSERT INTO control_event (
            control_event_id,
            control_id,
            checked_at,
            object_refs,
            control_point,
            severity,
            check_status,
            observed_status,
            expected_status,
            description,
            trace_refs,
            block_effect,
            blocked_process,
            owner_level,
            resolution_status,
            evidence_ref,
            resolution_ref,
            predecessor_event_ref,
            created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            event.control_event_id,
            event.control_id,
            event.checked_at,
            object_refs_json,
            event.control_point,
            event.severity,
            event.check_status,
            event.observed_status,
            event.expected_status,
            event.description,
            trace_refs_json,
            event.block_effect,
            event.blocked_process,
            event.owner_level,
            event.resolution_status,
            event.evidence_ref,
            event.resolution_ref,
            event.predecessor_event_ref,
            event.created_at,
        ),
    )
    return event


def read_control_event(
    connection: sqlite3.Connection, control_event_id: str
) -> ControlEvent:
    row = connection.execute(
        """
        SELECT
            control_event_id,
            control_id,
            checked_at,
            object_refs,
            control_point,
            severity,
            check_status,
            observed_status,
            expected_status,
            description,
            trace_refs,
            block_effect,
            blocked_process,
            owner_level,
            resolution_status,
            evidence_ref,
            resolution_ref,
            predecessor_event_ref,
            created_at
        FROM control_event
        WHERE control_event_id = ?
        """,
        (control_event_id,),
    ).fetchone()
    if row is None:
        raise KeyError(f"unknown control_event_id: {control_event_id}")
    return ControlEvent(
        control_event_id=row["control_event_id"],
        control_id=row["control_id"],
        checked_at=row["checked_at"],
        object_refs=_deserialize_refs(row["object_refs"], "object_refs"),
        control_point=row["control_point"],
        severity=row["severity"],
        check_status=row["check_status"],
        observed_status=row["observed_status"],
        expected_status=row["expected_status"],
        description=row["description"],
        trace_refs=_deserialize_refs(row["trace_refs"], "trace_refs"),
        block_effect=row["block_effect"],
        blocked_process=row["blocked_process"],
        owner_level=row["owner_level"],
        resolution_status=row["resolution_status"],
        evidence_ref=row["evidence_ref"],
        resolution_ref=row["resolution_ref"],
        predecessor_event_ref=row["predecessor_event_ref"],
        created_at=row["created_at"],
    )
