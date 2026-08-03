from __future__ import annotations

from copy import deepcopy
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

from xentry.config import load_config_text, normalize_config
from xentry.contracts import ResponseContractError, validate_response
from xentry.decode import decode_entry
from xentry.errors import ConfigError, FragmentError, UnsupportedConfigField
from xentry.format import error_response, to_xout
from xentry.fragments import bytes_to_bits, parse_hex_bytes


CONFIG = {
    "name": "entry",
    "version": 1,
    "total_bits": 20,
    "fragment_byte_order": "msb_first",
    "bit_numbering": "byte_lsb0",
    "fields": [
        {"name": "opcode", "bits": "[3:0]"},
        {"name": "cross", "bits": "[15:8]"},
        {"name": "tail", "bits": "[19:16]"},
    ],
}


class ConfigTests(unittest.TestCase):
    def test_yaml_subset(self):
        cfg = load_config_text(
            """
name: entry
version: 1
total_bits: 8
fragment_byte_order: msb_first
bit_numbering: byte_lsb0
fields:
  - name: low
    bits: "[3:0]"
"""
        )
        config, warnings = normalize_config(cfg)
        self.assertEqual(config.name, "entry")
        self.assertEqual(config.fields[0].width, 4)
        self.assertEqual(warnings, [])

    def test_invalid_bits(self):
        cfg = dict(CONFIG)
        cfg["fields"] = [{"name": "bad", "bits": "[0:3]"}]
        with self.assertRaises(ConfigError):
            normalize_config(cfg)

    def test_unsupported_type(self):
        cfg = dict(CONFIG)
        cfg["fields"] = [{"name": "bad", "bits": "[0:0]", "type": "bool"}]
        with self.assertRaises(UnsupportedConfigField):
            normalize_config(cfg)

    def test_overlap_warning(self):
        cfg = dict(CONFIG)
        cfg["fields"] = [{"name": "a", "bits": "[3:0]"}, {"name": "b", "bits": "[2:1]"}]
        _, warnings = normalize_config(cfg)
        self.assertEqual(warnings[0]["code"], "FIELD_OVERLAP")


class FragmentTests(unittest.TestCase):
    def test_parse_hex_bytes(self):
        self.assertEqual(parse_hex_bytes("0x1122_33"), bytes.fromhex("112233"))
        self.assertEqual(parse_hex_bytes("11 22 33"), bytes.fromhex("112233"))
        with self.assertRaises(FragmentError):
            parse_hex_bytes("abc")

    def test_byte_order_and_numbering(self):
        self.assertEqual(bytes_to_bits(bytes.fromhex("80"), "lsb_first", "byte_lsb0")[7], 1)
        self.assertEqual(bytes_to_bits(bytes.fromhex("80"), "lsb_first", "byte_msb0")[0], 1)
        self.assertEqual(bytes_to_bits(bytes.fromhex("1234"), "msb_first", "byte_lsb0")[0], 0x34 & 1)
        self.assertEqual(bytes_to_bits(bytes.fromhex("1234"), "lsb_first", "byte_lsb0")[0], 0x12 & 1)

    def test_fragment_metadata_types_are_strict(self):
        base = {"seq": 0, "data": "0x12", "valid_lsb": 0, "valid_width": 8}
        config = {
            **CONFIG,
            "total_bits": 8,
            "fields": [{"name": "byte", "bits": "[7:0]"}],
        }
        for mutation in (
            {"entry_id": True},
            {"time": ""},
            {"source": 4},
            {"line": 0},
            {"tag": ""},
        ):
            with self.subTest(mutation=mutation):
                with self.assertRaises(FragmentError):
                    decode_entry(config, [{**base, **mutation}])


class DecodeTests(unittest.TestCase):
    def test_decode_cross_fragment(self):
        payload = decode_entry(
            CONFIG,
            [
                {"seq": 0, "data": "0x1234", "valid_lsb": 0, "valid_width": 12, "source": "a"},
                {"seq": 1, "data": "0xab", "valid_lsb": 0, "valid_width": 8, "source": "b"},
            ],
        )
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["entry_raw"], "0xab234")
        self.assertEqual(payload["fields"]["opcode"]["raw_hex"], "0x4")
        self.assertEqual(payload["fields"]["cross"]["source"][0]["seq"], 0)
        self.assertEqual(payload["fields"]["cross"]["source"][1]["seq"], 1)
        self.assertEqual(payload["fields"]["tail"]["raw_hex"], "0xa")

    def test_total_bits_mismatch(self):
        with self.assertRaises(FragmentError):
            decode_entry(CONFIG, [{"seq": 0, "data": "0x12", "valid_lsb": 0, "valid_width": 8}])

    def test_valid_range_overflow(self):
        with self.assertRaises(FragmentError):
            decode_entry(CONFIG, [{"seq": 0, "data": "0x12", "valid_lsb": 4, "valid_width": 9}])


