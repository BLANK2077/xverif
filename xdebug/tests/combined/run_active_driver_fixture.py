#!/usr/bin/env python3
"""Live combined regression tests for trace.active_driver.

Requires pre-published fixtures and an available NPI runtime.

This is an internal leaf runner; invoke it through the catalog pytest suite.
"""

import json
import os
import subprocess
import sys
import atexit
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
TESTS_ROOT = REPO_ROOT / "xdebug" / "tests"
if str(TESTS_ROOT) not in sys.path:
    sys.path.insert(0, str(TESTS_ROOT))

from runner import StdioLoopRunner

# When run via "make -C xdebug combined-test", CWD is the xdebug directory
_XDEBUG_CANDIDATES = [
    os.environ.get("XDEBUG", ""),
    str(Path.cwd() / "xdebug"),           # CWD = xdebug/
    str(REPO_ROOT / "tools" / "xdebug"),   # repo root tools/
    str(REPO_ROOT / "xdebug" / "xdebug"),   # xdebug/xdebug binary
]
XDEBUG = next((c for c in _XDEBUG_CANDIDATES if c and Path(c).is_file()), "xdebug")

ACTIVE_DRIVER_DIR = Path(
    os.environ.get(
        "XDEBUG_ACTIVE_DRIVER_FIXTURE_DIR",
        str(
            Path(__file__).resolve().parent.parent.parent
            / "testdata"
            / "combined"
            / "active_driver"
        ),
    )
)
IF_PORT_ROOT_DIR = Path(
    os.environ.get(
        "XDEBUG_INTERFACE_PORT_ROOT_FIXTURE_DIR",
        str(
            Path(__file__).resolve().parent.parent.parent
            / "testdata"
            / "combined"
            / "interface_port_root"
        ),
    )
)

ACTIVE_DRIVER_DAIDIR = str(ACTIVE_DRIVER_DIR / "out" / "simv.daidir")
ACTIVE_DRIVER_FSDB = str(ACTIVE_DRIVER_DIR / "out" / "waves.fsdb")
IF_PORT_ROOT_DAIDIR = str(IF_PORT_ROOT_DIR / "out" / "simv.daidir")
IF_PORT_ROOT_FSDB = str(IF_PORT_ROOT_DIR / "out" / "waves.fsdb")

failed = 0
passed = 0
skipped = 0
opened_sessions = []
stdio_loop = None


def _has_license_issue(output: str) -> bool:
    """Check if output contains license-related errors."""
    lower = output.lower()
    return any(phrase in lower for phrase in [
        "npi_init_failed",
        "failed to check out license",
        "license checkout failed",
        "npi initialization failed",
        "cannot check out license",
        "npi_init failed",
    ])


def run_xdebug(request_body: str) -> "tuple[int, str]":
    """Use one persistent JSON frontend and return CLI-compatible output."""
    global stdio_loop
    if stdio_loop is None:
        stdio_loop = StdioLoopRunner(
            Path(XDEBUG),
            cwd=REPO_ROOT,
            default_json=True,
            wait_for_stderr_idle=False,
        )
        stdio_loop.start()
    request = json.loads(request_body)
    result = stdio_loop.request(request, timeout_sec=120)
    output = (
        json.dumps(result.response, indent=2)
        if isinstance(result.response, dict)
        else result.stdout_raw
    )
    if result.stderr_raw:
        output += "\n" + result.stderr_raw
    return result.returncode, output


def cleanup_opened_sessions():
    global stdio_loop
    for session_id in reversed(opened_sessions):
        req = json.dumps({
            "api_version": "xdebug.v1",
            "action": "session.kill",
            "target": {"session_id": session_id},
        })
        try:
            run_xdebug(req)
        except Exception:
            pass
    if stdio_loop is not None:
        try:
            stdio_loop.quit()
        finally:
            stdio_loop.terminate()
            stdio_loop = None


atexit.register(cleanup_opened_sessions)


def open_session(name: str, daidir: str, fsdb: str) -> "tuple[str, str]":
    """Open a session, returns (session_id, error_message or "")."""
    req = json.dumps({
        "api_version": "xdebug.v1",
        "action": "session.open",
        "target": {"daidir": daidir, "fsdb": fsdb},
        "args": {"name": name},
    })
    _, out = run_xdebug(req)

    if _has_license_issue(out):
        return name, out

    # Try to extract the last complete JSON object from the output.
    # xdebug --json emits pretty-printed JSON that starts at a top-level '{'.
    # Use bracket matching to find the corresponding '}'.
    resp = None
    stripped = out.strip()
    # Find the first '{' that starts the main JSON response
    start = stripped.find("{")
    if start >= 0:
        # Bracket-match to find the matching closing '}'
        depth = 0
        end = -1
        for i in range(start, len(stripped)):
            if stripped[i] == "{":
                depth += 1
            elif stripped[i] == "}":
                depth -= 1
                if depth == 0:
                    end = i
                    break
        if end >= 0:
            try:
                candidate = json.loads(stripped[start:end + 1])
                if isinstance(candidate, dict) and "api_version" in candidate:
                    resp = candidate
            except (json.JSONDecodeError, ValueError):
                pass

    if resp is None:
        return name, out

    if not resp.get("ok"):
        err = resp.get("error", {})
        return name, err.get("code", "UNKNOWN") + ": " + err.get("message", str(resp))

    # Extract the canonical public session identifier.
    session = resp.get("session", {}) or resp.get("data", {}).get("session", {})
    sid = session.get("session_id")
    if not isinstance(sid, str) or not sid:
        return name, "session.open response missing canonical session_id"
    return sid, ""


