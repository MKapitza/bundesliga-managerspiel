CREATE TABLE player_club_state_confirmation (
    player_club_state_confirmation_id TEXT PRIMARY KEY,
    player_id TEXT NOT NULL,
    club_id TEXT NOT NULL,
    as_of TEXT NOT NULL,
    evidence_ref TEXT NOT NULL,
    source_reference TEXT NOT NULL,
    observed_at TEXT NOT NULL,
    verification_status TEXT NOT NULL CHECK (verification_status = 'CONFIRMED'),
    release_status TEXT NOT NULL CHECK (release_status = 'RELEASED'),
    conflict_status TEXT NOT NULL CHECK (conflict_status = 'CLEAR'),
    ssot_version_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    CHECK (length(as_of) = 10),
    UNIQUE (player_id, club_id, as_of, evidence_ref, ssot_version_id),
    FOREIGN KEY (ssot_version_id) REFERENCES ssot_version(ssot_version_id)
);

CREATE INDEX idx_player_club_state_confirmation_player_as_of
    ON player_club_state_confirmation(player_id, as_of);
CREATE INDEX idx_player_club_state_confirmation_club_as_of
    ON player_club_state_confirmation(club_id, as_of);
CREATE INDEX idx_player_club_state_confirmation_version
    ON player_club_state_confirmation(ssot_version_id);

CREATE TRIGGER player_club_state_confirmation_no_interval_fields_insert
BEFORE INSERT ON player_club_state_confirmation
BEGIN
    SELECT CASE
        WHEN NEW.as_of IS NULL OR NEW.as_of = ''
        THEN RAISE(ABORT, 'current-state confirmation requires explicit as_of')
    END;
END;

CREATE TRIGGER player_club_state_confirmation_immutable_update
BEFORE UPDATE ON player_club_state_confirmation
BEGIN SELECT RAISE(ABORT, 'player_club_state_confirmation is immutable'); END;

CREATE TRIGGER player_club_state_confirmation_immutable_delete
BEFORE DELETE ON player_club_state_confirmation
BEGIN SELECT RAISE(ABORT, 'player_club_state_confirmation is immutable'); END;
