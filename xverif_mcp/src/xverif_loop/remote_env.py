"""Compute-node pre-exec verification for SDK-free LSF environments."""

from __future__ import annotations

import argparse
import json
import os
import sys

from xverif_loop.env_config import (
    ENV_FINGERPRINT_ENV,
    ENV_KEYS_ENV,
    VERIFIED_FINGERPRINT_ENV,
    observed_environment_fingerprint,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--protocol")
    parser.add_argument("command", nargs=argparse.REMAINDER)
    ns = parser.parse_args(argv)
    command = list(ns.command)
    if command and command[0] == "--":
        command.pop(0)
    if not command:
        print("LSF environment verifier received no command", file=sys.stderr)
        return 2
    expected = os.environ.get(ENV_FINGERPRINT_ENV)
    raw_keys = os.environ.get(ENV_KEYS_ENV, "")
    if expected is not None:
        observed = observed_environment_fingerprint(
            tuple(name for name in raw_keys.split(",") if name),
            os.environ,
        )
        if observed != expected:
            if ns.protocol:
                print(json.dumps({
                    "type": "ready",
                    "protocol": ns.protocol,
                    "version": 1,
                    "pid": os.getpid(),
                    "environment_fingerprint": observed,
                    "environment_verified": False,
                }, separators=(",", ":")), flush=True)
            else:
                print(
                    "LSF_ENV_MISMATCH: compute-node environment fingerprint differs",
                    file=sys.stderr,
                )
            return 79
        os.environ[VERIFIED_FINGERPRINT_ENV] = observed
    os.execvpe(command[0], command, dict(os.environ))
    return 127


if __name__ == "__main__":
    raise SystemExit(main())
