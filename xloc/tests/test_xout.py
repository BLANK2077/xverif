from copy import deepcopy
import json
import os
import tempfile
import unittest

from xloc.resolver import context_payload, resolve_payload
from xloc.stats import render_stats, stats_payload
from xloc.xout import to_xout


class TestXout(unittest.TestCase):
    def test_stats_rows_use_compact_domain_columns(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            log_path = os.path.join(tmpdir, "sim.log")
            map_path = log_path + ".xloc.jsonl"
            open(log_path, "w", encoding="utf-8").write("L_00000001 " * 7)
            open(map_path, "w", encoding="utf-8").write('{"loc_id":"L_00000001","file":"tb/scoreboard.sv"}\n')
            output = render_stats(stats_payload(log_path, map_path))
        self.assertTrue(output.startswith("@xloc.stats.v1\n"))
        self.assertIn("L_00000001 7 resolved tb/scoreboard.sv", output)
        self.assertNotIn("pointer\tkind\tvalue", output)

    def test_context_preserves_full_source_text_and_validates_hit(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            source_path = os.path.join(tmpdir, "source.sv")
            map_path = os.path.join(tmpdir, "map.jsonl")
            open(source_path, "w", encoding="utf-8").write("first\n" + "x" * 5000 + "\nthird\n")
            open(map_path, "w", encoding="utf-8").write(json.dumps({"loc_id": "L_00000001", "file": source_path}) + "\n")
            payload = context_payload("L_00000001", map_path, 2, 1, 1)
            output = to_xout(payload)
        self.assertIn("> 2 " + "x" * 5000, output)
        mutated = deepcopy(payload)
        for row in mutated["context"]:
            row["hit"] = False
        with self.assertRaises(ValueError):
            to_xout(mutated)

    def test_public_response_contract_rejects_unknown_fields(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            map_path = os.path.join(tmpdir, "map.jsonl")
            open(map_path, "w", encoding="utf-8").write('{"loc_id":"L_00000001","file":"source.sv"}\n')
            payload = resolve_payload("L_00000001", map_path)
        payload["unexpected"] = True
        with self.assertRaisesRegex(ValueError, "unknown fields"):
            to_xout(payload)


if __name__ == "__main__":
    unittest.main()
