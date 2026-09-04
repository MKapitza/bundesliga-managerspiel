from __future__ import annotations

import ast
import hashlib
import json
import re
import sqlite3
import sys
import tomllib
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from .control_events import ControlEvent, read_control_event, store_control_event
from .imports import import_fixture, validate_fixture
from .manifests import build_run_manifest
from .mapping import (
    derive_g2,
    map_external_identity,
    read_mapping_record,
    run_applicable_k1,
)
from .persistence import apply_migrations, connect_database
from .ssot import (
    SSOTVersion,
    read_ssot_version,
    register_evidence_manifest,
    store_authorized_player_bootstrap,
    store_ssot_version,
)
from .storage import (
    read_evidence,
    read_raw_observation,
    store_evidence,
    verify_evidence,
)
from .w2_c1 import derive_g1, run_k0


BASELINE_COMMIT = "569d81f93e614699abf39b11c530e38a506979f7"
PLAYER_ID = "9ed46b81-bb6e-4f84-a28d-92b0f019beb5"
PLAYER_LEGITIMATION_REF = "ssot-legit:dc4a7f13-6cb3-4144-a9ca-89991a281962"
CLUB_ID = "5e5baf09-5fef-46b3-8db4-361565c5a484"
CLUB_LEGITIMATION_REF = "ssot-legit:d110b867-ae87-4426-a3d8-c0e470fc9593"
SEASON_ID = "73745028-426a-4970-a812-95455407ad77"
WIKIDATA_EVIDENCE_REF = "seed-evidence:w2-c3-positive-01:player:wikidata"
BUNDESLIGA_EVIDENCE_REF = "seed-evidence:w2-c3-positive-01:player:bundesliga"
FCB_EVIDENCE_REF = "seed-evidence:w2-c3-positive-01:player:fcb"
BASELINE_MIGRATION_HASHES = {
    "0001_raw_evidence.sql": "678d5a3f2674d5abadb54de84fd17b60378eee16583153d8e35c5cba4f4a1354",
    "0002_control_event.sql": "360c498fb7dfdc3790e07dc4884f0950705841a7b6e54ae6aac8c8f8ef27be27",
    "0003_import_envelope.sql": "43e356dbcc76b217c885d9f37702f244ff73781d09e47772e329a11afb253f1b",
    "0004_mapping_review.sql": "a3150a74c296edbd1059d48250ccaa7e26826d2548ed468a9baa825c2d9f2fa5",
    "0005_ssot_persistence.sql": "656316d9b952bdfb9e0ee2a98bdead9fa5abcc267d85aeadf80cce475256e176",
}
REQUIRED_BASE_K2 = (
    "CTL-K2-002",
    "CTL-K2-003",
    "CTL-K2-004",
    "CTL-K2-005",
    "CTL-K2-006",
)
POSITION_CLASSES = {"T", "A", "M", "S"}


class W2C3Error(RuntimeError):
    """Raised when the integrated C3 slice cannot complete safely."""


@dataclass(frozen=True)
class SSOTVersionRelease:
    release_id: str
    ssot_version_id: str
    run_id: str
    g3_decision: str
    g3_evidence_id: str
    released_at: str
    created_at: str


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z"
    )


def _canonical_bytes(value: dict[str, Any]) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _prepare_output(output_dir: Path) -> None:
    if output_dir.exists() and not output_dir.is_dir():
        raise W2C3Error(f"output path is not a directory: {output_dir}")
    if output_dir.exists() and any(output_dir.iterdir()):
        raise W2C3Error(f"output directory is not empty and will not be reused: {output_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)


def _technical_id(kind: str, *values: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, "bms:c3.2:" + kind + ":" + ":".join(values)))


def build_positive_ssot_state(mapping_record_id: str) -> dict[str, Any]:
    """Materialize the already approved positive C3 handoff without deriving values."""
    club_assignment_id = _technical_id(
        "player-club-assignment", PLAYER_ID, CLUB_ID, "2019-07-04"
    )
    position_assignment_id = _technical_id(
        "player-position-assignment", PLAYER_ID, SEASON_ID, "M"
    )
    return {
        "status": "SSOT_PROCESSABLE",
        "open_critical_review_cases": [],
        "external_deviation": None,
        "player": {
            "player_id": PLAYER_ID,
            "identity_status": "IDENTITY_LEGITIMATED",
            "legitimation_ref": PLAYER_LEGITIMATION_REF,
        },
        "club": {
            "club_id": CLUB_ID,
            "club_name": "FC Bayern München",
            "identity_status": "IDENTITY_LEGITIMATED",
            "legitimation_ref": CLUB_LEGITIMATION_REF,
        },
        "season": {
            "season_id": SEASON_ID,
            "label": "2026/27",
            "valid_from": "2026-08-28",
            "valid_to": "2027-05-22",
        },
        "player_club_assignment": {
            "player_club_assignment_id": club_assignment_id,
            "player_id": PLAYER_ID,
            "club_id": CLUB_ID,
            "valid_from": "2019-07-04",
            "valid_to": None,
            "verification_status": "CONFIRMED",
            "conflict_status": "CLEAR",
            "evidence_ref": FCB_EVIDENCE_REF,
        },
        "player_position_assignment": {
            "player_position_assignment_id": position_assignment_id,
            "player_id": PLAYER_ID,
            "season_id": SEASON_ID,
            "position": "M",
            "valid_from": "2026-08-28",
            "valid_to": "2027-05-22",
            "verification_status": "CONFIRMED",
            "conflict_status": "CLEAR",
            "evidence_ref": BUNDESLIGA_EVIDENCE_REF,
        },
        "mapping": {
            "mapping_record_id": mapping_record_id,
            "mapping_status": "CONFIRMED",
            "confirmation_evidence_ref": WIKIDATA_EVIDENCE_REF,
        },
    }