def do_active_driver(session_id: str, signal: str, requested_time: str,
                     extra_args: dict = None,
                     limits: dict = None) -> "tuple[int, str, dict]":
    """Run trace.active_driver, returns (rc, raw_output, json_response)."""
    args = {
        "signal": signal,
        "time": requested_time,
    }
    if extra_args:
        args.update(extra_args)
    request = {
        "api_version": "xdebug.v1",
        "action": "trace.active_driver",
        "target": {"session_id": session_id},
        "args": args,
    }
    if limits is not None:
        request["limits"] = limits
    rc, out = run_xdebug(json.dumps(request))
    resp = None
    # Bracket-match to extract the outermost JSON object
    stripped = out.strip()
    start = stripped.find("{")
    if start >= 0:
        depth = 0
        end = -1
        for i in range(start, len(stripped)):
            if stripped[i] == "{":
                depth += 1
            elif stripped[i] == "}":
                depth -= 1
                if depth == 0:
                    end = i
                    break
        if end >= 0:
            try:
                candidate = json.loads(stripped[start:end + 1])
                if isinstance(candidate, dict) and "api_version" in candidate:
                    resp = candidate
            except (json.JSONDecodeError, ValueError):
                pass
    if resp is None:
        return rc, out, {}
    return rc, out, resp


def do_scope_list(session_id: str, args: dict) -> "tuple[int, str, dict]":
    """Run scope.list, returns (rc, raw_output, json_response)."""
    request = {
        "api_version": "xdebug.v1",
        "action": "scope.list",
        "target": {"session_id": session_id},
        "args": args,
    }
    rc, out = run_xdebug(json.dumps(request))
    stripped = out.strip()
    start = stripped.find("{")
    if start < 0:
        return rc, out, {}
    depth = 0
    for index in range(start, len(stripped)):
        if stripped[index] == "{":
            depth += 1
        elif stripped[index] == "}":
            depth -= 1
            if depth == 0:
                try:
                    response = json.loads(stripped[start:index + 1])
                except (json.JSONDecodeError, ValueError):
                    return rc, out, {}
                return rc, out, response if isinstance(response, dict) else {}
    return rc, out, {}


def check_interface_is_signal(session_id: str):
    """Verify interface instances/ports are classified without expansion."""
    global failed, passed
    rc, raw, response = do_scope_list(
        session_id,
        {
            "path": "if_root_tb",
            "level": 0,
            "kind": "signal",
            "include_patterns": ["link", "link.*"],
        },
    )
    if rc != 0 or response.get("ok") is not True:
        print(f"FAIL: scope_list_interface_signal — request failed: {raw[-500:]}")
        failed += 1
        return
    signals = response.get("data", {}).get("signals", [])
    if signals != [{"name": "link", "width": None}]:
        print(
            "FAIL: scope_list_interface_signal — expected one unexpanded "
            f"interface signal, got {signals}"
        )
        failed += 1
        return
    if response.get("data", {}).get("modules") or response.get("data", {}).get("ports"):
        print("FAIL: scope_list_interface_signal — kind filter leaked another category")
        failed += 1
        return

    rc, raw, response = do_scope_list(
        session_id,
        {
            "path": "if_root_tb",
            "level": 1,
            "kind": "port",
            "include_patterns": ["u_src.bus", "u_src.bus.*"],
        },
    )
    if rc != 0 or response.get("ok") is not True:
        print(f"FAIL: scope_list_interface_port — request failed: {raw[-500:]}")
        failed += 1
        return
    ports = response.get("data", {}).get("ports", [])
    if ports != [
        {"name": "u_src.bus", "direction": "interface", "width": None}
    ]:
        print(
            "FAIL: scope_list_interface_port — expected direction=interface, "
            f"got {ports}"
        )
        failed += 1
        return
    print("PASS: scope_list_interface_signal")
    passed += 1


