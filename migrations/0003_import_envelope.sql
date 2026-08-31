CREATE TABLE import_envelope (
    raw_record_id TEXT PRIMARY KEY,
    import_batch_id TEXT NOT NULL,
    source_record_id TEXT NULL,
    published_at TEXT NULL,
    effective_from TEXT NULL,
    effective_to TEXT NULL,
    season_id_ref TEXT NULL,
    season_label_raw TEXT NULL,
    gameweek_raw TEXT NULL,
    match_ref_raw TEXT NULL,
    external_player_id TEXT NULL,
    external_club_id TEXT NULL,
    player_name_raw TEXT NULL,
    club_name_raw TEXT NULL,
    data_type TEXT NOT NULL,
    raw_label TEXT NOT NULL,
    raw_value TEXT NULL,
    mapping_status TEXT NOT NULL CHECK (
        mapping_status IN (
            'UNMAPPED', 'AUTO_MATCHED', 'REVIEW_REQUIRED', 'CONFIRMED', 'REJECTED'
        )
    ),
    check_status TEXT NOT NULL CHECK (
        check_status IN ('CHECK_PENDING', 'CHECK_PASSED', 'CHECK_FAILED')
    ),
    information_status TEXT NOT NULL CHECK (
        information_status IN (
            'PENDING', 'MISSING', 'ACTUAL_ZERO', 'NOT_APPLICABLE', 'CONFIRMED_VALUE'
        )
    ),
    conflict_status TEXT NOT NULL CHECK (
        conflict_status IN ('CLEAR', 'CONFLICTING', 'NOT_CHECKED')
    ),
    transformation_log_ref TEXT NULL,
    target_object_type TEXT NOT NULL,
    import_method TEXT NOT NULL CHECK (
        import_method IN (
            'DIRECT', 'SEMIAUTOMATIC', 'SAVED_SOURCE', 'STRUCTURED_FILE', 'MANUAL'
        )
    ),
    assertion_status TEXT NULL CHECK (
        assertion_status IS NULL OR assertion_status IN (
            'CONFIRMED', 'PROBABLE', 'UNCONFIRMED', 'OUTDATED'
        )
    ),
    created_at TEXT NOT NULL,
    FOREIGN KEY (raw_record_id) REFERENCES raw_observation(raw_record_id)
);

CREATE INDEX idx_import_envelope_batch
    ON import_envelope(import_batch_id);
CREATE INDEX idx_import_envelope_source_record
    ON import_envelope(source_record_id);

CREATE TRIGGER import_envelope_immutable_update
BEFORE UPDATE ON import_envelope
BEGIN
    SELECT RAISE(ABORT, 'import_envelope is immutable');
END;

CREATE TRIGGER import_envelope_immutable_delete
BEFORE DELETE ON import_envelope
BEGIN
    SELECT RAISE(ABORT, 'import_envelope is immutable');
END;
