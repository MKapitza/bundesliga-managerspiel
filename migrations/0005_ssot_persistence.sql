CREATE TABLE ssot_identity_legitimation (
    legitimation_ref TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    object_type TEXT NOT NULL CHECK (object_type IN ('PLAYER', 'CLUB')),
    decision_status TEXT NOT NULL CHECK (decision_status = 'IDENTITY_LEGITIMATED'),
    decided_at TEXT NOT NULL,
    authorized_by TEXT NOT NULL,
    evidence_refs_json TEXT NOT NULL CHECK (
        json_valid(evidence_refs_json)
        AND json_type(evidence_refs_json) = 'array'
        AND json_array_length(evidence_refs_json) > 0
    ),
    resulting_internal_object_id TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL
);

CREATE TABLE ssot_evidence_reference (
    evidence_ref TEXT PRIMARY KEY,
    evidence_id TEXT NOT NULL,
    artifact_path TEXT NOT NULL,
    manifest_sha256 TEXT NOT NULL CHECK (length(manifest_sha256) = 64),
    manifest_byte_length INTEGER NOT NULL CHECK (manifest_byte_length >= 0),
    media_type TEXT NOT NULL,
    source_reference TEXT NOT NULL,
    representation_type TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (evidence_id) REFERENCES evidence_artifact(evidence_id)
);

CREATE TABLE ssot_player (
    player_id TEXT PRIMARY KEY,
    display_name TEXT NOT NULL,
    given_name TEXT NULL,
    family_name TEXT NULL,
    identity_status TEXT NOT NULL CHECK (identity_status = 'IDENTITY_LEGITIMATED'),
    legitimation_ref TEXT NOT NULL UNIQUE,
    legitimized_at TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (legitimation_ref)
        REFERENCES ssot_identity_legitimation(legitimation_ref)
);

CREATE TABLE ssot_club (
    club_id TEXT PRIMARY KEY,
    club_name TEXT NOT NULL,
    short_name TEXT NULL,
    identity_status TEXT NOT NULL CHECK (identity_status = 'IDENTITY_LEGITIMATED'),
    legitimation_ref TEXT NOT NULL UNIQUE,
    legitimized_at TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (legitimation_ref)
        REFERENCES ssot_identity_legitimation(legitimation_ref)
);

CREATE TABLE ssot_legitimation_mapping (
    legitimation_ref TEXT PRIMARY KEY,
    mapping_record_id TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL,
    FOREIGN KEY (legitimation_ref)
        REFERENCES ssot_identity_legitimation(legitimation_ref),
    FOREIGN KEY (mapping_record_id) REFERENCES mapping_record(mapping_record_id)
);

CREATE TABLE ssot_version (
    ssot_version_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    data_as_of TEXT NOT NULL,
    released_at TEXT NULL,
    predecessor_ssot_version_id TEXT NULL,
    change_ref TEXT NOT NULL,
    release_evidence_ref TEXT NULL,
    state_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    CHECK (
        (released_at IS NULL AND release_evidence_ref IS NULL)
        OR
        (released_at IS NOT NULL AND release_evidence_ref IS NOT NULL)
    ),
    CHECK (
        predecessor_ssot_version_id IS NULL
        OR predecessor_ssot_version_id <> ssot_version_id
    ),
    FOREIGN KEY (predecessor_ssot_version_id)
        REFERENCES ssot_version(ssot_version_id)
);

CREATE INDEX idx_ssot_legitimation_internal_object
    ON ssot_identity_legitimation(resulting_internal_object_id);
CREATE INDEX idx_ssot_evidence_reference_evidence_id
    ON ssot_evidence_reference(evidence_id);
CREATE INDEX idx_ssot_version_predecessor
    ON ssot_version(predecessor_ssot_version_id);

CREATE TRIGGER ssot_player_legitimation_guard
BEFORE INSERT ON ssot_player
BEGIN
    SELECT CASE WHEN NOT EXISTS (
        SELECT 1 FROM ssot_identity_legitimation
        WHERE legitimation_ref = NEW.legitimation_ref
          AND object_type = 'PLAYER'
          AND decision_status = 'IDENTITY_LEGITIMATED'
          AND resulting_internal_object_id = NEW.player_id
          AND decided_at = NEW.legitimized_at
    ) THEN RAISE(ABORT, 'player identity requires matching positive legitimation') END;
END;

CREATE TRIGGER ssot_club_legitimation_guard
BEFORE INSERT ON ssot_club
BEGIN
    SELECT CASE WHEN NOT EXISTS (
        SELECT 1 FROM ssot_identity_legitimation
        WHERE legitimation_ref = NEW.legitimation_ref
          AND object_type = 'CLUB'
          AND decision_status = 'IDENTITY_LEGITIMATED'
          AND resulting_internal_object_id = NEW.club_id
          AND decided_at = NEW.legitimized_at
    ) THEN RAISE(ABORT, 'club identity requires matching positive legitimation') END;
END;

