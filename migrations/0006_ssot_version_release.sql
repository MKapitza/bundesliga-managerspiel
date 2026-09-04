CREATE TABLE ssot_version_release (
    release_id TEXT PRIMARY KEY,
    ssot_version_id TEXT NOT NULL UNIQUE,
    run_id TEXT NOT NULL,
    g3_decision TEXT NOT NULL CHECK (g3_decision = 'SSOT_RELEASED'),
    g3_evidence_id TEXT NOT NULL UNIQUE,
    released_at TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (ssot_version_id) REFERENCES ssot_version(ssot_version_id),
    FOREIGN KEY (g3_evidence_id) REFERENCES evidence_artifact(evidence_id)
);

CREATE INDEX idx_ssot_version_release_run_id
    ON ssot_version_release(run_id);

CREATE TRIGGER ssot_version_release_evidence_guard
BEFORE INSERT ON ssot_version_release
BEGIN
    SELECT CASE WHEN NOT EXISTS (
        SELECT 1
        FROM evidence_artifact
        WHERE evidence_id = NEW.g3_evidence_id
          AND run_id = NEW.run_id
          AND media_type = 'application/json'
          AND json_valid(content_blob)
          AND json_extract(content_blob, '$.schema') = 'bms.w2-c3-g3-decision'
          AND json_extract(content_blob, '$.decision') = 'SSOT_RELEASED'
          AND json_extract(content_blob, '$.ssot_version_id') = NEW.ssot_version_id
    ) THEN RAISE(ABORT, 'G3 release evidence does not match run provenance') END;
END;

CREATE TRIGGER ssot_version_release_immutable_update
BEFORE UPDATE ON ssot_version_release
BEGIN SELECT RAISE(ABORT, 'ssot_version_release is immutable'); END;

CREATE TRIGGER ssot_version_release_immutable_delete
BEFORE DELETE ON ssot_version_release
BEGIN SELECT RAISE(ABORT, 'ssot_version_release is immutable'); END;
