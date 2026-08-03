import os
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from xloc.annotate import annotate_payload, render_raw
from xloc.errors import XlocError
from xloc.stats import stats_payload


class TestStatsAndAnnotate(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.log_path = os.path.join(self.tmpdir.name, "sim.log")
        self.map_path = self.log_path + ".xloc.jsonl"

    def tearDown(self):
        self.tmpdir.cleanup()

    def _write_log(self, text):
        with open(self.log_path, "w", encoding="utf-8", newline="") as stream:
            stream.write(text)

    def _write_map(self, text):
        with open(self.map_path, "w", encoding="utf-8") as stream:
            stream.write(text)

    def test_stats_uses_only_python_scanner_and_deterministic_ties(self):
        self._write_log("L_00000002 L_00000001\nL_00000001 L_00000002\nL_00000003\n")
        self._write_map(
            '{"loc_id":"L_00000001","file":"one.sv"}\n'
            '{"loc_id":"L_00000002","file":"two.sv"}\n'
            '{"loc_id":"L_00000003","file":"three.sv"}\n'
        )
        with patch.object(subprocess, "run", side_effect=AssertionError("external scanner must not run")):
            payload = stats_payload(self.log_path, self.map_path)
        self.assertEqual([row["loc_id"] for row in payload["rows"]], ["L_00000001", "L_00000002", "L_00000003"])
        self.assertEqual(payload["total_occurrence_count"], 5)

    def test_stats_top_is_explicit_response_truncation(self):
        self._write_log("L_00000001 L_00000002 L_00000003\n")
        self._write_map(
            '{"loc_id":"L_00000001","file":"one.sv"}\n'
            '{"loc_id":"L_00000002","file":"two.sv"}\n'
            '{"loc_id":"L_00000003","file":"three.sv"}\n'
        )
        payload = stats_payload(self.log_path, self.map_path, top=2)
        self.assertEqual(payload["status"], "partial")
        self.assertTrue(payload["analysis_complete"])
        self.assertTrue(payload["response_truncated"])
        self.assertEqual(payload["truncation_scopes"], ["rows"])

    def test_missing_optional_map_is_explicit_partial_not_fake_file(self):
        self._write_log("L_00000001 L_00000001\n")
        payload = stats_payload(self.log_path)
        self.assertTrue(payload["ok"])
        self.assertFalse(payload["analysis_complete"])
        self.assertEqual(payload["rows"], [{"loc_id": "L_00000001", "count": 2, "resolution_status": "unresolved"}])
        self.assertNotIn("?", str(payload))
        self.assertEqual(payload["diagnostics"][0]["code"], "MAP_UNAVAILABLE")

    def test_explicit_missing_or_corrupt_map_fails(self):
        self._write_log("L_00000001\n")
        missing = stats_payload(self.log_path, os.path.join(self.tmpdir.name, "missing.jsonl"))
        self.assertEqual(missing["error"]["code"], "MAP_FILE_NOT_FOUND")
        self._write_map("bad json\n")
        self.assertEqual(stats_payload(self.log_path)["error"]["code"], "MAP_INVALID_JSON")

    def test_invalid_log_encoding_fails_instead_of_replacing_text(self):
        with open(self.log_path, "wb") as stream:
            stream.write(b"L_00000001 \xff\n")
        self.assertEqual(stats_payload(self.log_path)["error"]["code"], "LOG_INVALID_UTF8")

    def test_annotate_does_not_insert_unresolved_placeholder(self):
        self._write_log("UVM_ERROR L_00000001(2)\nUVM_ERROR L_00000002(3)\n")
        self._write_map('{"loc_id":"L_00000001","file":"one.sv"}\n')
        payload = annotate_payload(self.log_path, self.map_path)
        self.assertEqual(payload["status"], "partial")
        self.assertNotIn("?", "".join(payload["lines"]))
        with self.assertRaises(XlocError) as raised:
            render_raw(payload)
        self.assertEqual(raised.exception.code, "RAW_OUTPUT_INCOMPLETE")

    def test_annotate_preserves_crlf(self):
        self._write_log("UVM_ERROR L_00000001(2)\r\n")
        self._write_map('{"loc_id":"L_00000001","file":"one.sv"}\n')
        payload = annotate_payload(self.log_path, self.map_path)
        self.assertEqual(payload["lines"][0], "[loc] L_00000001 -> one.sv\r\n")


if __name__ == "__main__":
    unittest.main()