def check(name: str, session_id: str, signal: str, requested_time: str,
          checks: list, extra_args: dict = None, limits: dict = None):
    """Run a check case. Each check is a callable(resp, raw) -> bool."""
    global failed, passed
    rc, raw, resp = do_active_driver(
        session_id,
        signal,
        requested_time,
        extra_args,
        limits,
    )
    if not resp:
        print(f"FAIL: {name} — no JSON response")
        print(f"  raw output (last 500 chars): {raw[-500:]}")
        failed += 1
        return

    if not resp.get("ok", False):
        err = resp.get("error", {})
        print(f"FAIL: {name} — request failed: {err}")
        failed += 1
        return

    all_ok = True
    for check_fn in checks:
        ok, msg = check_fn(resp, raw)
        if not ok:
            print(f"FAIL: {name} — {msg}")
            all_ok = False

    if all_ok:
        print(f"PASS: {name}")
        passed += 1
    else:
        failed += 1


# ─── check helpers ───────────────────────────────────────────────────────────

def has_field(path: str, expected=None):
    """Check that resp has a field at dotted path, optionally matching value."""
    def fn(resp, raw):
        obj = resp
        for key in path.split("."):
            if isinstance(obj, dict) and key in obj:
                obj = obj[key]
            else:
                return False, f"missing field '{path}'"
        if expected is not None:
            if obj != expected:
                return False, f"field '{path}' is {json.dumps(obj)}, expected {json.dumps(expected)}"
        return True, ""
    return fn


def field_equals(path: str, expected):
    return has_field(path, expected)


def field_contains(path: str, substring: str):
    def fn(resp, raw):
        obj = resp
        for key in path.split("."):
            if isinstance(obj, dict) and key in obj:
                obj = obj[key]
            else:
                return False, f"missing field '{path}'"
        if not isinstance(obj, str) or substring not in obj:
            return False, f"field '{path}'='{obj}' does not contain '{substring}'"
        return True, ""
    return fn


def field_not_present(path: str):
    def fn(resp, raw):
        parts = path.split(".")
        obj = resp
        for i, key in enumerate(parts[:-1]):
            if isinstance(obj, dict) and key in obj:
                obj = obj[key]
            else:
                return True, ""  # parent missing, ok
        if isinstance(obj, dict) and parts[-1] in obj:
            return False, f"field '{path}' should not be present"
        return True, ""
    return fn


def summary_has(key: str, expected):
    return has_field(f"summary.{key}", expected)


def data_has(key: str, expected):
    return has_field(f"data.{key}", expected)


def summary_analysis_complete(expected: bool):
    def fn(resp, raw):
        summary = resp.get("summary", {})
        actual = summary.get("analysis_complete")
        if actual != expected:
            return False, f"summary.analysis_complete is {actual}, expected {expected}"
        if summary.get("response_truncated") is not False:
            return False, "analysis budget exhaustion must not mark response_truncated"
        scopes = summary.get("truncation_scopes", [])
        if not expected and "analysis_trace" not in scopes:
            return False, "analysis_trace is missing from summary.truncation_scopes"
        return True, ""
    return fn


def path_line(expected_line: int):
    def fn(resp, raw):
        paths = resp.get("data", {}).get("paths", [])
        lines = {path.get("line", 0) for path in paths if isinstance(path, dict)}
        if expected_line not in lines:
            return False, f"data.paths lines are {sorted(lines)}, expected {expected_line}"
        for path in paths:
            if path.get("line") == expected_line:
                if not path.get("signal_path"):
                    return False, "matching path has empty signal_path"
                if not any(row.get("active") for row in path.get("source_context", [])):
                    return False, "matching path has no active source_context row"
                break
        return True, ""
    return fn


def path_count_at_least(expected_count: int):
    def fn(resp, raw):
        paths = resp.get("data", {}).get("paths", [])
        if len(paths) < expected_count:
            return False, f"data.paths has {len(paths)} entries, expected at least {expected_count}"
        summary = resp.get("summary", {})
        if summary.get("returned_count") != len(paths):
            return False, "summary.returned_count does not match data.paths length"
        if summary.get("total_count", -1) < len(paths):
            return False, "summary.total_count is smaller than data.paths length"
        return True, ""
    return fn


def signal_path_contains(expected_signal: str):
    def fn(resp, raw):
        for path in resp.get("data", {}).get("paths", []):
            if expected_signal in path.get("signal_path", []):
                return True, ""
        return False, f"{expected_signal} not found in any signal_path"
    return fn


def no_legacy_active_fields():
    def fn(resp, raw):
        data = resp.get("data", {})
        for field in ("root_driver", "driver", "trace", "controls", "events"):
            if field in data:
                return False, f"legacy field data.{field} is present"
        return True, ""
    return fn


def active_time_present():
    def fn(resp, raw):
        summary = resp.get("summary", {})
        if "active_time" not in summary:
            return False, "summary.active_time is missing"
        return True, ""
    return fn


# ─── main ────────────────────────────────────────────────────────────────────

