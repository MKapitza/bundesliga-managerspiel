import sqlite3
import unittest

from bms.w3_1_current_state import (
    build_current_state_player,
    materialize_current_state_release,
    validate_tc6_050,
)

BASE_SCHEMA = """
CREATE TABLE evidence_artifact(evidence_id TEXT PRIMARY KEY, run_id TEXT NOT NULL, content_blob BLOB NOT NULL, content_sha256 TEXT NOT NULL, byte_length INTEGER NOT NULL, media_type TEXT, created_at TEXT NOT NULL);
CREATE TABLE control_event(control_event_id TEXT PRIMARY KEY, control_id TEXT NOT NULL, checked_at TEXT NOT NULL, object_refs TEXT NOT NULL, control_point TEXT NOT NULL, severity TEXT NOT NULL, check_status TEXT NOT NULL, observed_status TEXT, expected_status TEXT, description TEXT, trace_refs TEXT NOT NULL, block_effect TEXT NOT NULL, blocked_process TEXT, owner_level TEXT NOT NULL, resolution_status TEXT NOT NULL, evidence_ref TEXT NOT NULL, resolution_ref TEXT, predecessor_event_ref TEXT, created_at TEXT NOT NULL);
CREATE TABLE ssot_version(ssot_version_id TEXT PRIMARY KEY, run_id TEXT NOT NULL, data_as_of TEXT NOT NULL, released_at TEXT, predecessor_ssot_version_id TEXT, change_ref TEXT NOT NULL, release_evidence_ref TEXT, state_json TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE ssot_version_release(release_id TEXT PRIMARY KEY, ssot_version_id TEXT NOT NULL UNIQUE, run_id TEXT NOT NULL, g3_decision TEXT NOT NULL, g3_evidence_id TEXT NOT NULL UNIQUE, released_at TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE player_club_state_confirmation(player_club_state_confirmation_id TEXT PRIMARY KEY, player_id TEXT NOT NULL, club_id TEXT NOT NULL, as_of TEXT NOT NULL, evidence_ref TEXT NOT NULL, source_reference TEXT NOT NULL, observed_at TEXT NOT NULL, verification_status TEXT NOT NULL, release_status TEXT NOT NULL, conflict_status TEXT NOT NULL, ssot_version_id TEXT NOT NULL, created_at TEXT NOT NULL);
"""

PLAYER = {
    "player_id": "p1",
    "player_legitimation_ref": "l1",
    "club_id": "c1",
    "club_legitimation_ref": "cl1",
    "season_position": "M",
    "club_name": "Club",
    "observed_at": "2026-09-05T01:00:00+02:00",
    "source_reference": "canonical/kicker-roster-club.json#blob:abc",
}


class W31CurrentStateTests(unittest.TestCase):
    def test_tc6_050_current_state_is_not_historical_interval(self) -> None:
        state = build_current_state_player(
            PLAYER,
            data_as_of="2026-09-05",
            ssot_version_id="v1",
            club_state_evidence_ref="eclub",
            position_evidence_ref="epos",
        )
        self.assertTrue(validate_tc6_050(state, data_as_of="2026-09-05"))
        self.assertNotIn("club_valid_from", state["player_club_state_confirmation"])
        self.assertFalse(validate_tc6_050(state, data_as_of="2026-09-06"))

    def test_materialization_executes_k2_008_and_g3(self) -> None:
        connection = sqlite3.connect(":memory:")
        connection.executescript(BASE_SCHEMA)
        result = materialize_current_state_release(
            connection,
            run_id="run-test",
            data_as_of="2026-09-05",
            players=[PLAYER],
            blocked_inputs=[],
            club_state_evidence_ref="eclub",
            position_evidence_ref="epos",
            specification_manifest_sha256="a" * 64,
            change_ref="test",
            checked_at="2026-09-05T23:20:00Z",
        )
        self.assertEqual(result["k2_result"], "PASS")
        self.assertEqual(result["g3_decision"], "SSOT_RELEASED")
        self.assertEqual(result["tc6_050"], "PASS")
        self.assertEqual(
            connection.execute(
                "SELECT COUNT(*) FROM control_event WHERE control_id='CTL-K2-008' AND check_status='CHECK_PASSED'"
            ).fetchone()[0],
            1,
        )
        self.assertEqual(connection.execute("SELECT COUNT(*) FROM ssot_version_release").fetchone()[0], 1)


if __name__ == "__main__":
    unittest.main()
