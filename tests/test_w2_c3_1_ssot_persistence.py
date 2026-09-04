from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from bms.imports import import_fixture
from bms.persistence import apply_migrations, connect_database, schema_version
from bms.ssot import (
    EvidenceManifestError,
    IdentityLegitimationConflictError,
    read_evidence_reference,
    read_identity_legitimation,
    read_ssot_club,
    read_ssot_player,
    read_ssot_version,
    register_evidence_manifest,
    resolve_evidence_reference,
    store_authorized_player_bootstrap,
    store_identity_legitimation,
    store_ssot_club,
    store_ssot_player,
    store_ssot_version,
)
from bms.storage import store_evidence, store_raw_observation


REPO_ROOT = Path(__file__).resolve().parents[1]
MIGRATION = REPO_ROOT / "migrations/0005_ssot_persistence.sql"
POSITIVE_FIXTURE = REPO_ROOT / "pilot_data/w2/fixtures/w2-c3-positive-01"
POSITIVE_EVIDENCE_MANIFEST = POSITIVE_FIXTURE / "seed-evidence-manifest.json"
POSITIVE_PLAYER_EVIDENCE_REFS = (
    "seed-evidence:w2-c3-positive-01:player:wikidata",
    "seed-evidence:w2-c3-positive-01:player:bundesliga",
    "seed-evidence:w2-c3-positive-01:player:fcb",
)
POSITIVE_PLAYER_WIKIDATA_EVIDENCE_REF = POSITIVE_PLAYER_EVIDENCE_REFS[0]
SSOT_TABLES = {
    "ssot_evidence_reference",
    "ssot_identity_legitimation",
    "ssot_player",
    "ssot_club",
    "ssot_legitimation_mapping",
    "ssot_version",
}


