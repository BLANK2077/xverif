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

from xbit.check import run_check
from xbit.errors import ParseError, ValueError2State, WidthError
from xbit.eval import eval_expr, parse_vars
from xbit.format import ResponseContractError, failure, success, to_xout, validate_response
from xbit.literal import parse_value
from xbit import ops


class LiteralTests(unittest.TestCase):
    def test_signed_hex(self):
        value = parse_value("8'shff")
        self.assertEqual(value.width, 8)
        self.assertTrue(value.signed)
        self.assertEqual(value.unsigned, 255)
        self.assertEqual(value.signed_value, -1)
        self.assertEqual(value.to_result()["hex"], "0xff")

    def test_negative_sized_decimal(self):
        value = parse_value("32'd-1")
        self.assertEqual(value.width, 32)
        self.assertEqual(value.unsigned, 0xFFFFFFFF)
        self.assertEqual(value.signed_value, -1)

    def test_2state_rejects_x(self):
        with self.assertRaises(ValueError2State):
            parse_value("4'b10xz")

    def test_4state_preserves_xz(self):
        value = parse_value("4'b10xz", state="4state")
        self.assertFalse(value.known)
        self.assertEqual(value.to_bin_digits(), "10xz")


class OpTests(unittest.TestCase):
    def test_slice(self):
        value = ops.slice_bits(parse_value("32'hdead_beef"), 15, 8)
        self.assertEqual(value.width, 8)
        self.assertEqual(value.unsigned, 0xBE)

    def test_concat_repeat(self):
        self.assertEqual(ops.concat([parse_value("4'ha"), parse_value("4'h5")]).unsigned, 0xA5)
        self.assertEqual(ops.repeat(4, parse_value("2'b10")).to_bin_digits(), "10101010")

    def test_resize_reverse_mask(self):
        self.assertEqual(ops.trunc(parse_value("16'h12ff"), 8).unsigned, 0xFF)
        self.assertEqual(ops.zext(parse_value("8'h80"), 16).unsigned, 0x80)
        self.assertEqual(ops.sext(parse_value("8'h80"), 16).unsigned, 0xFF80)
        self.assertEqual(ops.reverse_bits(parse_value("4'b1001")).to_bin_digits(), "1001")
        self.assertEqual(ops.mask(13).unsigned, 0x1FFF)

    def test_predicates_and_gray(self):
        self.assertEqual(ops.popcount(parse_value("32'hdead_beef")).unsigned, 24)
        self.assertTrue(ops.onehot(parse_value("8'h20")).truthy())
        self.assertTrue(ops.onehot0(parse_value("8'h00")).truthy())
        self.assertEqual(ops.gray2bin(parse_value("4'b1110")).unsigned, 11)
        self.assertEqual(ops.bin2gray(parse_value("4'b1011")).to_bin_digits(), "1110")

    def test_bad_slice(self):
        with self.assertRaises(WidthError):
            ops.slice_bits(parse_value("8'hff"), 15, 8)


class EvalTests(unittest.TestCase):
    def test_arithmetic_shift(self):
        result = eval_expr("8'shff >>> 1")
        self.assertEqual(result.width, 8)
        self.assertEqual(result.unsigned, 0xFF)
        self.assertEqual(result.signed_value, -1)

    def test_concat_repeat_eval(self):
        self.assertEqual(eval_expr("{4{2'b10}}").to_bin_digits(), "10101010")
        self.assertEqual(eval_expr("{4'hA, 4'h5}").unsigned, 0xA5)

    def test_slice_compare_with_var(self):
        result = eval_expr("data[15:8] == 8'hbe", parse_vars(["data=32'hdead_beef"]))
        self.assertTrue(result.truthy())

    def test_logic(self):
        result = eval_expr("valid && ready", parse_vars(["valid=1'b1", "ready=1'b0"]))
        self.assertFalse(result.truthy())

    def test_ternary_and_params(self):
        variables = parse_vars(["ADDR_W=32", "ID_W=4", "sel=1'b1"])
        self.assertEqual(eval_expr("ADDR_W + ID_W - 1", variables).unsigned, 35)
        self.assertEqual(eval_expr("sel ? 8'ha5 : 8'h00", variables).unsigned, 0xA5)

    def test_duplicate_variable_assignment_is_rejected(self):
        with self.assertRaises(ParseError):
            parse_vars(["data=8'h01", "data=8'h02"])


