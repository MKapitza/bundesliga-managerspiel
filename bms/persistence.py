from __future__ import annotations

import hashlib
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

MIGRATION_FILENAME_RE = re.compile(r"^\d{4}_[A-Za-z0-9][A-Za-z0-9_-]*\.sql$")


class MigrationError(RuntimeError):
    """Raised when migration discovery or execution cannot proceed safely."""


@dataclass(frozen=True)
class Migration:
    migration_id: str
    path: Path
    checksum_sha256: str
    sql: str


def connect_database(database: Path | str) -> sqlite3.Connection:
    connection = sqlite3.connect(database, isolation_level=None)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    if connection.execute("PRAGMA foreign_keys").fetchone()[0] != 1:
        connection.close()
        raise MigrationError("SQLite foreign key enforcement could not be enabled")
    return connection


def ensure_schema_migrations(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            migration_id TEXT PRIMARY KEY,
            checksum_sha256 TEXT NOT NULL,
            applied_at TEXT NOT NULL
        )
        """
    )


def discover_migrations(migrations_dir: Path) -> list[Migration]:
    if not migrations_dir.exists():
        return []
    if not migrations_dir.is_dir():
        raise MigrationError(f"migration path is not a directory: {migrations_dir}")

    migrations: list[Migration] = []
    for path in migrations_dir.iterdir():
        if not path.is_file() or path.suffix != ".sql":
            continue
        if MIGRATION_FILENAME_RE.fullmatch(path.name) is None:
            raise MigrationError(f"invalid migration filename: {path.name}")
        content = path.read_bytes()
        try:
            sql = content.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise MigrationError(f"migration is not UTF-8: {path.name}") from exc
        migrations.append(
            Migration(
                migration_id=path.stem,
                path=path,
                checksum_sha256=hashlib.sha256(content).hexdigest(),
                sql=sql,
            )
        )
    return sorted(migrations, key=lambda migration: migration.path.name)


def _statements(sql: str) -> list[str]:
    statements: list[str] = []
    buffer: list[str] = []
    for character in sql:
        buffer.append(character)
        if character == ";" and sqlite3.complete_statement("".join(buffer)):
            statements.append("".join(buffer))
            buffer.clear()
    remainder = "".join(buffer)
    if remainder.strip():
        statements.append(remainder)
    return statements


def _deny_transaction_control(
    action: int,
    _argument_one: str | None,
    _argument_two: str | None,
    _database_name: str | None,
    _trigger_name: str | None,
) -> int:
    if action in {sqlite3.SQLITE_TRANSACTION, sqlite3.SQLITE_SAVEPOINT}:
        return sqlite3.SQLITE_DENY
    return sqlite3.SQLITE_OK


def _applied_migrations(connection: sqlite3.Connection) -> dict[str, str]:
    rows = connection.execute(
        "SELECT migration_id, checksum_sha256 FROM schema_migrations ORDER BY migration_id"
    )
    return {row["migration_id"]: row["checksum_sha256"] for row in rows}


def apply_migrations(
    connection: sqlite3.Connection,
    migrations_dir: Path,
    *,
    through: str | None = None,
) -> list[str]:
    ensure_schema_migrations(connection)
    migrations = discover_migrations(migrations_dir)
    if through is not None:
        available = {migration.migration_id for migration in migrations}
        if through not in available:
            raise MigrationError(f"unknown migration boundary: {through}")
        migrations = [
            migration for migration in migrations if migration.migration_id <= through
        ]
    applied = _applied_migrations(connection)

    for migration in migrations:
        recorded_checksum = applied.get(migration.migration_id)
        if recorded_checksum is not None and recorded_checksum != migration.checksum_sha256:
            raise MigrationError(
                f"checksum mismatch for applied migration {migration.migration_id}"
            )

    newly_applied: list[str] = []
    for migration in migrations:
        if migration.migration_id in applied:
            continue
        connection.execute("BEGIN IMMEDIATE")
        try:
            connection.set_authorizer(_deny_transaction_control)
            for statement in _statements(migration.sql):
                connection.execute(statement)
            connection.set_authorizer(None)
            applied_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
            connection.execute(
                """
                INSERT INTO schema_migrations (
                    migration_id, checksum_sha256, applied_at
                ) VALUES (?, ?, ?)
                """,
                (migration.migration_id, migration.checksum_sha256, applied_at),
            )
            connection.execute("COMMIT")
        except (sqlite3.Error, MigrationError) as exc:
            connection.set_authorizer(None)
            if connection.in_transaction:
                connection.execute("ROLLBACK")
            raise MigrationError(f"migration {migration.migration_id} failed: {exc}") from exc
        newly_applied.append(migration.migration_id)
    return newly_applied


def schema_version(connection: sqlite3.Connection) -> tuple[str | None, int]:
    ensure_schema_migrations(connection)
    row = connection.execute(
        """
        SELECT MAX(migration_id) AS latest_migration, COUNT(*) AS applied_migrations
        FROM schema_migrations
        """
    ).fetchone()
    return row["latest_migration"], row["applied_migrations"]


def migrate_database(database: Path, migrations_dir: Path) -> list[str]:
    connection = connect_database(database)
    try:
        return apply_migrations(connection, migrations_dir)
    finally:
        connection.close()


def read_schema_version(database: Path) -> dict[str, str | int | None]:
    connection = connect_database(database)
    try:
        latest_migration, applied_migrations = schema_version(connection)
    finally:
        connection.close()
    return {
        "database": str(database),
        "latest_migration": latest_migration,
        "applied_migrations": applied_migrations,
    }