def store_replay_safe_ssot_version(
    connection: sqlite3.Connection,
    *,
    run_id: str,
    data_as_of: str,
    change_ref: str,
    state: dict[str, Any],
) -> SSOTVersion:
    state_json = _canonical_bytes(state).decode("utf-8")
    rows = connection.execute(
        """
        SELECT ssot_version_id FROM ssot_version
        WHERE data_as_of = ? AND change_ref = ? AND state_json = ?
        ORDER BY ssot_version_id
        """,
        (data_as_of, change_ref, state_json),
    ).fetchall()
    if len(rows) > 1:
        raise W2C3Error("multiple SSOT versions exist for the same frozen C3 input")
    if rows:
        return read_ssot_version(connection, rows[0]["ssot_version_id"])
    return store_ssot_version(
        connection,
        run_id=run_id,
        data_as_of=data_as_of,
        change_ref=change_ref,
        state=state,
    )


def _parse_date(value: Any) -> date | None:
    if not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _valid_interval(record: dict[str, Any], at: date, *, open_end: bool) -> bool:
    start = _parse_date(record.get("valid_from"))
    end_value = record.get("valid_to")
    end = None if end_value is None and open_end else _parse_date(end_value)
    return bool(start and (end_value is None or end) and start <= at and (end is None or at <= end))


def _overlaps(records: list[dict[str, Any]]) -> bool:
    intervals: list[tuple[date, date]] = []
    for record in records:
        start = _parse_date(record.get("valid_from"))
        end = _parse_date(record.get("valid_to")) or date.max
        if start is None or start > end:
            return True
        intervals.append((start, end))
    intervals.sort()
    return any(current[0] <= previous[1] for previous, current in zip(intervals, intervals[1:]))


def _state_evaluations(version: SSOTVersion) -> dict[str, tuple[bool, str, str, str]]:
    state = version.state
    player = state.get("player") if isinstance(state.get("player"), dict) else {}
    club = state.get("club") if isinstance(state.get("club"), dict) else {}
    season = state.get("season") if isinstance(state.get("season"), dict) else {}
    club_assignment = (
        state.get("player_club_assignment")
        if isinstance(state.get("player_club_assignment"), dict)
        else {}
    )
    position_assignment = (
        state.get("player_position_assignment")
        if isinstance(state.get("player_position_assignment"), dict)
        else {}
    )
    at = datetime.fromisoformat(version.data_as_of).date()
    deviation = state.get("external_deviation")
    authority_ok = not (
        isinstance(deviation, dict) and deviation.get("attempted_silent_overwrite") is True
    )
    identity_ok = (
        player.get("player_id")
        and player.get("identity_status") == "IDENTITY_LEGITIMATED"
        and player.get("legitimation_ref")
        and club.get("club_id")
        and club.get("identity_status") == "IDENTITY_LEGITIMATED"
        and club.get("legitimation_ref")
        and state.get("mapping", {}).get("mapping_status") == "CONFIRMED"
    )
    club_ok = (
        club_assignment.get("player_id") == player.get("player_id")
        and club_assignment.get("club_id") == club.get("club_id")
        and club_assignment.get("verification_status") == "CONFIRMED"
        and club_assignment.get("conflict_status") == "CLEAR"
        and _valid_interval(club_assignment, at, open_end=True)
    )
    position_ok = (
        position_assignment.get("player_id") == player.get("player_id")
        and position_assignment.get("season_id") == season.get("season_id")
        and position_assignment.get("position") in POSITION_CLASSES
        and position_assignment.get("verification_status") == "CONFIRMED"
        and position_assignment.get("conflict_status") == "CLEAR"
        and _valid_interval(position_assignment, at, open_end=False)
    )
    season_ok = _valid_interval(season, at, open_end=False)
    club_history = state.get("player_club_history", [club_assignment])
    position_history = state.get("player_position_history", [position_assignment])
    history_ok = (
        isinstance(club_history, list)
        and isinstance(position_history, list)
        and not _overlaps([item for item in club_history if isinstance(item, dict)])
        and not _overlaps([item for item in position_history if isinstance(item, dict)])
    )
    time_ok = season_ok and club_ok and position_ok and history_ok
    open_cases = state.get("open_critical_review_cases")
    no_open_cases = isinstance(open_cases, list) and not open_cases
    processable_basis = bool(
        authority_ok and identity_ok and club_ok and position_ok and time_ok and no_open_cases
    )
    status_consistent = state.get("status") == (
        "SSOT_PROCESSABLE" if processable_basis else "SSOT_BLOCKED"
    )
    result = {
        "CTL-K2-002": (
            bool(identity_ok),
            str(state.get("mapping", {}).get("mapping_status")),
            "bestätigte Spieler-/Vereinsidentität und CONFIRMED-Mapping",
            "SSOT-Identität ist bestätigt und referenzierbar.",
        ),
        "CTL-K2-003": (
            bool(club_ok),
            str(club_assignment.get("verification_status")),
            "zeitlich gültige bestätigte Vereinszuordnung",
            "Vereinszuordnung ist eindeutig, bestätigt und zeitlich gültig.",
        ),
        "CTL-K2-004": (
            bool(position_ok),
            str(position_assignment.get("position")),
            "saisonal gültige Position T/A/M/S",
            "Saisonale Positionsklasse ist bestätigt und gültig.",
        ),
        "CTL-K2-005": (
            bool(time_ok),
            "CONSISTENT" if time_ok else "INVALID_OR_OVERLAPPING",
            "plausible, nicht destruktiv überlappende Gültigkeit",
            "Zeitliche Grenzen und Historien sind konsistent.",
        ),
        "CTL-K2-006": (
            bool(status_consistent),
            str(state.get("status")),
            "SSOT_PROCESSABLE genau ohne blockierenden kritischen Prüffall",
            "SSOT-Verarbeitbarkeitsstatus entspricht der unabhängigen Prüflage.",
        ),
    }
    if isinstance(deviation, dict):
        result["CTL-K2-001"] = (
            authority_ok,
            "NO_SILENT_OVERWRITE" if authority_ok else "SILENT_OVERWRITE",
            "externe Abweichung überschreibt keinen freigegebenen SSOT-Wert",
            "Externe Abweichung wurde ohne stille SSOT-Überschreibung behandelt.",
        )
    return result


