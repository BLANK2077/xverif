"""Canonical JSON-request CLI for xentry."""

from __future__ import annotations

import argparse
import json
import sys

from .api import dispatch_request
from .contracts import ACTIONS
from .errors import JsonError
from .format import dumps, error_response, to_xout


def emit(payload: dict, *, pretty: bool, json_mode: bool) -> int:
    if json_mode:
        print(dumps(payload, pretty=pretty))
    else:
        print(to_xout(payload), end="")
    return 0 if payload["ok"] else 1


def load_request_arg(arg: str) -> dict:
    if arg == "-":
        text = sys.stdin.read()
    elif arg.lstrip().startswith("{"):
        text = arg
    else:
        try:
            with open(arg, "r", encoding="utf-8") as source:
                text = source.read()
        except OSError as exc:
            raise JsonError(f"cannot read JSON request file: {arg}: {exc}") from exc
    try:
        request = json.loads(text)
    except json.JSONDecodeError as exc:
        raise JsonError(f"invalid JSON request: {exc}") from exc
    if not isinstance(request, dict):
        raise JsonError("JSON request must be an object")
    return request


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="xentry",
        allow_abbrev=False,
        description=(
            "deterministic multi-fragment entry decoder; accepts exactly one "
            "xentry.v1 JSON request"
        ),
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="emit the canonical response as JSON instead of XOUT",
    )
    parser.add_argument(
        "--pretty",
        action="store_true",
        help="pretty-print JSON; requires --json",
    )
    parser.add_argument(
        "request",
        nargs="?",
        default="-",
        help="JSON file, inline JSON object, or - for stdin",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    raw_argv = list(sys.argv[1:] if argv is None else argv)
    if "-help" in raw_argv:
        parser.error("unrecognized arguments: -help")
    args = parser.parse_args(raw_argv)
    if args.pretty and not args.json:
        parser.error("--pretty requires --json")

    request: dict | None = None
    try:
        request = load_request_arg(args.request)
        payload = dispatch_request(request)
    except Exception as exc:
        raw_action = request.get("action") if isinstance(request, dict) else None
        action = raw_action if raw_action in ACTIONS else "error"
        request_id = request.get("request_id") if isinstance(request, dict) else None
        payload = error_response(exc, action=action, request_id=request_id)
    return emit(payload, pretty=args.pretty, json_mode=args.json)


if __name__ == "__main__":
    sys.exit(main())
