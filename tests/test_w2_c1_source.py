from __future__ import annotations

import copy
import hashlib
import json
import sqlite3
import subprocess
import sys
import tempfile
import unittest
import uuid
from pathlib import Path

from bms.control_events import read_control_event
from bms.imports import (
    import_fixture,
    read_import_envelope,
    store_import_envelope,
    validate_fixture,
)
from bms.persistence import apply_migrations, connect_database, schema_version
from bms.storage import (
    read_evidence,
    read_raw_observation,
    store_evidence,
    store_raw_observation,
)
from bms.w2_c1 import REQUIRED_K0_CONTROLS, derive_g1, run_k0, run_w2_c1_smoke

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_DIR = REPO_ROOT / "pilot_data/w2/fixtures/w2-pilot-01"
EXPECTED_COLUMNS = [
    "raw_record_id",
    "import_batch_id",
    "source_record_id",
    "published_at",
    "effective_from",
    "effective_to",
    "season_id_ref",
    "season_label_raw",
    "gameweek_raw",
    "match_ref_raw",
    "external_player_id",
    "external_club_id",
    "player_name_raw",
    "club_name_raw",
    "data_type",
    "raw_label",
    "raw_value",
    "mapping_status",
    "check_status",
    "information_status",
    "conflict_status",
    "transformation_log_ref",
    "target_object_type",
    "import_method",
    "assertion_status",
    "created_at",
]