def applicable_k2_control_ids(version: SSOTVersion) -> tuple[str, ...]:
    controls = list(REQUIRED_BASE_K2)
    if isinstance(version.state.get("external_deviation"), dict):
        controls.insert(0, "CTL-K2-001")
    return tuple(controls)


def _stable_subject_refs(version: SSOTVersion, control_id: str) -> tuple[str, ...]:
    state = version.state
    player_id = str(state.get("player", {}).get("player_id", "MISSING"))
    if control_id == "CTL-K2-002":
        return (f"stable_subject:player:{player_id}",)
    if control_id == "CTL-K2-003":
        assignment_id = state.get("player_club_assignment", {}).get(
            "player_club_assignment_id", "MISSING"
        )
        return (f"stable_subject:player_club_assignment:{assignment_id}",)
    if control_id == "CTL-K2-004":
        assignment_id = state.get("player_position_assignment", {}).get(
            "player_position_assignment_id", "MISSING"
        )
        return (f"stable_subject:player_position_assignment:{assignment_id}",)
    return (f"stable_subject:ssot_player:{player_id}",)


def k2_lineage_key(event: ControlEvent) -> str:
    subjects = sorted(ref for ref in event.object_refs if ref.startswith("stable_subject:"))
    return event.control_id + "|" + "|".join(subjects)


def k2_evaluation_instance_key(event: ControlEvent) -> str:
    version_refs = sorted(ref for ref in event.object_refs if ref.startswith("ssot_version:"))
    return k2_lineage_key(event) + "|" + "|".join(version_refs)


def _events_for_version(
    connection: sqlite3.Connection, ssot_version_id: str
) -> list[ControlEvent]:
    rows = connection.execute(
        """
        SELECT DISTINCT event.control_event_id
        FROM control_event AS event
        JOIN json_each(event.object_refs) AS ref
          ON ref.value = ?
        WHERE event.control_point = 'K2'
        ORDER BY event.created_at, event.control_event_id
        """,
        (f"ssot_version:{ssot_version_id}",),
    ).fetchall()
    return [read_control_event(connection, row["control_event_id"]) for row in rows]


def effective_k2_heads(
    connection: sqlite3.Connection, ssot_version_id: str
) -> dict[str, list[ControlEvent]]:
    events = _events_for_version(connection, ssot_version_id)
    grouped: dict[str, list[ControlEvent]] = {}
    for event in events:
        grouped.setdefault(k2_lineage_key(event), []).append(event)
    heads: dict[str, list[ControlEvent]] = {}
    for lineage, lineage_events in grouped.items():
        event_ids = {event.control_event_id for event in lineage_events}
        predecessor_ids = {
            event.predecessor_event_ref
            for event in lineage_events
            if event.predecessor_event_ref in event_ids
        }
        heads[lineage] = [
            event for event in lineage_events if event.control_event_id not in predecessor_ids
        ]
    return heads


def run_k2(
    connection: sqlite3.Connection,
    *,
    ssot_version_id: str,
    run_id: str,
    checked_at: str,
    lineage_refs: list[str],
) -> list[ControlEvent]:
    version = read_ssot_version(connection, ssot_version_id)
    evaluations = _state_evaluations(version)
    existing = _events_for_version(connection, ssot_version_id)
    result: list[ControlEvent] = []
    for control_id in applicable_k2_control_ids(version):
        subjects = _stable_subject_refs(version, control_id)
        lineage = control_id + "|" + "|".join(sorted(subjects))
        matches = [event for event in existing if k2_lineage_key(event) == lineage]
        if matches:
            predecessor_ids = {
                event.predecessor_event_ref
                for event in matches
                if event.predecessor_event_ref is not None
            }
            result.extend(
                event for event in matches if event.control_event_id not in predecessor_ids
            )
            continue
        passed, observed, expected, description = evaluations[control_id]
        evidence_body = {
            "schema": "bms.w2-c3-k2-evaluation",
            "schema_version": "0.1",
            "control_id": control_id,
            "ssot_version_id": ssot_version_id,
            "lineage_key": lineage,
            "observed_status": observed,
            "expected_status": expected,
            "check_status": "CHECK_PASSED" if passed else "CHECK_FAILED",
        }
        evidence = store_evidence(
            connection,
            content=_canonical_bytes(evidence_body),
            run_id=run_id,
            media_type="application/json",
        )
        block_effect = "NONE" if passed else (
            "PROCESS_BLOCK" if control_id == "CTL-K2-001" else "RELEASE_BLOCK"
        )
        event = store_control_event(
            connection,
            control_id=control_id,
            checked_at=checked_at,
            object_refs=[
                f"ssot_version:{ssot_version_id}",
                *subjects,
                *lineage_refs,
            ],
            control_point="K2",
            severity="CRITICAL",
            check_status="CHECK_PASSED" if passed else "CHECK_FAILED",
            observed_status=observed,
            expected_status=expected,
            description=description,
            trace_refs=[
                "DOC-015",
                {
                    "CTL-K2-001": "TC6-040",
                    "CTL-K2-002": "TC6-030",
                    "CTL-K2-003": "TC6-005",
                    "CTL-K2-004": "TC6-030",
                    "CTL-K2-005": "TC6-006",
                    "CTL-K2-006": "TC6-029;TC6-030",
                }[control_id],
                f"k2_evidence:{evidence.evidence_id}",
            ],
            block_effect=block_effect,
            blocked_process=None if passed else "G3 SSOT-Version",
            owner_level="SSOT",
            resolution_status="RESOLVED" if passed else "OPEN",
            evidence_ref=evidence.evidence_id,
        )
        result.append(event)
    return result


