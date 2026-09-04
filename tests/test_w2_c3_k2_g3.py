from __future__ import annotations

import hashlib
import json
import sqlite3
import tempfile
import unittest
import uuid
from pathlib import Path

from bms.control_events import store_control_event
from bms.imports import import_fixture
from bms.mapping import store_mapping_record
from bms.persistence import apply_migrations, connect_database, schema_version
from bms.ssot import register_evidence_manifest, resolve_evidence_reference
from bms.storage import store_evidence, store_raw_observation
from bms.w2_c3 import (
    BASELINE_MIGRATION_HASHES,
    BASELINE_COMMIT,
    PLAYER_ID,
    WIKIDATA_EVIDENCE_REF,
    W2C3Error,
    _lineage_refs,
    build_positive_ssot_state,
    derive_g3,
    effective_k2_heads,
    k2_lineage_key,
    read_ssot_version_release,
    run_k2,
    run_w2_c3_smoke,
    store_g3_release,
    store_replay_safe_ssot_version,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
POSITIVE_FIXTURE = REPO_ROOT / "pilot_data/w2/fixtures/w2-c3-positive-01"


class W2C3K2G3Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.connection = connect_database(
            Path(self.temporary_directory.name) / "c3.sqlite3"
        )
        self.addCleanup(self.connection.close)
        apply_migrations(self.connection, REPO_ROOT / "migrations")
        self.run_id = "run-c3-2-test"
        self.specification_manifest_sha256 = hashlib.sha256(
            (REPO_ROOT / "spec/specification-manifest.json").read_bytes()
        ).hexdigest()
        self.lineage_evidence = store_evidence(
            self.connection,
            content=b'{"source":"test-lineage"}',
            run_id=self.run_id,
            media_type="application/json",
        )
        self.raw = store_raw_observation(
            self.connection,
            source_system="WIKIDATA",
            source_reference="fixture:test",
            retrieved_at="2026-09-02T15:57:44+02:00",
            observed_at="2026-09-02T15:57:44+02:00",
            raw_payload_ref=self.lineage_evidence.evidence_id,
            run_id=self.run_id,
        )
        self.mapping = store_mapping_record(
            self.connection,
            raw_record_id=self.raw.raw_record_id,
            run_id=self.run_id,
            source_system="WIKIDATA",
            external_id="Q96072055",
            object_type="PLAYER",
            mapping_status="CONFIRMED",
            conflict_status="CLEAR",
            criticality="CRITICAL",
            candidate_refs=(),
            internal_object_id=PLAYER_ID,
            confirmation_evidence_ref=self.lineage_evidence.evidence_id,
        )
        self.mapping_id = self.mapping.mapping_record_id

    def state(self) -> dict:
        return build_positive_ssot_state(self.mapping_id)

    def version(self, state: dict | None = None):
        return store_replay_safe_ssot_version(
            self.connection,
            run_id=self.run_id,
            data_as_of="2026-09-02T17:54:42Z",
            change_ref=f"test-change:{uuid.uuid4()}",
            state=self.state() if state is None else state,
        )

    def lineage_refs(self) -> list[str]:
        return _lineage_refs(
            run_id=self.run_id,
            raw_id=self.raw.raw_record_id,
            evidence_id=self.lineage_evidence.evidence_id,
            mapping_id=self.mapping_id,
            spec_hash=self.specification_manifest_sha256,
        )

    def g2(self) -> dict:
        return {
            "schema": "bms.w2-c2-g2-decision",
            "decision": "MAPPING_RELEASED",
            "mapping_record_ids": [self.mapping_id],
        }

    def execute_k2(self, version):
        return run_k2(
            self.connection,
            ssot_version_id=version.ssot_version_id,
            run_id=self.run_id,
            checked_at="2026-09-02T18:00:00Z",
            lineage_refs=self.lineage_refs(),
        )

    def derive(self, version):
        return derive_g3(
            self.connection,
            g2=self.g2(),
            ssot_version_id=version.ssot_version_id,
            specification_manifest_sha256=self.specification_manifest_sha256,
        )

    def store_manual_k2(
        self,
        version,
        *,
        control_id: str,
        status: str,
        predecessor: str | None = None,
        object_refs: tuple[str, ...] | None = None,
    ):
        evidence = store_evidence(
            self.connection,
            content=json.dumps({"control_id": control_id, "status": status}).encode(),
            run_id=self.run_id,
            media_type="application/json",
        )
        refs = object_refs or (
            f"ssot_version:{version.ssot_version_id}",
            f"stable_subject:player:{PLAYER_ID}",
            *self.lineage_refs(),
        )
        return store_control_event(
            self.connection,
            control_id=control_id,
            checked_at="2026-09-02T18:00:00Z",
            object_refs=refs,
            control_point="K2",
            severity="CRITICAL",
            check_status=status,
            observed_status="CONFIRMED",
            expected_status="CONFIRMED",
            description="C3.2 lineage regression",
            trace_refs=["DOC-015", "TC6-030", f"k2_evidence:{evidence.evidence_id}"],
            block_effect="NONE" if status == "CHECK_PASSED" else "RELEASE_BLOCK",
            blocked_process=None if status == "CHECK_PASSED" else "G3 SSOT-Version",
            owner_level="SSOT",
            resolution_status="RESOLVED" if status == "CHECK_PASSED" else "OPEN",
            evidence_ref=evidence.evidence_id,
            predecessor_event_ref=predecessor,
        )

    def test_t01_migration_0006_adds_only_immutable_release_relation(self) -> None:
        self.assertEqual(schema_version(self.connection), ("0006_ssot_version_release", 6))
        for name, digest in BASELINE_MIGRATION_HASHES.items():
            self.assertEqual(
                hashlib.sha256((REPO_ROOT / "migrations" / name).read_bytes()).hexdigest(),
                digest,
            )
        self.assertFalse(any((REPO_ROOT / "migrations").glob("0007_*.sql")))
        before = connect_database(Path(self.temporary_directory.name) / "before.sqlite3")
        self.addCleanup(before.close)
        apply_migrations(
            before, REPO_ROOT / "migrations", through="0005_ssot_persistence"
        )
        tables_before = {
            row["name"] for row in before.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        tables_after = {
            row["name"] for row in self.connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        self.assertEqual(tables_after - tables_before, {"ssot_version_release"})

    def test_t02_positive_k2_g3_release_and_replay_are_idempotent(self) -> None:
        version = self.version()
        events = self.execute_k2(version)
        self.assertEqual(
            [event.control_id for event in events],
            ["CTL-K2-002", "CTL-K2-003", "CTL-K2-004", "CTL-K2-005", "CTL-K2-006"],
        )
        self.assertTrue(all(event.check_status == "CHECK_PASSED" for event in events))
        g3 = self.derive(version)
        self.assertEqual(g3["decision"], "SSOT_RELEASED")
        release = store_g3_release(
            self.connection,
            run_id=self.run_id,
            g3=g3,
            released_at="2026-09-02T18:05:00Z",
        )
        self.assertEqual(release.ssot_version_id, version.ssot_version_id)
        self.assertEqual(read_ssot_version_release(self.connection, version.ssot_version_id), release)
        self.assertEqual(self.execute_k2(version), events)
        self.assertEqual(
            store_g3_release(
                self.connection,
                run_id=self.run_id,
                g3=g3,
                released_at="2026-09-02T18:05:00Z",
            ),
            release,
        )
        self.assertEqual(
            self.connection.execute("SELECT COUNT(*) FROM ssot_version_release").fetchone()[0], 1
        )
        with self.assertRaises(sqlite3.IntegrityError):
            self.connection.execute(
                "UPDATE ssot_version_release SET run_id='changed' WHERE release_id=?",
                (release.release_id,),
            )

    def test_t03_g3_blocks_ssot_blocked_independently_of_k2_006_consistency(self) -> None:
        state = self.state()
        state["status"] = "SSOT_BLOCKED"
        state["open_critical_review_cases"] = ["critical:test"]
        version = self.version(state)
        events = self.execute_k2(version)
        k2_006 = next(event for event in events if event.control_id == "CTL-K2-006")
        self.assertEqual(k2_006.check_status, "CHECK_PASSED")
        self.assertEqual(
            self.derive(version)["decision"],
            "BLOCKED",
        )

    def test_t04_missing_club_assignment_blocks(self) -> None:
        state = self.state()
        state["player_club_assignment"] = {}
        state["status"] = "SSOT_BLOCKED"
        version = self.version(state)
        events = self.execute_k2(version)
        self.assertEqual(
            next(event for event in events if event.control_id == "CTL-K2-003").check_status,
            "CHECK_FAILED",
        )
        self.assertEqual(self.derive(version)["decision"], "BLOCKED")

    def test_t05_missing_position_blocks(self) -> None:
        state = self.state()
        state["player_position_assignment"] = {}
        state["status"] = "SSOT_BLOCKED"
        version = self.version(state)
        events = self.execute_k2(version)
        self.assertEqual(next(event for event in events if event.control_id == "CTL-K2-004").check_status, "CHECK_FAILED")
        self.assertEqual(self.derive(version)["decision"], "BLOCKED")

    def test_t06_conflicting_assignment_blocks(self) -> None:
        state = self.state()
        state["player_club_assignment"]["conflict_status"] = "CONFLICTING"
        state["status"] = "SSOT_BLOCKED"
        version = self.version(state)
        events = self.execute_k2(version)
        self.assertEqual(next(event for event in events if event.control_id == "CTL-K2-003").check_status, "CHECK_FAILED")
        self.assertEqual(self.derive(version)["decision"], "BLOCKED")

    def test_t07_unplausible_time_blocks(self) -> None:
        state = self.state()
        state["player_position_assignment"]["valid_from"] = "2027-05-23"
        state["status"] = "SSOT_BLOCKED"
        version = self.version(state)
        events = self.execute_k2(version)
        self.assertEqual(next(event for event in events if event.control_id == "CTL-K2-005").check_status, "CHECK_FAILED")
        self.assertEqual(self.derive(version)["decision"], "BLOCKED")

    def test_t08_silent_ssot_overwrite_is_applicable_and_blocks(self) -> None:
        state = self.state()
        state["external_deviation"] = {"attempted_silent_overwrite": True}
        state["status"] = "SSOT_BLOCKED"
        version = self.version(state)
        events = self.execute_k2(version)
        self.assertEqual(events[0].control_id, "CTL-K2-001")
        self.assertEqual(events[0].check_status, "CHECK_FAILED")
        self.assertEqual(events[0].block_effect, "PROCESS_BLOCK")
        self.assertEqual(self.derive(version)["decision"], "BLOCKED")

    def test_t09_missing_required_head_blocks(self) -> None:
        version = self.version()
        g3 = self.derive(version)
        self.assertEqual(g3["decision"], "BLOCKED")
        self.assertFalse(g3["derivation"]["required_lineages_have_exactly_one_head"])

    def test_t10_multiple_effective_heads_block(self) -> None:
        version = self.version()
        events = self.execute_k2(version)
        original = events[0]
        self.store_manual_k2(
            version,
            control_id=original.control_id,
            status="CHECK_PASSED",
            object_refs=original.object_refs,
        )
        g3 = self.derive(version)
        self.assertEqual(g3["decision"], "BLOCKED")
        self.assertFalse(g3["derivation"]["required_lineages_have_exactly_one_head"])

    def test_t11_resolved_successor_replaces_historical_failed_head(self) -> None:
        version = self.version()
        failed = self.store_manual_k2(
            version, control_id="CTL-K2-002", status="CHECK_FAILED"
        )
        self.execute_k2(version)
        successor = self.store_manual_k2(
            version,
            control_id="CTL-K2-002",
            status="CHECK_PASSED",
            predecessor=failed.control_event_id,
            object_refs=failed.object_refs,
        )
        heads = effective_k2_heads(self.connection, version.ssot_version_id)
        self.assertEqual(heads[k2_lineage_key(failed)], [successor])
        self.assertEqual(
            self.derive(version)["decision"],
            "SSOT_RELEASED",
        )

    def test_t12_release_rejects_blocked_or_conflicting_replay(self) -> None:
        version = self.version()
        with self.assertRaisesRegex(sqlite3.IntegrityError, "G3 release evidence"):
            self.connection.execute(
                "INSERT INTO ssot_version_release VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    "release:invalid-evidence",
                    version.ssot_version_id,
                    self.run_id,
                    "SSOT_RELEASED",
                    self.lineage_evidence.evidence_id,
                    "2026-09-02T18:05:00Z",
                    "2026-09-02T18:05:00Z",
                ),
            )
        blocked = self.derive(version)
        with self.assertRaises(W2C3Error):
            store_g3_release(
                self.connection, run_id=self.run_id, g3=blocked,
                released_at="2026-09-02T18:05:00Z",
            )
        self.execute_k2(version)
        released = self.derive(version)
        release = store_g3_release(
            self.connection, run_id=self.run_id, g3=released,
            released_at="2026-09-02T18:05:00Z",
        )
        with self.assertRaisesRegex(W2C3Error, "conflicts with replay"):
            store_g3_release(
                self.connection, run_id="another-run", g3=released,
                released_at="2026-09-02T18:05:00Z",
            )
        self.assertEqual(release.ssot_version_id, version.ssot_version_id)

    def test_t13_c3_1_evidence_provenance_remains_resolvable(self) -> None:
        imported = import_fixture(
            self.connection, fixture_dir=POSITIVE_FIXTURE, run_id=self.run_id
        )
        bindings = register_evidence_manifest(
            self.connection,
            manifest_path=POSITIVE_FIXTURE / "seed-evidence-manifest.json",
            run_id=self.run_id,
        )
        self.assertEqual(len(bindings), 3)
        self.assertEqual(
            resolve_evidence_reference(self.connection, WIKIDATA_EVIDENCE_REF).evidence_id,
            imported.evidence.evidence_id,
        )

    def test_t14_integrated_smoke_executes_positive_replay_and_negative_short_circuit(self) -> None:
        output = Path(self.temporary_directory.name) / "evidence"
        smoke = run_w2_c3_smoke(output, repo_root=REPO_ROOT)
        self.assertEqual(smoke["status"], "PASS")
        positive = json.loads((output / "positive-run-a.json").read_text())
        self.assertEqual(positive["g1"]["decision"], "RELEASED_FOR_MAPPING")
        self.assertEqual(positive["mapping"]["mapping_status"], "CONFIRMED")
        self.assertEqual(positive["g2"]["decision"], "MAPPING_RELEASED")
        self.assertEqual(positive["ssot_status"], "SSOT_PROCESSABLE")
        self.assertEqual(positive["g3"]["decision"], "SSOT_RELEASED")
        self.assertEqual(len(positive["k2_controls"]), 5)
        self.assertEqual(positive["release"]["ssot_version_id"], positive["ssot_version_id"])
        negative = json.loads((output / "negative-short-circuit.json").read_text())
        self.assertEqual(negative["mapping"], "REVIEW_REQUIRED")
        self.assertEqual(negative["g2"], "BLOCKED")
        self.assertEqual(
            negative["counts"],
            {"ssot_versions": 0, "k2_events": 0, "g3_decisions": 0, "releases": 0},
        )
        self.assertTrue(negative["short_circuit"])
        self.assertEqual(json.loads((output / "replay-comparison.json").read_text())["status"], "PASS")
        self.assertEqual(json.loads((output / "scope-guard.json").read_text())["status"], "PASS")
        self.assertEqual(json.loads((output / "test-result.json").read_text())["status"], "PASS")
        self.assertEqual(json.loads((output / "run-manifest.json").read_text())["baseline_commit"], BASELINE_COMMIT)

    def test_t15_unresolved_raw_lineage_blocks_g3(self) -> None:
        version = self.version()
        original = self.execute_k2(version)[0]
        invalid_refs = tuple(
            "raw_record:unknown" if ref == f"raw_record:{self.raw.raw_record_id}" else ref
            for ref in original.object_refs
        )
        self.store_manual_k2(
            version,
            control_id=original.control_id,
            status="CHECK_PASSED",
            predecessor=original.control_event_id,
            object_refs=invalid_refs,
        )
        g3 = self.derive(version)
        self.assertEqual(g3["decision"], "BLOCKED")
        self.assertFalse(g3["derivation"]["head_contexts_valid"])

    def test_t16_wrong_well_formed_specification_hash_blocks_release(self) -> None:
        version = self.version()
        original = self.execute_k2(version)[0]
        wrong_hash = "f" * 64
        self.assertNotEqual(wrong_hash, self.specification_manifest_sha256)
        invalid_refs = tuple(
            f"specification_manifest_sha256:{wrong_hash}"
            if ref
            == f"specification_manifest_sha256:{self.specification_manifest_sha256}"
            else ref
            for ref in original.object_refs
        )
        successor = self.store_manual_k2(
            version,
            control_id=original.control_id,
            status="CHECK_PASSED",
            predecessor=original.control_event_id,
            object_refs=invalid_refs,
        )
        heads = effective_k2_heads(self.connection, version.ssot_version_id)
        self.assertEqual(heads[k2_lineage_key(original)], [successor])

        g3 = self.derive(version)
        self.assertEqual(g3["decision"], "BLOCKED")
        self.assertFalse(g3["derivation"]["head_contexts_valid"])
        with self.assertRaisesRegex(W2C3Error, "requires an SSOT_RELEASED decision"):
            store_g3_release(
                self.connection,
                run_id=self.run_id,
                g3=g3,
                released_at="2026-09-02T18:05:00Z",
            )
        self.assertEqual(
            self.connection.execute(
                "SELECT COUNT(*) FROM ssot_version_release"
            ).fetchone()[0],
            0,
        )


if __name__ == "__main__":
    unittest.main()