def main():
    global failed, passed, skipped

    # Check xdebug is available
    try:
        subprocess.run(
            [XDEBUG, "-h"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=5,
        )
    except Exception:
        print(f"FAIL: xdebug binary not available at {XDEBUG}")
        sys.exit(1)

    for name, fixture_dir in [("active_driver", ACTIVE_DRIVER_DIR),
                              ("interface_port_root", IF_PORT_ROOT_DIR)]:
        for resource in (fixture_dir / "out/simv.daidir", fixture_dir / "out/waves.fsdb"):
            if not resource.exists():
                print(f"FAIL: missing published {name} resource: {resource}")
                sys.exit(1)

    # Open sessions
    print("Opening sessions...")
    ad_sid, ad_err = open_session(
        f"active_driver_py_{os.getpid()}", ACTIVE_DRIVER_DAIDIR, ACTIVE_DRIVER_FSDB)
    if ad_err:
        print(f"active_driver session open error: {ad_err[:200]}")
        print("FAIL: cannot open active_driver session")
        failed += 1
    else:
        print(f"  active_driver session: {ad_sid}")
        opened_sessions.append(ad_sid)

    if_sid, if_err = open_session(
        f"if_port_root_py_{os.getpid()}", IF_PORT_ROOT_DAIDIR, IF_PORT_ROOT_FSDB)
    if if_err:
        print(f"interface_port_root session open error: {if_err[:200]}")
        print("FAIL: cannot open interface_port_root session")
        failed += 1
    else:
        print(f"  interface_port_root session: {if_sid}")
        opened_sessions.append(if_sid)

    if failed > 0:
        sys.exit(1)

    print()
    print("Running test cases...")
    print()

    check_interface_is_signal(if_sid)

    # ── Test 1: q_20ns ──
    check("q_20ns: basic assignment resolution",
          ad_sid, "active_driver_tb.u_dut.q", "20ns",
          checks=[
              active_time_present(),
              path_line(18),
              no_legacy_active_fields(),
          ])

    # ── Test 2: comb_q_16ns (pass-through: should go comb_q=q -> q<=data_a) ──
    check("comb_q_16ns: pass-through recursion to line 18",
          ad_sid, "active_driver_tb.u_dut.comb_q", "16ns",
          checks=[
              active_time_present(),
              path_line(18),
              no_legacy_active_fields(),
          ])

    # ── Test 3: q_force_40ns ──
    check("q_force_40ns: force detection at line 82",
          ad_sid, "active_driver_tb.u_dut.q", "40ns",
          checks=[
              path_line(82),
              no_legacy_active_fields(),
          ])

    # ── Test 4: comb_q_x_50ns (control_only or resolved) ──
    def check_comb_q_x(resp, raw):
        summary = resp.get("summary", {})
        if "returned_count" in summary and "active_time" in summary:
            return True, ""
        return False, "summary.returned_count or summary.active_time is missing"

    check("comb_q_x_50ns: control_only for default/X branch",
          ad_sid, "active_driver_tb.u_dut.comb_q", "50ns",
          checks=[check_comb_q_x])

    # ── Test 5: if_sink_observed_q_30ns (interface alias join) ──
    check("if_sink_observed_q_30ns: alias resolution to line 23",
          if_sid, "if_root_tb.u_sink.observed_q", "30ns",
          extra_args={},
          checks=[
              path_line(23),
              signal_path_contains("if_root_tb.u_sink.observed_q"),
              no_legacy_active_fields(),
          ])

    # ── Test 6: if_link_data_20ns ──
    check("if_link_data_20ns: modport data trace to line 21",
          if_sid, "if_root_tb.link.data", "20ns",
          checks=[
              path_line(21),
              no_legacy_active_fields(),
          ])

    # ── Test 7: if_link_data_30ns ──
    check("if_link_data_30ns: modport data trace to line 23",
          if_sid, "if_root_tb.link.data", "30ns",
          checks=[
              path_line(23),
              no_legacy_active_fields(),
          ])

    # ── Test 8: compact output does not expose internal trace nodes ──
    check("compact_output: no data.trace.nodes",
          ad_sid, "active_driver_tb.u_dut.q", "20ns",
          extra_args={},
          checks=[
              active_time_present(),
              path_line(18),
              field_not_present("data.trace.nodes"),
              field_not_present("data.root_driver"),
          ])

    # ── Test 9: limits_max_nodes ──
    check("limits_max_nodes: truncation with max_nodes=1",
          ad_sid, "active_driver_tb.u_dut.q", "20ns",
          limits={"max_nodes": 1},
          checks=[
              summary_analysis_complete(False),
          ])

    # ── Summary ──
    print()
    print("=" * 60)
    print(f"Results: {passed} passed, {failed} failed, {skipped} skipped")
    print("=" * 60)

    if failed > 0:
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