def _valid_k2_evidence(connection: sqlite3.Connection, event: ControlEvent) -> bool:
    try:
        evidence = read_evidence(connection, event.evidence_ref)
        return evidence.media_type == "application/json" and verify_evidence(
            connection, event.evidence_ref
        )
    except (KeyError, ValueError):
        return False


def _valid_k2_context(
    connection: sqlite3.Connection,
    *,
    event: ControlEvent,
    version: SSOTVersion,
    mapping_id: str,
    specification_manifest_sha256: str,
) -> bool:
    try:
        mapping = read_mapping_record(connection, mapping_id)
        raw = read_raw_observation(connection, mapping.raw_record_id)
    except KeyError:
        return False
    state = version.state
    player_id = state.get("player", {}).get("player_id")
    club_id = state.get("club", {}).get("club_id")
    legitimation_ref = state.get("player", {}).get("legitimation_ref")
    expected_refs = {
        f"run:{version.run_id}",
        f"raw_record:{raw.raw_record_id}",
        f"evidence:{raw.raw_payload_ref}",
        f"mapping_record:{mapping_id}",
        f"legitimation:{legitimation_ref}",
        f"player:{player_id}",
        f"club:{club_id}",
        f"baseline_commit:{BASELINE_COMMIT}",
    }
    specification_refs = [
        ref
        for ref in event.object_refs
        if ref.startswith("specification_manifest_sha256:")
    ]
    context_prefixes = (
        "run:",
        "raw_record:",
        "evidence:",
        "mapping_record:",
        "legitimation:",
        "player:",
        "club:",
        "baseline_commit:",
    )
    return bool(
        mapping.run_id == version.run_id == raw.run_id
        and mapping.raw_record_id == raw.raw_record_id
        and mapping.mapping_status == "CONFIRMED"
        and mapping.conflict_status == "CLEAR"
        and mapping.internal_object_id == player_id
        and expected_refs.issubset(event.object_refs)
        and all(
            len([ref for ref in event.object_refs if ref.startswith(prefix)]) == 1
            for prefix in context_prefixes
        )
        and len(specification_refs) == 1
        and specification_refs[0]
        == f"specification_manifest_sha256:{specification_manifest_sha256}"
    )


def derive_g3(
    connection: sqlite3.Connection,
    *,
    g2: dict[str, Any],
    ssot_version_id: str,
    specification_manifest_sha256: str,
) -> dict[str, Any]:
    if re.fullmatch(r"[0-9a-f]{64}", specification_manifest_sha256) is None:
        raise ValueError(
            "specification_manifest_sha256 must be a lowercase SHA-256"
        )
    version = read_ssot_version(connection, ssot_version_id)
    required_ids = applicable_k2_control_ids(version)
    expected_lineages = {
        control_id: control_id
        + "|"
        + "|".join(sorted(_stable_subject_refs(version, control_id)))
        for control_id in required_ids
    }
    heads = effective_k2_heads(connection, ssot_version_id)
    selected: dict[str, ControlEvent] = {}
    exactly_one = True
    for control_id, lineage in expected_lineages.items():
        candidates = heads.get(lineage, [])
        exactly_one = exactly_one and len(candidates) == 1
        if len(candidates) == 1:
            selected[control_id] = candidates[0]
    mapping_id = version.state.get("mapping", {}).get("mapping_record_id")
    contexts_valid = exactly_one and all(
        event.control_point == "K2"
        and f"ssot_version:{ssot_version_id}" in event.object_refs
        and isinstance(mapping_id, str)
        and _valid_k2_context(
            connection,
            event=event,
            version=version,
            mapping_id=mapping_id,
            specification_manifest_sha256=specification_manifest_sha256,
        )
        and _valid_k2_evidence(connection, event)
        for event in selected.values()
    )
    all_passed = exactly_one and all(
        event.check_status == "CHECK_PASSED"
        and event.block_effect == "NONE"
        and event.resolution_status == "RESOLVED"
        for event in selected.values()
    )
    evaluations = _state_evaluations(version)
    independent_processable = all(
        evaluations[control_id][0]
        for control_id in required_ids
        if control_id != "CTL-K2-006"
    ) and not version.state.get("open_critical_review_cases")
    state_processable = version.state.get("status") == "SSOT_PROCESSABLE"
    processability_control_consistent = (
        "CTL-K2-006" in selected
        and selected["CTL-K2-006"].observed_status == version.state.get("status")
        and evaluations["CTL-K2-006"][0]
    )
    upstream_ok = (
        g2.get("decision") == "MAPPING_RELEASED"
        and mapping_id in g2.get("mapping_record_ids", [])
    )
    released = bool(
        upstream_ok
        and exactly_one
        and contexts_valid
        and all_passed
        and independent_processable
        and state_processable
        and processability_control_consistent
    )
    return {
        "schema": "bms.w2-c3-g3-decision",
        "schema_version": "0.1",
        "decision": "SSOT_RELEASED" if released else "BLOCKED",
        "ssot_version_id": ssot_version_id,
        "specification_manifest_sha256": specification_manifest_sha256,
        "upstream_g2_decision": g2.get("decision"),
        "mapping_record_id": mapping_id,
        "required_control_ids": list(required_ids),
        "evaluated_head_ids": {
            control_id: event.control_event_id for control_id, event in selected.items()
        },
        "lineages": {
            control_id: {
                "lineage_key": lineage,
                "evaluation_instance_key": lineage + f"|ssot_version:{ssot_version_id}",
                "head_count": len(heads.get(lineage, [])),
            }
            for control_id, lineage in expected_lineages.items()
        },
        "derivation": {
            "upstream_g2_released": upstream_ok,
            "required_lineages_have_exactly_one_head": exactly_one,
            "head_contexts_valid": contexts_valid,
            "all_required_heads_passed": all_passed,
            "independently_processable": independent_processable,
            "ssot_state_processable": state_processable,
            "k2_006_consistent": processability_control_consistent,
        },
    }


