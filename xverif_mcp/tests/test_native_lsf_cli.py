"""Process tests for the native-compatible SDK-free LSF frontends."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import stat
import subprocess
import time


ROOT = Path(__file__).resolve().parents[2]


def _fake_tool(path: Path, *, tool: str) -> None:
    api_version = f"{tool}.v1"
    protocol = f"{tool}-stdio-loop"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"""#!/usr/bin/env python3
import json, os, sys

if len(sys.argv) > 1 and sys.argv[1] == "log":
    print("{tool} fake log " + " ".join(sys.argv[2:]))
    raise SystemExit(0)
if "--stdio-loop" not in sys.argv:
    if any(arg in sys.argv for arg in ("-h", "-help", "--help")):
        print("{tool} fake help")
        raise SystemExit(0)
    raise SystemExit(2)

print(json.dumps({{"type":"ready","protocol":{protocol!r},"version":1,"pid":os.getpid()}}), flush=True)
for line in sys.stdin:
    request = json.loads(line)
    action = request.get("action", "")
    request_id = request.get("request_id", "req")
    if action == "stdio.quit":
        payload = {{"ok": True, "api_version": {api_version!r}, "action": action}}
        envelope = {{"id": request_id, "request_id": request_id, "ok": True,
                    "payload_format": "json", "json": payload}}
        print(json.dumps(envelope), flush=True)
        raise SystemExit(0)
    if action == "session.open":
        name = request.get("args", {{}}).get("name", "case")
        payload = {{"ok": True, "api_version": {api_version!r}, "action": action,
                   "session": {{"session_id": name}},
                   "data": {{"session": {{"session_id": name}}}},
                   "summary": {{"status": "opened"}}}}
    elif action == "session.close":
        payload = {{"ok": True, "api_version": {api_version!r}, "action": action,
                   "summary": {{"removed": True}}}}
    else:
        payload = {{"ok": True, "api_version": {api_version!r}, "action": action,
                   "summary": {{"fake": True}}, "data": {{"tool": {tool!r}}}}}
    xout = "@{tool}.v1 ok action=" + action + "\\n"
    envelope = {{"id": request_id, "request_id": request_id, "ok": True,
                "payload_format": "json" if request.get("payload_format") == "json" else "xout",
                "json": payload, "xout": xout}}
    print(json.dumps(envelope), flush=True)
