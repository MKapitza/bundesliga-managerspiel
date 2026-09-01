from __future__ import annotations

import hashlib
import json
import sqlite3
import subprocess
import sys
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from bms.control_events import store_control_event
from bms.imports import import_fixture
from bms.mapping import (
    check_k1_001_external_id,
    check_k1_002_auto_matched,
    check_k1_003_duplicate_suspicion,
    check_k1_004_context_without_external_id,
    check_k1_005_changed_external_id,
    check_k1_006_conflicting_mapping,
    derive_g2,
    map_external_identity,
    read_mapping_record,
    run_applicable_k1,
    store_mapping_record,
)
from bms.persistence import apply_migrations, connect_database, schema_version
from bms.w2_c2 import W2C2Error, run_w2_c2_smoke

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_DIR = REPO_ROOT / "pilot_data/w2/fixtures/w2-pilot-01"
EXPECTED_COLUMNS = [
    "mapping_record_id",
    "raw_record_id",
    "run_id",
    "source_system",
    "external_id",
    "object_type",
    "internal_object_id",
    "mapping_status",
    "conflict_status",
    "criticality",
    "candidate_refs_json",
    "review_reason",
    "confirmation_evidence_ref",
    "valid_from",
    "valid_to",
    "predecessor_mapping_record_id",
    "created_at",
]


