from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

from .manifests import ManifestError, write_run_manifest
from .persistence import MigrationError, migrate_database, read_schema_version


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="MS2 technical utilities")
    subparsers = parser.add_subparsers(dest="command", required=True)
    smoke = subparsers.add_parser(
        "smoke", help="validate the specification manifest and emit a minimal run manifest"
    )
    smoke.add_argument(
        "--output",
        type=Path,
        default=Path(".runs/smoke-run.json"),
        help="run manifest output path (default: .runs/smoke-run.json)",
    )
    migrate = subparsers.add_parser(
        "migrate", help="apply pending SQLite migrations"
    )
    migrate.add_argument("--db", type=Path, required=True, help="SQLite database path")
    schema_version = subparsers.add_parser(
        "schema-version", help="report the current SQLite migration version"
    )
    schema_version.add_argument(
        "--db", type=Path, required=True, help="SQLite database path"
    )
    return parser


def main() -> int:
    args = _parser().parse_args()
    repo_root = _repo_root()
    if args.command == "smoke":
        try:
            data = write_run_manifest(
                args.output,
                repo_root=repo_root,
                specification_manifest=repo_root / "spec/specification-manifest.json",
            )
        except ManifestError as exc:
            print(f"SMOKE FAIL: {exc}", file=sys.stderr)
            return 1
        print("SMOKE PASS")
        print(json.dumps(data, sort_keys=True))
        return 0
    if args.command in {"migrate", "schema-version"}:
        try:
            if args.command == "migrate":
                migrate_database(args.db, repo_root / "migrations")
            data = read_schema_version(args.db)
        except (MigrationError, OSError, sqlite3.Error) as exc:
            print(f"{args.command} failed: {exc}", file=sys.stderr)
            return 1
        print(json.dumps(data, sort_keys=True))
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