""",
        encoding="utf-8",
    )
    path.chmod(path.stat().st_mode | stat.S_IEXEC)


def _environment(tmp_path: Path) -> dict[str, str]:
    home = tmp_path / "home"
    xverif_home = tmp_path / "xverif-home"
    _fake_tool(xverif_home / "tools" / "xdebug", tool="xdebug")
    _fake_tool(xverif_home / "tools" / "xcov", tool="xcov")
    env = dict(os.environ)
    env.update({
        "HOME": str(home),
        "XVERIF_HOME": str(xverif_home),
        "XVERIF_LSF_CLI_SOCKET": str(tmp_path / "manager.sock"),
        "XVERIF_LSF_CLI_LOG_DIR": str(tmp_path / "logs"),
        "XVERIF_LSF_CLI_FAKE_LSF": "1",
        "XVERIF_LSF_CLI_IDLE_TIMEOUT_SEC": "1",
        "XVERIF_LSF_CLI_STARTUP_TIMEOUT_SEC": "10",
        "XVERIF_LSF_CLI_REQUEST_TIMEOUT_SEC": "10",
        "PYTHON": os.environ.get("PYTHON", os.sys.executable),
        "PYTHONPATH": os.pathsep.join([
            str(ROOT / "xverif_mcp" / "src"),
            str(ROOT),
            env.get("PYTHONPATH", ""),
        ]),
    })
    return env


def _run(tool: str, request: dict, env: dict[str, str], *extra: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(ROOT / "tools" / f"{tool}_lsf"), "--json", *extra, "-"],
        input=json.dumps(request) + "\n",
        text=True,
        encoding="utf-8",
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
        cwd=ROOT,
        timeout=20,
        check=False,
    )


def test_native_lsf_frontends_reject_public_stdio_loop(tmp_path: Path) -> None:
    env = _environment(tmp_path)
    for tool in ("xdebug", "xcov"):
        result = subprocess.run(
            [str(ROOT / "tools" / f"{tool}_lsf"), "--stdio-loop"],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
            cwd=ROOT,
            timeout=10,
            check=False,
        )
        assert result.returncode == 2
        assert "internal LSF protocol" in result.stderr
    assert not Path(env["XVERIF_LSF_CLI_SOCKET"]).exists()


def test_native_lsf_xdebug_and_xcov_open_query_close(tmp_path: Path) -> None:
    env = _environment(tmp_path)
    cases = {
        "xdebug": {
            "api_version": "xdebug.v1",
            "target": {"fsdb": "waves.fsdb"},
        },
        "xcov": {
            "api_version": "xcov.v1",
            "target": {"vdb": "merged.vdb"},
        },
    }
    for tool, base in cases.items():
        name = f"{tool}_case"
        opened = _run(tool, {
            **base,
            "request_id": f"{tool}-open",
            "action": "session.open",
            "args": {"name": name},
        }, env)
        assert opened.returncode == 0, opened.stderr + opened.stdout
        assert json.loads(opened.stdout)["session"]["session_id"] == name

        action = "value.at" if tool == "xdebug" else "code_coverage.summary"
        queried = _run(tool, {
            "api_version": base["api_version"],
            "request_id": f"{tool}-query",
            "action": action,
            "target": {"session_id": name},
            "args": {},
        }, env)
        assert queried.returncode == 0, queried.stderr + queried.stdout
        assert json.loads(queried.stdout)["action"] == action

        closed = _run(tool, {
            "api_version": base["api_version"],
            "request_id": f"{tool}-close",
            "action": "session.close",
            "target": {"session_id": name},
            "args": {},
        }, env)
        assert closed.returncode == 0, closed.stderr + closed.stdout
        assert json.loads(closed.stdout)["action"] == "session.close"

    socket_path = Path(env["XVERIF_LSF_CLI_SOCKET"])
    deadline = time.monotonic() + 5
    while socket_path.exists() and time.monotonic() < deadline:
        time.sleep(0.05)
    assert not socket_path.exists()


def test_native_lsf_stateless_requests_use_temporary_loops(tmp_path: Path) -> None:
    env = _environment(tmp_path)
    for tool in ("xdebug", "xcov"):
        result = _run(tool, {
            "api_version": f"{tool}.v1",
            "request_id": f"{tool}-actions",
            "action": "actions",
        }, env)
        assert result.returncode == 0, result.stderr + result.stdout
        payload = json.loads(result.stdout)
        assert payload["ok"] is True
        assert payload["action"] == "actions"


def test_native_lsf_xout_and_file_inputs_match_native_surface(tmp_path: Path) -> None:
    env = _environment(tmp_path)
    request = {
        "api_version": "xdebug.v1",
        "request_id": "xout-file",
        "action": "actions",
    }
    request_path = tmp_path / "request.json"
    request_path.write_text(json.dumps(request), encoding="utf-8")
    debug = subprocess.run(
        [str(ROOT / "tools" / "xdebug_lsf"), str(request_path)],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
        cwd=ROOT,
        timeout=20,
        check=False,
    )
    assert debug.returncode == 0, debug.stderr
    assert debug.stdout == "@xdebug.v1 ok action=actions\n"

    request["api_version"] = "xcov.v1"
    request_path.write_text(json.dumps(request), encoding="utf-8")
    cov = subprocess.run(
        [str(ROOT / "tools" / "xcov_lsf"), "--request", str(request_path)],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
        cwd=ROOT,
        timeout=20,
        check=False,
    )
    assert cov.returncode == 0, cov.stderr
    assert cov.stdout == "@xcov.v1 ok action=actions\n"


def test_native_lsf_help_is_local_and_xdebug_log_uses_lsf(tmp_path: Path) -> None:
    env = _environment(tmp_path)
    socket_path = Path(env["XVERIF_LSF_CLI_SOCKET"])
    for tool, help_arg in (("xdebug", "-h"), ("xcov", "--help")):
        helped = subprocess.run(
            [str(ROOT / "tools" / f"{tool}_lsf"), help_arg],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
            cwd=ROOT,
            timeout=10,
            check=False,
        )
        assert helped.returncode == 0, helped.stderr
        assert helped.stdout == f"{tool} fake help\n"
        assert not socket_path.exists()

    logged = subprocess.run(
        [str(ROOT / "tools" / "xdebug_lsf"), "log", "doctor", "--session", "s0"],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
        cwd=ROOT,
        timeout=20,
        check=False,
    )
    assert logged.returncode == 0, logged.stderr
    assert "xdebug fake log doctor --session s0" in logged.stdout
    assert not socket_path.exists()


def test_native_lsf_concurrent_first_calls_share_one_manager(tmp_path: Path) -> None:
    env = _environment(tmp_path)

    def call(index: int) -> subprocess.CompletedProcess[str]:
        return _run("xdebug", {
            "api_version": "xdebug.v1",
            "request_id": f"parallel-{index}",
            "action": "actions",
        }, env)

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(call, range(4)))
    for result in results:
        assert result.returncode == 0, result.stderr + result.stdout
        assert json.loads(result.stdout)["action"] == "actions"
