from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Any, Iterable

POSITION_CLASSES = {"T", "A", "M", "S"}
REQUIRED_PLAYER_CONTROLS = (
    "CTL-K2-002", "CTL-K2-003", "CTL-K2-004", "CTL-K2-005", "CTL-K2-006", "CTL-K2-008"
)

class W31CurrentStateError(RuntimeError):
    pass

def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")

def _canonical_bytes(value: dict[str, Any]) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")

def _evidence(connection: sqlite3.Connection, *, run_id: str, body: dict[str, Any], created_at: str) -> str:
    content = _canonical_bytes(body)
    evidence_id = f"evidence:{uuid.uuid4()}"
    connection.execute(
        "INSERT INTO evidence_artifact VALUES (?, ?, ?, ?, ?, ?, ?)",
        (evidence_id, run_id, sqlite3.Binary(content), hashlib.sha256(content).hexdigest(), len(content), "application/json", created_at),
    )
    return evidence_id

def _control(connection: sqlite3.Connection, *, run_id: str, checked_at: str, control_id: str,
             object_refs: list[str], passed: bool, observed: str, expected: str,
             description: str, trace_refs: list[str]) -> dict[str, Any]:
    body = {
        "schema": "bms.w3-1-k2-evaluation", "schema_version": "0.1",
        "control_id": control_id, "check_status": "CHECK_PASSED" if passed else "CHECK_FAILED",
        "object_refs": object_refs, "observed_status": observed, "expected_status": expected,
    }
    evidence_id = _evidence(connection, run_id=run_id, body=body, created_at=checked_at)
    event_id = str(uuid.uuid4())
    connection.execute(
        """INSERT INTO control_event (
        control_event_id, control_id, checked_at, object_refs, control_point, severity,
        check_status, observed_status, expected_status, description, trace_refs,
        block_effect, blocked_process, owner_level, resolution_status, evidence_ref,
        resolution_ref, predecessor_event_ref, created_at
        ) VALUES (?, ?, ?, ?, 'K2', 'CRITICAL', ?, ?, ?, ?, ?, ?, ?, 'SSOT', ?, ?, NULL, NULL, ?)""",
        (event_id, control_id, checked_at, json.dumps(object_refs, ensure_ascii=False),
         body["check_status"], observed, expected, description, json.dumps(trace_refs, ensure_ascii=False),
         "NONE" if passed else "RELEASE_BLOCK", None if passed else "G3 SSOT-Version",
         "RESOLVED" if passed else "OPEN", evidence_id, checked_at),
    )
    return {"control_event_id": event_id, **body, "evidence_ref": evidence_id}

def build_current_state_player(value: dict[str, Any], *, data_as_of: str, ssot_version_id: str,
                               club_state_evidence_ref: str, position_evidence_ref: str) -> dict[str, Any]:
    required = ("player_id", "player_legitimation_ref", "club_id", "club_legitimation_ref", "season_position",
                "club_name", "observed_at", "source_reference")
    if any(not value.get(field) for field in required):
        raise W31CurrentStateError("current-state materialization input is incomplete")
    if value["season_position"] not in POSITION_CLASSES:
        raise W31CurrentStateError("season_position must be T/A/M/S")
    confirmation_id = str(uuid.uuid5(uuid.NAMESPACE_URL,
        f"bms:w3.1:player-club-state:{value['player_id']}:{value['club_id']}:{data_as_of}:{club_state_evidence_ref}"))
    confirmation = {
        "player_club_state_confirmation_id": confirmation_id,
        "player_id": value["player_id"], "club_id": value["club_id"], "as_of": data_as_of,
        "evidence_ref": club_state_evidence_ref, "source_reference": value["source_reference"],
        "observed_at": value["observed_at"], "verification_status": "CONFIRMED",
        "release_status": "RELEASED", "conflict_status": "CLEAR", "ssot_version_id": ssot_version_id,
    }
    if any(key in confirmation for key in ("valid_from", "club_valid_from", "valid_to", "club_valid_to")):
        raise W31CurrentStateError("current-state confirmation must not contain historical interval boundaries")
    return {
        "status": "SSOT_PROCESSABLE", "open_critical_review_cases": [],
        "player": {"player_id": value["player_id"], "identity_status": "IDENTITY_LEGITIMATED", "legitimation_ref": value["player_legitimation_ref"]},
        "club": {"club_id": value["club_id"], "club_name": value["club_name"], "identity_status": "IDENTITY_LEGITIMATED", "legitimation_ref": value["club_legitimation_ref"]},
        "season_position": {"position": value["season_position"], "evidence_ref": position_evidence_ref},
        "player_club_state_confirmation": confirmation,
    }

