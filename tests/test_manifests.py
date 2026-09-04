from __future__ import annotations

import json
import re
import tempfile
import unittest
from pathlib import Path

from bms.manifests import (
    RUN_ID_RE,
    ManifestError,
    validate_run_manifest,
    validate_specification_manifest,
    write_run_manifest,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
SPEC_PATH = REPO_ROOT / "spec/specification-manifest.json"
EXPECTED_SPECIFICATIONS = {
    "DOC-REG-001": "3.8",
    "DOC-013": "0.1",
    "DOC-014": "0.7",
    "DOC-015": "0.6",
    "DOC-016": "0.2",
}


class SpecificationManifestTests(unittest.TestCase):
    def test_manifest_matches_current_registered_specifications(self) -> None:
        manifest = validate_specification_manifest(SPEC_PATH)
        self.assertEqual(manifest["specifications"], EXPECTED_SPECIFICATIONS)
        self.assertTrue(manifest["requires_explicit_update_on_document_register_change"])

    def test_missing_doc_register_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "spec.json"
            path.write_text(
                json.dumps(
                    {
                        "schema": "bms.specification-manifest",
                        "schema_version": "1.0",
                        "created_at": "2026-08-17T00:00:00Z",
                        "requires_explicit_update_on_document_register_change": True,
                        "specifications": {"DOC-016": "0.2"},
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaises(ManifestError):
                validate_specification_manifest(path)


class RunManifestTests(unittest.TestCase):
    def test_run_manifest_has_minimal_traceability_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "run.json"
            manifest = write_run_manifest(
                output,
                repo_root=REPO_ROOT,
                specification_manifest=SPEC_PATH,
            )
            validate_run_manifest(manifest)
            self.assertRegex(manifest["run_id"], RUN_ID_RE)
            self.assertEqual(manifest["specification_manifest"], "spec/specification-manifest.json")
            self.assertEqual(manifest["execution_status"], "SUCCEEDED")
            self.assertTrue(output.is_file())

    def test_run_id_is_unique(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            first = write_run_manifest(
                Path(tmp) / "run-1.json",
                repo_root=REPO_ROOT,
                specification_manifest=SPEC_PATH,
            )
            second = write_run_manifest(
                Path(tmp) / "run-2.json",
                repo_root=REPO_ROOT,
                specification_manifest=SPEC_PATH,
            )
            self.assertNotEqual(first["run_id"], second["run_id"])
            self.assertIsNotNone(re.fullmatch(RUN_ID_RE, first["run_id"]))


if __name__ == "__main__":
    unittest.main()
