import json
import os
import tempfile
import unittest
from io import StringIO
from unittest.mock import patch

from xloc.resolver import cmd_context, cmd_resolve, context_payload, resolve_payload


class TestResolver(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.source_path = os.path.join(self.tmpdir.name, "scoreboard.sv")
        with open(self.source_path, "w", encoding="utf-8", newline="") as stream:
            stream.write("first  \nsecond\t \nthird\n")
        self.map_path = os.path.join(self.tmpdir.name, "test.xloc.jsonl")
        with open(self.map_path, "w", encoding="utf-8") as stream:
            stream.write(json.dumps({"loc_id": "L_00000001", "file": self.source_path}) + "\n")

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_resolve_found_has_strict_completeness(self):
        payload = resolve_payload("L_00000001", self.map_path)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["status"], "complete")
        self.assertTrue(payload["scan_complete"])
        self.assertTrue(payload["analysis_complete"])
        self.assertFalse(payload["response_truncated"])
        self.assertEqual(payload["total_count"], 1)
        self.assertEqual(payload["returned_count"], 1)
        self.assertEqual(payload["diagnostics"], [])

    def test_resolve_not_found_is_typed_xout_failure(self):
        out = StringIO()
        with patch("sys.stdout", out):
            self.assertEqual(cmd_resolve("L_99999999", self.map_path), 1)
        self.assertIn("code: LOC_ID_NOT_FOUND", out.getvalue())
        self.assertIn("L_99999999", out.getvalue())

    def test_invalid_loc_id_is_rejected_before_lookup(self):
        payload = resolve_payload("L_0000000G", self.map_path)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"]["code"], "INVALID_LOC_ID")

    def test_corrupt_map_is_typed_failure(self):
        with open(self.map_path, "w", encoding="utf-8") as stream:
            stream.write("bad json\n")
        payload = resolve_payload("L_00000001", self.map_path)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"]["code"], "MAP_INVALID_JSON")

    def test_context_preserves_source_text_and_marks_hit(self):
        payload = context_payload("L_00000001", self.map_path, line=2, before=1, after=1)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["context"], [
            {"line": 1, "hit": False, "text": "first  "},
            {"line": 2, "hit": True, "text": "second\t "},
            {"line": 3, "hit": False, "text": "third"},
        ])
        self.assertEqual(payload["total_count"], 3)
        self.assertEqual(payload["returned_count"], 3)

    def test_context_missing_source_is_failure_not_warning_success(self):
        os.unlink(self.source_path)
        payload = context_payload("L_00000001", self.map_path, 2)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"]["code"], "SOURCE_FILE_NOT_FOUND")

    def test_context_out_of_range_is_failure(self):
        payload = context_payload("L_00000001", self.map_path, 20)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"]["code"], "SOURCE_LINE_OUT_OF_RANGE")
        self.assertEqual(payload["diagnostics"][0]["count"], 3)

    def test_context_rejects_invalid_window(self):
        for line, before, after, code in ((0, 1, 1, "INVALID_LINE"), (1, -1, 1, "INVALID_ARGUMENT"), (1, 1, -1, "INVALID_ARGUMENT")):
            with self.subTest(line=line, before=before, after=after):
                payload = context_payload("L_00000001", self.map_path, line, before, after)
                self.assertFalse(payload["ok"])
                self.assertEqual(payload["error"]["code"], code)

    def test_cmd_context_returns_failure_code_and_canonical_xout(self):
        out = StringIO()
        with patch("sys.stdout", out):
            self.assertEqual(cmd_context("L_99999999", self.map_path, 2), 1)
        self.assertIn("code: LOC_ID_NOT_FOUND", out.getvalue())


if __name__ == "__main__":
    unittest.main()
