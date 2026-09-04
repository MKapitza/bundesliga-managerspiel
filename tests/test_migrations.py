from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from bms.persistence import (
    MigrationError,
    apply_migrations,
    connect_database,
    schema_version,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN_C3_TABLES = {
    "mapping",
    "ssot",
    "monitoring",
    "recommendation",
    "snapshot",
    "result",
    "evaluation",
    "import_batch",
}


def write_migration(directory: Path, name: str, sql: str) -> Path:
    path = directory / name
    path.write_text(sql, encoding="utf-8")
    return path


def user_tables(connection: sqlite3.Connection) -> set[str]:
    rows = connection.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
    )
    return {row[0] for row in rows}


class MigrationTests(unittest.TestCase):
    def test_fresh_setup_creates_only_migration_history(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            migrations = root / "migrations"
            migrations.mkdir()
            connection = connect_database(root / "fresh.sqlite3")
            try:
                self.assertEqual(apply_migrations(connection, migrations), [])
                self.assertEqual(user_tables(connection), {"schema_migrations"})
                self.assertEqual(connection.execute("PRAGMA foreign_keys").fetchone()[0], 1)
            finally:
                connection.close()

    def test_migrations_run_in_filename_order(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            migrations = root / "migrations"
            migrations.mkdir()
            write_migration(
                migrations,
                "0002_second.sql",
                "INSERT INTO execution_order (step) VALUES (2);",
            )
            write_migration(
                migrations,
                "0001_first.sql",
                "CREATE TABLE execution_order (step INTEGER NOT NULL);"
                "INSERT INTO execution_order (step) VALUES (1);",
            )
            connection = connect_database(root / "ordered.sqlite3")
            try:
                applied = apply_migrations(connection, migrations)
                rows = connection.execute(
                    "SELECT step FROM execution_order ORDER BY rowid"
                ).fetchall()
                self.assertEqual(applied, ["0001_first", "0002_second"])
                self.assertEqual([row[0] for row in rows], [1, 2])
            finally:
                connection.close()

    def test_second_run_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            migrations = root / "migrations"
            migrations.mkdir()
            write_migration(migrations, "0001_once.sql", "CREATE TABLE once_only (id INTEGER);")
            connection = connect_database(root / "idempotent.sqlite3")
            try:
                self.assertEqual(apply_migrations(connection, migrations), ["0001_once"])
                self.assertEqual(apply_migrations(connection, migrations), [])
                count = connection.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0]
                self.assertEqual(count, 1)
            finally:
                connection.close()

    def test_migration_boundary_is_explicit_and_validated(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            migrations = root / "migrations"
            migrations.mkdir()
            write_migration(migrations, "0001_first.sql", "CREATE TABLE first (id INTEGER);")
            write_migration(migrations, "0002_second.sql", "CREATE TABLE second (id INTEGER);")
            connection = connect_database(root / "bounded.sqlite3")
            try:
                self.assertEqual(
                    apply_migrations(connection, migrations, through="0001_first"),
                    ["0001_first"],
                )
                self.assertEqual(schema_version(connection), ("0001_first", 1))
                with self.assertRaisesRegex(MigrationError, "unknown migration boundary"):
                    apply_migrations(connection, migrations, through="0003_missing")
            finally:
                connection.close()

    def test_changed_applied_migration_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            migrations = root / "migrations"
            migrations.mkdir()
            migration = write_migration(
                migrations, "0001_guarded.sql", "CREATE TABLE guarded (id INTEGER);"
            )
            connection = connect_database(root / "guarded.sqlite3")
            try:
                apply_migrations(connection, migrations)
                migration.write_text(
                    "CREATE TABLE guarded (id INTEGER, changed INTEGER);", encoding="utf-8"
                )
                with self.assertRaisesRegex(MigrationError, "checksum mismatch"):
                    apply_migrations(connection, migrations)
                count = connection.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0]
                self.assertEqual(count, 1)
            finally:
                connection.close()

    def test_failed_migration_rolls_back_all_changes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            migrations = root / "migrations"
            migrations.mkdir()
            write_migration(
                migrations,
                "0001_broken.sql",
                "CREATE TABLE partial_change (id INTEGER); THIS IS NOT SQL;",
            )
            connection = connect_database(root / "rollback.sqlite3")
            try:
                with self.assertRaisesRegex(MigrationError, "0001_broken"):
                    apply_migrations(connection, migrations)
                self.assertNotIn("partial_change", user_tables(connection))
                count = connection.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0]
                self.assertEqual(count, 0)
            finally:
                connection.close()

    def test_schema_version_reports_none_and_latest_migration(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            migrations = root / "migrations"
            migrations.mkdir()
            connection = connect_database(root / "version.sqlite3")
            try:
                apply_migrations(connection, migrations)
                self.assertEqual(schema_version(connection), (None, 0))
                write_migration(migrations, "0001_alpha.sql", "CREATE TABLE alpha (id INTEGER);")
                write_migration(migrations, "0002_beta.sql", "CREATE TABLE beta (id INTEGER);")
                apply_migrations(connection, migrations)
                self.assertEqual(schema_version(connection), ("0002_beta", 2))
            finally:
                connection.close()

    def test_fresh_rebuild_produces_same_schema_and_history(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            migrations = root / "migrations"
            migrations.mkdir()
            write_migration(
                migrations,
                "0001_rebuild.sql",
                "CREATE TABLE rebuilt (id INTEGER PRIMARY KEY, value TEXT NOT NULL);",
            )
            results = []
            for database_name in ("first.sqlite3", "second.sqlite3"):
                connection = connect_database(root / database_name)
                try:
                    apply_migrations(connection, migrations)
                    schema = connection.execute(
                        "SELECT name, sql FROM sqlite_master WHERE type = 'table' ORDER BY name"
                    ).fetchall()
                    history = connection.execute(
                        "SELECT migration_id, checksum_sha256 FROM schema_migrations"
                    ).fetchall()
                    results.append(([tuple(row) for row in schema], [tuple(row) for row in history]))
                finally:
                    connection.close()
            self.assertEqual(results[0], results[1])

    def test_cli_migrate_and_schema_version_on_fresh_database(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            database = Path(tmp) / "cli.sqlite3"
            migrate = subprocess.run(
                [sys.executable, "-m", "bms", "migrate", "--db", str(database)],
                cwd=REPO_ROOT,
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(migrate.returncode, 0, msg=migrate.stderr)
            report = subprocess.run(
                [sys.executable, "-m", "bms", "schema-version", "--db", str(database)],
                cwd=REPO_ROOT,
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(report.returncode, 0, msg=report.stderr)
            self.assertEqual(
                json.loads(report.stdout),
                {
                    "database": str(database),
                    "latest_migration": "0005_ssot_persistence",
                    "applied_migrations": 5,
                },
            )

    def test_current_scope_contains_c3_1_ssot_persistence_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            connection = connect_database(Path(tmp) / "scope.sqlite3")
            try:
                apply_migrations(connection, REPO_ROOT / "migrations")
                self.assertEqual(
                    user_tables(connection),
                    {
                        "schema_migrations",
                        "evidence_artifact",
                        "raw_observation",
                        "control_event",
                        "import_envelope",
                        "mapping_record",
                        "ssot_evidence_reference",
                        "ssot_identity_legitimation",
                        "ssot_player",
                        "ssot_club",
                        "ssot_legitimation_mapping",
                        "ssot_version",
                    },
                )
                self.assertTrue(FORBIDDEN_C3_TABLES.isdisjoint(user_tables(connection)))
            finally:
                connection.close()
        self.assertTrue((REPO_ROOT / "migrations/0001_raw_evidence.sql").is_file())
        self.assertTrue((REPO_ROOT / "migrations/0002_control_event.sql").is_file())
        self.assertTrue((REPO_ROOT / "migrations/0003_import_envelope.sql").is_file())
        self.assertTrue((REPO_ROOT / "migrations/0004_mapping_review.sql").is_file())
        self.assertTrue((REPO_ROOT / "migrations/0005_ssot_persistence.sql").is_file())


if __name__ == "__main__":
    unittest.main()
