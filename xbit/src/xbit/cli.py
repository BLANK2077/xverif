from __future__ import annotations

import argparse
import sys

from . import ops
from .bitvector import BitVector
from .check import run_check
from .errors import XbitError
from .eval import eval_expr, parse_vars
from .format import dumps, failure, success, to_xout, validate_response
from .literal import parse_value


def _state(value: str) -> str:
    if value == "2":
        return "2state"
    if value == "4":
        return "4state"
    raise argparse.ArgumentTypeError("--state must be 2 or 4")


def add_common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--json", action="store_true", help="emit xbit.result.v1 JSON")
    parser.add_argument("--pretty", action="store_true", help="pretty-print JSON")
    parser.add_argument("--state", type=_state, default="2", help="2 or 4; default: 2")


def add_value_common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--width", type=int, help="resize result to N bits")
    sign = parser.add_mutually_exclusive_group()
    sign.add_argument("--signed", dest="signed", action="store_true", default=None)
    sign.add_argument("--unsigned", dest="signed", action="store_false")


def emit(payload: dict, *, json_mode: bool, pretty: bool) -> int:
    validate_response(payload)
    if json_mode:
        print(dumps(payload, pretty=pretty))
    else:
        print(to_xout(payload), end="")
    return 0 if payload.get("ok") else 1


def parse_input(value: str, args: argparse.Namespace) -> BitVector:
    parsed = parse_value(value, state=args.state)
    if getattr(args, "width", None) is not None:
        parsed = parsed.resize(args.width, signed_extend=bool(getattr(args, "signed", False)))
    if getattr(args, "signed", None) is not None:
        parsed = parsed.with_signed(args.signed)
    return parsed


def cmd_conv(args: argparse.Namespace) -> dict:
    return success("conv", result=parse_input(args.value, args))


def cmd_eval(args: argparse.Namespace) -> dict:
    variables = parse_vars(args.var, state=args.state)
    result = eval_expr(args.expr, variables, state=args.state, width=args.width, signed=args.signed)
    return success("eval", result=result)


def cmd_slice(args: argparse.Namespace) -> dict:
    value = parse_value(args.value, state=args.state)
    return success("slice", result=ops.slice_bits(value, args.msb, args.lsb))


def cmd_index(args: argparse.Namespace) -> dict:
    value = parse_value(args.value, state=args.state)
    return success("index", result=ops.index_bit(value, args.bit))


def cmd_concat(args: argparse.Namespace) -> dict:
    values = [parse_value(v, state=args.state) for v in args.values]
    return success("concat", result=ops.concat(values))


def cmd_repeat(args: argparse.Namespace) -> dict:
    return success("repeat", result=ops.repeat(args.count, parse_value(args.value, state=args.state)))


def cmd_resize(args: argparse.Namespace) -> dict:
    value = parse_value(args.value, state=args.state)
    fn = {"trunc": ops.trunc, "zext": ops.zext, "sext": ops.sext}[args.command]
    return success(args.command, result=fn(value, args.to))


def cmd_reverse(args: argparse.Namespace) -> dict:
    return success("reverse", result=ops.reverse_bits(parse_value(args.value, state=args.state)))


def cmd_mask(args: argparse.Namespace) -> dict:
    return success("mask", result=ops.mask(args.width, args.lsb))


def cmd_align(args: argparse.Namespace) -> dict:
    return success("align", result=ops.align(parse_value(args.value, state=args.state), args.to))


def cmd_unary_op(args: argparse.Namespace) -> dict:
    value = parse_value(args.value, state=args.state)
    fn = {
        "popcount": ops.popcount,
        "onehot": ops.onehot,
        "onehot0": ops.onehot0,
        "gray2bin": ops.gray2bin,
        "bin2gray": ops.bin2gray,
    }[args.command]
    result = fn(value)
    return success(args.command, result=result)


def cmd_check(args: argparse.Namespace) -> dict:
    result = run_check(args.expr, var_items=args.var, values_file=args.values, state=args.state)
    return success("check", result=result["result"], matched=result["matched"], evaluated=result["evaluated"])


def cmd_agent(args: argparse.Namespace) -> int:
    from .agent.stdio import serve

    return serve()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="xbit", description="deterministic bit/value/expression calculator")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("conv")
    add_common(p)
    add_value_common(p)
    p.add_argument("value")
    p.set_defaults(func=cmd_conv)

    p = sub.add_parser("eval")
    add_common(p)
    add_value_common(p)
    p.add_argument("expr")
    p.add_argument("--var", action="append", default=[])
    p.set_defaults(func=cmd_eval)

    p = sub.add_parser("slice")
    add_common(p)
    p.add_argument("value")
    p.add_argument("msb", type=int)
    p.add_argument("lsb", type=int)
    p.set_defaults(func=cmd_slice)

    p = sub.add_parser("index")
    add_common(p)
    p.add_argument("value")
    p.add_argument("bit", type=int)
    p.set_defaults(func=cmd_index)

    p = sub.add_parser("concat")
    add_common(p)
    p.add_argument("values", nargs="+")
    p.set_defaults(func=cmd_concat)

    p = sub.add_parser("repeat")
    add_common(p)
    p.add_argument("count", type=int)
    p.add_argument("value")
    p.set_defaults(func=cmd_repeat)

    for name in ("trunc", "zext", "sext"):
        p = sub.add_parser(name)
        add_common(p)
        p.add_argument("value")
        p.add_argument("--to", type=int, required=True)
        p.set_defaults(func=cmd_resize)

    p = sub.add_parser("reverse")
    add_common(p)
    p.add_argument("value")
    p.set_defaults(func=cmd_reverse)

    p = sub.add_parser("mask")
    add_common(p)
    p.add_argument("--width", type=int, required=True)
    p.add_argument("--lsb", type=int, default=0)
    p.set_defaults(func=cmd_mask)

    p = sub.add_parser("align")
    add_common(p)
    p.add_argument("value")
    p.add_argument("--to", type=int, required=True)
    p.set_defaults(func=cmd_align)

    for name in ("popcount", "onehot", "onehot0", "gray2bin", "bin2gray"):
        p = sub.add_parser(name)
        add_common(p)
        p.add_argument("value")
        p.set_defaults(func=cmd_unary_op)

    p = sub.add_parser("check")
    add_common(p)
    p.add_argument("--expr", required=True)
    check_values = p.add_mutually_exclusive_group()
    check_values.add_argument("--var", action="append", default=[])
    check_values.add_argument("--values")
    p.set_defaults(func=cmd_check)

    p = sub.add_parser("agent")
    agent_sub = p.add_subparsers(dest="agent_command", required=True)
    serve_parser = agent_sub.add_parser("serve")
    serve_parser.add_argument("--stdio", action="store_true", required=True)
    serve_parser.set_defaults(func=cmd_agent)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        result = args.func(args)
        if isinstance(result, int):
            return result
        return emit(result, json_mode=getattr(args, "json", False), pretty=getattr(args, "pretty", False))
    except Exception as exc:
        return emit(failure(exc, op=getattr(args, "command", None)), json_mode=getattr(args, "json", False), pretty=getattr(args, "pretty", False))


if __name__ == "__main__":
    sys.exit(main())
