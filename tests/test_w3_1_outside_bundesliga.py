import sqlite3
import unittest

from bms.w3_1_outside_bundesliga import (
    OUTSIDE_BUNDESLIGA,
    build_outside_bundesliga_state,
    store_outside_bundesliga_confirmation,
    validate_outside_bundesliga_state,
)


class W31OutsideBundesligaTests(unittest.TestCase):
    def _state(self):
        return build_outside_bundesliga_state(
            player_id="p1",
            player_legitimation_ref="l1",
            season_position="A",
            as_of="2026-09-05",
            evidence_ref="e1",
            source_reference="18 canonical Bundesliga rosters",
            observed_at="2026-09-06T01:00:00+02:00",
            ssot_version_id="v1",
        )

    def test_outside_state_has_no_fictional_club_or_interval(self) -> None:
        state = self._state()
        self.assertTrue(validate_outside_bundesliga_state(state, data_as_of="2026-09-05"))
        self.assertNotIn("club", state)
        self.assertNotIn("player_club_state_confirmation", state)
        confirmation = state["player_bundesliga_state_confirmation"]
        self.assertEqual(confirmation["membership_status"], OUTSIDE_BUNDESLIGA)
        self.assertNotIn("club_id", confirmation)
        self.assertNotIn("club_valid_from", confirmation)
        self.assertFalse(validate_outside_bundesliga_state(state, data_as_of="2026-09-06"))

    def test_persistence_is_point_in_time_and_club_free(self) -> None:
        connection = sqlite3.connect(":memory:")
        connection.executescript("""
        CREATE TABLE player_bundesliga_state_confirmation(
            player_bundesliga_state_confirmation_id TEXT PRIMARY KEY,
            player_id TEXT NOT NULL,
            as_of TEXT NOT NULL,
            membership_status TEXT NOT NULL,
            evidence_ref TEXT NOT NULL,
            source_reference TEXT NOT NULL,
            observed_at TEXT NOT NULL,
            verification_status TEXT NOT NULL,
            release_status TEXT NOT NULL,
            conflict_status TEXT NOT NULL,
            ssot_version_id TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        """)
        state = self._state()
        store_outside_bundesliga_confirmation(connection, player_state=state, created_at="2026-09-06T00:00:00Z")
        row = connection.execute("SELECT * FROM player_bundesliga_state_confirmation").fetchone()
        self.assertEqual(row[3], OUTSIDE_BUNDESLIGA)
        self.assertEqual(row[2], "2026-09-05")


if __name__ == "__main__":
    unittest.main()
