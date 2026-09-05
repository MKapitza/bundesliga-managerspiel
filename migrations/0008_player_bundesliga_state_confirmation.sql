CREATE TABLE player_bundesliga_state_confirmation (
    player_bundesliga_state_confirmation_id TEXT PRIMARY KEY,
    player_id TEXT NOT NULL,
    as_of TEXT NOT NULL,
    membership_status TEXT NOT NULL CHECK (membership_status = 'OUTSIDE_BUNDESLIGA'),
    evidence_ref TEXT NOT NULL,
    source_reference TEXT NOT NULL,
    observed_at TEXT NOT NULL,
    verification_status TEXT NOT NULL CHECK (verification_status = 'CONFIRMED'),
    release_status TEXT NOT NULL CHECK (release_status = 'RELEASED'),
    conflict_status TEXT NOT NULL CHECK (conflict_status = 'CLEAR'),
    ssot_version_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    CHECK (length(as_of) = 10),
    UNIQUE (player_id, as_of, membership_status, evidence_ref, ssot_version_id),
    FOREIGN KEY (ssot_version_id) REFERENCES ssot_version(ssot_version_id)
);

CREATE INDEX idx_player_bundesliga_state_confirmation_player_as_of
    ON player_bundesliga_state_confirmation(player_id, as_of);
CREATE INDEX idx_player_bundesliga_state_confirmation_version
    ON player_bundesliga_state_confirmation(ssot_version_id);

CREATE TRIGGER player_bundesliga_state_confirmation_immutable_update
BEFORE UPDATE ON player_bundesliga_state_confirmation
BEGIN SELECT RAISE(ABORT, 'player_bundesliga_state_confirmation is immutable'); END;

CREATE TRIGGER player_bundesliga_state_confirmation_immutable_delete
BEFORE DELETE ON player_bundesliga_state_confirmation
BEGIN SELECT RAISE(ABORT, 'player_bundesliga_state_confirmation is immutable'); END;
