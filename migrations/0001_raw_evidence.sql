CREATE TABLE evidence_artifact (
    evidence_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    content_blob BLOB NOT NULL,
    content_sha256 TEXT NOT NULL,
    byte_length INTEGER NOT NULL CHECK (byte_length >= 0),
    media_type TEXT NULL,
    created_at TEXT NOT NULL,
    CHECK (typeof(content_blob) = 'blob'),
    CHECK (byte_length = length(content_blob))
);

CREATE TABLE raw_observation (
    raw_record_id TEXT PRIMARY KEY,
    source_system TEXT NOT NULL,
    source_reference TEXT NOT NULL,
    retrieved_at TEXT NOT NULL,
    observed_at TEXT NOT NULL,
    raw_payload_ref TEXT NOT NULL,
    run_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    predecessor_raw_record_id TEXT NULL,
    CHECK (
        predecessor_raw_record_id IS NULL
        OR predecessor_raw_record_id <> raw_record_id
    ),
    FOREIGN KEY (raw_payload_ref)
        REFERENCES evidence_artifact(evidence_id),
    FOREIGN KEY (predecessor_raw_record_id)
        REFERENCES raw_observation(raw_record_id)
);

CREATE INDEX idx_evidence_artifact_run_id
    ON evidence_artifact(run_id);
CREATE INDEX idx_raw_observation_run_id
    ON raw_observation(run_id);
CREATE INDEX idx_raw_observation_raw_payload_ref
    ON raw_observation(raw_payload_ref);
CREATE INDEX idx_raw_observation_predecessor
    ON raw_observation(predecessor_raw_record_id);
CREATE INDEX idx_raw_observation_source
    ON raw_observation(source_system, source_reference);

CREATE TRIGGER evidence_artifact_immutable_update
BEFORE UPDATE ON evidence_artifact
BEGIN
    SELECT RAISE(ABORT, 'evidence_artifact is immutable');
END;

CREATE TRIGGER evidence_artifact_immutable_delete
BEFORE DELETE ON evidence_artifact
BEGIN
    SELECT RAISE(ABORT, 'evidence_artifact is immutable');
END;

CREATE TRIGGER raw_observation_immutable_update
BEFORE UPDATE ON raw_observation
BEGIN
    SELECT RAISE(ABORT, 'raw_observation is immutable');
END;

CREATE TRIGGER raw_observation_immutable_delete
BEFORE DELETE ON raw_observation
BEGIN
    SELECT RAISE(ABORT, 'raw_observation is immutable');
END;
