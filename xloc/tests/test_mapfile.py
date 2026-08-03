import json
import os
import tempfile
import unittest

from xloc.errors import XlocError
from xloc.mapfile import LOC_ID_RE, find_map_file, iter_loc_ids, load_map, resolve_loc


class TestLocIdRe(unittest.TestCase):
    def test_match_exact(self):
        self.assertIsNotNone(LOC_ID_RE.fullmatch("L_00000001"))
        self.assertIsNotNone(LOC_ID_RE.fullmatch("L_FFFFFFFF"))

    def test_no_match_invalid(self):
        for value in ("L_0000000", "L_0000000G", "L_00000001X", "XL_00000001", "X_00000001"):
            with self.subTest(value=value):
                self.assertIsNone(LOC_ID_RE.fullmatch(value))

    def test_find_in_text_rejects_invalid_token_prefixes(self):
        text = (
            "UVM_ERROR L_00000001 @ 100ns\n"
            "bad=L_00000002X embedded=XL_00000003\n"
            "UVM_WARNING L_00000004 @ 200ns\n"
        )
        self.assertEqual(list(iter_loc_ids(text)), ["L_00000001", "L_00000004"])


class TestMapFile(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.map_path = os.path.join(self.tmpdir.name, "test.xloc.jsonl")

    def tearDown(self):
        self.tmpdir.cleanup()

    def _write_jsonl(self, entries):
        with open(self.map_path, "w", encoding="utf-8") as stream:
            for entry in entries:
                stream.write(json.dumps(entry) + "\n")

    def assert_map_error(self, code, content, *, binary=False):
        mode = "wb" if binary else "w"
        kwargs = {} if binary else {"encoding": "utf-8"}
        with open(self.map_path, mode, **kwargs) as stream:
            stream.write(content)
        with self.assertRaises(XlocError) as raised:
            load_map(self.map_path)
        self.assertEqual(raised.exception.code, code)
        return raised.exception

    def test_empty_file_is_valid_empty_map(self):
        open(self.map_path, "w", encoding="utf-8").close()
        self.assertEqual(load_map(self.map_path), {})

    def test_missing_file_is_typed_failure(self):
        with self.assertRaises(XlocError) as raised:
            load_map(self.map_path)
        self.assertEqual(raised.exception.code, "MAP_FILE_NOT_FOUND")
        self.assertEqual(raised.exception.path, self.map_path)

    def test_load_and_resolve(self):
        self._write_jsonl([
            {"loc_id": "L_00000001", "file": "tb/scoreboard.sv"},
            {"loc_id": "L_00000002", "file": "tb/monitor.sv"},
        ])
        entries = load_map(self.map_path)
        self.assertEqual(len(entries), 2)
        self.assertEqual(resolve_loc(entries, "L_00000001"), {"loc_id": "L_00000001", "file": "tb/scoreboard.sv"})
        self.assertIsNone(resolve_loc(entries, "L_99999999"))

    def test_malformed_json_and_blank_lines_fail(self):
        error = self.assert_map_error("MAP_INVALID_JSON", 'not json\n{"loc_id":"L_00000001","file":"x.sv"}\n')
        self.assertEqual(error.line, 1)
        error = self.assert_map_error("MAP_INVALID_JSONL", '{"loc_id":"L_00000001","file":"x.sv"}\n\n')
        self.assertEqual(error.line, 2)

    def test_field_shape_and_types_are_closed(self):
        cases = [
            ("MAP_SCHEMA_VIOLATION", {"file": "x.sv"}),
            ("MAP_SCHEMA_VIOLATION", {"loc_id": "L_00000001", "file": "x.sv", "line": 1}),
            ("MAP_INVALID_LOC_ID", {"loc_id": 1, "file": "x.sv"}),
            ("MAP_INVALID_LOC_ID", {"loc_id": "L_0000000G", "file": "x.sv"}),
            ("MAP_INVALID_FILE", {"loc_id": "L_00000001", "file": ""}),
            ("MAP_INVALID_FILE", {"loc_id": "L_00000001", "file": "a\nb.sv"}),
            ("MAP_INVALID_FILE", {"loc_id": "L_00000001", "file": "a\tb.sv"}),
            ("MAP_INVALID_FILE", {"loc_id": "L_00000001", "file": "\ud800"}),
        ]
        for code, entry in cases:
            with self.subTest(code=code, entry=entry):
                self.assert_map_error(code, json.dumps(entry) + "\n")

    def test_non_object_record_fails(self):
        self.assert_map_error("MAP_INVALID_ENTRY", "[]\n")

    def test_duplicate_loc_id_fails_without_overwrite(self):
        error = self.assert_map_error(
            "MAP_DUPLICATE_LOC_ID",
            '{"loc_id":"L_00000001","file":"first.sv"}\n{"loc_id":"L_00000001","file":"second.sv"}\n',
        )
        self.assertEqual(error.line, 2)
        self.assertEqual(error.loc_id, "L_00000001")

    def test_duplicate_json_field_fails_without_last_value_wins(self):
        self.assert_map_error("MAP_DUPLICATE_FIELD", '{"loc_id":"L_00000001","loc_id":"L_00000002","file":"x.sv"}\n')

    def test_invalid_utf8_fails(self):
        self.assert_map_error("MAP_INVALID_UTF8", b'{"loc_id":"L_00000001","file":"\xff.sv"}\n', binary=True)

    def test_find_map_file_uses_only_canonical_sidecar(self):
        log = os.path.join(self.tmpdir.name, "sim.log")
        canonical = log + ".xloc.jsonl"
        open(canonical, "w", encoding="utf-8").close()
        self.assertEqual(find_map_file(log), canonical)
        os.unlink(canonical)
        open(log + ".map", "w", encoding="utf-8").close()
        self.assertIsNone(find_map_file(log))


if __name__ == "__main__":
    unittest.main()
