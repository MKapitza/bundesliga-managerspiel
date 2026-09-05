from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Any

OUTSIDE_BUNDESLIGA = "OUTSIDE_BUNDESLIGA"


class W31OutsideBundesligaError(RuntimeError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _canonical_bytes(value: dict[str, Any]) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def build_outside_bundesliga_state(
    *,
    player_id: str,
    player_legitimation_ref: str,
    season_position: str,
    as_of: str,
    evidence_ref: str,
    source_reference: str,
    observed_at: str,
    ssot_version_id: str,
) -> dict[str, Any]:
    required = {
        "player_id": player_id,
        "player_legitimation_ref": player_legitimation_ref,
        "as_of": as_of,
        "evidence_ref": evidence_ref,
        "source_reference": source_reference,
        "observed_at": observed_at,
        "ssot_version_id": ssot_version_id,
    }
    if any(not value for value in required.values()):
        raise W31OutsideBundesligaError("outside-Bundesliga state input is incomplete")
    if season_position not in {"T", "A", "M", "S"}:
        raise W31OutsideBundesligaError("season_position must be T/A/M/S")
    confirmation_id = str(uuid.uuid5(
        uuid.NAMESPACE_URL,
        f"bms:w3.1:bundesliga-state:{player_id}:{OUTSIDE_BUNDESLIGA}:{as_of}:{evidence_ref}",
    ))
    confirmation = {
        "player_bundesliga_state_confirmation_id": confirmation_id,
        "player_id": player_id,
        "as_of": as_of,
        "membership_status": OUTSIDE_BUNDESLIGA,
        "evidence_ref": evidence_ref,
        "source_reference": source_reference,
        "observed_at": observed_at,
        "verification_status": "CONFIRMED",
        "release_status": "RELEASED",
        "conflict_status": "CLEAR",
        "ssot_version_id": ssot_version_id,
    }
    return {
        "status": "SSOT_PROCESSABLE",
        "open_critical_review_cases": [],
        "player": {
            "player_id": player_id,
            "identity_status": "IDENTITY_LEGITIMATED",
            "legitimation_ref": player_legitimation_ref,
        },
        "season_position": {"position": season_position},
        "player_bundesliga_state_confirmation": confirmation,
        "eligibility_effect": "NOT_CURRENTLY_BUNDESLIGA_ASSIGNABLE",
    }


def validate_outside_bundesliga_state(player_state: dict[str, Any], *, data_as_of: str) -> bool:
    confirmation = player_state.get("player_bundesliga_state_confirmation", {})
    return bool(
        confirmation.get("membership_status") == OUTSIDE_BUNDESLIGA
        and confirmation.get("as_of") == data_as_of
        and confirmation.get("verification_status") == "CONFIRMED"
        and confirmation.get("release_status") == "RELEASED"
        and confirmation.get("conflict_status") == "CLEAR"
        and confirmation.get("evidence_ref")
        and confirmation.get("source_reference")
        and confirmation.get("observed_at")
        and "club_id" not in confirmation
        and "club" not in player_state
        and "player_club_state_confirmation" not in player_state
        and not any(key in confirmation for key in ("valid_from", "club_valid_from", "valid_to", "club_valid_to"))
    )


def store_outside_bundesliga_confirmation(
    connection: sqlite3.Connection,
    *,
    player_state: dict[str, Any],
    created_at: str | None = None,
) -> None:
    if not validate_outside_bundesliga_state(
        player_state,
        data_as_of=player_state["player_bundesliga_state_confirmation"]["as_of"],
    ):
        raise W31OutsideBundesligaError("outside-Bundesliga confirmation is invalid")
    c = player_state["player_bundesliga_state_confirmation"]
    connection.execute(
        """INSERT INTO player_bundesliga_state_confirmation (
        player_bundesliga_state_confirmation_id, player_id, as_of, membership_status,
        evidence_ref, source_reference, observed_at, verification_status, release_status,
        conflict_status, ssot_version_id, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            c["player_bundesliga_state_confirmation_id"], c["player_id"], c["as_of"],
            c["membership_status"], c["evidence_ref"], c["source_reference"], c["observed_at"],
            c["verification_status"], c["release_status"], c["conflict_status"],
            c["ssot_version_id"], created_at or _now(),
        ),
    )


def store_k2_evidence(
    connection: sqlite3.Connection,
    *,
    run_id: str,
    control_id: str,
    object_refs: list[str],
    checked_at: str,
) -> str:
    body = {
        "schema": "bms.w3-1-k2-evaluation",
        "schema_version": "0.2",
        "control_id": control_id,
        "check_status": "CHECK_PASSED",
        "observed_status": OUTSIDE_BUNDESLIGA,
        "expected_status": "EVIDENCED_BUNDESLIGA_SCOPE_STATE",
        "object_refs": object_refs,
    }
    content = _canonical_bytes(body)
    evidence_id = f"evidence:{uuid.uuid4()}"
    connection.execute(
        "INSERT INTO evidence_artifact VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            evidence_id, run_id, sqlite3.Binary(content), hashlib.sha256(content).hexdigest(),
            len(content), "application/json", checked_at,
        ),
    )
    return evidence_id