def read_ssot_version_release(
    connection: sqlite3.Connection, ssot_version_id: str
) -> SSOTVersionRelease:
    row = connection.execute(
        "SELECT * FROM ssot_version_release WHERE ssot_version_id = ?",
        (ssot_version_id,),
    ).fetchone()
    if row is None:
        raise KeyError(f"unknown SSOT version release: {ssot_version_id}")
    return SSOTVersionRelease(**dict(row))


def store_g3_release(
    connection: sqlite3.Connection,
    *,
    run_id: str,
    g3: dict[str, Any],
    released_at: str,
) -> SSOTVersionRelease:
    if g3.get("decision") != "SSOT_RELEASED":
        raise W2C3Error("a G3 release requires an SSOT_RELEASED decision")
    derivation = g3.get("derivation")
    if not isinstance(derivation, dict) or not derivation or not all(
        value is True for value in derivation.values()
    ):
        raise W2C3Error("G3 release prerequisites are not completely positive")
    ssot_version_id = g3.get("ssot_version_id")
    if not isinstance(ssot_version_id, str):
        raise W2C3Error("G3 decision has no SSOT version reference")
    read_ssot_version(connection, ssot_version_id)
    existing = connection.execute(
        "SELECT 1 FROM ssot_version_release WHERE ssot_version_id = ?",
        (ssot_version_id,),
    ).fetchone()
    if existing is not None:
        release = read_ssot_version_release(connection, ssot_version_id)
        evidence = read_evidence(connection, release.g3_evidence_id)
        if (
            release.run_id != run_id
            or release.released_at != released_at
            or evidence.content_blob != _canonical_bytes(g3)
        ):
            raise W2C3Error("existing G3 release conflicts with replay input")
        return release
    parsed_release = datetime.fromisoformat(released_at)
    if parsed_release.tzinfo is None or parsed_release.utcoffset() is None:
        raise W2C3Error("released_at must include a timezone offset")
    connection.execute("SAVEPOINT store_g3_release")
    try:
        evidence = store_evidence(
            connection,
            content=_canonical_bytes(g3),
            run_id=run_id,
            media_type="application/json",
        )
        release = SSOTVersionRelease(
            release_id=str(uuid.uuid4()),
            ssot_version_id=ssot_version_id,
            run_id=run_id,
            g3_decision="SSOT_RELEASED",
            g3_evidence_id=evidence.evidence_id,
            released_at=released_at,
            created_at=_now(),
        )
        connection.execute(
            "INSERT INTO ssot_version_release VALUES (?, ?, ?, ?, ?, ?, ?)",
            tuple(release.__dict__.values()),
        )
        connection.execute("RELEASE store_g3_release")
        return release
    except Exception:
        connection.execute("ROLLBACK TO store_g3_release")
        connection.execute("RELEASE store_g3_release")
        raise


def _lineage_refs(
    *, run_id: str, raw_id: str, evidence_id: str, mapping_id: str, spec_hash: str
) -> list[str]:
    return [
        f"run:{run_id}",
        f"raw_record:{raw_id}",
        f"evidence:{evidence_id}",
        f"mapping_record:{mapping_id}",
        f"legitimation:{PLAYER_LEGITIMATION_REF}",
        f"player:{PLAYER_ID}",
        f"club:{CLUB_ID}",
        f"specification_manifest_sha256:{spec_hash}",
        f"baseline_commit:{BASELINE_COMMIT}",
    ]


