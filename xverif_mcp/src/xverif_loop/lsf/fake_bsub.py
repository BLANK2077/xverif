"""A small fake of ``bsub -I`` for local tests."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from typing import List, Optional


def _env_int(name: str, default: int = 0) -> int:
    try:
        return int(os.environ.get(name, str(default)))
    except ValueError:
        return default


def _split_command(argv: List[str]) -> List[str]:
    args = list(argv)
    # Consume -I / -Is flag
    if args and args[0] in ("-I", "-Is"):
        args.pop(0)
    while args and args[0].startswith("-"):
        if args[0] == "--":
            args.pop(0)
            break
        flag = args.pop(0)
        if flag in {"-q", "-R", "-J", "-env"} and args:
            args.pop(0)
    return args


def main(argv: Optional[List[str]] = None) -> int:
    raw_args = list(argv or sys.argv[1:])
    if os.environ.get("FAKE_BSUB_REQUIRE_ENV_ALL"):
        try:
            env_index = raw_args.index("-env")
        except ValueError:
            print("fake_bsub: missing -env all", file=sys.stderr)
            return 78
        if env_index + 1 >= len(raw_args) or raw_args[env_index + 1] != "all":
            print("fake_bsub: invalid -env contract", file=sys.stderr)
            return 78
    command = _split_command(raw_args)
    if not command:
        print("fake_bsub: missing command", file=sys.stderr)
        return 2

    if os.environ.get("FAKE_BSUB_STDOUT_NOISE_BEFORE_READY"):
        print("Job <123> is submitted to fake queue.", flush=True)
    if os.environ.get("FAKE_BSUB_SCHEDULER_FRAMING"):
        print("<<Waiting for dispatch ...>>", flush=True)

    delay_ms = _env_int("FAKE_BSUB_PENDING_DELAY_MS")
    if delay_ms > 0:
        time.sleep(delay_ms / 1000.0)

    if os.environ.get("FAKE_BSUB_SCHEDULER_FRAMING"):
        print("<<Starting on fake-host>>", flush=True)

    stderr_lines = _env_int("FAKE_BSUB_STDERR_LINES")
    for i in range(stderr_lines):
        print(f"fake_bsub stderr line {i}", file=sys.stderr, flush=True)

    if os.environ.get("FAKE_BSUB_EXIT_BEFORE_READY"):
        return 77

    child_env = dict(os.environ)
    drop_name = child_env.get("FAKE_BSUB_DROP_ENV")
    if drop_name:
        child_env.pop(drop_name, None)
    mutate_name = child_env.get("FAKE_BSUB_MUTATE_ENV")
    if mutate_name:
        child_env[mutate_name] = "fake-bsub-mutated"
    proc = subprocess.Popen(command, env=child_env)

    def _terminate_child(signum, frame):  # type: ignore[no-untyped-def]
        del frame
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=5)
        raise SystemExit(128 + int(signum))

    signal.signal(signal.SIGTERM, _terminate_child)
    signal.signal(signal.SIGINT, _terminate_child)
    kill_after = _env_int("FAKE_BSUB_KILL_CHILD_AFTER_MS")
    if kill_after > 0:
        time.sleep(kill_after / 1000.0)
        proc.kill()
    rc = proc.wait()
    if os.environ.get("FAKE_BSUB_EXIT_AFTER_READY"):
        return 88
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