class ContractTests(unittest.TestCase):
    def payload(self):
        return decode_entry(
            {
                **CONFIG,
                "total_bits": 8,
                "fields": [{"name": "byte", "bits": "[7:0]"}],
            },
            [{"seq": 0, "data": "0xaa", "valid_lsb": 0, "valid_width": 8}],
        )

    def test_nested_objects_are_closed(self):
        payload = self.payload()
        mutations = []
        for target, key, value in (
            ("envelope", "errors", []),
            ("field", "decoded", 0xAA),
            ("source", "fallback", True),
            ("schema", "revision", 1),
        ):
            mutated = deepcopy(payload)
            if target == "envelope":
                mutated[key] = value
            elif target == "field":
                mutated["fields"]["byte"][key] = value
            elif target == "source":
                mutated["fields"]["byte"]["source"][0][key] = value
            else:
                mutated["schema"][key] = value
            mutations.append(mutated)
        for mutated in mutations:
            with self.subTest(mutated=mutated):
                with self.assertRaises(ResponseContractError):
                    validate_response(mutated)
                with self.assertRaises(ResponseContractError):
                    to_xout(mutated)

    def test_cross_field_facts_are_bound(self):
        payload = self.payload()
        mutations = []
        changes = (
            ("bits", "[6:0]"),
            ("raw_bin", "10101011"),
            ("raw_hex", "0xab"),
        )
        for key, value in changes:
            mutated = deepcopy(payload)
            mutated["fields"]["byte"][key] = value
            mutations.append(mutated)
        mutated = deepcopy(payload)
        mutated["entry_raw"] = "0xab"
        mutations.append(mutated)
        mutated = deepcopy(payload)
        mutated["total_bits"] = 7
        mutations.append(mutated)
        mutated = deepcopy(payload)
        source = mutated["fields"]["byte"]["source"][0]
        source["entry_bits"] = "[6:0]"
        source["fragment_bits"] = "[6:0]"
        mutations.append(mutated)
        for mutated in mutations:
            with self.subTest(mutated=mutated):
                with self.assertRaises(ResponseContractError):
                    validate_response(mutated, expected_action="decode")

    def test_warning_error_and_expected_action_contracts(self):
        error = error_response(
            FragmentError("valid_width must be positive", seq=0, valid_width=0),
            action="decode",
        )
        validate_response(error, expected_action="decode")
        error["error"]["details"]["fallback"] = 1
        with self.assertRaises(ResponseContractError):
            validate_response(error, expected_action="decode")
        with self.assertRaises(ResponseContractError):
            validate_response(self.payload(), expected_action="explain")

    def test_xout_does_not_hide_long_values(self):
        config = deepcopy(CONFIG)
        config["total_bits"] = 8
        config["fields"] = [
            {"name": "a", "bits": "[3:0]"},
            {"name": "b", "bits": "[2:1]"},
        ]
        payload = decode_entry(
            config,
            [{"seq": 0, "data": "0xaa", "valid_lsb": 0, "valid_width": 8}],
        )
        message = "m" * 5000
        payload["warnings"][0]["message"] = message
        output = to_xout(payload)
        self.assertIn(message, output)
        self.assertNotIn("...", output)


class CliTests(unittest.TestCase):
    def run_cli_proc(self, *args, input_text=None, check=False):
        env = os.environ.copy()
        env["PYTHONPATH"] = str(SRC)
        return subprocess.run(
            [sys.executable, "-m", "xentry.cli", *args],
            cwd=str(ROOT),
            env=env,
            input=input_text,
            check=check,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

    def run_cli(self, *args, input_text=None):
        return json.loads(self.run_cli_proc(*args, input_text=input_text, check=True).stdout)

    def test_json_stdin(self):
        request = {"api_version": "xentry.v1", "action": "decode", "config": CONFIG, "fragments": [
            {"seq": 0, "data": "0x1234", "valid_lsb": 0, "valid_width": 12},
            {"seq": 1, "data": "0xab", "valid_lsb": 0, "valid_width": 8},
        ]}
        payload = self.run_cli("--json", "-", input_text=json.dumps(request))
        self.assertTrue(payload["ok"])

    def test_json_arg(self):
        request = {"api_version": "xentry.v1", "action": "explain", "config": CONFIG}
        payload = self.run_cli("--json", json.dumps(request))
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["action"], "explain")

    def test_json_file(self):
        request = {"api_version": "xentry.v1", "action": "validate", "config": CONFIG}
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False) as fh:
            json.dump(request, fh)
            path = fh.name
        try:
            payload = self.run_cli("--json", path)
            self.assertTrue(payload["ok"])
        finally:
            os.unlink(path)

    def test_xout_default(self):
        request = {"api_version": "xentry.v1", "action": "explain", "config": CONFIG}
        env = os.environ.copy()
        env["PYTHONPATH"] = str(SRC)
        proc = subprocess.run(
            [sys.executable, "-m", "xentry.cli", json.dumps(request)],
            cwd=str(ROOT),
            env=env,
            check=True,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        self.assertTrue(proc.stdout.startswith("@xentry.explain.v1"))

    def test_request_output_is_rejected(self):
        request = {
            "api_version": "xentry.v1",
            "action": "explain",
            "config": CONFIG,
            "output": {"format": "json"},
        }
        proc = self.run_cli_proc("--json", json.dumps(request))
        self.assertEqual(proc.returncode, 1)
        self.assertEqual(json.loads(proc.stdout)["error"]["code"], "INVALID_REQUEST")

    def test_retired_subcommands_and_aliases_are_rejected(self):
        request = json.dumps({"api_version": "xentry.v1", "action": "explain", "config": CONFIG})
        for invocation in (
            ("decode", "--config", "examples/entry.yaml"),
            ("--text", request),
            ("--xout", request),
            ("-help",),
        ):
            with self.subTest(invocation=invocation):
                self.assertEqual(self.run_cli_proc(*invocation).returncode, 2)

    def test_pretty_requires_json(self):
        request = json.dumps({"api_version": "xentry.v1", "action": "explain", "config": CONFIG})
        self.assertEqual(self.run_cli_proc("--pretty", request).returncode, 2)


if __name__ == "__main__":
    unittest.main()
