from __future__ import annotations

import json
import sqlite3
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timezone

from .control_events import ControlEvent, read_control_event, store_control_event
from .storage import read_raw_observation


@dataclass(frozen=True)
class MappingRecord:
    mapping_record_id: str
    raw_record_id: str
    run_id: str
    source_system: str
    external_id: str | None
    object_type: str
    internal_object_id: str | None
    mapping_status: str
    conflict_status: str
    criticality: str
    candidate_refs: tuple[str, ...]
    review_reason: str | None
    confirmation_evidence_ref: str | None
    valid_from: str | None
    valid_to: str | None
    predecessor_mapping_record_id: str | None
    created_at: str


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z"
    )


def _serialize_candidates(candidate_refs: Sequence[str]) -> tuple[str, tuple[str, ...]]:
    if isinstance(candidate_refs, (str, bytes, bytearray)) or not isinstance(
        candidate_refs, Sequence
    ):
        raise TypeError("candidate_refs must be a sequence of strings")
    values = tuple(candidate_refs)
    if any(not isinstance(value, str) for value in values):
        raise TypeError("candidate_refs entries must be strings")
    if any(not value for value in values):
        raise ValueError("candidate_refs entries must be non-empty")
    return json.dumps(values, ensure_ascii=False, separators=(",", ":")), values


def _deserialize_candidates(value: str) -> tuple[str, ...]:
    try:
        decoded = json.loads(value)
    except (TypeError, json.JSONDecodeError) as exc:
        raise ValueError("stored candidate_refs_json is not valid JSON") from exc
    if not isinstance(decoded, list):
        raise ValueError("stored candidate_refs_json must be a JSON array")
    if any(not isinstance(item, str) or not item for item in decoded):
        raise ValueError("stored candidate refs must be non-empty strings")
    return tuple(decoded)


