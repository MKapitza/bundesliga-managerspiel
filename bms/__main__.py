from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

from .manifests import ManifestError, write_run_manifest
from .persistence import MigrationError, migrate_database, read_schema_version
from .w1_ig1_evidence import W1IG1EvidenceError, run_w1_ig1_evidence
from .w1_smoke import W1SmokeError, run_w1_smoke
from .imports import FixtureValidationError
from .w2_c1 import W2C1Error, run_w2_c1_smoke
from .w2_c2 import W2C2Error, run_w2_c2_smoke
from .w2_c3 import W2C3Error, run_w2_c3_smoke


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
    w1_smoke = subparsers.add_parser(
        "w1-smoke", help="run the integrated W1 persistence replay smoke"
    )
    w1_smoke.add_argument(
        "--output-dir",
        type=Path,
        required=True,
        help="new output directory for W1 replay evidence",
    )
    w1_evidence = subparsers.add_parser(
        "w1-ig1-evidence", help="produce the complete technical W1 IG1 candidate evidence"
    )
    w1_evidence.add_argument(
        "--output-dir",
        type=Path,
        required=True,
        help="new output directory for complete W1 IG1 candidate evidence",
    )
    w1_evidence.add_argument(
        "--require-clean",
        action="store_true",
        help="fail technical validation when the recorded worktree is dirty",
    )
    w2_c1_smoke = subparsers.add_parser(
        "w2-c1-smoke", help="run the archived-source W2-C1 import and K0/G1 smoke"
    )
    w2_c1_smoke.add_argument(
        "--fixture-dir", type=Path, required=True, help="pilot fixture directory"
    )
    w2_c1_smoke.add_argument(
        "--output-dir", type=Path, required=True, help="new C1 evidence output directory"
    )
    w2_c2_smoke = subparsers.add_parser(
        "w2-c2-smoke", help="run the integrated C1-to-mapping K1/G2 smoke"
    )
    w2_c2_smoke.add_argument(
        "--fixture-dir", type=Path, required=True, help="pilot fixture directory"
    )
    w2_c3_smoke = subparsers.add_parser(
        "w2-c3-smoke", help="run the integrated Source-to-SSOT K2/G3 smoke"
    )
    w2_c3_smoke.add_argument(
        "--output-dir", type=Path, required=True, help="new C3 evidence output directory"
    )
    w2_c2_smoke.add_argument(
        "--output-dir", type=Path, required=True, help="new C2 evidence output directory"
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
    if args.command == "w1-smoke":
        try:
            data = run_w1_smoke(args.output_dir, repo_root=repo_root)
        except (W1SmokeError, ManifestError, MigrationError, OSError, sqlite3.Error) as exc:
            print(f"W1 SMOKE FAIL: {exc}", file=sys.stderr)
            return 1
        print("W1 SMOKE PASS")
        print(json.dumps(data, sort_keys=True))
        return 0
    if args.command == "w1-ig1-evidence":
        try:
            data = run_w1_ig1_evidence(
                args.output_dir,
                repo_root=repo_root,
                require_clean=args.require_clean,
            )
        except (W1IG1EvidenceError, OSError, ValueError) as exc:
            print(f"W1 IG1 EVIDENCE FAIL: {exc}", file=sys.stderr)
            return 1
        print(f"W1 IG1 EVIDENCE {data['status']}")
        print(json.dumps(data, sort_keys=True))
        return 0 if data["status"] == "PASS" else 1
    if args.command == "w2-c1-smoke":
        try:
            data = run_w2_c1_smoke(
                args.fixture_dir, args.output_dir, repo_root=repo_root
            )
        except (
            W2C1Error,
            FixtureValidationError,
            ManifestError,
            MigrationError,
            OSError,
            sqlite3.Error,
            ValueError,
        ) as exc:
            print(f"W2-C1 SMOKE FAIL: {exc}", file=sys.stderr)
            return 1
        print("W2-C1 SMOKE PASS")
        print(json.dumps(data, sort_keys=True))
        return 0
    if args.command == "w2-c2-smoke":
        try:
            data = run_w2_c2_smoke(
                args.fixture_dir, args.output_dir, repo_root=repo_root
            )
        except (
            W2C2Error,
            FixtureValidationError,
            ManifestError,
            MigrationError,
            OSError,
            sqlite3.Error,
            ValueError,
        ) as exc:
            print(f"W2-C2 SMOKE FAIL: {exc}", file=sys.stderr)
            return 1
        print("W2-C2 SMOKE PASS")
        print(json.dumps(data, sort_keys=True))
        return 0
    if args.command == "w2-c3-smoke":
        try:
            data = run_w2_c3_smoke(args.output_dir, repo_root=repo_root)
        except (
            W2C3Error,
            FixtureValidationError,
            ManifestError,
            MigrationError,
            OSError,
            sqlite3.Error,
            ValueError,
        ) as exc:
            print(f"W2-C3 SMOKE FAIL: {exc}", file=sys.stderr)
            return 1
        print("W2-C3 SMOKE PASS")
        print(json.dumps(data, sort_keys=True))
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
