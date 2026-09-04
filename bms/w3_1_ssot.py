from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date
from typing import Any

POSITION_CLASSES = {"T", "A", "M", "S"}
SEASON_ID_2026_27 = "73745028-426a-4970-a812-95455407ad77"
SEASON_START_2026_27 = "2026-08-28"
SEASON_END_2026_27 = "2027-05-22"


class W31SSOTError(ValueError):
    """Raised when W3.1 SSOT materialization input is incomplete or inconsistent."""


@dataclass(frozen=True)
class MaterializationInput:
    player_id: str
    player_legitimation_ref: str
    club_id: str | None
    club_legitimation_ref: str | None
    season_position: str
    club_valid_from: str | None
    club_valid_to: str | None
    club_evidence_ref: str | None
    position_evidence_ref: str
    current_bundesliga_assignment_required: bool = True


def _technical_id(kind: str, *values: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, "bms:w3.1:" + kind + ":" + ":".join(values)))


def _iso_date(value: str | None, field_name: str, *, required: bool = True) -> date | None:
    if value is None:
        if required:
            raise W31SSOTError(f"{field_name} is required")
        return None
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise W31SSOTError(f"{field_name} must be ISO date YYYY-MM-DD") from exc


def _require_registered_evidence_ref(value: str | None, field_name: str) -> str:
    if not isinstance(value, str) or not value:
        raise W31SSOTError(f"{field_name} must be non-empty")
    if value.startswith("PENDING_"):
        raise W31SSOTError(f"{field_name} is not registered evidence: {value}")
    return value


def build_player_state(
    value: MaterializationInput, *, data_as_of: str
) -> dict[str, Any]:
    """Build one W3.1 player SSOT state without deriving identity or position from names.

    The function consumes already authorized DEC-030 identities and explicit registered
    evidence references. It deliberately supports mapping-free identities because
    DOC-015 v0.6 separates internal identity legitimacy from optional external mapping.
    Current club validity is evaluated at ``data_as_of`` so a historical assignment
    cannot accidentally satisfy the current-club control.
    """
    for field_name in ("player_id", "player_legitimation_ref"):
        field_value = getattr(value, field_name)
        if not isinstance(field_value, str) or not field_value:
            raise W31SSOTError(f"{field_name} must be non-empty")
    position_evidence_ref = _require_registered_evidence_ref(
        value.position_evidence_ref, "position_evidence_ref"
    )
    if value.season_position not in POSITION_CLASSES:
        raise W31SSOTError("season_position must be one of T/A/M/S")

    season_start = _iso_date(SEASON_START_2026_27, "season.valid_from")
    season_end = _iso_date(SEASON_END_2026_27, "season.valid_to")
    as_of = _iso_date(data_as_of, "data_as_of")
    assert season_start is not None and season_end is not None and as_of is not None
    if not season_start <= as_of <= season_end:
        raise W31SSOTError("data_as_of must lie within season 2026/27")

    club_start = _iso_date(value.club_valid_from, "club_valid_from", required=False)
    club_end = _iso_date(value.club_valid_to, "club_valid_to", required=False)
    if club_start and club_end and club_start > club_end:
        raise W31SSOTError("club assignment validity is inverted")

    club_evidence_ref: str | None = None
    if value.club_id or value.club_legitimation_ref or value.club_valid_from or value.club_valid_to:
        club_evidence_ref = _require_registered_evidence_ref(
            value.club_evidence_ref, "club_evidence_ref"
        )

    has_current_club = bool(
        value.club_id
        and value.club_legitimation_ref
        and club_evidence_ref
        and club_start
        and club_start <= as_of
        and (club_end is None or as_of <= club_end)
    )
    if value.current_bundesliga_assignment_required and not has_current_club:
        status = "SSOT_BLOCKED"
        open_cases = ["MISSING_CURRENT_BUNDESLIGA_CLUB_ASSIGNMENT"]
    else:
        status = "SSOT_PROCESSABLE"
        open_cases = []

    player_club_assignment = None
    if value.club_id and value.club_legitimation_ref and club_evidence_ref and club_start:
        assignment_id = _technical_id(
            "player-club-assignment", value.player_id, value.club_id, value.club_valid_from or ""
        )
        player_club_assignment = {
            "player_club_assignment_id": assignment_id,
            "player_id": value.player_id,
            "club_id": value.club_id,
            "valid_from": value.club_valid_from,
            "valid_to": value.club_valid_to,
            "verification_status": "CONFIRMED",
            "conflict_status": "CLEAR",
            "evidence_ref": club_evidence_ref,
        }

    position_assignment_id = _technical_id(
        "player-position-assignment", value.player_id, SEASON_ID_2026_27, value.season_position
    )
    state: dict[str, Any] = {
        "status": status,
        "open_critical_review_cases": open_cases,
        "external_deviation": None,
        "player": {
            "player_id": value.player_id,
            "identity_status": "IDENTITY_LEGITIMATED",
            "legitimation_ref": value.player_legitimation_ref,
        },
        "season": {
            "season_id": SEASON_ID_2026_27,
            "label": "2026/27",
            "valid_from": SEASON_START_2026_27,
            "valid_to": SEASON_END_2026_27,
        },
        "player_position_assignment": {
            "player_position_assignment_id": position_assignment_id,
            "player_id": value.player_id,
            "season_id": SEASON_ID_2026_27,
            "position": value.season_position,
            "valid_from": SEASON_START_2026_27,
            "valid_to": SEASON_END_2026_27,
            "verification_status": "CONFIRMED",
            "conflict_status": "CLEAR",
            "evidence_ref": position_evidence_ref,
        },
        "identity_mapping": {
            "mode": "MAPPING_FREE_ALLOWED",
            "mapping_record_id": None,
        },
    }
    if player_club_assignment is not None:
        state["club"] = {
            "club_id": value.club_id,
            "identity_status": "IDENTITY_LEGITIMATED",
            "legitimation_ref": value.club_legitimation_ref,
        }
        state["player_club_assignment"] = player_club_assignment
    return state
