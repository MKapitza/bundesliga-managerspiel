CREATE TABLE mapping_record (
    mapping_record_id TEXT PRIMARY KEY,
    raw_record_id TEXT NOT NULL,
    run_id TEXT NOT NULL,
    source_system TEXT NOT NULL,
    external_id TEXT NULL,
    object_type TEXT NOT NULL CHECK (object_type IN ('PLAYER', 'CLUB')),
    internal_object_id TEXT NULL,
    mapping_status TEXT NOT NULL CHECK (
        mapping_status IN (
            'UNMAPPED', 'AUTO_MATCHED', 'REVIEW_REQUIRED', 'CONFIRMED', 'REJECTED'
        )
    ),
    conflict_status TEXT NOT NULL CHECK (
        conflict_status IN ('CLEAR', 'CONFLICTING', 'NOT_CHECKED')
    ),
    criticality TEXT NOT NULL CHECK (
        criticality IN ('CRITICAL', 'NONCRITICAL')
    ),
    candidate_refs_json TEXT NOT NULL,
    review_reason TEXT NULL,
    confirmation_evidence_ref TEXT NULL,
    valid_from TEXT NULL,
    valid_to TEXT NULL,
    predecessor_mapping_record_id TEXT NULL,
    created_at TEXT NOT NULL,
    CHECK (
        mapping_status <> 'CONFIRMED'
        OR (
            internal_object_id IS NOT NULL
            AND confirmation_evidence_ref IS NOT NULL
        )
    ),
    CHECK (
        predecessor_mapping_record_id IS NULL
        OR predecessor_mapping_record_id <> mapping_record_id
    ),
    FOREIGN KEY (raw_record_id) REFERENCES raw_observation(raw_record_id),
    FOREIGN KEY (predecessor_mapping_record_id)
        REFERENCES mapping_record(mapping_record_id)
);

CREATE INDEX idx_mapping_record_raw
    ON mapping_record(raw_record_id);
CREATE INDEX idx_mapping_record_run
    ON mapping_record(run_id);
CREATE INDEX idx_mapping_record_source_external
    ON mapping_record(source_system, external_id);
CREATE INDEX idx_mapping_record_predecessor
    ON mapping_record(predecessor_mapping_record_id);

CREATE TRIGGER mapping_record_immutable_update
BEFORE UPDATE ON mapping_record
BEGIN
    SELECT RAISE(ABORT, 'mapping_record is immutable');
END;

CREATE TRIGGER mapping_record_immutable_delete
BEFORE DELETE ON mapping_record
BEGIN
    SELECT RAISE(ABORT, 'mapping_record is immutable');
END;