def _positive_run(
    database_path: Path, fixture_dir: Path, *, repo_root: Path, run_id: str
) -> dict[str, Any]:
    connection = connect_database(database_path)
    try:
        applied = apply_migrations(connection, repo_root / "migrations")
        imported = import_fixture(connection, fixture_dir=fixture_dir, run_id=run_id)
        k0 = run_k0(
            connection,
            contract=imported.contract,
            run_id=run_id,
            import_batch_id=imported.envelope.import_batch_id,
            raw_record_id=imported.raw_observation.raw_record_id,
        )
        g1 = derive_g1(
            connection,
            run_id=run_id,
            import_batch_id=imported.envelope.import_batch_id,
            control_event_ids=[event.control_event_id for event in k0],
            raw_record_ids=[imported.raw_observation.raw_record_id],
            evidence_ids=[imported.evidence.evidence_id],
        )
        if g1["decision"] != "RELEASED_FOR_MAPPING":
            raise W2C3Error("positive fixture did not pass G1")
        evidence_bindings = register_evidence_manifest(
            connection,
            manifest_path=fixture_dir / "seed-evidence-manifest.json",
            run_id=run_id,
        )
        entity = imported.parsed_source["entities"]["Q96072055"]
        bootstrap = store_authorized_player_bootstrap(
            connection,
            run_id=run_id,
            legitimation_ref=PLAYER_LEGITIMATION_REF,
            decided_at="2026-09-02T15:57:44+02:00",
            authorized_by="Fach-Chat Erstellung SSOT",
            player_id=PLAYER_ID,
            display_name=entity["labels"]["de"]["value"],
            evidence_refs=(WIKIDATA_EVIDENCE_REF, BUNDESLIGA_EVIDENCE_REF, FCB_EVIDENCE_REF),
            raw_record_id=imported.raw_observation.raw_record_id,
            source_system="WIKIDATA",
            external_id="Q96072055",
            confirmation_evidence_ref=WIKIDATA_EVIDENCE_REF,
        )
        k1 = run_applicable_k1(connection, bootstrap.mapping.mapping_record_id)
        g2 = derive_g2(
            connection,
            mapping_record_ids=[bootstrap.mapping.mapping_record_id],
            control_event_ids=[event.control_event_id for event in k1],
        )
        if g2["decision"] != "MAPPING_RELEASED":
            raise W2C3Error("positive bootstrap did not pass G2")
        state = build_positive_ssot_state(bootstrap.mapping.mapping_record_id)
        version = store_replay_safe_ssot_version(
            connection,
            run_id=run_id,
            data_as_of="2026-09-02T17:54:42Z",
            change_ref="c3-handoff:w2-c3-positive-01",
            state=state,
        )
        spec_hash = hashlib.sha256(
            (repo_root / "spec/specification-manifest.json").read_bytes()
        ).hexdigest()
        lineage_refs = _lineage_refs(
            run_id=run_id,
            raw_id=imported.raw_observation.raw_record_id,
            evidence_id=imported.evidence.evidence_id,
            mapping_id=bootstrap.mapping.mapping_record_id,
            spec_hash=spec_hash,
        )
        k2 = run_k2(
            connection,
            ssot_version_id=version.ssot_version_id,
            run_id=run_id,
            checked_at="2026-09-02T18:00:00Z",
            lineage_refs=lineage_refs,
        )
        g3 = derive_g3(
            connection,
            g2=g2,
            ssot_version_id=version.ssot_version_id,
            specification_manifest_sha256=spec_hash,
        )
        release = store_g3_release(
            connection,
            run_id=run_id,
            g3=g3,
            released_at="2026-09-02T18:05:00Z",
        )
        replay_bootstrap = store_authorized_player_bootstrap(
            connection,
            run_id=run_id,
            legitimation_ref=PLAYER_LEGITIMATION_REF,
            decided_at="2026-09-02T15:57:44+02:00",
            authorized_by="Fach-Chat Erstellung SSOT",
            player_id=PLAYER_ID,
            display_name="Jamal Musiala",
            evidence_refs=(FCB_EVIDENCE_REF, BUNDESLIGA_EVIDENCE_REF, WIKIDATA_EVIDENCE_REF),
            raw_record_id=imported.raw_observation.raw_record_id,
            source_system="WIKIDATA",
            external_id="Q96072055",
            confirmation_evidence_ref=WIKIDATA_EVIDENCE_REF,
        )
        replay_version = store_replay_safe_ssot_version(
            connection,
            run_id=run_id,
            data_as_of="2026-09-02T17:54:42Z",
            change_ref="c3-handoff:w2-c3-positive-01",
            state=state,
        )
        replay_k2 = run_k2(
            connection,
            ssot_version_id=version.ssot_version_id,
            run_id=run_id,
            checked_at="2026-09-02T18:00:00Z",
            lineage_refs=lineage_refs,
        )
        replay_release = store_g3_release(
            connection,
            run_id=run_id,
            g3=g3,
            released_at="2026-09-02T18:05:00Z",
        )
        counts = {
            table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in (
                "ssot_identity_legitimation",
                "ssot_player",
                "ssot_version",
                "ssot_version_release",
            )
        }
        return {
            "status": "PASS",
            "run_id": run_id,
            "applied_migrations": applied,
            "raw_record_id": imported.raw_observation.raw_record_id,
            "raw_evidence_id": imported.evidence.evidence_id,
            "evidence_bindings": evidence_bindings,
            "g1": g1,
            "mapping": bootstrap.mapping,
            "g2": g2,
            "ssot_version": version,
            "k2": k2,
            "g3": g3,
            "release": release,
            "state": state,
            "counts": counts,
            "idempotent": (
                replay_bootstrap == bootstrap
                and replay_version == version
                and replay_k2 == k2
                and replay_release == release
                and counts == {
                    "ssot_identity_legitimation": 1,
                    "ssot_player": 1,
                    "ssot_version": 1,
                    "ssot_version_release": 1,
                }
            ),
        }
    finally:
        connection.close()