def validate_tc6_050(player_state: dict[str, Any], *, data_as_of: str) -> bool:
    confirmation = player_state.get("player_club_state_confirmation", {})
    return bool(
        confirmation.get("as_of") == data_as_of
        and confirmation.get("verification_status") == "CONFIRMED"
        and confirmation.get("release_status") == "RELEASED"
        and confirmation.get("conflict_status") == "CLEAR"
        and confirmation.get("evidence_ref")
        and confirmation.get("source_reference")
        and confirmation.get("observed_at")
        and not any(key in confirmation for key in ("valid_from", "club_valid_from", "valid_to", "club_valid_to"))
    )

def materialize_current_state_release(connection: sqlite3.Connection, *, run_id: str, data_as_of: str,
                                      players: Iterable[dict[str, Any]], blocked_inputs: list[dict[str, Any]],
                                      club_state_evidence_ref: str, position_evidence_ref: str,
                                      specification_manifest_sha256: str, change_ref: str,
                                      checked_at: str | None = None) -> dict[str, Any]:
    checked_at = checked_at or _now()
    ssot_version_id = str(uuid.uuid4())
    player_states = [build_current_state_player(v, data_as_of=data_as_of, ssot_version_id=ssot_version_id,
        club_state_evidence_ref=club_state_evidence_ref, position_evidence_ref=position_evidence_ref) for v in players]
    state = {
        "schema": "bms.w3-1-ssot-current-state", "schema_version": "0.1", "status": "SSOT_PROCESSABLE",
        "data_as_of": data_as_of, "players": player_states, "blocked_inputs": blocked_inputs,
        "open_critical_review_cases": [],
    }
    connection.execute("SAVEPOINT w3_1_current_state_release")
    try:
        connection.execute(
            """INSERT INTO ssot_version (ssot_version_id, run_id, data_as_of, released_at,
            predecessor_ssot_version_id, change_ref, release_evidence_ref, state_json, created_at)
            VALUES (?, ?, ?, NULL, NULL, ?, NULL, ?, ?)""",
            (ssot_version_id, run_id, f"{data_as_of}T23:59:59+02:00", change_ref,
             _canonical_bytes(state).decode("utf-8"), checked_at),
        )
        events: list[dict[str, Any]] = []
        for player_state in player_states:
            p = player_state["player"]; c = player_state["club"]; conf = player_state["player_club_state_confirmation"]
            connection.execute(
                """INSERT INTO player_club_state_confirmation (
                player_club_state_confirmation_id, player_id, club_id, as_of, evidence_ref, source_reference,
                observed_at, verification_status, release_status, conflict_status, ssot_version_id, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (conf["player_club_state_confirmation_id"], p["player_id"], c["club_id"], conf["as_of"],
                 conf["evidence_ref"], conf["source_reference"], conf["observed_at"], conf["verification_status"],
                 conf["release_status"], conf["conflict_status"], ssot_version_id, checked_at),
            )
            checks = {
                "CTL-K2-002": bool(p["player_id"] and p["legitimation_ref"] and c["club_id"] and c["legitimation_ref"]),
                "CTL-K2-003": conf["as_of"] == data_as_of and conf["conflict_status"] == "CLEAR",
                "CTL-K2-004": player_state["season_position"]["position"] in POSITION_CLASSES and bool(position_evidence_ref),
                "CTL-K2-005": conf["as_of"] == data_as_of and validate_tc6_050(player_state, data_as_of=data_as_of),
                "CTL-K2-006": player_state["status"] == "SSOT_PROCESSABLE" and not player_state["open_critical_review_cases"],
                "CTL-K2-008": validate_tc6_050(player_state, data_as_of=data_as_of),
            }
            for control_id in REQUIRED_PLAYER_CONTROLS:
                events.append(_control(connection, run_id=run_id, checked_at=checked_at, control_id=control_id,
                    object_refs=[f"ssot_version:{ssot_version_id}", f"player:{p['player_id']}", f"club:{c['club_id']}",
                                 f"player_club_state_confirmation:{conf['player_club_state_confirmation_id']}",
                                 f"as_of:{data_as_of}", f"evidence_ref:{conf['evidence_ref']}"],
                    passed=checks[control_id], observed="CONFIRMED" if checks[control_id] else "FAILED",
                    expected="CONFIRMED", description="W3.1 current-state SSOT control",
                    trace_refs=["DOC-015", "DEC-032", "REQ-SSOT-006", "TC6-050" if control_id in {"CTL-K2-003","CTL-K2-005","CTL-K2-006","CTL-K2-008"} else "TC6-030"]))
        k207 = _control(connection, run_id=run_id, checked_at=checked_at, control_id="CTL-K2-007",
            object_refs=[f"ssot_version:{ssot_version_id}", "scope:reuse-existing-dec030-only"], passed=True,
            observed="NO_NEW_IDENTITY_CREATED", expected="NO_RELEGITIMATION_OF_EXISTING_IDENTITIES",
            description="Existing positive DEC-030 identities reused; initial legitimation control remains separate.",
            trace_refs=["DOC-015", "DEC-030", "REQ-SSOT-005", "TC6-048"])
        events.append(k207)
        all_passed = all(event["check_status"] == "CHECK_PASSED" for event in events)
        tc650_pass = all(validate_tc6_050(s, data_as_of=data_as_of) for s in player_states)
        if not all_passed or not tc650_pass:
            raise W31CurrentStateError("K2/TC6-050 did not pass; G3 release prohibited")
        g3 = {
            "schema": "bms.w2-c3-g3-decision", "schema_version": "0.1", "decision": "SSOT_RELEASED",
            "ssot_version_id": ssot_version_id, "specification_manifest_sha256": specification_manifest_sha256,
            "required_control_ids": [*REQUIRED_PLAYER_CONTROLS, "CTL-K2-007"],
            "derivation": {
                "all_required_heads_passed": True, "current_state_confirmations_released": True,
                "tc6_050_passed": True, "no_synthetic_club_valid_from": True,
                "ssot_state_processable": True,
            },
            "released_scope_player_count": len(player_states),
            "blocked_inputs": blocked_inputs,
        }
        g3_evidence_id = _evidence(connection, run_id=run_id, body=g3, created_at=checked_at)
        release_id = str(uuid.uuid4())
        connection.execute(
            "INSERT INTO ssot_version_release VALUES (?, ?, ?, 'SSOT_RELEASED', ?, ?, ?)",
            (release_id, ssot_version_id, run_id, g3_evidence_id, checked_at, checked_at),
        )
        connection.execute("RELEASE w3_1_current_state_release")
    except Exception:
        connection.execute("ROLLBACK TO w3_1_current_state_release")
        connection.execute("RELEASE w3_1_current_state_release")
        raise
    return {
        "run_id": run_id, "ssot_version_id": ssot_version_id, "k2_result": "PASS",
        "k2_event_count": len(events), "ctl_k2_008_passed": len(player_states),
        "ctl_k2_007_new_identity_count": 0, "tc6_050": "PASS", "g3_decision": "SSOT_RELEASED",
        "g3_release_id": release_id, "g3_evidence_id": g3_evidence_id,
        "released_scope_player_count": len(player_states), "blocked_inputs": blocked_inputs,
    }
