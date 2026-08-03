#!/usr/bin/env python3

import argparse
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = ROOT.parents[3]


def query(binary, home, action, args=None, target=None, expect_ok=True):
    request = {"api_version": "xdebug.v1", "action": action, "args": args or {}}
    if target is not None:
        request["target"] = target
    env = os.environ.copy()
    env["HOME"] = str(home)
    proc = subprocess.run(
        [binary, "--json", "-"],
        input=json.dumps(request) + "\n",
        universal_newlines=True,
        cwd=str(REPO_ROOT),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        result = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise AssertionError(
            "{} returned non-JSON stdout: {!r}; stderr: {!r}".format(
                action, proc.stdout[:500], proc.stderr[:500]
            )
        ) from exc
    if expect_ok and (proc.returncode != 0 or not result.get("ok")):
        raise AssertionError("{} failed: {} {}".format(action, result, proc.stderr))
    if not expect_ok and result.get("ok"):
        raise AssertionError("{} unexpectedly passed".format(action))
    return result


def value_text(value):
    if isinstance(value, dict):
        value = value.get("value", "")
    text = str(value).lower()
    tick = text.find("'")
    if tick > 0 and text[:tick].isdigit():
        return text[tick:]
    return text


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def require_event_with_signals(events, expected):
    for event in events:
        signals = event.get("signals", {})
        if all(value_text(signals.get(name)) == value.lower()
               for name, value in expected.items()):
            return
    raise AssertionError("missing event with signals {} in {}".format(expected, events[:3]))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--xdebug", default=str(REPO_ROOT / "tools" / "xdebug"))
    parser.add_argument("--fsdb", default=str(ROOT / "out" / "waves" / "xif_event_multi_if_test.fsdb"))
    args = parser.parse_args()
    fsdb = Path(args.fsdb).resolve()
    if not fsdb.exists():
        raise RuntimeError("missing FSDB: {}".format(fsdb))

    home = Path(tempfile.mkdtemp(prefix="xdebug-event-check-"))
    session = "xif_event_check"
    try:
        query(args.xdebug, home, "session.open",
              {"name": session}, {"fsdb": str(fsdb)})
        configs = {
            "rdy": "event_rdy.json",
            "bp": "event_bp.json",
            "none": "event_none.json",
            "pair_master": "event_pair_master.json",
            "pair_slave": "event_pair_slave.json",
            "xz": "event_xz.json",
        }
        for name, config in configs.items():
            query(args.xdebug, home, "event.config.load",
                  {"name": name, "config_path": str(ROOT / config)},
                  {"session_id": session})

        def export(name, expr):
            return query(args.xdebug, home, "event.export",
                         {"name": name, "expr": expr},
                         {"session_id": session})["data"]["events"]

        matrix = [
            ("rdy", "vld && rdy", {"opcode": "'h5a", "channel": "'h3", "id": "'h2", "data": "'ha55a"}),
            ("rdy", "vld && rdy", {"opcode": "'h10", "channel": "'h1", "id": "'h1", "data": "'h1000"}),
            ("bp", "vld && !bp", {"opcode": "'hb2", "channel": "'h2", "id": "'h2", "data": "'h2002"}),
            ("bp", "vld && !bp", {"opcode": "'hb3", "channel": "'h3", "id": "'h3", "data": "'h2003"}),
            ("none", "vld", {"opcode": "'hc0", "channel": "'h0", "id": "'h1", "data": "'h3000"}),
            ("none", "vld", {"opcode": "'hc2", "channel": "'h2", "id": "'h3", "data": "'h3002"}),
            ("pair_master", "vld && rdy", {"opcode": "'hd0", "channel": "'h0", "id": "'h0", "data": "'h4000"}),
            ("pair_master", "vld && rdy", {"opcode": "'hd2", "channel": "'h2", "id": "'h2", "data": "'h4002"}),
            ("pair_slave", "vld && rdy", {"opcode": "'hd0", "channel": "'h0", "id": "'h0", "data": "'h4000"}),
            ("pair_slave", "vld && rdy", {"opcode": "'hd2", "channel": "'h2", "id": "'h2", "data": "'h4002"}),
        ]
        counts = {}
        for name, prefix, expected in matrix:
            expr = "{} && opcode == {} && channel == {} && id == {} && data == {}".format(
                prefix,
                expected["opcode"],
                expected["channel"],
                expected["id"],
                expected["data"],
            )
            events = export(name, expr)
            require(events, "{} direct pd field expression produced no events: {}".format(name, expr))
            require_event_with_signals(events, expected)
            counts[name] = counts.get(name, 0) + len(events)

        rdy_ge = export("rdy", "vld && rdy && opcode >= 8'h10 && data <= 16'h1002")
        require(rdy_ge, "direct pd field comparison expression failed")
        xz_events = export("xz", "vld && data != 0")
        require(not xz_events, "X/Z data expression should not become a known match")

        abnormal = query(args.xdebug, home, "signal.anomaly.inspect", {
            "signals": [
                "xif_event_top.if_rdy.pd.opcode",
                "xif_event_top.if_rdy.pd.data",
                "xif_event_top.if_pair_master.pd.opcode",
                "xif_event_top.xz_data",
            ],
            "time_range": {"begin": "0ns", "end": "200ns"},
            "checks": [
                {"type": "unknown_xz"},
                {"type": "stuck", "min_duration": "20ns"},
            ],
            "line_limit": 20,
        }, {"session_id": session})
        findings = abnormal["data"].get("findings", [])
        require(any(f.get("type") == "unknown_xz" and f.get("signal") == "xif_event_top.xz_data"
                    for f in findings), "signal.anomaly.inspect did not find xz_data unknown_xz")
        require(any(f.get("type") == "stuck" and f.get("signal") == "xif_event_top.if_rdy.pd.opcode"
                    for f in findings), "signal.anomaly.inspect did not scan direct struct member path")

        query(args.xdebug, home, "event.find",
              {"name": "rdy", "expr": "vld && missing_alias"},
              {"session_id": session}, expect_ok=False)
        print("PASS: xdebug event direct struct checks {} abnormal_findings={}".format(
            counts, len(findings)))
    finally:
        try:
            query(args.xdebug, home, "session.kill", target={"session_id": "all"})
        except Exception:
            pass
        shutil.rmtree(str(home), ignore_errors=True)


if __name__ == "__main__":
    main()