def store_mapping_record(
    connection: sqlite3.Connection,
    *,
    raw_record_id: str,
    run_id: str,
    source_system: str,
    external_id: str | None,
    object_type: str,
    mapping_status: str,
    conflict_status: str,
    criticality: str,
    candidate_refs: Sequence[str],
    internal_object_id: str | None = None,
    review_reason: str | None = None,
    confirmation_evidence_ref: str | None = None,
    valid_from: str | None = None,
    valid_to: str | None = None,
    predecessor_mapping_record_id: str | None = None,
) -> MappingRecord:
    candidate_refs_json, candidates = _serialize_candidates(candidate_refs)
    record = MappingRecord(
        mapping_record_id=str(uuid.uuid4()),
        raw_record_id=raw_record_id,
        run_id=run_id,
        source_system=source_system,
        external_id=external_id,
        object_type=object_type,
        internal_object_id=internal_object_id,
        mapping_status=mapping_status,
        conflict_status=conflict_status,
        criticality=criticality,
        candidate_refs=candidates,
        review_reason=review_reason,
        confirmation_evidence_ref=confirmation_evidence_ref,
        valid_from=valid_from,
        valid_to=valid_to,
        predecessor_mapping_record_id=predecessor_mapping_record_id,
        created_at=_now(),
    )
    connection.execute(
        """
        INSERT INTO mapping_record (
            mapping_record_id, raw_record_id, run_id, source_system, external_id,
            object_type, internal_object_id, mapping_status, conflict_status,
            criticality, candidate_refs_json, review_reason,
            confirmation_evidence_ref, valid_from, valid_to,
            predecessor_mapping_record_id, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            record.mapping_record_id,
            record.raw_record_id,
            record.run_id,
            record.source_system,
            record.external_id,
            record.object_type,
            record.internal_object_id,
            record.mapping_status,
            record.conflict_status,
            record.criticality,
            candidate_refs_json,
            record.review_reason,
            record.confirmation_evidence_ref,
            record.valid_from,
            record.valid_to,
            record.predecessor_mapping_record_id,
            record.created_at,
        ),
    )
    return record


def read_mapping_record(
    connection: sqlite3.Connection, mapping_record_id: str
) -> MappingRecord:
    row = connection.execute(
        "SELECT * FROM mapping_record WHERE mapping_record_id = ?",
        (mapping_record_id,),
    ).fetchone()
    if row is None:
        raise KeyError(f"unknown mapping_record_id: {mapping_record_id}")
    values = dict(row)
    values["candidate_refs"] = _deserialize_candidates(
        values.pop("candidate_refs_json")
    )
    return MappingRecord(**values)


def _head_predicate(alias: str) -> str:
    return (
        "NOT EXISTS (SELECT 1 FROM mapping_record AS successor "
        f"WHERE successor.predecessor_mapping_record_id = {alias}.mapping_record_id)"
    )


def _older_external_id_change_candidates(
    connection: sqlite3.Connection, record: MappingRecord
) -> list[MappingRecord]:
    if record.internal_object_id is None:
        return []
    rows = connection.execute(
        """
        SELECT older.mapping_record_id
        FROM mapping_record AS older
        JOIN mapping_record AS current
          ON current.mapping_record_id = ?
        WHERE older.rowid < current.rowid
          AND older.source_system = current.source_system
          AND older.object_type = current.object_type
          AND older.internal_object_id = current.internal_object_id
          AND older.external_id IS NOT current.external_id
        ORDER BY older.rowid
        """,
        (record.mapping_record_id,),
    ).fetchall()
    return [read_mapping_record(connection, row["mapping_record_id"]) for row in rows]


def _requires_k1_005(
    connection: sqlite3.Connection, record: MappingRecord
) -> bool:
    if record.predecessor_mapping_record_id is not None:
        predecessor = read_mapping_record(
            connection, record.predecessor_mapping_record_id
        )
        return predecessor.external_id != record.external_id
    return bool(_older_external_id_change_candidates(connection, record))


def _has_unresolved_history_branch(
    connection: sqlite3.Connection, record: MappingRecord
) -> bool:
    if record.internal_object_id is None:
        return False
    current_heads = connection.execute(
        f"""
        SELECT COUNT(*)
        FROM mapping_record AS candidate
        WHERE candidate.source_system = ?
          AND candidate.object_type = ?
          AND candidate.internal_object_id = ?
          AND {_head_predicate("candidate")}
        """,
        (record.source_system, record.object_type, record.internal_object_id),
    ).fetchone()[0]
    return current_heads > 1


def map_external_identity(
    connection: sqlite3.Connection,
    *,
    raw_record_id: str,
    run_id: str,
    source_system: str,
    external_id: str | None,
    object_type: str,
    criticality: str,
) -> MappingRecord:
    if external_id is not None:
        confirmed = connection.execute(
            f"""
            SELECT mapping_record_id
            FROM mapping_record AS candidate
            WHERE source_system = ? AND external_id = ? AND object_type = ?
              AND mapping_status = 'CONFIRMED'
              AND conflict_status = 'CLEAR'
              AND {_head_predicate("candidate")}
            ORDER BY mapping_record_id
            """,
            (source_system, external_id, object_type),
        ).fetchall()
        if len(confirmed) == 1:
            return read_mapping_record(connection, confirmed[0]["mapping_record_id"])
        if len(confirmed) > 1:
            return store_mapping_record(
                connection,
                raw_record_id=raw_record_id,
                run_id=run_id,
                source_system=source_system,
                external_id=external_id,
                object_type=object_type,
                mapping_status="REVIEW_REQUIRED",
                conflict_status="CONFLICTING",
                criticality=criticality,
                candidate_refs=[row["mapping_record_id"] for row in confirmed],
                review_reason="Mehrere aktive bestätigte Mappingclaims; keine stille Auswahl.",
            )
    return store_mapping_record(
        connection,
        raw_record_id=raw_record_id,
        run_id=run_id,
        source_system=source_system,
        external_id=external_id,
        object_type=object_type,
        mapping_status="REVIEW_REQUIRED",
        conflict_status="NOT_CHECKED",
        criticality=criticality,
        candidate_refs=[],
        review_reason=(
            "Unbekannte externe Identität; Mapping-Review erforderlich."
            if external_id is not None
            else "Keine externe ID; Name allein bestätigt keine Identität."
        ),
    )


def _mapping_refs(
    connection: sqlite3.Connection, record: MappingRecord
) -> tuple[list[str], str]:
    raw = read_raw_observation(connection, record.raw_record_id)
    return (
        [
            f"run:{record.run_id}",
            f"mapping_record:{record.mapping_record_id}",
            f"raw_record:{record.raw_record_id}",
            f"evidence:{raw.raw_payload_ref}",
        ],
        raw.raw_payload_ref,
    )


def _store_k1_event(
    connection: sqlite3.Connection,
    *,
    record: MappingRecord,
    control_id: str,
    passed: bool,
    observed_status: str,
    expected_status: str,
    description: str,
    trace_refs: Sequence[str],
    passed_block_effect: str,
    failed_block_effect: str,
    blocked_process: str | None,
    passed_resolution_status: str,
) -> ControlEvent:
    object_refs, evidence_ref = _mapping_refs(connection, record)
    block_effect = passed_block_effect if passed else failed_block_effect
    return store_control_event(
        connection,
        control_id=control_id,
        checked_at=_now(),
        object_refs=object_refs,
        control_point="K1",
        severity="CRITICAL",
        check_status="CHECK_PASSED" if passed else "CHECK_FAILED",
        observed_status=observed_status,
        expected_status=expected_status,
        description=description,
        trace_refs=[*trace_refs, "DOC-015 v0.4"],
        block_effect=block_effect,
        blocked_process=None if block_effect == "NONE" else blocked_process,
        owner_level="Mapping/SSOT",
        resolution_status=passed_resolution_status if passed else "OPEN",
        evidence_ref=evidence_ref,
    )


def check_k1_001_external_id(
    connection: sqlite3.Connection, mapping_record_id: str
) -> ControlEvent:
    record = read_mapping_record(connection, mapping_record_id)
    known = connection.execute(
        f"""
        SELECT COUNT(*)
        FROM mapping_record AS candidate
        WHERE mapping_record_id <> ? AND source_system = ? AND external_id = ?
          AND object_type = ?
          AND mapping_status = 'CONFIRMED' AND conflict_status = 'CLEAR'
          AND {_head_predicate("candidate")}
        """,
        (
            record.mapping_record_id,
            record.source_system,
            record.external_id,
            record.object_type,
        ),
    ).fetchone()[0]
    handled = (
        record.external_id is not None
        and known == 0
        and record.mapping_status == "REVIEW_REQUIRED"
        and record.internal_object_id is None
    )
    return _store_k1_event(
        connection,
        record=record,
        control_id="CTL-K1-001",
        passed=handled,
        observed_status=record.mapping_status,
        expected_status="REVIEW_REQUIRED",
        description="Unbekannte externe ID wurde als Mapping-Prüffall ohne SSOT-Neuanlage behandelt.",
        trace_refs=["DEC-001", "DEC-028", "TP-01", "TC6-003"],
        passed_block_effect="PARTIAL_BLOCK",
        failed_block_effect="PARTIAL_BLOCK",
        blocked_process=f"Identität mapping_record_id={record.mapping_record_id}",
        passed_resolution_status="OPEN",
    )


def check_k1_002_auto_matched(
    connection: sqlite3.Connection, mapping_record_id: str
) -> ControlEvent:
    record = read_mapping_record(connection, mapping_record_id)
    handled = (
        record.mapping_status == "AUTO_MATCHED"
        and record.confirmation_evidence_ref is None
    )
    return _store_k1_event(
        connection,
        record=record,
        control_id="CTL-K1-002",
        passed=handled,
        observed_status=record.mapping_status,
        expected_status="AUTO_MATCHED bleibt unbestätigt",
        description="AUTO_MATCHED wurde nicht als CONFIRMED oder verbindlich behandelt.",
        trace_refs=["DEC-001", "DEC-015", "TP-04", "TC6-004"],
        passed_block_effect="RELEASE_BLOCK",
        failed_block_effect="RELEASE_BLOCK",
        blocked_process="G2 Mapping",
        passed_resolution_status="OPEN",
    )


def check_k1_003_duplicate_suspicion(
    connection: sqlite3.Connection, mapping_record_id: str
) -> ControlEvent:
    record = read_mapping_record(connection, mapping_record_id)
    handled = (
        len(record.candidate_refs) > 1
        and record.mapping_status == "REVIEW_REQUIRED"
        and record.internal_object_id is None
    )
    return _store_k1_event(
        connection,
        record=record,
        control_id="CTL-K1-003",
        passed=handled,
        observed_status=f"{record.mapping_status}; candidates={len(record.candidate_refs)}",
        expected_status="REVIEW_REQUIRED mit erhaltener Kandidatenliste",
        description="Mehrfachkandidaten wurden ohne stillen Merge als Prüffall erhalten.",
        trace_refs=["DEC-001", "DEC-016", "REQ-DAT-001", "TC6-002"],
        passed_block_effect="PARTIAL_BLOCK",
        failed_block_effect="PARTIAL_BLOCK",
        blocked_process=f"Identität mapping_record_id={record.mapping_record_id}",
        passed_resolution_status="OPEN",
    )


def check_k1_004_context_without_external_id(
    connection: sqlite3.Connection, mapping_record_id: str
) -> ControlEvent:
    record = read_mapping_record(connection, mapping_record_id)
    handled = (
        record.external_id is None
        and record.mapping_status == "REVIEW_REQUIRED"
        and record.internal_object_id is None
    )
    return _store_k1_event(
        connection,
        record=record,
        control_id="CTL-K1-004",
        passed=handled,
        observed_status=record.mapping_status,
        expected_status="REVIEW_REQUIRED bei fehlender externer ID ohne deterministische Zusatzmerkmale",
        description="Fehlende externe ID wurde nicht allein anhand eines Namens bestätigt.",
        trace_refs=["TP-01", "TC6-003"],
        passed_block_effect="PARTIAL_BLOCK",
        failed_block_effect="PARTIAL_BLOCK",
        blocked_process=f"Identität mapping_record_id={record.mapping_record_id}",
        passed_resolution_status="OPEN",
    )


def check_k1_005_changed_external_id(
    connection: sqlite3.Connection, mapping_record_id: str
) -> ControlEvent:
    record = read_mapping_record(connection, mapping_record_id)
    predecessor = (
        read_mapping_record(connection, record.predecessor_mapping_record_id)
        if record.predecessor_mapping_record_id is not None
        else None
    )
    older_candidates = (
        _older_external_id_change_candidates(connection, record)
        if predecessor is None
        else []
    )
    history_loss = bool(older_candidates)
    handled = (
        predecessor is not None
        and record.mapping_status == "CONFIRMED"
        and predecessor.external_id != record.external_id
        and predecessor.internal_object_id is not None
        and predecessor.internal_object_id == record.internal_object_id
        and predecessor.source_system == record.source_system
        and predecessor.object_type == record.object_type
    )
    failed_block_effect = "PROCESS_BLOCK" if history_loss else "RELEASE_BLOCK"
    blocked_process = (
        "Mapping/SSOT-Verarbeitung"
        if history_loss
        else "G3 SSOT-Version"
    )
    return _store_k1_event(
        connection,
        record=record,
        control_id="CTL-K1-005",
        passed=handled,
        observed_status=(
            f"predecessor={record.predecessor_mapping_record_id}; "
            f"external_id={record.external_id}; mapping_status={record.mapping_status}; "
            f"older_change_candidates={len(older_candidates)}"
        ),
        expected_status="CONFIRMED-Nachfolger mit geänderter externer ID, stabiler interner ID und konsistentem Vorgänger",
        description="Der externe ID-Wechsel wurde als neuer historisierter Mappingdatensatz geprüft.",
        trace_refs=["DEC-001", "DEC-012", "TP-05", "TC6-038"],
        passed_block_effect="NONE",
        failed_block_effect=failed_block_effect,
        blocked_process=blocked_process,
        passed_resolution_status="RESOLVED",
    )


def check_k1_006_conflicting_mapping(
    connection: sqlite3.Connection, mapping_record_id: str
) -> ControlEvent:
    record = read_mapping_record(connection, mapping_record_id)
    handled = (
        record.conflict_status == "CONFLICTING"
        and record.mapping_status == "REVIEW_REQUIRED"
        and record.internal_object_id is None
        and len(record.candidate_refs) > 1
    )
    return _store_k1_event(
        connection,
        record=record,
        control_id="CTL-K1-006",
        passed=handled,
        observed_status=f"{record.conflict_status}; {record.mapping_status}",
        expected_status="CONFLICTING mit Prüffall und ohne stille Auswahl",
        description="Konkurrierende Mappingclaims wurden sichtbar erhalten und nicht überschrieben.",
        trace_refs=["DEC-016", "CON-001", "TC6-005"],
        passed_block_effect="PARTIAL_BLOCK",
        failed_block_effect="PARTIAL_BLOCK",
        blocked_process=f"Identität mapping_record_id={record.mapping_record_id}",
        passed_resolution_status="OPEN",
    )


def run_applicable_k1(
    connection: sqlite3.Connection, mapping_record_id: str
) -> list[ControlEvent]:
    record = read_mapping_record(connection, mapping_record_id)
    if _requires_k1_005(connection, record):
        return [check_k1_005_changed_external_id(connection, mapping_record_id)]
    if record.conflict_status == "CONFLICTING":
        return [check_k1_006_conflicting_mapping(connection, mapping_record_id)]
    if len(record.candidate_refs) > 1:
        return [check_k1_003_duplicate_suspicion(connection, mapping_record_id)]
    if record.external_id is None:
        return [check_k1_004_context_without_external_id(connection, mapping_record_id)]
    if record.mapping_status == "AUTO_MATCHED":
        return [check_k1_002_auto_matched(connection, mapping_record_id)]
    if record.mapping_status == "REVIEW_REQUIRED":
        return [check_k1_001_external_id(connection, mapping_record_id)]
    return []


def derive_g2(
    connection: sqlite3.Connection,
    *,
    mapping_record_ids: Sequence[str],
    control_event_ids: Sequence[str],
) -> dict[str, object]:
    records = [read_mapping_record(connection, record_id) for record_id in mapping_record_ids]
    events = [read_control_event(connection, event_id) for event_id in control_event_ids]
    critical_records = [record for record in records if record.criticality == "CRITICAL"]
    current_heads = all(
        connection.execute(
            """
            SELECT NOT EXISTS (
                SELECT 1 FROM mapping_record
                WHERE predecessor_mapping_record_id = ?
            )
            """,
            (record.mapping_record_id,),
        ).fetchone()[0]
        for record in critical_records
    )
    confirmed = bool(critical_records) and all(
        record.mapping_status == "CONFIRMED"
        and record.internal_object_id is not None
        and record.confirmation_evidence_ref is not None
        for record in critical_records
    )
    conflicts_clear = all(
        record.conflict_status == "CLEAR" for record in critical_records
    )
    no_ambiguity = all(len(record.candidate_refs) <= 1 for record in critical_records)
    no_history_branch = all(
        not _has_unresolved_history_branch(connection, record)
        for record in critical_records
    )
    no_competing_claims = True
    for record in critical_records:
        if record.external_id is None:
            continue
        competing = connection.execute(
            f"""
            SELECT COUNT(*)
            FROM mapping_record AS candidate
            WHERE mapping_record_id <> ?
              AND source_system = ? AND external_id = ?
              AND object_type = ?
              AND {_head_predicate("candidate")}
              AND (
                  conflict_status = 'CONFLICTING'
                  OR mapping_status IN ('UNMAPPED', 'AUTO_MATCHED', 'REVIEW_REQUIRED', 'REJECTED')
                  OR internal_object_id <> ?
              )
            """,
            (
                record.mapping_record_id,
                record.source_system,
                record.external_id,
                record.object_type,
                record.internal_object_id,
            ),
        ).fetchone()[0]
        no_competing_claims = no_competing_claims and competing == 0
    required_control_pairs: set[tuple[str, str]] = set()
    for record in records:
        if _requires_k1_005(connection, record):
            control_id = "CTL-K1-005"
        elif record.conflict_status == "CONFLICTING":
            control_id = "CTL-K1-006"
        elif len(record.candidate_refs) > 1:
            control_id = "CTL-K1-003"
        elif record.external_id is None:
            control_id = "CTL-K1-004"
        elif record.mapping_status == "AUTO_MATCHED":
            control_id = "CTL-K1-002"
        elif record.mapping_status == "REVIEW_REQUIRED":
            control_id = "CTL-K1-001"
        else:
            continue
        required_control_pairs.add((record.mapping_record_id, control_id))

    records_by_id = {record.mapping_record_id: record for record in records}
    covered_control_pairs: set[tuple[str, str]] = set()
    event_contexts_valid = True
    for event in events:
        mapping_refs = [
            ref.removeprefix("mapping_record:")
            for ref in event.object_refs
            if ref.startswith("mapping_record:")
        ]
        if len(mapping_refs) != 1 or mapping_refs[0] not in records_by_id:
            event_contexts_valid = False
            continue
        record = records_by_id[mapping_refs[0]]
        raw = read_raw_observation(connection, record.raw_record_id)
        required_refs = {
            f"run:{record.run_id}",
            f"mapping_record:{record.mapping_record_id}",
            f"raw_record:{record.raw_record_id}",
            f"evidence:{raw.raw_payload_ref}",
        }
        persisted_trace_refs = {
            ref
            for ref in event.object_refs
            if ref.startswith(("run:", "mapping_record:", "raw_record:", "evidence:"))
        }
        valid = (
            event.control_point == "K1"
            and persisted_trace_refs == required_refs
            and event.evidence_ref == raw.raw_payload_ref
        )
        event_contexts_valid = event_contexts_valid and valid
        if valid:
            covered_control_pairs.add((record.mapping_record_id, event.control_id))
    contexts_valid = (
        event_contexts_valid
        and required_control_pairs.issubset(covered_control_pairs)
    )

    def blocks_g2(event: ControlEvent) -> bool:
        if event.check_status != "CHECK_FAILED" or event.blocked_process is None:
            return False
        if event.block_effect == "PROCESS_BLOCK":
            return "Mapping" in event.blocked_process
        if event.block_effect == "RELEASE_BLOCK":
            return "G2" in event.blocked_process
        if event.block_effect == "PARTIAL_BLOCK":
            return "Identität" in event.blocked_process
        return False

    no_g2_control_blocker = contexts_valid and not any(blocks_g2(event) for event in events)
    released = (
        confirmed
        and current_heads
        and conflicts_clear
        and no_ambiguity
        and no_history_branch
        and no_competing_claims
        and no_g2_control_blocker
    )
    return {
        "schema": "bms.w2-c2-g2-decision",
        "schema_version": "0.1",
        "decision": "MAPPING_RELEASED" if released else "BLOCKED",
        "mapping_record_ids": list(mapping_record_ids),
        "evaluated_control_event_ids": list(control_event_ids),
        "derivation": {
            "critical_mappings_present_and_confirmed": confirmed,
            "critical_mappings_are_current_heads": current_heads,
            "conflicts_clear": conflicts_clear,
            "no_unresolved_ambiguity": no_ambiguity,
            "no_unresolved_history_branch": no_history_branch,
            "no_active_competing_claims": no_competing_claims,
            "required_control_ids": sorted(
                {control_id for _, control_id in required_control_pairs}
            ),
            "required_mapping_control_pairs": [
                {"mapping_record_id": record_id, "control_id": control_id}
                for record_id, control_id in sorted(required_control_pairs)
            ],
            "covered_mapping_control_pairs": [
                {"mapping_record_id": record_id, "control_id": control_id}
                for record_id, control_id in sorted(covered_control_pairs)
            ],
            "persisted_k1_context_valid": contexts_valid,
            "no_g2_relevant_control_blocker": no_g2_control_blocker,
            "reason": (
                "Alle kritischen Identitäten sind bestätigt und konfliktfrei."
                if released
                else "Mindestens ein kritisches Mapping ist unbestätigt, mehrdeutig, konfliktbehaftet oder kontrollseitig blockiert."
            ),
        },
    }
