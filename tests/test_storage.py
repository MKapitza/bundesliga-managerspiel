from __future__ import annotations

import hashlib
import re
import sqlite3
import tempfile
import unittest
import uuid
from pathlib import Path

from bms.persistence import apply_migrations, connect_database
from bms.storage import (
    read_evidence,
    read_raw_observation,
    store_evidence,
    store_raw_observation,
    verify_evidence,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
MIGRATION_PATH = REPO_ROOT / "migrations/0001_raw_evidence.sql"
EXPECTED_COLUMNS = {
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
FORBIDDEN_C2_SEMANTICS = {
    "mapping",
    "ssot",
    "monitoring",
    "recommendation",
    "snapshot",
    "result",
    "evaluation",
    "import_batch",
    "data_type",
    "raw_label",
    "raw_value",
    "normalized_value",
    "information_status",
    "mapping_status",
    "check_status",
    "conflict_status",
    "severity",
    "block_effect",
    "gate_status",
    "gate_engine",
    "release_engine",
    "control_runner",
    "control_executor",
    "severity_calculator",
    "block_enforcer",
}


class StorageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        database = Path(self.temporary_directory.name) / "storage.sqlite3"
        self.connection = connect_database(database)
        self.addCleanup(self.connection.close)
        apply_migrations(
            self.connection,
            REPO_ROOT / "migrations",
            through="0004_mapping_review",
        )

    def store_example_evidence(self, *, run_id: str = "run-c2-test"):
        return store_evidence(
            self.connection,
            content=b"\x00\xffraw\x80payload",
            run_id=run_id,
            media_type="application/octet-stream",
        )

    def store_example_raw(self, evidence_id: str, **overrides):
        values = {
            "source_system": "fixture-source",
            "source_reference": "fixture://observation/17",
            "retrieved_at": "2026-08-29T10:11:12.123456+02:00",
            "observed_at": "2026-08-29T08:10:00Z",
            "raw_payload_ref": evidence_id,
            "run_id": "run-c2-test",
        }
        values.update(overrides)
        return store_raw_observation(self.connection, **values)

    def test_c2_t01_fresh_migration_schema_and_checksum(self) -> None:
        tables = {
            row[0]
            for row in self.connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        self.assertTrue({"evidence_artifact", "raw_observation"}.issubset(tables))
        for table, expected in EXPECTED_COLUMNS.items():
            actual = [
                row["name"]
                for row in self.connection.execute(f"PRAGMA table_info({table})")
            ]
            self.assertEqual(actual, expected)
        expected_checksum = hashlib.sha256(MIGRATION_PATH.read_bytes()).hexdigest()
        recorded_checksum = self.connection.execute(
            "SELECT checksum_sha256 FROM schema_migrations WHERE migration_id = ?",
            ("0001_raw_evidence",),
        ).fetchone()[0]
        self.assertEqual(recorded_checksum, expected_checksum)

    def test_c2_t02_and_t03_evidence_binary_roundtrip_hash_and_length(self) -> None:
        content = bytes(range(256)) + b"\x00\xff\xfe"
        stored = store_evidence(
            self.connection,
            content=content,
            run_id="run-binary",
        )
        loaded = read_evidence(self.connection, stored.evidence_id)
        self.assertEqual(loaded.content_blob, content)
        self.assertEqual(loaded.content_sha256, hashlib.sha256(content).hexdigest())
        self.assertEqual(loaded.byte_length, len(content))
        self.assertTrue(verify_evidence(self.connection, stored.evidence_id))

    def test_database_rejects_inconsistent_evidence_length(self) -> None:
        with self.assertRaises(sqlite3.IntegrityError):
            self.connection.execute(
                """
                INSERT INTO evidence_artifact VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(uuid.uuid4()),
                    "run-invalid",
                    b"abc",
                    hashlib.sha256(b"abc").hexdigest(),
                    4,
                    None,
                    "2026-08-29T00:00:00Z",
                ),
            )

    def test_c2_t04_identical_content_is_not_deduplicated(self) -> None:
        first = store_evidence(self.connection, content=b"same", run_id="run-a")
        second = store_evidence(self.connection, content=b"same", run_id="run-b")
        self.assertNotEqual(first.evidence_id, second.evidence_id)
        self.assertEqual(first.content_sha256, second.content_sha256)
        self.assertEqual(
            self.connection.execute(
                "SELECT COUNT(*) FROM evidence_artifact WHERE content_sha256 = ?",
                (first.content_sha256,),
            ).fetchone()[0],
            2,
        )
        self.assertEqual(uuid.UUID(first.evidence_id).version, 4)
        self.assertEqual(uuid.UUID(second.evidence_id).version, 4)

    def test_c2_t05_and_t09_raw_roundtrip_and_run_traceability(self) -> None:
        evidence = self.store_example_evidence(run_id="run-trace-42")
        stored = self.store_example_raw(
            evidence.evidence_id,
            run_id="run-trace-42",
        )
        loaded = read_raw_observation(self.connection, stored.raw_record_id)
        self.assertEqual(loaded, stored)
        self.assertEqual(loaded.source_system, "fixture-source")
        self.assertEqual(loaded.source_reference, "fixture://observation/17")
        self.assertEqual(loaded.raw_payload_ref, evidence.evidence_id)
        self.assertEqual(loaded.run_id, "run-trace-42")
        self.assertEqual(read_evidence(self.connection, evidence.evidence_id).run_id, "run-trace-42")
        self.assertEqual(uuid.UUID(loaded.raw_record_id).version, 4)
        self.assertRegex(loaded.created_at, r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")

    def test_c2_t06_unknown_evidence_fails_without_partial_raw_row(self) -> None:
        with self.assertRaises(sqlite3.IntegrityError):
            self.store_example_raw(str(uuid.uuid4()))
        self.assertEqual(
            self.connection.execute("SELECT COUNT(*) FROM raw_observation").fetchone()[0],
            0,
        )

    def test_c2_t07_evidence_and_raw_are_database_immutable(self) -> None:
        evidence = self.store_example_evidence()
        raw = self.store_example_raw(evidence.evidence_id)
        attempts = [
            ("UPDATE evidence_artifact SET run_id = ? WHERE evidence_id = ?", ("changed", evidence.evidence_id), "evidence_artifact is immutable"),
            ("DELETE FROM evidence_artifact WHERE evidence_id = ?", (evidence.evidence_id,), "evidence_artifact is immutable"),
            ("UPDATE raw_observation SET run_id = ? WHERE raw_record_id = ?", ("changed", raw.raw_record_id), "raw_observation is immutable"),
            ("DELETE FROM raw_observation WHERE raw_record_id = ?", (raw.raw_record_id,), "raw_observation is immutable"),
        ]
        for sql, parameters, message in attempts:
            with self.subTest(sql=sql):
                with self.assertRaisesRegex(sqlite3.IntegrityError, message):
                    self.connection.execute(sql, parameters)
        self.assertEqual(read_evidence(self.connection, evidence.evidence_id), evidence)
        self.assertEqual(read_raw_observation(self.connection, raw.raw_record_id), raw)

    def test_c2_t08_predecessor_chain_and_self_reference(self) -> None:
        evidence = self.store_example_evidence()
        first = self.store_example_raw(evidence.evidence_id)
        second = self.store_example_raw(
            evidence.evidence_id,
            source_reference="fixture://observation/17/correction",
            predecessor_raw_record_id=first.raw_record_id,
        )
        self.assertEqual(
            read_raw_observation(self.connection, second.raw_record_id).predecessor_raw_record_id,
            first.raw_record_id,
        )
        self.assertEqual(read_raw_observation(self.connection, first.raw_record_id), first)
        self.assertEqual(
            self.connection.execute("SELECT COUNT(*) FROM raw_observation").fetchone()[0],
            2,
        )

        self_reference = str(uuid.uuid4())
        with self.assertRaises(sqlite3.IntegrityError):
            self.connection.execute(
                """
                INSERT INTO raw_observation VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    self_reference,
                    "fixture-source",
                    "fixture://self-reference",
                    "2026-08-29T10:00:00+02:00",
                    "2026-08-29T08:00:00Z",
                    evidence.evidence_id,
                    "run-self-reference",
                    "2026-08-29T08:00:01Z",
                    self_reference,
                ),
            )
        with self.assertRaises(sqlite3.IntegrityError):
            self.store_example_raw(
                evidence.evidence_id,
                predecessor_raw_record_id=str(uuid.uuid4()),
            )

    def test_c2_t10_timezone_aware_time_text_is_preserved_exactly(self) -> None:
        evidence = self.store_example_evidence()
        cases = [
            ("2026-08-29T10:11:12.123456+02:00", "2026-08-29T08:10:00Z"),
            ("2026-08-29T10:11:12.5-03:30", "2026-08-29T08:10:00.000001+00:00"),
        ]
        for retrieved_at, observed_at in cases:
            with self.subTest(retrieved_at=retrieved_at, observed_at=observed_at):
                raw = self.store_example_raw(
                    evidence.evidence_id,
                    retrieved_at=retrieved_at,
                    observed_at=observed_at,
                    source_reference=f"fixture://time/{retrieved_at}",
                )
                loaded = read_raw_observation(self.connection, raw.raw_record_id)
                self.assertEqual(loaded.retrieved_at, retrieved_at)
                self.assertEqual(loaded.observed_at, observed_at)

        for invalid in ("2026-08-29T10:11:12", "not-a-time"):
            with self.subTest(invalid=invalid):
                with self.assertRaises(ValueError):
                    self.store_example_raw(evidence.evidence_id, retrieved_at=invalid)
        self.assertRegex(
            read_evidence(self.connection, evidence.evidence_id).created_at,
            re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$"),
        )

    def test_c2_t11_schema_and_modules_have_no_w2_semantics(self) -> None:
        production_columns = {
            row["name"]
            for table in EXPECTED_COLUMNS
            for row in self.connection.execute(f"PRAGMA table_info({table})")
        }
        production_tables = {
            row["name"]
            for row in self.connection.execute(
                """
                SELECT name FROM sqlite_master
                WHERE type = 'table' AND name NOT LIKE 'sqlite_%'
                """
            )
        }
        module_names = {path.stem for path in (REPO_ROOT / "bms").glob("*.py")}
        self.assertTrue(FORBIDDEN_C2_SEMANTICS.isdisjoint(production_columns))
        self.assertTrue(FORBIDDEN_C2_SEMANTICS.isdisjoint(production_tables))
        self.assertTrue(
            (FORBIDDEN_C2_SEMANTICS - {"mapping", "ssot"}).isdisjoint(module_names)
        )


if __name__ == "__main__":
    unittest.main()