def _negative_run(
    database_path: Path, fixture_dir: Path, *, repo_root: Path, run_id: str
) -> dict[str, Any]:
    connection = connect_database(database_path)
    try:
        applied = apply_migrations(connection, repo_root / "migrations")
        imported = import_fixture(connection, fixture_dir=fixture_dir, run_id=run_id)
        k0 = run_k0(
            connection,
            contract=imported.contract,
            run_id=run_id,
            import_batch_id=imported.envelope.import_batch_id,
            raw_record_id=imported.raw_observation.raw_record_id,
        )
        g1 = derive_g1(
            connection,
            run_id=run_id,
            import_batch_id=imported.envelope.import_batch_id,
            control_event_ids=[event.control_event_id for event in k0],
            raw_record_ids=[imported.raw_observation.raw_record_id],
            evidence_ids=[imported.evidence.evidence_id],
        )
        mapping = map_external_identity(
            connection,
            raw_record_id=imported.raw_observation.raw_record_id,
            run_id=run_id,
            source_system=imported.raw_observation.source_system,
            external_id=imported.envelope.external_player_id,
            object_type="PLAYER",
            criticality="CRITICAL",
        )
        k1 = run_applicable_k1(connection, mapping.mapping_record_id)
        g2 = derive_g2(
            connection,
            mapping_record_ids=[mapping.mapping_record_id],
            control_event_ids=[event.control_event_id for event in k1],
        )
        counts = {
            "ssot_versions": connection.execute("SELECT COUNT(*) FROM ssot_version").fetchone()[0],
            "k2_events": connection.execute("SELECT COUNT(*) FROM control_event WHERE control_point='K2'").fetchone()[0],
            "g3_decisions": connection.execute(
                """
                SELECT COUNT(*) FROM evidence_artifact
                WHERE CASE
                    WHEN json_valid(content_blob)
                    THEN json_extract(content_blob, '$.schema') = 'bms.w2-c3-g3-decision'
                    ELSE 0
                END
                """
            ).fetchone()[0],
            "releases": connection.execute("SELECT COUNT(*) FROM ssot_version_release").fetchone()[0],
        }
        short_circuit = g2["decision"] == "BLOCKED" and not any(counts.values())
        return {
            "status": "PASS" if short_circuit else "FAIL",
            "run_id": run_id,
            "applied_migrations": applied,
            "g1": g1["decision"],
            "mapping": mapping.mapping_status,
            "g2": g2["decision"],
            "counts": counts,
            "stopped_after": "G2",
            "short_circuit": short_circuit,
        }
    finally:
        connection.close()


