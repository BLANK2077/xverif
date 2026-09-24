from __future__ import annotations

from copy import deepcopy
import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

from xbit.check import run_check
from xbit.errors import DivisionByZero, ParseError, ValueError2State, WidthError
from xbit.eval import parse_vars
from xbit.format import ResponseContractError, failure, success, to_xout, validate_response
from xbit.agent.stdio import validate_wrapped_response, wrap_response
from xbit.literal import parse_value
from xbit import ops


class LiteralTests(unittest.TestCase):
    def test_2state_rejects_x(self):
        with self.assertRaises(ValueError2State):
            parse_value("4'b10xz")


class OpTests(unittest.TestCase):
    def test_bad_slice(self):
        with self.assertRaises(WidthError):
            ops.slice_bits(parse_value("8'hff"), 15, 8)

    def test_division_by_zero_is_typed_for_divide_and_modulo(self):
        for op in ("/", "%"):
            with self.assertRaises(DivisionByZero):
                ops.binary_arithmetic(op, parse_value("64'd1"), parse_value("64'd0"))


class EvalTests(unittest.TestCase):
    def test_duplicate_variable_assignment_is_rejected(self):
        with self.assertRaises(ParseError):
            parse_vars(["data=8'h01", "data=8'h02"])


class CheckTests(unittest.TestCase):
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

    def test_response_contract_rejects_cross_field_contradictions(self):
        known = success("conv", result=parse_value("8'h5a"))
        check = success(
            "check",
            result=parse_value("1'b1"),
            matched=True,
            evaluated={"ready": "1'b1"},
        )
        unknown = success("conv", result=parse_value("4'b10xz", state="4state"))
        mutations = []
        bad_signed = deepcopy(known)
        bad_signed["result"]["signed_value"] = True
        mutations.append(bad_signed)
        too_wide = deepcopy(known)
        too_wide["result"]["unsigned"] = 0x15A
        mutations.append(too_wide)
        mismatched = deepcopy(check)
        mismatched["matched"] = False
        mutations.append(mismatched)
        oversized_mask = deepcopy(unknown)
        oversized_mask["result"]["x_mask"] = "0x12"
        mutations.append(oversized_mask)
        for mutated in mutations:
            with self.subTest(mutated=mutated):
                with self.assertRaises(ResponseContractError):
                    validate_response(mutated)

    def test_error_expected_op_and_stdio_correlation_are_strict(self):
        payload = failure(WidthError("bad width", width=8), op="slice")
        with self.assertRaises(ResponseContractError):
            validate_response(payload, expected_op="conv")

        request = {"id": 7, "jsonrpc": "2.0"}
        response = wrap_response(request, success("conv", result=parse_value("8'h5a")))
        validate_wrapped_response(request, response)
        wrong_id = deepcopy(response)
        wrong_id["id"] = 8
        with self.assertRaises(Exception):
            validate_wrapped_response(request, wrong_id)
        missing_jsonrpc = deepcopy(response)
        del missing_jsonrpc["jsonrpc"]
        with self.assertRaises(Exception):
            validate_wrapped_response(request, missing_jsonrpc)

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
