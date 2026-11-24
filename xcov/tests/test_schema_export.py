"""Canonical JSON schema export stays equivalent to the programmatic builders."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import sys

import pytest

from xcov import schemas
from xcov.errors import XcovError

ROOT = Path(__file__).resolve().parents[2]
SCHEMA_ROOT = ROOT / "xcov" / "xcov" / "schemas_data" / "v1"
EXPORT_TOOL = ROOT / "xcov" / "tools" / "export_schemas.py"


def _read(relative: str) -> dict:
    with (SCHEMA_ROOT / relative).open(encoding="utf-8") as fh:
        return json.load(fh)


def test_exported_schema_matches_programmatic_builders():
    assert schemas.schema_actions() == sorted(schemas.BUILT_SCHEMAS)
    assert schemas.SCHEMAS == schemas.BUILT_SCHEMAS
    assert schemas.RUN_MANIFEST_INPUT == schemas.BUILT_RUN_MANIFEST_INPUT
    assert schemas.STDIO_QUIT_REQUEST == schemas.BUILT_STDIO_QUIT_REQUEST


def test_export_check_passes():
    completed = subprocess.run(
        [sys.executable, str(EXPORT_TOOL), "--check"],
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr


def test_every_action_has_request_and_response_files():
    for action in schemas.schema_actions():
        for kind in ("request", "response"):
            path = SCHEMA_ROOT / "actions" / f"{action}.{kind}.schema.json"
            assert path.is_file(), f"missing {path}"
            payload = _read(f"actions/{action}.{kind}.schema.json")
            assert payload == schemas.SCHEMAS[action][kind]


def test_manifest_digests_match_files():
    manifest = _read("manifest.json")
    assert manifest["schema_version"] == "xcov.schema.v1"
    for action, kinds in manifest["actions"].items():
        for kind in ("request", "response"):
            path = SCHEMA_ROOT / "actions" / f"{action}.{kind}.schema.json"
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            assert digest == kinds[kind], f"digest mismatch for {action}.{kind}"
    for name, relative in (
        ("run_manifest", "internal/run_manifest.input.schema.json"),
        ("stdio_quit", "internal/stdio_quit.request.schema.json"),
    ):
        path = SCHEMA_ROOT / relative
        assert hashlib.sha256(path.read_bytes()).hexdigest() == manifest["internal"][name]


def test_missing_schema_data_raises_structured_error(monkeypatch):
    monkeypatch.setattr(schemas, "_SCHEMA_DATA_ROOT", Path("/nonexistent/xcov-schemas"))
    with pytest.raises(XcovError) as caught:
        schemas._read_schema_file("manifest.json")
    assert caught.value.code == "SCHEMA_DATA_MISSING"


def test_request_validation_accepts_canonical_minimal_request():
    schemas.validate_request(
        {
            "api_version": "xcov.v1",
            "request_id": "r1",
            "action": "session.open",
            "target": {"vdb": "merged.vdb"},
            "args": {"name": "cov0"},
        }
    )


def test_request_validation_rejects_unknown_field():
    with pytest.raises(XcovError) as caught:
        schemas.validate_request(
            {
                "api_version": "xcov.v1",
                "request_id": "r1",
                "action": "session.open",
                "target": {"vdb": "merged.vdb"},
                "args": {"name": "cov0", "reuse": True},
            }
        )
    assert caught.value.code == "SCHEMA_INVALID"