def _scope_guard(repo_root: Path) -> dict[str, Any]:
    migrations = sorted(path.name for path in (repo_root / "migrations").glob("*.sql"))
    current_hashes = {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in (repo_root / "migrations").glob("000[1-5]_*.sql")
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
    dependencies = tomllib.loads((repo_root / "pyproject.toml").read_text())["project"].get(
        "dependencies", []
    )
    forbidden = {
        "monitoring", "eligibility", "recommendation", "snapshot",
        "manager_decision", "result", "evaluation", "gate_engine",
    }
    checks = {
        "migrations_exact_0001_0006": migrations == [
            "0001_raw_evidence.sql", "0002_control_event.sql",
            "0003_import_envelope.sql", "0004_mapping_review.sql",
            "0005_ssot_persistence.sql", "0006_ssot_version_release.sql",
        ],
        "baseline_migrations_unchanged": current_hashes == BASELINE_MIGRATION_HASHES,
        "forbidden_modules_absent": forbidden.isdisjoint(modules),
        "no_network_imports": {"http", "socket", "urllib", "requests"}.isdisjoint(imports),
        "stdlib_only": not (imports - sys.stdlib_module_names) and dependencies == [],
    }
    return {
        "schema": "bms.w2-c3-scope-guard",
        "schema_version": "0.1",
        "status": "PASS" if all(checks.values()) else "FAIL",
        "checks": checks,
        "migrations": migrations,
    }


def _serialize_positive(result: dict[str, Any]) -> dict[str, Any]:
    state = result["state"]
    return {
        "status": result["status"],
        "run_id": result["run_id"],
        "raw_record_id": result["raw_record_id"],
        "raw_evidence_id": result["raw_evidence_id"],
        "g1": result["g1"],
        "mapping": result["mapping"].__dict__,
        "g2": result["g2"],
        "legitimation_ref": PLAYER_LEGITIMATION_REF,
        "player_id": PLAYER_ID,
        "club_id": CLUB_ID,
        "season_id": SEASON_ID,
        "evidence_bindings": [
            binding.__dict__ for binding in result["evidence_bindings"]
        ],
        "ssot_version_id": result["ssot_version"].ssot_version_id,
        "ssot_status": state["status"],
        "club_assignment_ref": state["player_club_assignment"]["player_club_assignment_id"],
        "position_assignment_ref": state["player_position_assignment"]["player_position_assignment_id"],
        "k2_controls": [
            {
                "control_event_id": event.control_event_id,
                "control_id": event.control_id,
                "check_status": event.check_status,
                "block_effect": event.block_effect,
                "resolution_status": event.resolution_status,
                "evidence_ref": event.evidence_ref,
                "object_refs": list(event.object_refs),
                "trace_refs": list(event.trace_refs),
                "lineage_key": k2_lineage_key(event),
                "evaluation_instance_key": k2_evaluation_instance_key(event),
            }
            for event in result["k2"]
        ],
        "g3": result["g3"],
        "release": result["release"].__dict__,
        "idempotent": result["idempotent"],
        "counts": result["counts"],
    }


def run_w2_c3_smoke(output_dir: Path, *, repo_root: Path) -> dict[str, Any]:
    _prepare_output(output_dir)
    positive_fixture = repo_root / "pilot_data/w2/fixtures/w2-c3-positive-01"
    negative_fixture = repo_root / "pilot_data/w2/fixtures/w2-pilot-01"
    validate_fixture(positive_fixture)
    validate_fixture(negative_fixture)
    manifest = build_run_manifest(
        repo_root=repo_root,
        specification_manifest=repo_root / "spec/specification-manifest.json",
    )
    run_id = manifest["run_id"]
    a = _positive_run(
        output_dir / "positive-a.sqlite3", positive_fixture,
        repo_root=repo_root, run_id=run_id,
    )
    b = _positive_run(
        output_dir / "positive-b.sqlite3", positive_fixture,
        repo_root=repo_root, run_id=run_id,
    )
    negative = _negative_run(
        output_dir / "negative.sqlite3", negative_fixture,
        repo_root=repo_root, run_id=run_id,
    )
    positive_a = _serialize_positive(a)
    positive_b = _serialize_positive(b)
    def stable_projection(value: dict[str, Any]) -> dict[str, Any]:
        return {
            "g1": value["g1"]["decision"],
            "mapping_status": value["mapping"]["mapping_status"],
            "g2": value["g2"]["decision"],
            "player_id": value["player_id"],
            "club_id": value["club_id"],
            "season_id": value["season_id"],
            "ssot_status": value["ssot_status"],
            "club_assignment_ref": value["club_assignment_ref"],
            "position_assignment_ref": value["position_assignment_ref"],
            "k2": [
                item["control_id"] + ":" + item["check_status"]
                for item in value["k2_controls"]
            ],
            "g3": value["g3"]["decision"],
            "idempotent": value["idempotent"],
        }
    replay = {
        "schema": "bms.w2-c3-replay-comparison",
        "schema_version": "0.1",
        "status": "PASS" if stable_projection(positive_a) == stable_projection(positive_b) else "FAIL",
        "stable_projection_a": stable_projection(positive_a),
        "stable_projection_b": stable_projection(positive_b),
    }
    scope = _scope_guard(repo_root)
    migration_rows = connect_database(output_dir / "positive-a.sqlite3")
    try:
        migrations = [dict(row) for row in migration_rows.execute(
            "SELECT migration_id, checksum_sha256 FROM schema_migrations ORDER BY migration_id"
        )]
    finally:
        migration_rows.close()
    acceptance_checks = {
        "positive_g1_released": positive_a["g1"]["decision"]
        == "RELEASED_FOR_MAPPING",
        "positive_mapping_confirmed": positive_a["mapping"]["mapping_status"]
        == "CONFIRMED",
        "positive_g2_released": positive_a["g2"]["decision"]
        == "MAPPING_RELEASED",
        "positive_ssot_processable": positive_a["ssot_status"]
        == "SSOT_PROCESSABLE",
        "all_applicable_k2_passed": all(
            item["check_status"] == "CHECK_PASSED"
            for item in positive_a["k2_controls"]
        ),
        "positive_g3_released": positive_a["g3"]["decision"]
        == "SSOT_RELEASED",
        "release_matches_ssot_version": positive_a["release"]["ssot_version_id"]
        == positive_a["ssot_version_id"],
        "in_database_replay_idempotent": positive_a["idempotent"],
        "a_b_replay_stable": replay["status"] == "PASS",
        "negative_stops_at_g2_without_c3_artifacts": negative["short_circuit"],
        "scope_guard_passed": scope["status"] == "PASS",
    }
    test_result = {
        "schema": "bms.w2-c3-smoke-acceptance",
        "schema_version": "0.1",
        "status": "PASS" if all(acceptance_checks.values()) else "FAIL",
        "checks": acceptance_checks,
    }
    reports = {
        "positive-run-a.json": positive_a,
        "positive-run-b.json": positive_b,
        "negative-short-circuit.json": negative,
        "replay-comparison.json": replay,
        "scope-guard.json": scope,
        "test-result.json": test_result,
        "run-manifest.json": {
            **manifest,
            "baseline_commit": BASELINE_COMMIT,
            "schema_migrations": migrations,
            "positive_fixture": "w2-c3-positive-01",
            "negative_fixture": "w2-pilot-01",
        },
    }
    overall = all(
        (
            test_result["status"] == "PASS",
        )
    )
    smoke = {
        "schema": "bms.w2-c3-smoke-report",
        "schema_version": "0.1",
        "status": "PASS" if overall else "FAIL",
        "run_id": run_id,
        "positive_end_status": positive_a["g3"]["decision"],
        "negative_short_circuit": negative["short_circuit"],
        "replay_status": replay["status"],
        "scope_status": scope["status"],
    }
    reports["smoke-report.json"] = smoke
    for name, report in reports.items():
        _write_json(output_dir / name, report)
    indexed_names = [
        *reports,
        "positive-a.sqlite3",
        "positive-b.sqlite3",
        "negative.sqlite3",
    ]
    artifacts = [
        {
            "path": name,
            "sha256": hashlib.sha256((output_dir / name).read_bytes()).hexdigest(),
        }
        for name in indexed_names
    ]
    _write_json(
        output_dir / "evidence-index.json",
        {
            "schema": "bms.w2-c3-evidence-index",
            "schema_version": "0.1",
            "status": smoke["status"],
            "run_id": run_id,
            "artifacts": artifacts,
        },
    )
    if smoke["status"] != "PASS":
        raise W2C3Error(f"C3 smoke failed: {smoke}")
    return smoke