class CheckTests(unittest.TestCase):
    def test_check_vars(self):
        result = run_check(
            "valid && ready && data[15:8] == 8'hbe",
            var_items=["valid=1'b1", "ready=1'b1", "data=32'hdead_beef"],
        )
        self.assertTrue(result["matched"])
        self.assertIn("data", result["evaluated"])

    def test_check_values_file(self):
        payload = {"valid": "1'b1", "ready": "1'b1", "opcode": "4'ha"}
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False) as fh:
            json.dump(payload, fh)
            path = fh.name
        try:
            result = run_check("valid && ready && opcode == 4'ha", values_file=path)
            self.assertTrue(result["matched"])
        finally:
            os.unlink(path)

    def test_check_rejects_wrapped_values_and_multiple_sources(self):
        with self.assertRaises(ParseError):
            run_check("valid", values_payload={"values": {"valid": "1'b1"}})
        with self.assertRaises(ParseError):
            run_check("valid", var_items=["valid=1'b1"],
                      values_payload={"valid": "1'b1"})


class CliTests(unittest.TestCase):
    def run_cli(self, *args):
        env = os.environ.copy()
        env["PYTHONPATH"] = str(SRC)
        proc = subprocess.run(
            [sys.executable, "-m", "xbit.cli", *args],
            cwd=str(ROOT),
            env=env,
            check=True,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        return json.loads(proc.stdout)

    def test_conv_json(self):
        payload = self.run_cli("conv", "8'shff", "--json")
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["result"]["signed_value"], -1)

    def test_eval_json(self):
        payload = self.run_cli("eval", "data[15:8] == 8'hbe", "--var", "data=32'hdead_beef", "--json")
        self.assertTrue(payload["ok"])
        self.assertTrue(payload["result"]["bool"])

    def test_default_xout_is_token_efficient_domain_text(self):
        payload = success("conv", result=parse_value("8'h5a"))
        output = to_xout(payload)
        self.assertIn("  result: 8'h5a", output)
        self.assertIn("  unsigned: 90", output)
        self.assertNotIn("pointer\tkind\tvalue", output)

    def test_response_contract_rejects_unknown_or_contradictory_fields(self):
        payload = success("conv", result=parse_value("8'h5a"))
        unknown = deepcopy(payload)
        unknown["input"] = "8'h00"
        contradictory = deepcopy(payload)
        contradictory["result"]["hex"] = "0x00"
        for mutated in (unknown, contradictory):
            with self.assertRaises(ResponseContractError):
                validate_response(mutated)

    def test_error_contract_rejects_unknown_detail_fields(self):
        payload = failure(
            WidthError("slice range is invalid for value width",
                       msb=15, lsb=8, width=8),
            op="slice",
        )
        payload["error"]["details"]["fallback_value"] = 0
        with self.assertRaises(ResponseContractError):
            validate_response(payload)

    def test_agent_stdio(self):
        env = os.environ.copy()
        env["PYTHONPATH"] = str(SRC)
        request = {"id": 7, "method": "xbit.eval", "params": {"expr": "8'shff >>> 1"}}
        proc = subprocess.run(
            [sys.executable, "-m", "xbit.cli", "agent", "serve", "--stdio"],
            input=json.dumps(request) + "\n",
            cwd=str(ROOT),
            env=env,
            check=True,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["id"], 7)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["result"]["unsigned"], 255)


if __name__ == "__main__":
    unittest.main()