class W2C31SSOTPersistenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.connection = connect_database(
            Path(self.temporary_directory.name) / "ssot.sqlite3"
        )
        self.addCleanup(self.connection.close)
        apply_migrations(
            self.connection,
            REPO_ROOT / "migrations",
            through="0005_ssot_persistence",
        )
        self.evidence = store_evidence(
            self.connection,
            content=b"documented-positive-legitimation-evidence",
            run_id="run-c3-1-test",
            media_type="application/octet-stream",
        )

    def legitimation(self, *, object_type: str, internal_id: str):
        return store_identity_legitimation(
            self.connection,
            run_id="run-c3-1-test",
            object_type=object_type,
            decided_at="2026-09-02T18:00:00+00:00",
            authorized_by="SSOT-Fachprüfung",
            resulting_internal_object_id=internal_id,
            evidence_refs=[self.evidence.evidence_id],
            legitimation_ref=f"fachentscheid:{object_type.lower()}:{internal_id}",
        )

    def copied_positive_fixture(self) -> Path:
        root = Path(self.temporary_directory.name) / str(uuid.uuid4())
        shutil.copytree(POSITIVE_FIXTURE, root)
        return root

    @staticmethod
    def write_manifest(fixture: Path, manifest: dict) -> Path:
        path = fixture / "seed-evidence-manifest.json"
        path.write_text(
            json.dumps(manifest, ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8",
        )
        return path

    def test_t01_migration_is_current_ordered_and_checksummed(self) -> None:
        self.assertEqual(schema_version(self.connection), ("0005_ssot_persistence", 5))
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
                "0005_ssot_persistence",
            ],
        )
        self.assertEqual(
            history[-1]["checksum_sha256"], hashlib.sha256(MIGRATION.read_bytes()).hexdigest()
        )

    def test_t02_only_c3_1_ssot_tables_are_added(self) -> None:
        tables = {
            row["name"]
            for row in self.connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            )
        }
        self.assertTrue(SSOT_TABLES.issubset(tables))
        legitimation_columns = {
            row["name"]
            for row in self.connection.execute(
                "PRAGMA table_info(ssot_identity_legitimation)"
            )
        }
        self.assertIn("evidence_refs_json", legitimation_columns)
        self.assertNotIn("primary_evidence_id", legitimation_columns)
        self.assertNotIn("authorization_ref", legitimation_columns)
        self.assertFalse(
            {
                "ssot_review_case",
                "player_club_assignment",
                "player_position_assignment",
                "monitoring",
                "eligibility",
                "recommendation",
                "snapshot",
                "result",
                "evaluation",
            }
            & tables
        )

    def test_t03_given_legitimation_ref_is_preserved_exactly(self) -> None:
        second = store_evidence(
            self.connection, content=b"second", run_id="run-c3-1-test"
        )
        stored = store_identity_legitimation(
            self.connection,
            run_id="run-c3-1-test",
            object_type="PLAYER",
            decided_at="2026-09-02T20:00:00+02:00",
            authorized_by="SSOT-Fachprüfung",
            resulting_internal_object_id="player:stable",
            evidence_refs=[second.evidence_id, self.evidence.evidence_id],
            legitimation_ref="LEGIT/2026-09-02/ÄÖ-Seed:01",
        )
        self.assertEqual(read_identity_legitimation(self.connection, stored.legitimation_ref), stored)
        self.assertEqual(
            stored.legitimation_ref, "LEGIT/2026-09-02/ÄÖ-Seed:01"
        )
        persisted_ref = self.connection.execute(
            "SELECT legitimation_ref FROM ssot_identity_legitimation"
        ).fetchone()[0]
        self.assertEqual(
            persisted_ref.encode("utf-8"),
            "LEGIT/2026-09-02/ÄÖ-Seed:01".encode("utf-8"),
        )
        self.assertEqual(
            stored.evidence_refs, tuple(sorted((second.evidence_id, self.evidence.evidence_id)))
        )

    def test_t04_legitimation_evidence_bundle_requires_resolved_references(self) -> None:
        with self.assertRaises(ValueError):
            store_identity_legitimation(
                self.connection,
                run_id="run-c3-1-test",
                object_type="PLAYER",
                decided_at="2026-09-02T18:00:00Z",
                authorized_by="SSOT-Fachprüfung",
                resulting_internal_object_id="player:none",
                evidence_refs=[],
                legitimation_ref="fachentscheid:no-evidence",
            )
        with self.assertRaisesRegex(EvidenceManifestError, "unresolved evidence_ref"):
            store_identity_legitimation(
                self.connection,
                run_id="run-c3-1-test",
                object_type="PLAYER",
                decided_at="2026-09-02T18:00:00Z",
                authorized_by="SSOT-Fachprüfung",
                resulting_internal_object_id="player:fach-evidence",
                evidence_refs=["fach-evidence:player:source-a"],
                legitimation_ref="fachentscheid:fach-evidence",
            )

    def test_t05_player_and_club_require_matching_positive_legitimation(self) -> None:
        player_legitimation = self.legitimation(
            object_type="PLAYER", internal_id="player:stable"
        )
        player = store_ssot_player(
            self.connection,
            player_id="player:stable",
            display_name="Test Player",
            legitimation_ref=player_legitimation.legitimation_ref,
            legitimized_at=player_legitimation.decided_at,
        )
        self.assertEqual(read_ssot_player(self.connection, player.player_id), player)

        club_legitimation = self.legitimation(
            object_type="CLUB", internal_id="club:stable"
        )
        club = store_ssot_club(
            self.connection,
            club_id="club:stable",
            club_name="Test Club",
            short_name=None,
            legitimation_ref=club_legitimation.legitimation_ref,
            legitimized_at=club_legitimation.decided_at,
        )
        self.assertEqual(read_ssot_club(self.connection, club.club_id), club)
        self.assertEqual(
            self.connection.execute(
                "SELECT COUNT(*) FROM ssot_legitimation_mapping"
            ).fetchone()[0],
            0,
        )
        self.assertEqual(
            self.connection.execute("SELECT COUNT(*) FROM mapping_record").fetchone()[0],
            0,
        )

        with self.assertRaisesRegex(sqlite3.IntegrityError, "matching positive legitimation"):
            store_ssot_player(
                self.connection,
                player_id="player:not-legitimated",
                display_name="No Identity",
                legitimation_ref=club_legitimation.legitimation_ref,
                legitimized_at=club_legitimation.decided_at,
            )

    def test_t06_positive_replay_is_idempotent_for_decision_and_identity(self) -> None:
        second_evidence = store_evidence(
            self.connection, content=b"replay-evidence", run_id="run-c3-1-test"
        )
        values = {
            "object_type": "PLAYER",
            "decided_at": "2026-09-02T18:00:00Z",
            "authorized_by": "SSOT-Fachprüfung",
            "resulting_internal_object_id": "player:replay-stable",
            "evidence_refs": [self.evidence.evidence_id, second_evidence.evidence_id],
            "legitimation_ref": "fachlich-vorgegeben:replay-001",
        }
        first_legitimation = store_identity_legitimation(
            self.connection, run_id="run-original", **values
        )
        first_player = store_ssot_player(
            self.connection,
            player_id="player:replay-stable",
            display_name="Replay Player",
            legitimation_ref=first_legitimation.legitimation_ref,
            legitimized_at=first_legitimation.decided_at,
        )

        replay_legitimation = store_identity_legitimation(
            self.connection,
            run_id="run-replay",
            **{**values, "evidence_refs": list(reversed(values["evidence_refs"]))},
        )
        replay_player = store_ssot_player(
            self.connection,
            player_id="player:replay-stable",
            display_name="Replay Player",
            legitimation_ref=first_legitimation.legitimation_ref,
            legitimized_at=first_legitimation.decided_at,
        )

        self.assertEqual(replay_legitimation, first_legitimation)
        self.assertEqual(replay_player, first_player)
        self.assertEqual(
            self.connection.execute(
                "SELECT COUNT(*) FROM ssot_identity_legitimation"
            ).fetchone()[0],
            1,
        )
        self.assertEqual(
            self.connection.execute("SELECT COUNT(*) FROM ssot_player").fetchone()[0],
            1,
        )

    def test_t07_conflicting_reuse_of_legitimation_ref_is_rejected(self) -> None:
        original = self.legitimation(
            object_type="PLAYER", internal_id="player:conflict-original"
        )
        with self.assertRaisesRegex(
            IdentityLegitimationConflictError, "different decision basis"
        ):
            store_identity_legitimation(
                self.connection,
                run_id="run-replay",
                object_type="PLAYER",
                decided_at=original.decided_at,
                authorized_by="Andere Autorisierung",
                resulting_internal_object_id=original.resulting_internal_object_id,
                evidence_refs=original.evidence_refs,
                legitimation_ref=original.legitimation_ref,
            )
        self.assertEqual(
            read_identity_legitimation(self.connection, original.legitimation_ref),
            original,
        )
        self.assertEqual(
            self.connection.execute(
                "SELECT COUNT(*) FROM ssot_identity_legitimation"
            ).fetchone()[0],
            1,
        )

    def test_t08_positive_seed_contract_structure_is_persistable(self) -> None:
        imported = import_fixture(
            self.connection,
            fixture_dir=POSITIVE_FIXTURE,
            run_id="run-positive-seed-contract",
        )
        provided_legitimation_ref = (
            "ssot-legit:dc4a7f13-6cb3-4144-a9ca-89991a281962"
        )
        provided_internal_player_id = "9ed46b81-bb6e-4f84-a28d-92b0f019beb5"
        provided_decided_at = "2026-09-02T15:57:44+02:00"
        entity = imported.parsed_source["entities"]["Q96072055"]
        bindings = register_evidence_manifest(
            self.connection,
            manifest_path=POSITIVE_EVIDENCE_MANIFEST,
            run_id="run-positive-seed-contract",
        )
        self.assertEqual(
            {binding.evidence_ref for binding in bindings},
            set(POSITIVE_PLAYER_EVIDENCE_REFS),
        )
        wikidata_binding = read_evidence_reference(
            self.connection, POSITIVE_PLAYER_WIKIDATA_EVIDENCE_REF
        )
        self.assertEqual(wikidata_binding.evidence_id, imported.evidence.evidence_id)
        self.assertEqual(
            resolve_evidence_reference(
                self.connection, POSITIVE_PLAYER_WIKIDATA_EVIDENCE_REF
            ),
            imported.evidence,
        )

        bootstrap = store_authorized_player_bootstrap(
            self.connection,
            run_id="run-positive-seed-contract",
            legitimation_ref=provided_legitimation_ref,
            decided_at=provided_decided_at,
            authorized_by="Fach-Chat Erstellung SSOT",
            player_id=provided_internal_player_id,
            display_name=entity["labels"]["de"]["value"],
            evidence_refs=POSITIVE_PLAYER_EVIDENCE_REFS,
            raw_record_id=imported.raw_observation.raw_record_id,
            source_system="WIKIDATA",
            external_id="Q96072055",
            confirmation_evidence_ref=POSITIVE_PLAYER_WIKIDATA_EVIDENCE_REF,
        )

        self.assertEqual(bootstrap.legitimation.legitimation_ref, provided_legitimation_ref)
        self.assertEqual(bootstrap.legitimation.decision_status, "IDENTITY_LEGITIMATED")
        self.assertEqual(bootstrap.legitimation.decided_at, provided_decided_at)
        self.assertEqual(bootstrap.legitimation.authorized_by, "Fach-Chat Erstellung SSOT")
        self.assertEqual(
            bootstrap.legitimation.evidence_refs,
            tuple(sorted(POSITIVE_PLAYER_EVIDENCE_REFS)),
        )
        self.assertEqual(bootstrap.player.player_id, provided_internal_player_id)
        self.assertEqual(bootstrap.player.display_name, "Jamal Musiala")
        self.assertEqual(bootstrap.mapping.source_system, "WIKIDATA")
        self.assertEqual(bootstrap.mapping.external_id, "Q96072055")
        self.assertEqual(bootstrap.mapping.object_type, "PLAYER")
        self.assertEqual(bootstrap.mapping.mapping_status, "CONFIRMED")
        self.assertEqual(bootstrap.mapping.internal_object_id, provided_internal_player_id)
        self.assertEqual(
            bootstrap.mapping.confirmation_evidence_ref,
            POSITIVE_PLAYER_WIKIDATA_EVIDENCE_REF,
        )
        self.assertEqual(
            self.connection.execute(
                """
                SELECT mapping_record_id FROM ssot_legitimation_mapping
                WHERE legitimation_ref = ?
                """,
                (provided_legitimation_ref,),
            ).fetchone()[0],
            bootstrap.mapping.mapping_record_id,
        )

        replay = store_authorized_player_bootstrap(
            self.connection,
            run_id="run-positive-seed-replay",
            legitimation_ref=provided_legitimation_ref,
            decided_at=provided_decided_at,
            authorized_by="Fach-Chat Erstellung SSOT",
            player_id=provided_internal_player_id,
            display_name="Jamal Musiala",
            evidence_refs=tuple(reversed(POSITIVE_PLAYER_EVIDENCE_REFS)),
            raw_record_id=imported.raw_observation.raw_record_id,
            source_system="WIKIDATA",
            external_id="Q96072055",
            confirmation_evidence_ref=POSITIVE_PLAYER_WIKIDATA_EVIDENCE_REF,
        )
        self.assertEqual(replay, bootstrap)
        self.assertEqual(
            register_evidence_manifest(
                self.connection,
                manifest_path=POSITIVE_EVIDENCE_MANIFEST,
                run_id="run-positive-seed-replay",
            ),
            bindings,
        )
        replay_legitimation = read_identity_legitimation(
            self.connection, provided_legitimation_ref
        )
        self.assertEqual(replay_legitimation.decided_at, provided_decided_at)
        self.assertEqual(
            replay_legitimation.authorized_by, "Fach-Chat Erstellung SSOT"
        )
        self.assertEqual(
            replay_legitimation.evidence_refs,
            tuple(sorted(POSITIVE_PLAYER_EVIDENCE_REFS)),
        )
        for table in (
            "ssot_evidence_reference",
            "ssot_identity_legitimation",
            "ssot_player",
            "mapping_record",
            "ssot_legitimation_mapping",
        ):
            self.assertEqual(
                self.connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0],
                3 if table == "ssot_evidence_reference" else 1,
            )

        with self.assertRaises(IdentityLegitimationConflictError):
            store_authorized_player_bootstrap(
                self.connection,
                run_id="run-positive-seed-conflict",
                legitimation_ref=provided_legitimation_ref,
                decided_at=provided_decided_at,
                authorized_by="Fach-Chat Erstellung SSOT",
                player_id="00000000-0000-4000-8000-000000000001",
                display_name="Jamal Musiala",
                evidence_refs=POSITIVE_PLAYER_EVIDENCE_REFS,
                raw_record_id=imported.raw_observation.raw_record_id,
                source_system="WIKIDATA",
                external_id="Q96072055",
                confirmation_evidence_ref=POSITIVE_PLAYER_WIKIDATA_EVIDENCE_REF,
            )
        for table in (
            "ssot_identity_legitimation",
            "ssot_player",
            "mapping_record",
            "ssot_legitimation_mapping",
        ):
            self.assertEqual(
                self.connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0],
                1,
            )
        self.assertEqual(
            self.connection.execute(
                "SELECT COUNT(*) FROM control_event WHERE control_point='K2'"
            ).fetchone()[0],
            0,
        )

    def test_t08a_distinct_refs_may_share_artifact_and_package_path(self) -> None:
        content = b'{"fixture":"shared-cardinality-artifact"}'
        digest = hashlib.sha256(content).hexdigest()
        references = (
            "test-only:evidence-cardinality:context-a",
            "test-only:evidence-cardinality:context-b",
        )
        manifests: list[Path] = []
        bindings = []
        for context, evidence_ref in enumerate(references, start=1):
            package = Path(self.temporary_directory.name) / f"package-{context}"
            artifact = package / "evidence/shared.json"
            artifact.parent.mkdir(parents=True)
            artifact.write_bytes(content)
            manifest = {
                "schema": "bms.seed-evidence-manifest",
                "schema_version": "1.0",
                "evidence": [
                    {
                        "evidence_ref": evidence_ref,
                        "artifact_path": "evidence/shared.json",
                        "sha256": digest,
                        "byte_length": len(content),
                        "media_type": "application/json",
                        "source_reference": f"fixture://cardinality/context-{context}",
                        "representation_type": "ARCHIVED_RAW_SOURCE",
                        "representation_status": "CONFIRMED",
                        "confirmation": f"Test binding for {evidence_ref}",
                    }
                ],
            }
            manifest_path = self.write_manifest(package, manifest)
            manifests.append(manifest_path)
            bindings.append(
                register_evidence_manifest(
                    self.connection,
                    manifest_path=manifest_path,
                    run_id="run-cardinality-regression",
                )[0]
            )

        first, second = bindings
        self.assertNotEqual(first.evidence_ref, second.evidence_ref)
        self.assertEqual(first.evidence_id, second.evidence_id)
        self.assertEqual(first.artifact_path, second.artifact_path)
        self.assertEqual(
            read_evidence_reference(self.connection, first.evidence_ref), first
        )
        self.assertEqual(
            read_evidence_reference(self.connection, second.evidence_ref), second
        )
        self.assertEqual(
            resolve_evidence_reference(self.connection, first.evidence_ref),
            resolve_evidence_reference(self.connection, second.evidence_ref),
        )
        for binding in bindings:
            self.assertEqual(binding.manifest_sha256, digest)
            self.assertEqual(binding.manifest_byte_length, len(content))
            self.assertEqual(binding.media_type, "application/json")
        self.assertEqual(
            self.connection.execute(
                "SELECT COUNT(*) FROM ssot_evidence_reference"
            ).fetchone()[0],
            2,
        )
        replayed = [
            register_evidence_manifest(
                self.connection,
                manifest_path=manifest_path,
                run_id="run-cardinality-replay",
            )[0]
            for manifest_path in manifests
        ]
        self.assertEqual(replayed, bindings)
        self.assertEqual(
            self.connection.execute(
                "SELECT COUNT(*) FROM ssot_evidence_reference"
            ).fetchone()[0],
            2,
        )

    def test_t08b_missing_manifest_artifact_is_rejected(self) -> None:
        fixture = self.copied_positive_fixture()
        (fixture / "evidence/player_fcb.json").unlink()
        with self.assertRaisesRegex(EvidenceManifestError, "artifact not found"):
            register_evidence_manifest(
                self.connection,
                manifest_path=fixture / "seed-evidence-manifest.json",
                run_id="run-missing-artifact",
            )
        self.assertEqual(
            self.connection.execute(
                "SELECT COUNT(*) FROM ssot_evidence_reference"
            ).fetchone()[0],
            0,
        )

    def test_t08c_manifest_hash_mismatch_is_rejected(self) -> None:
        fixture = self.copied_positive_fixture()
        manifest = json.loads((fixture / "seed-evidence-manifest.json").read_bytes())
        manifest["evidence"][0]["sha256"] = "0" * 64
        with self.assertRaisesRegex(EvidenceManifestError, "SHA-256 mismatch"):
            register_evidence_manifest(
                self.connection,
                manifest_path=self.write_manifest(fixture, manifest),
                run_id="run-hash-mismatch",
            )

    def test_t08d_manifest_byte_length_mismatch_is_rejected(self) -> None:
        fixture = self.copied_positive_fixture()
        manifest = json.loads((fixture / "seed-evidence-manifest.json").read_bytes())
        manifest["evidence"][0]["byte_length"] += 1
        with self.assertRaisesRegex(EvidenceManifestError, "byte length mismatch"):
            register_evidence_manifest(
                self.connection,
                manifest_path=self.write_manifest(fixture, manifest),
                run_id="run-length-mismatch",
            )

    def test_t08e_wrong_referent_to_artifact_assignment_is_rejected(self) -> None:
        fixture = self.copied_positive_fixture()
        manifest = json.loads((fixture / "seed-evidence-manifest.json").read_bytes())
        bundesliga, fcb = manifest["evidence"][1:]
        bundesliga["artifact_path"] = fcb["artifact_path"]
        bundesliga["sha256"] = fcb["sha256"]
        bundesliga["byte_length"] = fcb["byte_length"]
        manifest["evidence"] = manifest["evidence"][:2]
        with self.assertRaisesRegex(
            EvidenceManifestError, "record does not match evidence_ref"
        ):
            register_evidence_manifest(
                self.connection,
                manifest_path=self.write_manifest(fixture, manifest),
                run_id="run-wrong-assignment",
            )

    def test_t08f_incomplete_evidence_cannot_bootstrap_positive_identity(self) -> None:
        fixture = self.copied_positive_fixture()
        imported = import_fixture(
            self.connection, fixture_dir=fixture, run_id="run-incomplete-evidence"
        )
        manifest = json.loads((fixture / "seed-evidence-manifest.json").read_bytes())
        manifest["evidence"] = manifest["evidence"][:2]
        register_evidence_manifest(
            self.connection,
            manifest_path=self.write_manifest(fixture, manifest),
            run_id="run-incomplete-evidence",
        )
        with self.assertRaisesRegex(EvidenceManifestError, "unresolved evidence_ref"):
            store_authorized_player_bootstrap(
                self.connection,
                run_id="run-incomplete-evidence",
                legitimation_ref="ssot-legit:dc4a7f13-6cb3-4144-a9ca-89991a281962",
                decided_at="2026-09-02T15:57:44+02:00",
                authorized_by="Fach-Chat Erstellung SSOT",
                player_id="9ed46b81-bb6e-4f84-a28d-92b0f019beb5",
                display_name="Jamal Musiala",
                evidence_refs=POSITIVE_PLAYER_EVIDENCE_REFS,
                raw_record_id=imported.raw_observation.raw_record_id,
                source_system="WIKIDATA",
                external_id="Q96072055",
                confirmation_evidence_ref=POSITIVE_PLAYER_WIKIDATA_EVIDENCE_REF,
            )
        for table in (
            "ssot_identity_legitimation",
            "ssot_player",
            "mapping_record",
            "ssot_legitimation_mapping",
        ):
            self.assertEqual(
                self.connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0],
                0,
            )

    def test_t09_failed_bootstrap_rolls_back_all_partial_persistence(self) -> None:
        raw = store_raw_observation(
            self.connection,
            source_system="WIKIDATA",
            source_reference="fixture://atomic-failure",
            retrieved_at="2026-09-02T18:00:00Z",
            observed_at="2026-09-02T18:00:00Z",
            raw_payload_ref=self.evidence.evidence_id,
            run_id="run-atomic-failure",
        )
        with patch(
            "bms.ssot.store_mapping_record",
            side_effect=sqlite3.IntegrityError("synthetic mapping persistence failure"),
        ):
            with self.assertRaises(sqlite3.IntegrityError):
                store_authorized_player_bootstrap(
                    self.connection,
                    run_id="run-atomic-failure",
                    legitimation_ref="ssot-legit:atomic-failure",
                    decided_at="2026-09-02T18:10:00Z",
                    authorized_by="Fach-Chat Erstellung SSOT",
                    player_id="9ed46b81-bb6e-4f84-a28d-92b0f019beb5",
                    display_name="Jamal Musiala",
                    evidence_refs=[self.evidence.evidence_id],
                    raw_record_id=raw.raw_record_id,
                    source_system="WIKIDATA",
                    external_id="Q96072055",
                    confirmation_evidence_ref=self.evidence.evidence_id,
                )
        self.assertEqual(
            self.connection.execute(
                "SELECT COUNT(*) FROM ssot_identity_legitimation"
            ).fetchone()[0],
            0,
        )
        self.assertEqual(
            self.connection.execute("SELECT COUNT(*) FROM ssot_player").fetchone()[0],
            0,
        )
        self.assertEqual(
            self.connection.execute("SELECT COUNT(*) FROM mapping_record").fetchone()[0],
            0,
        )

    def test_t10_ssot_objects_and_legitimation_are_append_only(self) -> None:
        legitimation = self.legitimation(object_type="PLAYER", internal_id="player:immutable")
        player = store_ssot_player(
            self.connection,
            player_id="player:immutable",
            display_name="Immutable Player",
            legitimation_ref=legitimation.legitimation_ref,
            legitimized_at=legitimation.decided_at,
        )
        for sql, parameters in (
            (
                "UPDATE ssot_identity_legitimation SET authorized_by='changed' WHERE legitimation_ref=?",
                (legitimation.legitimation_ref,),
            ),
            ("DELETE FROM ssot_player WHERE player_id=?", (player.player_id,)),
        ):
            with self.subTest(sql=sql), self.assertRaises(sqlite3.IntegrityError):
                self.connection.execute(sql, parameters)

    def test_t11_version_roundtrip_predecessor_and_history(self) -> None:
        first = store_ssot_version(
            self.connection,
            run_id="run-c3-1-test",
            data_as_of="2026-09-02T18:00:00Z",
            change_ref="change:test:first",
            state={"players": ["player:a"], "status": "SSOT_BLOCKED"},
        )
        second = store_ssot_version(
            self.connection,
            run_id="run-c3-1-test",
            data_as_of="2026-09-02T19:00:00Z",
            released_at="2026-09-02T19:05:00Z",
            change_ref="change:test:second",
            release_evidence_ref="release-evidence:test:second",
            predecessor_ssot_version_id=first.ssot_version_id,
            state={"status": "SSOT_PROCESSABLE", "players": ["player:a"]},
        )
        self.assertEqual(read_ssot_version(self.connection, first.ssot_version_id), first)
        self.assertEqual(read_ssot_version(self.connection, second.ssot_version_id), second)
        self.assertEqual(second.predecessor_ssot_version_id, first.ssot_version_id)
        self.assertEqual(uuid.UUID(second.ssot_version_id).version, 4)

    def test_t12_versions_are_immutable_and_release_fields_stay_consistent(self) -> None:
        draft = store_ssot_version(
            self.connection,
            run_id="run-c3-1-test",
            data_as_of="2026-09-02T18:00:00Z",
            change_ref="change:test:draft",
            state={},
        )
        with self.assertRaises(sqlite3.IntegrityError):
            self.connection.execute(
                "UPDATE ssot_version SET state_json='{}' WHERE ssot_version_id=?",
                (draft.ssot_version_id,),
            )
        with self.assertRaises(sqlite3.IntegrityError):
            store_ssot_version(
                self.connection,
                run_id="run-c3-1-test",
                data_as_of="2026-09-02T18:00:00Z",
                released_at="2026-09-02T18:01:00Z",
                change_ref="change:test:invalid-release",
                state={},
            )

    def test_t13_unknown_or_self_predecessor_is_rejected(self) -> None:
        with self.assertRaises(sqlite3.IntegrityError):
            store_ssot_version(
                self.connection,
                run_id="run-c3-1-test",
                data_as_of="2026-09-02T18:00:00Z",
                change_ref="change:test:unknown-predecessor",
                predecessor_ssot_version_id=str(uuid.uuid4()),
                state={},
            )
        identity = str(uuid.uuid4())
        with self.assertRaises(sqlite3.IntegrityError):
            self.connection.execute(
                """
                INSERT INTO ssot_version VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    identity, "run", "2026-09-02T18:00:00Z", None,
                    identity, "change:self", None, "{}", "2026-09-02T18:00:00Z",
                ),
            )

    def test_t14_c3_1_bounded_database_excludes_c3_2_objects(self) -> None:
        self.assertEqual(
            self.connection.execute(
                "SELECT COUNT(*) FROM control_event WHERE control_point='K2'"
            ).fetchone()[0],
            0,
        )
        tables = {
            row["name"]
            for row in self.connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        self.assertNotIn("ssot_version_release", tables)


if __name__ == "__main__":
    unittest.main()
