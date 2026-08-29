CREATE TABLE control_event (
    control_event_id TEXT PRIMARY KEY,
    control_id TEXT NOT NULL,
    checked_at TEXT NOT NULL,
    object_refs TEXT NOT NULL,
    control_point TEXT NOT NULL CHECK (
        control_point IN ('K0', 'K1', 'K2', 'K3', 'K4', 'K5', 'K6', 'K7')
    ),
    severity TEXT NOT NULL CHECK (
        severity IN ('CRITICAL', 'NONCRITICAL', 'OPTIONAL')
    ),
    check_status TEXT NOT NULL CHECK (
        check_status IN (
            'NOT_CHECKED', 'CHECK_PENDING', 'CHECK_PASSED', 'CHECK_FAILED'
        )
    ),
    observed_status TEXT NULL,
    expected_status TEXT NULL,
    description TEXT NULL,
    trace_refs TEXT NOT NULL,
    block_effect TEXT NOT NULL CHECK (
        block_effect IN (
            'NONE', 'WARNING', 'PARTIAL_BLOCK', 'RELEASE_BLOCK', 'PROCESS_BLOCK'
        )
    ),
    blocked_process TEXT NULL,
    owner_level TEXT NOT NULL,
    resolution_status TEXT NOT NULL CHECK (
        resolution_status IN (
            'OPEN', 'IN_REVIEW', 'RESOLVED', 'ACCEPTED_AS_WARNING'
        )
    ),
    evidence_ref TEXT NOT NULL,
    resolution_ref TEXT NULL,
    predecessor_event_ref TEXT NULL,
    created_at TEXT NOT NULL,
    CHECK (
        predecessor_event_ref IS NULL
        OR predecessor_event_ref <> control_event_id
    ),
    FOREIGN KEY (predecessor_event_ref)
        REFERENCES control_event(control_event_id)
);

CREATE INDEX idx_control_event_control_id
    ON control_event(control_id);
CREATE INDEX idx_control_event_control_point
    ON control_event(control_point);
CREATE INDEX idx_control_event_check_status
    ON control_event(check_status);
CREATE INDEX idx_control_event_block_effect
    ON control_event(block_effect);
CREATE INDEX idx_control_event_resolution_status
    ON control_event(resolution_status);
CREATE INDEX idx_control_event_predecessor
    ON control_event(predecessor_event_ref);
CREATE INDEX idx_control_event_checked_at
    ON control_event(checked_at);

CREATE TRIGGER control_event_immutable_update
BEFORE UPDATE ON control_event
BEGIN
    SELECT RAISE(ABORT, 'control_event is immutable');
END;

CREATE TRIGGER control_event_immutable_delete
BEFORE DELETE ON control_event
BEGIN
    SELECT RAISE(ABORT, 'control_event is immutable');
END;