CREATE TRIGGER ssot_identity_legitimation_evidence_guard
BEFORE INSERT ON ssot_identity_legitimation
BEGIN
    SELECT CASE WHEN EXISTS (
        SELECT 1
        FROM json_each(NEW.evidence_refs_json) AS bundle
        WHERE bundle.type <> 'text'
           OR length(bundle.value) = 0
    ) THEN RAISE(ABORT, 'legitimation evidence bundle is invalid') END;
    SELECT CASE WHEN json_array_length(NEW.evidence_refs_json) <> (
        SELECT COUNT(DISTINCT bundle.value)
        FROM json_each(NEW.evidence_refs_json) AS bundle
    ) THEN RAISE(ABORT, 'legitimation evidence bundle contains duplicates') END;
    SELECT CASE WHEN EXISTS (
        SELECT 1
        FROM json_each(NEW.evidence_refs_json) AS bundle
        WHERE NOT EXISTS (
            SELECT 1 FROM evidence_artifact
            WHERE evidence_id = bundle.value
        )
          AND NOT EXISTS (
            SELECT 1 FROM ssot_evidence_reference
            WHERE evidence_ref = bundle.value
        )
    ) THEN RAISE(ABORT, 'legitimation evidence reference is unresolved') END;
END;

CREATE TRIGGER ssot_legitimation_mapping_guard
BEFORE INSERT ON ssot_legitimation_mapping
BEGIN
    SELECT CASE WHEN NOT EXISTS (
        SELECT 1
        FROM ssot_identity_legitimation AS legitimation
        JOIN mapping_record AS mapping
          ON mapping.mapping_record_id = NEW.mapping_record_id
        JOIN raw_observation AS raw
          ON raw.raw_record_id = mapping.raw_record_id
        WHERE legitimation.legitimation_ref = NEW.legitimation_ref
          AND mapping.mapping_status = 'CONFIRMED'
          AND mapping.conflict_status = 'CLEAR'
          AND mapping.object_type = legitimation.object_type
          AND mapping.internal_object_id = legitimation.resulting_internal_object_id
          AND EXISTS (
              SELECT 1
              FROM json_each(legitimation.evidence_refs_json) AS evidence
              WHERE evidence.value = mapping.confirmation_evidence_ref
          )
          AND (
              mapping.confirmation_evidence_ref = raw.raw_payload_ref
              OR EXISTS (
                  SELECT 1
                  FROM ssot_evidence_reference AS evidence_binding
                  WHERE evidence_binding.evidence_ref = mapping.confirmation_evidence_ref
                    AND evidence_binding.evidence_id = raw.raw_payload_ref
              )
          )
    ) THEN RAISE(ABORT, 'mapping does not match positive legitimation') END;
END;

CREATE TRIGGER ssot_evidence_reference_immutable_update
BEFORE UPDATE ON ssot_evidence_reference
BEGIN SELECT RAISE(ABORT, 'ssot_evidence_reference is immutable'); END;
CREATE TRIGGER ssot_evidence_reference_immutable_delete
BEFORE DELETE ON ssot_evidence_reference
BEGIN SELECT RAISE(ABORT, 'ssot_evidence_reference is immutable'); END;

CREATE TRIGGER ssot_evidence_reference_artifact_guard
BEFORE INSERT ON ssot_evidence_reference
BEGIN
    SELECT CASE WHEN NOT EXISTS (
        SELECT 1
        FROM evidence_artifact
        WHERE evidence_id = NEW.evidence_id
          AND content_sha256 = NEW.manifest_sha256
          AND byte_length = NEW.manifest_byte_length
          AND media_type = NEW.media_type
    ) THEN RAISE(ABORT, 'evidence binding does not match artifact metadata') END;
END;

CREATE TRIGGER ssot_identity_legitimation_immutable_update
BEFORE UPDATE ON ssot_identity_legitimation
BEGIN SELECT RAISE(ABORT, 'ssot_identity_legitimation is immutable'); END;
CREATE TRIGGER ssot_identity_legitimation_immutable_delete
BEFORE DELETE ON ssot_identity_legitimation
BEGIN SELECT RAISE(ABORT, 'ssot_identity_legitimation is immutable'); END;
CREATE TRIGGER ssot_player_immutable_update
BEFORE UPDATE ON ssot_player
BEGIN SELECT RAISE(ABORT, 'ssot_player is immutable'); END;
CREATE TRIGGER ssot_player_immutable_delete
BEFORE DELETE ON ssot_player
BEGIN SELECT RAISE(ABORT, 'ssot_player is immutable'); END;
CREATE TRIGGER ssot_club_immutable_update
BEFORE UPDATE ON ssot_club
BEGIN SELECT RAISE(ABORT, 'ssot_club is immutable'); END;
CREATE TRIGGER ssot_club_immutable_delete
BEFORE DELETE ON ssot_club
BEGIN SELECT RAISE(ABORT, 'ssot_club is immutable'); END;
CREATE TRIGGER ssot_legitimation_mapping_immutable_update
BEFORE UPDATE ON ssot_legitimation_mapping
BEGIN SELECT RAISE(ABORT, 'ssot_legitimation_mapping is immutable'); END;
CREATE TRIGGER ssot_legitimation_mapping_immutable_delete
BEFORE DELETE ON ssot_legitimation_mapping
BEGIN SELECT RAISE(ABORT, 'ssot_legitimation_mapping is immutable'); END;
CREATE TRIGGER ssot_version_immutable_update
BEFORE UPDATE ON ssot_version
BEGIN SELECT RAISE(ABORT, 'ssot_version is immutable'); END;
CREATE TRIGGER ssot_version_immutable_delete
BEFORE DELETE ON ssot_version
BEGIN SELECT RAISE(ABORT, 'ssot_version is immutable'); END;
