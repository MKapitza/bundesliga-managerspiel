from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from bms.control_events import read_control_event, store_control_event
from bms.persistence import apply_migrations, connect_database, schema_version
from bms.storage import store_evidence

REPO_ROOT = Path(__file__).resolve().parents[1]
MIGRATION_PATH = REPO_ROOT / "migrations/0002_control_event.sql"
EXPECTED_COLUMNS = [
    "control_event_id",
    "control_id",
    "checked_at",
    "object_refs",
    "control_point",
    "severity",
    "check_status",
    "observed_status",
    "expected_status",
    "description",
    "trace_refs",
    "block_effect",
    "blocked_process",
    "owner_level",
    "resolution_status",
    "evidence_ref",
    "resolution_ref",
    "predecessor_event_ref",
    "created_at",
]
EXPECTED_C2_COLUMNS = {
    "evidence_artifact": [
        "evidence_id",
        "run_id",
        "content_blob",
        "content_sha256",
        "byte_length",
        "media_type",
        "created_at",
    ],
    "raw_observation": [
        "raw_record_id",
        "source_system",
        "source_reference",
        "retrieved_at",
        "observed_at",
        "raw_payload_ref",
        "run_id",
        "created_at",
        "predecessor_raw_record_id",
    ],
}
VALID_ENUMS = {
    "control_point": ("K0", "K1", "K2", "K3", "K4", "K5", "K6", "K7"),
    "severity": ("CRITICAL", "NONCRITICAL", "OPTIONAL"),
    "check_status": (
        "NOT_CHECKED",
        "CHECK_PENDING",
        "CHECK_PASSED",
        "CHECK_FAILED",
    ),
    "block_effect": (
        "NONE",
        "WARNING",
        "PARTIAL_BLOCK",
        "RELEASE_BLOCK",
        "PROCESS_BLOCK",
    ),
    "resolution_status": (
        "OPEN",
        "IN_REVIEW",
        "RESOLVED",
        "ACCEPTED_AS_WARNING",
    ),
}
FORBIDDEN_C3_PRODUCTION_NAMES = {
    "mapping",
    "ssot",
    "monitoring",
    "recommendation",
    "snapshot",
    "result",
    "evaluation",
    "import_batch",
    "gate_engine",
    "release_engine",
    "control_runner",
    "control_executor",
    "severity_calculator",
    "block_enforcer",
}


class ControlEventTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        database = Path(self.temporary_directory.name) / "control-events.sqlite3"
        self.connection = connect_database(database)
        self.addCleanup(self.connection.close)
        apply_migrations(
            self.connection,
            REPO_ROOT / "migrations",
            through="0004_mapping_review",
        )

    def event_values(self, **overrides):
        values = {
            "control_id": "CTL-K0-001",
            "checked_at": "2026-08-29T20:10:11.123456+02:00",
            "object_refs": ["raw:17", "evidence:42"],
            "control_point": "K0",
            "severity": "CRITICAL",
            "check_status": "CHECK_FAILED",
            "observed_status": "MISSING",
            "expected_status": "PRESENT",
            "description": "Required source reference is absent",
            "trace_refs": ["DEC-019", "REQ-NFR-007", "DOC-015"],
            "block_effect": "RELEASE_BLOCK",
            "blocked_process": "G1 raw data release",
            "owner_level": "raw-data",
            "resolution_status": "OPEN",
            "evidence_ref": "check:fixture:42",
            "resolution_ref": "correction:fixture:43",
        }
        values.update(overrides)
        return values

    def store_event(self, **overrides):
        return store_control_event(self.connection, **self.event_values(**overrides))

    def test_c3_t01_migration_order_version_checksum_and_c2_schema(self) -> None:
        self.assertEqual(schema_version(self.connection), ("0004_mapping_review", 4))
        history = self.connection.execute(
            "SELECT migration_id, checksum_sha256 FROM schema_migrations ORDER BY migration_id"
        ).fetchall()
        self.assertEqual(
            [row["migration_id"] for row in history],
            [
                "0001_raw_evidence",
                "0002_control_event",
                "0003_import_envelope",
                "0004_mapping_review",
            ],
        )
        self.assertEqual(
            history[1]["checksum_sha256"],
            hashlib.sha256(MIGRATION_PATH.read_bytes()).hexdigest(),
        )
        tables = {
            row["name"]
            for row in self.connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        self.assertTrue(
            {"evidence_artifact", "raw_observation", "control_event"}.issubset(tables)
        )
        for table, expected_columns in EXPECTED_C2_COLUMNS.items():
            actual_columns = [
                row["name"]
                for row in self.connection.execute(f"PRAGMA table_info({table})")
            ]
            self.assertEqual(actual_columns, expected_columns)

    def test_c3_t02_exact_control_event_schema(self) -> None:
        columns = [
            row["name"]
            for row in self.connection.execute("PRAGMA table_info(control_event)")
        ]
        self.assertEqual(columns, EXPECTED_COLUMNS)

    def test_c3_t03_control_event_ids_are_distinct_uuid4(self) -> None:
        first = self.store_event()
        second = self.store_event(control_id="CTL-K0-002")
        self.assertNotEqual(first.control_event_id, second.control_event_id)
        self.assertEqual(uuid.UUID(first.control_event_id).version, 4)
        self.assertEqual(uuid.UUID(second.control_event_id).version, 4)
        self.assertEqual(str(uuid.UUID(first.control_event_id)), first.control_event_id)

    def test_c3_t04_all_fields_roundtrip_exactly(self) -> None:
        stored = self.store_event()
        loaded = read_control_event(self.connection, stored.control_event_id)
        self.assertEqual(loaded, stored)
        self.assertRegex(
            loaded.created_at,
            re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$"),
        )

    def test_c3_t05_json_reference_order_and_validation(self) -> None:
        object_refs = ["raw:z", "raw:a", "Objekt ü"]
        trace_refs = ["DOC-015", "DEC-019", "CON-008"]
        event = self.store_event(object_refs=object_refs, trace_refs=trace_refs)
        loaded = read_control_event(self.connection, event.control_event_id)
        self.assertEqual(loaded.object_refs, tuple(object_refs))
        self.assertEqual(loaded.trace_refs, tuple(trace_refs))
        row = self.connection.execute(
            "SELECT object_refs, trace_refs FROM control_event WHERE control_event_id = ?",
            (event.control_event_id,),
        ).fetchone()
        self.assertEqual(row["object_refs"], '["raw:z","raw:a","Objekt ü"]')
        self.assertEqual(json.loads(row["object_refs"]), object_refs)
        self.assertEqual(json.loads(row["trace_refs"]), trace_refs)

        invalid_cases = (
            {"object_refs": []},
            {"trace_refs": []},
            {"object_refs": ["valid", 3]},
            {"trace_refs": [""]},
            {"object_refs": "not-an-array"},
        )
        for invalid in invalid_cases:
            with self.subTest(invalid=invalid):
                with self.assertRaises((TypeError, ValueError)):
                    self.store_event(**invalid)

    def test_c3_t06_checked_at_text_is_preserved_and_validated(self) -> None:
        timestamps = (
            "2026-08-29T20:10:11.123456+02:00",
            "2026-08-29T20:10:11.5-03:30",
            "2026-08-29T18:10:11Z",
        )
        for checked_at in timestamps:
            with self.subTest(checked_at=checked_at):
                event = self.store_event(checked_at=checked_at)
                self.assertEqual(
                    read_control_event(self.connection, event.control_event_id).checked_at,
                    checked_at,
                )
        for invalid in ("2026-08-29T20:10:11", "not-a-time"):
            with self.subTest(invalid=invalid):
                with self.assertRaises(ValueError):
                    self.store_event(checked_at=invalid)

    def test_c3_t07_all_enum_values_and_invalid_values(self) -> None:
        for field, valid_values in VALID_ENUMS.items():
            for value in valid_values:
                with self.subTest(field=field, value=value):
                    event = self.store_event(**{field: value})
                    self.assertEqual(getattr(event, field), value)
            with self.subTest(field=field, value="INVALID"):
                with self.assertRaises(sqlite3.IntegrityError):
                    self.store_event(**{field: "INVALID"})

    def test_c3_t08_evidence_reference_remains_opaque(self) -> None:
        evidence = store_evidence(
            self.connection,
            content=b"control-event evidence",
            run_id="run-c3-evidence",
        )
        c2_reference = self.store_event(evidence_ref=evidence.evidence_id)
        opaque_reference = self.store_event(evidence_ref="snapshot:synthetic-check:42")
        self.assertEqual(c2_reference.evidence_ref, evidence.evidence_id)
        self.assertEqual(opaque_reference.evidence_ref, "snapshot:synthetic-check:42")
        foreign_keys = self.connection.execute(
            "PRAGMA foreign_key_list(control_event)"
        ).fetchall()
        self.assertEqual(
            [(row["from"], row["table"]) for row in foreign_keys],
            [("predecessor_event_ref", "control_event")],
        )

    def test_c3_t09_control_event_is_database_immutable(self) -> None:
        event = self.store_event()
        with self.assertRaisesRegex(sqlite3.IntegrityError, "control_event is immutable"):
            self.connection.execute(
                "UPDATE control_event SET control_id = ? WHERE control_event_id = ?",
                ("changed", event.control_event_id),
            )
        with self.assertRaisesRegex(sqlite3.IntegrityError, "control_event is immutable"):
            self.connection.execute(
                "DELETE FROM control_event WHERE control_event_id = ?",
                (event.control_event_id,),
            )
        self.assertEqual(read_control_event(self.connection, event.control_event_id), event)

    def test_c3_t10_predecessor_chain_unknown_and_self_reference(self) -> None:
        first = self.store_event()
        second = self.store_event(
            control_id="CTL-K0-001-FOLLOW-UP",
            predecessor_event_ref=first.control_event_id,
        )
        self.assertEqual(
            read_control_event(
                self.connection, second.control_event_id
            ).predecessor_event_ref,
            first.control_event_id,
        )
        self.assertEqual(read_control_event(self.connection, first.control_event_id), first)

        with self.assertRaises(sqlite3.IntegrityError):
            self.store_event(predecessor_event_ref=str(uuid.uuid4()))

        self_reference = uuid.uuid4()
        with patch("bms.control_events.uuid.uuid4", return_value=self_reference):
            with self.assertRaises(sqlite3.IntegrityError):
                self.store_event(predecessor_event_ref=str(self_reference))

    def test_c3_t11_conditional_fields_remain_null_without_derivation(self) -> None:
        event = self.store_event(
            check_status="CHECK_PASSED",
            observed_status=None,
            expected_status=None,
            description=None,
            block_effect="NONE",
            blocked_process=None,
            resolution_ref=None,
        )
        loaded = read_control_event(self.connection, event.control_event_id)
        self.assertIsNone(loaded.observed_status)
        self.assertIsNone(loaded.expected_status)
        self.assertIsNone(loaded.description)
        self.assertIsNone(loaded.blocked_process)
        self.assertIsNone(loaded.resolution_ref)

    def test_c3_t12_no_gate_or_control_execution_components(self) -> None:
        tables = {
            row["name"]
            for row in self.connection.execute(
                """
                SELECT name FROM sqlite_master
                WHERE type = 'table' AND name NOT LIKE 'sqlite_%'
                """
            )
        }
        modules = {path.stem for path in (REPO_ROOT / "bms").glob("*.py")}
        self.assertEqual(
            tables,
            {
                "schema_migrations",
                "evidence_artifact",
                "raw_observation",
                "control_event",
                "import_envelope",
                "mapping_record",
            },
        )
        self.assertTrue(FORBIDDEN_C3_PRODUCTION_NAMES.isdisjoint(tables))
        self.assertTrue(
            (FORBIDDEN_C3_PRODUCTION_NAMES - {"mapping", "ssot"}).isdisjoint(modules)
        )
        self.assertTrue((REPO_ROOT / "migrations/0003_import_envelope.sql").is_file())
        self.assertTrue((REPO_ROOT / "migrations/0004_mapping_review.sql").is_file())


if __name__ == "__main__":
    unittest.main()