class W2C2MappingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.connection = connect_database(
            Path(self.temporary_directory.name) / "mapping.sqlite3"
        )
        self.addCleanup(self.connection.close)
        apply_migrations(self.connection, REPO_ROOT / "migrations")
        self.run_id = f"run-c2-test-{uuid.uuid4()}"
        self.imported = import_fixture(
            self.connection, fixture_dir=FIXTURE_DIR, run_id=self.run_id
        )

    def record(self, **overrides):
        values = {
            "raw_record_id": self.imported.raw_observation.raw_record_id,
            "run_id": self.run_id,
            "source_system": "WIKIDATA",
            "external_id": f"Q-{uuid.uuid4()}",
            "object_type": "PLAYER",
            "mapping_status": "REVIEW_REQUIRED",
            "conflict_status": "NOT_CHECKED",
            "criticality": "CRITICAL",
            "candidate_refs": [],
            "review_reason": "synthetic test review",
        }
        values.update(overrides)
        return store_mapping_record(self.connection, **values)

    def confirmed(self, **overrides):
        values = {
            "mapping_status": "CONFIRMED",
            "conflict_status": "CLEAR",
            "internal_object_id": f"internal-player-{uuid.uuid4()}",
            "confirmation_evidence_ref": self.imported.evidence.evidence_id,
            "review_reason": None,
        }
        values.update(overrides)
        return self.record(**values)

    def g2(self, record, event):
        return derive_g2(
            self.connection,
            mapping_record_ids=[record.mapping_record_id],
            control_event_ids=[event.control_event_id],
        )

    def test_t01_fresh_database_migrates_0001_through_0004(self) -> None:
        self.assertEqual(schema_version(self.connection), ("0004_mapping_review", 4))
        history = self.connection.execute(
            "SELECT migration_id FROM schema_migrations ORDER BY migration_id"
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

    def test_t02_c1_migrations_remain_byte_identical(self) -> None:
        expected = {
            "0001_raw_evidence.sql": "678d5a3f2674d5abadb54de84fd17b60378eee16583153d8e35c5cba4f4a1354",
            "0002_control_event.sql": "360c498fb7dfdc3790e07dc4884f0950705841a7b6e54ae6aac8c8f8ef27be27",
            "0003_import_envelope.sql": "43e356dbcc76b217c885d9f37702f244ff73781d09e47772e329a11afb253f1b",
        }
        for name, digest in expected.items():
            self.assertEqual(
                hashlib.sha256((REPO_ROOT / "migrations" / name).read_bytes()).hexdigest(),
                digest,
            )

    def test_t03_mapping_record_exact_schema_json_order_and_fk(self) -> None:
        columns = [
            row["name"]
            for row in self.connection.execute("PRAGMA table_info(mapping_record)")
        ]
        self.assertEqual(columns, EXPECTED_COLUMNS)
        stored = self.record(candidate_refs=["candidate:b", "candidate:a"])
        self.assertEqual(
            read_mapping_record(self.connection, stored.mapping_record_id).candidate_refs,
            ("candidate:b", "candidate:a"),
        )
        with self.assertRaises(sqlite3.IntegrityError):
            self.record(raw_record_id="unknown-raw")
        for overrides in (
            {"mapping_status": "MAPPED_SOMEHOW"},
            {"conflict_status": "MAYBE_CLEAR"},
            {"criticality": "VERY_CRITICAL"},
        ):
            with self.assertRaises(sqlite3.IntegrityError):
                self.record(**overrides)

    def test_t04_mapping_record_id_is_uuid4(self) -> None:
        self.assertEqual(uuid.UUID(self.record().mapping_record_id).version, 4)

    def test_t05_mapping_record_update_and_delete_are_blocked(self) -> None:
        record = self.record()
        with self.assertRaises(sqlite3.IntegrityError):
            self.connection.execute(
                "UPDATE mapping_record SET review_reason='changed' WHERE mapping_record_id=?",
                (record.mapping_record_id,),
            )
        with self.assertRaises(sqlite3.IntegrityError):
            self.connection.execute(
                "DELETE FROM mapping_record WHERE mapping_record_id=?",
                (record.mapping_record_id,),
            )

    def test_t06_external_id_is_nullable(self) -> None:
        record = self.record(external_id=None)
        self.assertIsNone(read_mapping_record(self.connection, record.mapping_record_id).external_id)

    def test_t07_object_type_accepts_player_club_and_rejects_other(self) -> None:
        self.record(object_type="PLAYER")
        self.record(object_type="CLUB")
        with self.assertRaises(sqlite3.IntegrityError):
            self.record(object_type="FANTASY_OBJECT")

    def test_t08_confirmed_requires_internal_object_id(self) -> None:
        with self.assertRaises(sqlite3.IntegrityError):
            self.record(
                mapping_status="CONFIRMED",
                conflict_status="CLEAR",
                confirmation_evidence_ref=self.imported.evidence.evidence_id,
            )

    def test_t09_confirmed_requires_confirmation_evidence(self) -> None:
        with self.assertRaises(sqlite3.IntegrityError):
            self.record(
                mapping_status="CONFIRMED",
                conflict_status="CLEAR",
                internal_object_id="internal-player-1",
            )

    def test_t10_review_required_allows_null_confirmation_evidence(self) -> None:
        record = self.record(confirmation_evidence_ref=None)
        self.assertEqual(record.mapping_status, "REVIEW_REQUIRED")
        self.assertIsNone(record.confirmation_evidence_ref)

    def test_t11_source_external_pair_is_not_unique(self) -> None:
        external_id = "Q-CONCURRENT"
        first = self.record(external_id=external_id)
        second = self.record(external_id=external_id)
        self.assertNotEqual(first.mapping_record_id, second.mapping_record_id)

    def test_t12_k1_001_unknown_external_id_requires_review_and_blocks_g2(self) -> None:
        record = map_external_identity(
            self.connection,
            raw_record_id=self.imported.raw_observation.raw_record_id,
            run_id=self.run_id,
            source_system="WIKIDATA",
            external_id="Q969725",
            object_type="PLAYER",
            criticality="CRITICAL",
        )
        event = check_k1_001_external_id(self.connection, record.mapping_record_id)
        self.assertEqual(record.mapping_status, "REVIEW_REQUIRED")
        self.assertIsNone(record.internal_object_id)
        self.assertEqual(event.check_status, "CHECK_PASSED")
        self.assertEqual(event.block_effect, "PARTIAL_BLOCK")
        self.assertEqual(self.g2(record, event)["decision"], "BLOCKED")

    def test_t12a_unique_confirmed_direct_mapping_is_reused_without_artificial_k1(self) -> None:
        confirmed = self.confirmed(external_id="Q-KNOWN")
        selected = map_external_identity(
            self.connection,
            raw_record_id=self.imported.raw_observation.raw_record_id,
            run_id=self.run_id,
            source_system="WIKIDATA",
            external_id="Q-KNOWN",
            object_type="PLAYER",
            criticality="CRITICAL",
        )
        self.assertEqual(selected.mapping_record_id, confirmed.mapping_record_id)
        self.assertEqual(
            derive_g2(
                self.connection,
                mapping_record_ids=[selected.mapping_record_id],
                control_event_ids=[],
            )["decision"],
            "MAPPING_RELEASED",
        )

    def test_t13_k1_002_auto_matched_is_not_confirmed_and_blocks_g2(self) -> None:
        record = self.record(
            mapping_status="AUTO_MATCHED",
            candidate_refs=["internal-player:candidate"],
        )
        event = check_k1_002_auto_matched(self.connection, record.mapping_record_id)
        self.assertEqual(event.check_status, "CHECK_PASSED")
        self.assertEqual(record.mapping_status, "AUTO_MATCHED")
        self.assertEqual(self.g2(record, event)["decision"], "BLOCKED")

    def test_t14_k1_003_duplicate_candidates_are_preserved_and_block_g2(self) -> None:
        record = self.record(candidate_refs=["candidate:1", "candidate:2"])
        event = check_k1_003_duplicate_suspicion(
            self.connection, record.mapping_record_id
        )
        self.assertEqual(event.check_status, "CHECK_PASSED")
        self.assertEqual(record.candidate_refs, ("candidate:1", "candidate:2"))
        self.assertIsNone(record.internal_object_id)
        self.assertEqual(self.g2(record, event)["decision"], "BLOCKED")

    def test_t15_k1_004_name_only_context_is_not_confirmed(self) -> None:
        record = self.record(external_id=None, review_reason="Name allein nicht ausreichend")
        event = check_k1_004_context_without_external_id(
            self.connection, record.mapping_record_id
        )
        self.assertEqual(event.check_status, "CHECK_PASSED")
        self.assertEqual(record.mapping_status, "REVIEW_REQUIRED")
        self.assertIsNone(record.internal_object_id)
        self.assertEqual(self.g2(record, event)["decision"], "BLOCKED")

    def test_t16_k1_005_external_id_change_creates_history_without_update(self) -> None:
        internal_id = "internal-player-stable"
        previous = self.confirmed(
            external_id="Q-OLD", internal_object_id=internal_id, valid_to="2026-08-31T00:00:00Z"
        )
        current = self.confirmed(
            external_id="Q-NEW",
            internal_object_id=internal_id,
            predecessor_mapping_record_id=previous.mapping_record_id,
        )
        event = check_k1_005_changed_external_id(
            self.connection, current.mapping_record_id
        )
        self.assertEqual(event.check_status, "CHECK_PASSED")
        self.assertEqual(event.block_effect, "NONE")
        self.assertEqual(current.predecessor_mapping_record_id, previous.mapping_record_id)
        self.assertEqual(
            read_mapping_record(self.connection, previous.mapping_record_id), previous
        )

    def test_t17_k1_006_competing_claims_stay_conflicting_and_block_g2(self) -> None:
        external_id = "Q-CONFLICT"
        first = self.confirmed(external_id=external_id, internal_object_id="internal:1")
        second = self.confirmed(external_id=external_id, internal_object_id="internal:2")
        conflict = map_external_identity(
            self.connection,
            raw_record_id=self.imported.raw_observation.raw_record_id,
            run_id=self.run_id,
            source_system="WIKIDATA",
            external_id=external_id,
            object_type="PLAYER",
            criticality="CRITICAL",
        )
        event = check_k1_006_conflicting_mapping(
            self.connection, conflict.mapping_record_id
        )
        self.assertEqual(conflict.conflict_status, "CONFLICTING")
        self.assertEqual(
            conflict.candidate_refs,
            tuple(sorted((first.mapping_record_id, second.mapping_record_id))),
        )
        self.assertIsNone(conflict.internal_object_id)
        self.assertEqual(event.check_status, "CHECK_PASSED")
        self.assertEqual(self.g2(conflict, event)["decision"], "BLOCKED")

    def test_t18_confirmed_conflict_free_mapping_releases_g2(self) -> None:
        previous = self.confirmed(
            external_id="Q-PREVIOUS",
            internal_object_id="internal:stable",
            valid_to="2026-08-31T00:00:00Z",
        )
        current = self.confirmed(
            external_id="Q-CURRENT",
            internal_object_id="internal:stable",
            predecessor_mapping_record_id=previous.mapping_record_id,
        )
        event = check_k1_005_changed_external_id(
            self.connection, current.mapping_record_id
        )
        self.assertEqual(self.g2(current, event)["decision"], "MAPPING_RELEASED")

    def test_t19_g2_reads_persisted_mapping_and_control_ids(self) -> None:
        previous = self.confirmed(
            external_id="Q-BEFORE",
            internal_object_id="internal:persisted",
            valid_to="2026-08-31T00:00:00Z",
        )
        record = self.confirmed(
            external_id="Q-AFTER",
            internal_object_id="internal:persisted",
            predecessor_mapping_record_id=previous.mapping_record_id,
        )
        missing_control = derive_g2(
            self.connection,
            mapping_record_ids=[record.mapping_record_id],
            control_event_ids=[],
        )
        self.assertEqual(missing_control["decision"], "BLOCKED")
        event = check_k1_005_changed_external_id(
            self.connection, record.mapping_record_id
        )
        decision = self.g2(record, event)
        self.assertEqual(decision["decision"], "MAPPING_RELEASED")
        self.assertEqual(decision["mapping_record_ids"], [record.mapping_record_id])
        self.assertEqual(
            decision["evaluated_control_event_ids"], [event.control_event_id]
        )
        with self.assertRaises(KeyError):
            derive_g2(
                self.connection,
                mapping_record_ids=["not-persisted"],
                control_event_ids=[event.control_event_id],
            )

    def test_t20_k1_traceability_reaches_mapping_raw_evidence_and_run(self) -> None:
        record = self.record()
        event = check_k1_001_external_id(self.connection, record.mapping_record_id)
        self.assertEqual(
            set(event.object_refs),
            {
                f"run:{self.run_id}",
                f"mapping_record:{record.mapping_record_id}",
                f"raw_record:{self.imported.raw_observation.raw_record_id}",
                f"evidence:{self.imported.evidence.evidence_id}",
            },
        )
        self.assertEqual(event.evidence_ref, self.imported.evidence.evidence_id)

    def test_t21_real_pilot_does_not_invent_internal_player_id(self) -> None:
        record = map_external_identity(
            self.connection,
            raw_record_id=self.imported.raw_observation.raw_record_id,
            run_id=self.run_id,
            source_system="WIKIDATA",
            external_id="Q969725",
            object_type="PLAYER",
            criticality="CRITICAL",
        )
        self.assertIsNone(record.internal_object_id)

    def test_t22_no_ssot_or_monitoring_production_objects_exist(self) -> None:
        tables = {
            row["name"]
            for row in self.connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        forbidden = {
            "ssot_player",
            "ssot_club",
            "ssot_version",
            "external_identity",
            "ssot_review_case",
            "monitoring",
        }
        self.assertTrue(forbidden.isdisjoint(tables))

    def test_t23_real_smoke_uses_only_applicable_k1_and_expected_block_is_pass(self) -> None:
        output = Path(self.temporary_directory.name) / "c2-smoke"
        result = run_w2_c2_smoke(FIXTURE_DIR, output, repo_root=REPO_ROOT)
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["g2_gate_result"], "BLOCKED")
        k1 = json.loads((output / "k1-control-report.json").read_text())
        self.assertEqual(
            [control["control_id"] for control in k1["controls"]], ["CTL-K1-001"]
        )
        mapping = json.loads((output / "mapping-review-report.json").read_text())
        self.assertEqual(mapping["mapping_status"], "REVIEW_REQUIRED")
        self.assertIsNone(mapping["internal_object_id"])
        smoke = json.loads((output / "smoke-report.json").read_text())
        self.assertTrue(smoke["checks"]["k1_report_pass"])
        self.assertTrue(smoke["checks"]["ssot_not_executed"])
        self.assertTrue(smoke["checks"]["k2_g3_not_executed"])
        database = sqlite3.connect(output / "w2-c2.sqlite3")
        self.addCleanup(database.close)
        self.assertEqual(
            database.execute(
                "SELECT COUNT(*) FROM control_event WHERE control_point = 'K2'"
            ).fetchone()[0],
            0,
        )
        self.assertFalse(any("g3" in path.name.lower() for path in output.iterdir()))

    def test_pilot_smoke_fails_for_persisted_traceable_failed_k1_001(self) -> None:
        output = Path(self.temporary_directory.name) / "failed-k1-c2-smoke"

        def persist_failed_k1(connection, mapping_record_id):
            mapping = read_mapping_record(connection, mapping_record_id)
            raw = connection.execute(
                "SELECT raw_payload_ref FROM raw_observation WHERE raw_record_id = ?",
                (mapping.raw_record_id,),
            ).fetchone()
            event = store_control_event(
                connection,
                control_id="CTL-K1-001",
                checked_at="2026-09-01T00:00:00+00:00",
                object_refs=[
                    f"run:{mapping.run_id}",
                    f"mapping_record:{mapping.mapping_record_id}",
                    f"raw_record:{mapping.raw_record_id}",
                    f"evidence:{raw['raw_payload_ref']}",
                ],
                control_point="K1",
                severity="CRITICAL",
                check_status="CHECK_FAILED",
                observed_status=mapping.mapping_status,
                expected_status="REVIEW_REQUIRED",
                description="Synthetische Pilotregression mit fehlgeschlagener K1-001.",
                trace_refs=["TC6-003", "DOC-015 v0.4"],
                block_effect="PARTIAL_BLOCK",
                blocked_process=f"Identität mapping_record_id={mapping.mapping_record_id}",
                owner_level="Mapping/SSOT",
                resolution_status="OPEN",
                evidence_ref=raw["raw_payload_ref"],
            )
            return [event]

        with patch("bms.w2_c2.run_applicable_k1", side_effect=persist_failed_k1):
            with self.assertRaises(W2C2Error):
                run_w2_c2_smoke(FIXTURE_DIR, output, repo_root=REPO_ROOT)

        k1 = json.loads((output / "k1-control-report.json").read_text())
        smoke = json.loads((output / "smoke-report.json").read_text())
        self.assertEqual(k1["status"], "FAIL")
        self.assertTrue(k1["traceability_pass"])
        self.assertEqual(k1["controls"][0]["check_status"], "CHECK_FAILED")
        self.assertFalse(smoke["checks"]["k1_report_pass"])
        self.assertEqual(smoke["status"], "FAIL")

    def test_review_successor_is_the_immutable_head_and_can_release_g2(self) -> None:
        review = self.record(external_id="Q-REVIEW-THEN-CONFIRMED")
        confirmed = self.confirmed(
            external_id=review.external_id,
            predecessor_mapping_record_id=review.mapping_record_id,
        )

        selected = map_external_identity(
            self.connection,
            raw_record_id=self.imported.raw_observation.raw_record_id,
            run_id=self.run_id,
            source_system="WIKIDATA",
            external_id=review.external_id,
            object_type="PLAYER",
            criticality="CRITICAL",
        )

        self.assertEqual(selected.mapping_record_id, confirmed.mapping_record_id)
        self.assertEqual(read_mapping_record(self.connection, review.mapping_record_id), review)
        self.assertIsNone(review.valid_to)
        decision = derive_g2(
            self.connection,
            mapping_record_ids=[confirmed.mapping_record_id],
            control_event_ids=[],
        )
        self.assertTrue(decision["derivation"]["no_active_competing_claims"])
        self.assertEqual(decision["decision"], "MAPPING_RELEASED")

    def test_k1_coverage_is_required_for_each_mapping_record(self) -> None:
        first_previous = self.confirmed(
            external_id="Q-FIRST-OLD", internal_object_id="internal:first"
        )
        first = self.confirmed(
            external_id="Q-FIRST-NEW",
            internal_object_id="internal:first",
            predecessor_mapping_record_id=first_previous.mapping_record_id,
        )
        second_previous = self.confirmed(
            external_id="Q-SECOND-OLD", internal_object_id="internal:second"
        )
        second = self.confirmed(
            external_id="Q-SECOND-NEW",
            internal_object_id="internal:second",
            predecessor_mapping_record_id=second_previous.mapping_record_id,
        )
        first_event = check_k1_005_changed_external_id(
            self.connection, first.mapping_record_id
        )
        missing = derive_g2(
            self.connection,
            mapping_record_ids=[first.mapping_record_id, second.mapping_record_id],
            control_event_ids=[first_event.control_event_id],
        )
        self.assertFalse(missing["derivation"]["persisted_k1_context_valid"])
        self.assertEqual(missing["decision"], "BLOCKED")

        second_event = check_k1_005_changed_external_id(
            self.connection, second.mapping_record_id
        )
        complete = derive_g2(
            self.connection,
            mapping_record_ids=[first.mapping_record_id, second.mapping_record_id],
            control_event_ids=[first_event.control_event_id, second_event.control_event_id],
        )
        self.assertTrue(complete["derivation"]["persisted_k1_context_valid"])
        self.assertEqual(complete["decision"], "MAPPING_RELEASED")

    def test_k1_005_auto_matched_successor_is_not_a_successful_none_case(self) -> None:
        previous = self.confirmed(
            external_id="Q-AUTO-OLD", internal_object_id="internal:auto"
        )
        current = self.record(
            external_id="Q-AUTO-NEW",
            internal_object_id="internal:auto",
            mapping_status="AUTO_MATCHED",
            predecessor_mapping_record_id=previous.mapping_record_id,
        )
        event = check_k1_005_changed_external_id(
            self.connection, current.mapping_record_id
        )
        self.assertEqual(event.check_status, "CHECK_FAILED")
        self.assertEqual(event.block_effect, "RELEASE_BLOCK")
        self.assertEqual(event.blocked_process, "G3 SSOT-Version")

    def test_k1_005_internal_id_change_blocks_only_g3_release(self) -> None:
        previous = self.confirmed(
            external_id="Q-ID-OLD", internal_object_id="internal:old"
        )
        current = self.confirmed(
            external_id="Q-ID-NEW",
            internal_object_id="internal:new",
            predecessor_mapping_record_id=previous.mapping_record_id,
        )
        event = check_k1_005_changed_external_id(
            self.connection, current.mapping_record_id
        )
        self.assertEqual(event.check_status, "CHECK_FAILED")
        self.assertEqual(event.block_effect, "RELEASE_BLOCK")
        self.assertEqual(event.blocked_process, "G3 SSOT-Version")
        self.assertEqual(self.g2(current, event)["decision"], "MAPPING_RELEASED")

    def test_k1_005_missing_predecessor_is_process_blocking_history_loss(self) -> None:
        self.confirmed(
            external_id="Q-HISTORY-OLD", internal_object_id="internal:history"
        )
        current = self.confirmed(
            external_id="Q-HISTORY-NEW", internal_object_id="internal:history"
        )
        event = check_k1_005_changed_external_id(
            self.connection, current.mapping_record_id
        )
        self.assertEqual(event.check_status, "CHECK_FAILED")
        self.assertEqual(event.block_effect, "PROCESS_BLOCK")
        self.assertEqual(event.blocked_process, "Mapping/SSOT-Verarbeitung")
        self.assertEqual(self.g2(current, event)["decision"], "BLOCKED")

    def test_k1_005_rejects_predecessor_from_another_identity_context(self) -> None:
        predecessor = self.confirmed(
            source_system="OTHER",
            external_id="Q-CONTEXT-OLD",
            internal_object_id="internal:context",
        )
        current = self.confirmed(
            external_id="Q-CONTEXT-NEW",
            internal_object_id="internal:context",
            predecessor_mapping_record_id=predecessor.mapping_record_id,
        )
        event = check_k1_005_changed_external_id(
            self.connection, current.mapping_record_id
        )
        self.assertEqual(event.check_status, "CHECK_FAILED")
        self.assertEqual(event.block_effect, "RELEASE_BLOCK")
        self.assertEqual(event.blocked_process, "G3 SSOT-Version")

    def test_k1_005_uses_only_direct_predecessor_in_linear_history(self) -> None:
        first = self.confirmed(
            external_id="Q-LINEAR-OLD", internal_object_id="internal:linear"
        )
        second = self.confirmed(
            external_id="Q-LINEAR-NEW",
            internal_object_id="internal:linear",
            predecessor_mapping_record_id=first.mapping_record_id,
        )
        third = self.confirmed(
            external_id="Q-LINEAR-NEW",
            internal_object_id="internal:linear",
            predecessor_mapping_record_id=second.mapping_record_id,
        )

        second_events = run_applicable_k1(self.connection, second.mapping_record_id)
        third_events = run_applicable_k1(self.connection, third.mapping_record_id)

        self.assertEqual(len(second_events), 1)
        self.assertEqual(second_events[0].control_id, "CTL-K1-005")
        self.assertEqual(second_events[0].check_status, "CHECK_PASSED")
        self.assertEqual(second_events[0].block_effect, "NONE")
        self.assertEqual(third_events, [])
        decision = derive_g2(
            self.connection,
            mapping_record_ids=[third.mapping_record_id],
            control_event_ids=[],
        )
        self.assertTrue(decision["derivation"]["no_unresolved_history_branch"])
        self.assertEqual(decision["decision"], "MAPPING_RELEASED")

    def test_g2_blocks_each_confirmed_head_of_a_branched_history(self) -> None:
        predecessor = self.confirmed(
            external_id="Q-BRANCH-OLD", internal_object_id="internal:branch"
        )
        first_head = self.confirmed(
            external_id="Q-BRANCH-FIRST",
            internal_object_id="internal:branch",
            predecessor_mapping_record_id=predecessor.mapping_record_id,
        )
        second_head = self.confirmed(
            external_id="Q-BRANCH-SECOND",
            internal_object_id="internal:branch",
            predecessor_mapping_record_id=predecessor.mapping_record_id,
        )
        first_event = check_k1_005_changed_external_id(
            self.connection, first_head.mapping_record_id
        )
        second_event = check_k1_005_changed_external_id(
            self.connection, second_head.mapping_record_id
        )

        for record, event in (
            (first_head, first_event),
            (second_head, second_event),
        ):
            decision = self.g2(record, event)
            self.assertEqual(event.check_status, "CHECK_PASSED")
            self.assertFalse(
                decision["derivation"]["no_unresolved_history_branch"]
            )
            self.assertEqual(decision["decision"], "BLOCKED")

    def test_g2_detects_deep_history_branch_between_current_heads(self) -> None:
        root = self.confirmed(
            external_id="Q-DEEP-ROOT", internal_object_id="internal:deep-branch"
        )
        first_head = self.confirmed(
            external_id="Q-DEEP-FIRST-HEAD",
            internal_object_id="internal:deep-branch",
            predecessor_mapping_record_id=root.mapping_record_id,
        )
        intermediate = self.confirmed(
            external_id="Q-DEEP-INTERMEDIATE",
            internal_object_id="internal:deep-branch",
            predecessor_mapping_record_id=root.mapping_record_id,
        )
        second_head = self.confirmed(
            external_id="Q-DEEP-SECOND-HEAD",
            internal_object_id="internal:deep-branch",
            predecessor_mapping_record_id=intermediate.mapping_record_id,
        )
        event = check_k1_005_changed_external_id(
            self.connection, second_head.mapping_record_id
        )

        decision = self.g2(second_head, event)

        self.assertEqual(event.check_status, "CHECK_PASSED")
        self.assertFalse(decision["derivation"]["no_unresolved_history_branch"])
        self.assertEqual(decision["decision"], "BLOCKED")
        heads = self.connection.execute(
            """
            SELECT mapping_record_id
            FROM mapping_record AS candidate
            WHERE candidate.internal_object_id = ?
              AND NOT EXISTS (
                  SELECT 1 FROM mapping_record AS successor
                  WHERE successor.predecessor_mapping_record_id = candidate.mapping_record_id
              )
            ORDER BY mapping_record_id
            """,
            ("internal:deep-branch",),
        ).fetchall()
        self.assertEqual(
            {row["mapping_record_id"] for row in heads},
            {first_head.mapping_record_id, second_head.mapping_record_id},
        )

    def test_g2_releases_only_head_of_four_record_linear_history(self) -> None:
        root = self.confirmed(
            external_id="Q-FOUR-A", internal_object_id="internal:four-linear"
        )
        second = self.confirmed(
            external_id="Q-FOUR-B",
            internal_object_id="internal:four-linear",
            predecessor_mapping_record_id=root.mapping_record_id,
        )
        third = self.confirmed(
            external_id="Q-FOUR-C",
            internal_object_id="internal:four-linear",
            predecessor_mapping_record_id=second.mapping_record_id,
        )
        head = self.confirmed(
            external_id="Q-FOUR-D",
            internal_object_id="internal:four-linear",
            predecessor_mapping_record_id=third.mapping_record_id,
        )
        event = check_k1_005_changed_external_id(
            self.connection, head.mapping_record_id
        )

        decision = self.g2(head, event)

        self.assertEqual(event.check_status, "CHECK_PASSED")
        self.assertTrue(decision["derivation"]["no_unresolved_history_branch"])
        self.assertEqual(decision["decision"], "MAPPING_RELEASED")

    def test_cli_w2_c2_smoke_generates_required_evidence(self) -> None:
        output = Path(self.temporary_directory.name) / "cli-c2-smoke"
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "bms",
                "w2-c2-smoke",
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
        required = {
            "run-manifest.json",
            "migration-report.json",
            "mapping-review-report.json",
            "k1-control-report.json",
            "g2-decision.json",
            "scope-guard.json",
            "smoke-report.json",
            "evidence-index.json",
        }
        self.assertTrue(required.issubset({path.name for path in output.iterdir()}))


if __name__ == "__main__":
    unittest.main()