class W2C1SourceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.connection = connect_database(
            Path(self.temporary_directory.name) / "w2-c1.sqlite3"
        )
        self.addCleanup(self.connection.close)
        apply_migrations(self.connection, REPO_ROOT / "migrations")
        self.run_id = f"run-test-{uuid.uuid4()}"
        self.imported = import_fixture(
            self.connection, fixture_dir=FIXTURE_DIR, run_id=self.run_id
        )

    def execute_k0(self, contract=None, imported=None):
        imported = imported or self.imported
        return run_k0(
            self.connection,
            contract=contract or imported.contract,
            run_id=self.run_id,
            import_batch_id=imported.envelope.import_batch_id,
            raw_record_id=imported.raw_observation.raw_record_id,
        )

    def make_import(
        self,
        content: bytes,
        *,
        contract=None,
        observed_at=None,
        import_batch_id=None,
    ):
        contract = copy.deepcopy(contract or self.imported.contract)
        evidence = store_evidence(
            self.connection,
            content=content,
            run_id=self.run_id,
            media_type=contract["media_type"],
        )
        raw = store_raw_observation(
            self.connection,
            source_system=contract["source_system"],
            source_reference=contract["source_reference"],
            retrieved_at=contract["retrieved_at"],
            observed_at=observed_at or contract["observed_at"],
            raw_payload_ref=evidence.evidence_id,
            run_id=self.run_id,
        )
        envelope = store_import_envelope(
            self.connection,
            raw_record_id=raw.raw_record_id,
            import_batch_id=import_batch_id or str(uuid.uuid4()),
            contract=contract,
        )
        return type(self.imported)(
            contract=contract,
            source_path=self.imported.source_path,
            source_bytes=content,
            parsed_source={},
            evidence=evidence,
            raw_observation=raw,
            envelope=envelope,
        )

    def decision(self, events, imported=None):
        imported = imported or self.imported
        return derive_g1(
            self.connection,
            run_id=self.run_id,
            import_batch_id=imported.envelope.import_batch_id,
            control_event_ids=[event.control_event_id for event in events],
            raw_record_ids=[imported.raw_observation.raw_record_id],
            evidence_ids=[imported.evidence.evidence_id],
        )

    def test_t01_fresh_database_migrates_0001_through_0003(self) -> None:
        self.assertEqual(schema_version(self.connection), ("0003_import_envelope", 3))
        columns = [
            row["name"]
            for row in self.connection.execute("PRAGMA table_info(import_envelope)")
        ]
        self.assertEqual(columns, EXPECTED_COLUMNS)

    def test_t02_existing_migrations_are_byte_unchanged(self) -> None:
        expected = {
            "0001_raw_evidence.sql": "678d5a3f2674d5abadb54de84fd17b60378eee16583153d8e35c5cba4f4a1354",
            "0002_control_event.sql": "360c498fb7dfdc3790e07dc4884f0950705841a7b6e54ae6aac8c8f8ef27be27",
        }
        for name, digest in expected.items():
            self.assertEqual(
                hashlib.sha256((REPO_ROOT / "migrations" / name).read_bytes()).hexdigest(),
                digest,
            )

    def test_t03_and_t04_original_evidence_bytes_hash_and_length(self) -> None:
        source = (FIXTURE_DIR / "source/wikidata_Q969725.json").read_bytes()
        evidence = read_evidence(self.connection, self.imported.evidence.evidence_id)
        self.assertEqual(evidence.content_blob, source)
        self.assertEqual(evidence.content_sha256, hashlib.sha256(source).hexdigest())
        self.assertEqual(evidence.byte_length, 119372)

    def test_t05_raw_observation_traces_evidence_and_run(self) -> None:
        raw = read_raw_observation(
            self.connection, self.imported.raw_observation.raw_record_id
        )
        self.assertEqual(raw.raw_payload_ref, self.imported.evidence.evidence_id)
        self.assertEqual(raw.run_id, self.run_id)
        self.assertEqual(read_evidence(self.connection, raw.raw_payload_ref).run_id, self.run_id)

    def test_t06_envelope_is_one_to_one_and_immutable(self) -> None:
        envelope = read_import_envelope(
            self.connection, self.imported.raw_observation.raw_record_id
        )
        self.assertEqual(envelope, self.imported.envelope)
        with self.assertRaises(sqlite3.IntegrityError):
            self.connection.execute(
                "UPDATE import_envelope SET raw_value='changed' WHERE raw_record_id=?",
                (envelope.raw_record_id,),
            )
        with self.assertRaises(sqlite3.IntegrityError):
            self.connection.execute(
                "DELETE FROM import_envelope WHERE raw_record_id=?",
                (envelope.raw_record_id,),
            )

    def test_t06a_source_record_id_is_nullable(self) -> None:
        contract = copy.deepcopy(self.imported.contract)
        contract.pop("source_record_id")
        imported = self.make_import(self.imported.source_bytes, contract=contract)
        loaded = read_import_envelope(
            self.connection, imported.raw_observation.raw_record_id
        )
        self.assertIsNone(loaded.source_record_id)

    def test_t07_import_batch_is_uuid4_and_not_run_id(self) -> None:
        self.assertEqual(uuid.UUID(self.imported.envelope.import_batch_id).version, 4)
        self.assertNotEqual(self.imported.envelope.import_batch_id, self.run_id)

    def test_t08_and_t09_status_dimensions_remain_separate(self) -> None:
        envelope = self.imported.envelope
        self.assertEqual(envelope.mapping_status, "UNMAPPED")
        self.assertEqual(envelope.check_status, "CHECK_PENDING")
        self.assertEqual(envelope.information_status, "CONFIRMED_VALUE")
        self.assertEqual(envelope.conflict_status, "NOT_CHECKED")
        self.assertIsNone(envelope.assertion_status)
        self.execute_k0()
        self.assertEqual(
            read_import_envelope(self.connection, envelope.raw_record_id), envelope
        )

    def test_t10_happy_path_executes_and_persists_real_k0_events(self) -> None:
        events = self.execute_k0()
        self.assertEqual([event.control_id for event in events], list(REQUIRED_K0_CONTROLS))
        self.assertTrue(all(event.check_status == "CHECK_PASSED" for event in events))
        self.assertTrue(all(event.block_effect == "NONE" for event in events))
        count = self.connection.execute("SELECT COUNT(*) FROM control_event").fetchone()[0]
        self.assertEqual(count, 6)

    def test_t11_manipulated_test_input_produces_k0_failure(self) -> None:
        altered = self.make_import(self.imported.source_bytes + b" ")
        events = self.execute_k0(imported=altered)
        statuses = {event.control_id: event.check_status for event in events}
        self.assertEqual(statuses["CTL-K0-003"], "CHECK_FAILED")
        self.assertEqual(statuses["CTL-K0-008"], "CHECK_PASSED")
        self.assertEqual(self.decision(events, altered)["decision"], "BLOCKED")

    def test_t12_invalid_technical_structure_blocks(self) -> None:
        invalid = self.make_import(b'{"entities":{"Q969725":{"id":"WRONG"}}}')
        events = self.execute_k0(imported=invalid)
        self.assertEqual(
            {event.control_id: event.check_status for event in events}["CTL-K0-004"],
            "CHECK_FAILED",
        )
        self.assertEqual(self.decision(events, invalid)["decision"], "BLOCKED")

    def test_t12a_k0_003_failure_blocks_the_concrete_raw_process(self) -> None:
        altered = self.make_import(self.imported.source_bytes + b" ")
        event = {
            item.control_id: item for item in self.execute_k0(imported=altered)
        }["CTL-K0-003"]
        self.assertEqual(event.check_status, "CHECK_FAILED")
        self.assertEqual(event.severity, "CRITICAL")
        self.assertEqual(event.block_effect, "PROCESS_BLOCK")
        self.assertIn(altered.raw_observation.raw_record_id, event.blocked_process)

    def test_t12b_k0_004_failure_blocks_the_concrete_import_batch(self) -> None:
        invalid = self.make_import(b'{"entities":{"Q969725":{"id":"WRONG"}}}')
        event = {
            item.control_id: item for item in self.execute_k0(imported=invalid)
        }["CTL-K0-004"]
        self.assertEqual(event.check_status, "CHECK_FAILED")
        self.assertEqual(event.severity, "CRITICAL")
        self.assertEqual(event.block_effect, "PROCESS_BLOCK")
        self.assertIn(invalid.envelope.import_batch_id, event.blocked_process)

    def test_t13_wrong_critical_expected_count_blocks(self) -> None:
        self.make_import(
            self.imported.source_bytes,
            import_batch_id=self.imported.envelope.import_batch_id,
        )
        events = self.execute_k0()
        self.assertEqual(
            {event.control_id: event.check_status for event in events}["CTL-K0-005"],
            "CHECK_FAILED",
        )
        self.assertEqual(self.decision(events)["decision"], "BLOCKED")

    def test_t14_inconsistent_time_and_evidence_each_block(self) -> None:
        future = self.make_import(
            self.imported.source_bytes,
            observed_at="2026-09-01T16:36:38+00:00",
        )
        events = self.execute_k0(imported=future)
        statuses = {event.control_id: event.check_status for event in events}
        self.assertEqual(statuses["CTL-K0-002"], "CHECK_FAILED")
        self.assertEqual(self.decision(events, future)["decision"], "BLOCKED")

    def test_t15_saved_source_fallback_evidence_is_actually_checked(self) -> None:
        events = self.execute_k0()
        fallback = {event.control_id: event for event in events}["CTL-K0-008"]
        self.assertEqual(fallback.check_status, "CHECK_PASSED")
        required = {"CTL-K0-001", "CTL-K0-002", "CTL-K0-003", "CTL-K0-004", "CTL-K0-005"}
        prerequisite_events = [event for event in events if event.control_id in required]
        self.assertEqual({event.control_id for event in prerequisite_events}, required)
        self.assertTrue(
            all(
                read_control_event(self.connection, event.control_event_id) == event
                for event in prerequisite_events
            )
        )
        self.assertTrue(
            all(event.evidence_ref == self.imported.evidence.evidence_id for event in prerequisite_events)
        )

    def test_t15a_saved_source_path_deviation_fails_k0_008_and_blocks_g1(self) -> None:
        contract = copy.deepcopy(self.imported.contract)
        contract["import_method"] = "MANUAL"
        imported = self.make_import(self.imported.source_bytes, contract=contract)
        events = self.execute_k0(imported=imported)
        statuses = {event.control_id: event.check_status for event in events}
        self.assertTrue(
            all(statuses[control_id] == "CHECK_PASSED" for control_id in REQUIRED_K0_CONTROLS[:-1])
        )
        self.assertEqual(statuses["CTL-K0-008"], "CHECK_FAILED")
        self.assertEqual(self.decision(events, imported)["decision"], "BLOCKED")

    def test_t16_and_t17_g1_uses_complete_persisted_k0_and_blocks_failures(self) -> None:
        passed = self.execute_k0()
        self.assertEqual(self.decision(passed)["decision"], "RELEASED_FOR_MAPPING")
        self.assertEqual(self.decision(passed[:-1])["decision"], "BLOCKED")
        bad_contract = copy.deepcopy(self.imported.contract)
        bad_contract["sha256"] = "0" * 64
        failed = self.execute_k0(contract=bad_contract)
        self.assertEqual(self.decision(failed)["decision"], "BLOCKED")

    def test_t18_control_traceability_reaches_raw_evidence_and_run(self) -> None:
        events = self.execute_k0()
        expected_refs = {
            f"run:{self.run_id}",
            f"import_batch:{self.imported.envelope.import_batch_id}",
            f"raw_record:{self.imported.raw_observation.raw_record_id}",
            f"evidence:{self.imported.evidence.evidence_id}",
        }
        for event in events:
            self.assertEqual(set(event.object_refs), expected_refs)
            self.assertEqual(event.evidence_ref, self.imported.evidence.evidence_id)

    def test_t19_no_mapping_or_ssot_production_objects_exist(self) -> None:
        names = {
            row["name"]
            for row in self.connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        self.assertFalse({"mapping", "ssot", "mapping_version", "ssot_version"} & names)
        self.assertFalse((REPO_ROOT / "bms/mapping.py").exists())
        self.assertFalse((REPO_ROOT / "bms/ssot.py").exists())

    def test_cli_smoke_generates_complete_execution_evidence(self) -> None:
        output = Path(self.temporary_directory.name) / "cli-evidence"
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "bms",
                "w2-c1-smoke",
                "--fixture-dir",
                str(FIXTURE_DIR),
                "--output-dir",
                str(output),
            ],
            cwd=REPO_ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        expected = {
            "fixture-validation.json",
            "import-report.json",
            "k0-control-report.json",
            "g1-decision.json",
            "run-manifest.json",
            "migration-report.json",
            "scope-guard.json",
            "smoke-report.json",
            "evidence-index.json",
        }
        self.assertTrue(expected.issubset({path.name for path in output.iterdir()}))
        self.assertEqual(
            json.loads((output / "g1-decision.json").read_text())["decision"],
            "RELEASED_FOR_MAPPING",
        )

    def test_fixture_contract_reproduces_expected_identity(self) -> None:
        validated = validate_fixture(FIXTURE_DIR)
        self.assertEqual(
            validated["parsed_source"]["entities"]["Q969725"]["id"], "Q969725"
        )


if __name__ == "__main__":
    unittest.main()
