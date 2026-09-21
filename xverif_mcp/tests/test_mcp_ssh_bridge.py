"""Hermetic contracts for the SSH MCP bridge, its payload and its remote bootstrap.

Only the ssh *process boundary* is stood in for here: the tests provide a local
executable where ``ssh`` would be, and it consumes exactly the argument layout the bridge
produces (launcher, interpreter, bootstrap module, payload). The bootstrap, the
environment frame and the bridge's MCP front end are the real implementations.

The integration layer that reaches a real server lives in
``test_mcp_ssh_bridge_transport.py``.
"""

from __future__ import annotations

import base64
import json
import os
import shlex
import subprocess
import sys
from pathlib import Path

import pytest

from mcp_ssh.bootstrap import apply_payload
from mcp_ssh.config import (
    BOOTSTRAP_LAUNCHER,
    BOOTSTRAP_MODULE,
    CONFIG_KEYS,
    FRAME_ENV_NAME,
    BridgeConfig,
    ConfigError,
    build_env_frame,
    build_payload,
    build_ssh_argv,
    decode_payload,
    expand_frame,
    forwarded_names,
    load_config,
    remote_programs,
    with_remote_root,
)

ROOT = Path(__file__).resolve().parents[2]
MCP_SRC = ROOT / "xverif_mcp" / "src"
PYTHON = sys.executable

@pytest.fixture(autouse=True)
def _isolate_environment():
    """Restore the process environment after each test.

    ``apply_payload`` mutates ``os.environ`` on purpose - that is what it must do on the
    remote side - so a test that exercises it also mutates this interpreter's environment.
    Later tests read ``os.environ`` to build the child's environment, which made a test that
    passed alone fail when an earlier test had run.
    """
    snapshot = dict(os.environ)
    yield
    os.environ.clear()
    os.environ.update(snapshot)


REQUIRED_ENV = {
    "XVERIF_MCP_SSH_HOST": "user@eda-host",
    "XVERIF_MCP_SSH_REMOTE_ROOT": "<remote>/xverif",
}


def _config(**overrides: str) -> BridgeConfig:
    env = {**REQUIRED_ENV, **overrides}
    return load_config(env)


def _payload(payload_b64: str) -> dict:
    return json.loads(base64.b64decode(payload_b64).decode("utf-8"))


# ---------------------------------------------------------------------------
# Configuration surface
# ---------------------------------------------------------------------------


def test_required_host_and_root_are_enforced() -> None:
    for missing in ("XVERIF_MCP_SSH_HOST", "XVERIF_MCP_SSH_REMOTE_ROOT"):
        env = {name: value for name, value in REQUIRED_ENV.items() if name != missing}
        with pytest.raises(ConfigError) as excinfo:
            load_config(env)
        assert missing in str(excinfo.value)


def test_defaults_keep_the_remote_command_a_plain_module_invocation() -> None:
    cfg = _config()
    assert cfg.remote_command == ("-m", "xverif_mcp.server")
    assert cfg.remote_python == "python3"
    assert cfg.ssh_bin == "ssh"
    assert cfg.port is None and cfg.identity is None


def test_port_must_be_numeric_and_options_are_shell_split() -> None:
    with pytest.raises(ConfigError):
        _config(XVERIF_MCP_SSH_PORT="not-a-port")
    cfg = _config(XVERIF_MCP_SSH_PORT="2222", XVERIF_MCP_SSH_OPTIONS="-o StrictHostKeyChecking=no -v")
    assert cfg.port == "2222"
    assert cfg.ssh_options == ("-o", "StrictHostKeyChecking=no", "-v")


def test_remote_command_must_be_a_json_array_of_strings() -> None:
    with pytest.raises(ConfigError):
        _config(XVERIF_MCP_SSH_REMOTE_COMMAND="not json")
    with pytest.raises(ConfigError):
        _config(XVERIF_MCP_SSH_REMOTE_COMMAND='["-m", 7]')
    assert _config(XVERIF_MCP_SSH_REMOTE_COMMAND='["-m", "custom.server"]').remote_command == (
        "-m",
        "custom.server",
    )


# ---------------------------------------------------------------------------
# Environment forwarding
# ---------------------------------------------------------------------------


def test_forwarding_keeps_site_variables_and_drops_credentials_and_bookkeeping() -> None:
    environ = {
        "PATH": "<bin>",
        "SITE_TAG": "site-1",
        "XVERIF_MCP_SSH_SITE_TAG": "site-1",
        "SITE_API_TOKEN": "must-not-travel",
        "MY_PASSWORD": "must-not-travel",
        "SSH_AUTH_SOCK": "<sock>/agent.sock",
        "PWD": "<cwd>",
        "SHLVL": "2",
        "BASH_FUNC_ls%%": "() { :; }",
        "CONDA_PREFIX": "<conda>",
        **{name: "bridge-config" for name in CONFIG_KEYS},
        FRAME_ENV_NAME: "stale",
    }
    names = forwarded_names(environ, frozenset())
    assert "SITE_TAG" in names
    # A site variable that merely shares the bridge prefix is not the bridge's own config.
    assert "XVERIF_MCP_SSH_SITE_TAG" in names
    for dropped in (
        "SITE_API_TOKEN",
        "MY_PASSWORD",
        "SSH_AUTH_SOCK",
        "PWD",
        "SHLVL",
        "BASH_FUNC_ls%%",
        "CONDA_PREFIX",
        FRAME_ENV_NAME,
        *CONFIG_KEYS,
    ):
        assert dropped not in names, dropped
    assert names == sorted(names)


def test_env_deny_removes_explicit_names() -> None:
    environ = {"PATH": "<bin>", "SITE_TAG": "site-1"}
    assert forwarded_names(environ, frozenset({"SITE_TAG"})) == ["PATH"]


def test_frame_round_trips_and_carries_the_remote_root() -> None:
    environ = {"PATH": "<bin>", "SITE_TAG": "site-1"}
    raw, b64 = build_env_frame(environ, frozenset(), "<remote>/xverif")
    assert json.loads(raw.decode("utf-8"))["env"]["SITE_TAG"] == "site-1"
    expanded = expand_frame(b64)
    assert expanded["SITE_TAG"] == "site-1"
    assert expanded["XVERIF_MCP_SSH_REMOTE_ROOT"] == "<remote>/xverif"


def test_frame_rejects_oversized_payloads() -> None:
    environ = {"BIG": "x" * (1024 * 1024 + 1)}
    with pytest.raises(ConfigError) as excinfo:
        build_env_frame(environ, frozenset(), "<remote>/xverif")
    assert "above the" in str(excinfo.value)


def test_expand_frame_refuses_an_unexpected_shape() -> None:
    with pytest.raises(ConfigError):
        expand_frame(base64.b64encode(json.dumps({"env": {}}).encode("utf-8")).decode("ascii"))


# ---------------------------------------------------------------------------
# Payload and remote command
# ---------------------------------------------------------------------------


def test_payload_is_one_base64_word_carrying_frame_root_and_command() -> None:
    cfg = _config()
    raw, b64 = build_env_frame({"PATH": "/usr/bin"}, frozenset(), cfg.remote_root)
    payload_b64 = build_payload(cfg, b64)
    assert " " not in payload_b64 and "\n" not in payload_b64
    payload = decode_payload(payload_b64)
    assert payload["frame"] == b64
    assert payload["root"] == cfg.remote_root
    assert payload["argv"] == ["-m", "xverif_mcp.server"]


def test_ssh_argv_places_the_payload_after_the_launcher() -> None:
    cfg = _config(XVERIF_MCP_SSH_PORT="2222", XVERIF_MCP_SSH_IDENTITY="<keys>/id_ed25519")
    raw, b64 = build_env_frame({"PATH": "/usr/bin"}, frozenset(), cfg.remote_root)
    argv = build_ssh_argv(cfg, b64)

    assert argv[0] == "ssh"
    # -T and BatchMode matter: a pty would break JSON-RPC framing, and an interactive
    # password prompt would hang instead of failing.
    assert "-T" in argv
    assert "BatchMode=yes" in argv
    assert argv[argv.index("-p") + 1] == "2222"
    assert argv[argv.index("-i") + 1] == "<keys>/id_ed25519"
    # Only the identity path travels; no key material is read or embedded here.
    assert not any("PRIVATE KEY" in word for word in argv)

    remote = argv[argv.index(cfg.host) + 1 :]
    assert remote[0] == "bash" and remote[1] == "-c"
    assert shlex.split(remote[2]) == [BOOTSTRAP_LAUNCHER]
    assert remote[4] == cfg.remote_python
    assert remote[5] == BOOTSTRAP_MODULE
    assert remote[6] == build_payload(cfg, b64)


def test_remote_command_survives_ssh_joining_and_remote_shell_reparsing() -> None:
    """ssh joins the remote words with spaces and the remote shell re-splits them.

    Both the launcher and the payload must therefore be inert in that context.
    """
    cfg = _config()
    raw, b64 = build_env_frame({"PATH": "/usr/bin"}, frozenset(), cfg.remote_root)
    argv = build_ssh_argv(cfg, b64)
    remote = argv[argv.index(cfg.host) + 1 :]

    reparsed = shlex.split(" ".join(remote))
    assert reparsed[2] == BOOTSTRAP_LAUNCHER
    assert reparsed[5] == BOOTSTRAP_MODULE
    assert reparsed[6] == build_payload(cfg, b64)


def test_launcher_is_quote_free() -> None:
    launcher, module = remote_programs()
    # shlex.quote protects exactly one shell layer; the remote shell removes it, so a quote
    # inside the launcher would be re-read as shell source. The module name is a plain
    # identifier for the same reason.
    assert "'" not in launcher
    assert '"' not in launcher
    assert "\n" not in launcher
    assert all(part.isidentifier() for part in module.split("."))


# ---------------------------------------------------------------------------
# Remote bootstrap
# ---------------------------------------------------------------------------


def test_apply_payload_sets_the_forwarded_environment_and_pythonpath(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("XVERIF_MCP_SSH_SITE_TAG", "site-1")
    monkeypatch.setenv("SITE_FOO", "bar")
    # The forwarded names are the client's configuration, so the frame is built from a
    # copy of the environment rather than from the live one.
    environ = {"PATH": "<bin>", "SITE_FOO": "bar", "XVERIF_MCP_SSH_SITE_TAG": "site-1"}
    raw, b64 = build_env_frame(environ, frozenset(), str(ROOT))
    cfg = _config(XVERIF_MCP_SSH_REMOTE_ROOT=str(ROOT))
    payload_b64 = build_payload(cfg, b64)

    monkeypatch.delenv("SITE_FOO", raising=False)
    command = apply_payload(payload_b64)

    assert os.environ["SITE_FOO"] == "bar"
    assert os.environ["XVERIF_MCP_SSH_SITE_TAG"] == "site-1"
    assert os.environ["XVERIF_HOME"] == str(ROOT)
    assert os.environ["PYTHONPATH"].split(os.pathsep)[:2] == [
        str(MCP_SRC),
        str(ROOT),
    ]
    # The frame itself is transport state, not part of the server's environment.
    assert FRAME_ENV_NAME not in os.environ
    assert command == ["-m", "xverif_mcp.server"]


def test_apply_payload_rejects_a_missing_remote_root() -> None:
    raw, b64 = build_env_frame({"PATH": "<bin>"}, frozenset(), "<remote>/missing")
    payload_b64 = build_payload(_config(XVERIF_MCP_SSH_REMOTE_ROOT="<remote>/missing"), b64)
    with pytest.raises(SystemExit) as excinfo:
        apply_payload(payload_b64)
    assert "not a directory" in str(excinfo.value)


def test_bootstrap_rejects_a_corrupt_payload(tmp_path: Path) -> None:
    env = {
        "PATH": os.environ["PATH"],
        "HOME": os.environ.get("HOME", ""),
        "PYTHONPATH": str(MCP_SRC),
    }
    result = subprocess.run(
        [PYTHON, "-m", "mcp_ssh.bootstrap", "not-base64!!"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
        env=env,
        cwd=str(tmp_path),
    )
    assert result.returncode != 0
    assert "Error" in result.stderr or "error" in result.stderr


# ---------------------------------------------------------------------------
# Bridge front end
# ---------------------------------------------------------------------------

SSH_BOUNDARY_SHIM = '''#!/usr/bin/env python3
"""Stand in for ssh: run the remote command the bridge built, locally.

ssh takes the words after the host, joins them with single spaces, and hands the result
to the remote login shell, which re-splits and unquotes it. This shim does exactly that,
so a remote command that only works when its words are passed through untouched still
fails here. It asserts the layout on the way:

    bash -c <launcher> <$0> <interpreter> <module> <payload>
"""
import os, shlex, sys

# sys.argv[1:] is ssh's own option vector followed by the host and the remote command.
# ssh's contract is about the words after the host: it joins them with single spaces and
# hands the result to the remote login shell, which re-splits and unquotes it. shlex is
# what re-splits it here; a naive split on spaces would tear the quoted launcher apart and
# would prove nothing about whether the real transport survives.
try:
    host_index = next(i for i, word in enumerate(sys.argv[1:], start=1) if word == "loopback")
except StopIteration:
    print(f"ssh boundary: no host in {sys.argv[1:]!r}", file=sys.stderr)
    raise SystemExit(3)
joined = " ".join(sys.argv[host_index + 1 :])
words = shlex.split(joined)
if words[:2] != ["bash", "-c"]:
    print(f"ssh boundary: remote command does not start with bash -c: {words[:2]!r}", file=sys.stderr)
    raise SystemExit(3)
if len(words) != 7:
    print(f"ssh boundary: expected 7 remote words, got {len(words)}: {words!r}", file=sys.stderr)
    raise SystemExit(3)
if words[2] != "exec $1 -m $2 $3":
    print(f"ssh boundary: the launcher changed in transit: {words[2]!r}", file=sys.stderr)
    raise SystemExit(3)
if words[3] != "xverif-mcp-ssh-bootstrap" or words[5] != "mcp_ssh.bootstrap":
    print(f"ssh boundary: unexpected remote layout {words[3]!r} {words[5]!r}", file=sys.stderr)
    raise SystemExit(3)
os.execvp("bash", ["bash", "-c", joined])
'''


def _boundary(tmp_path: Path) -> Path:
    """Write the ssh stand-in and make sure it is actually runnable."""
    shim = tmp_path / "ssh-boundary"
    shim.write_text(SSH_BOUNDARY_SHIM, encoding="utf-8")
    shim.chmod(0o755)
    assert os.access(shim, os.X_OK), (
        f"boundary is not executable: {shim} mode={oct(shim.stat().st_mode)}"
        f" tmpdir={tmp_path} mount={os.statvfs(tmp_path).f_flag:#x}"
    )
    return shim


def _bridge_env(tmp_path: Path, log_dir: Path, **extra: str) -> dict[str, str]:
    boundary = _boundary(tmp_path)
    env = {
        "PATH": os.environ["PATH"],
        "HOME": os.environ.get("HOME", ""),
        "LANG": os.environ.get("LANG", "C.UTF-8"),
        # The remote interpreter is this same python, and it needs the bridge package on
        # its path to import mcp_ssh.bootstrap. A real deployment gets this from the
        # repository it is pointed at, which the bootstrap prepends to PYTHONPATH.
        "PYTHONPATH": str(MCP_SRC),
        "XVERIF_MCP_SSH_SSH_BIN": str(boundary),
        "XVERIF_MCP_SSH_HOST": "loopback",
        "XVERIF_MCP_SSH_REMOTE_ROOT": str(ROOT),
        "XVERIF_MCP_SSH_REMOTE_PYTHON": PYTHON,
        "XVERIF_MCP_LOG_DIR": str(log_dir),
    }
    env.update(extra)
    return env


def _spawn_bridge(env: dict[str, str]) -> subprocess.Popen[str]:
    # The boundary is a script, so the child needs an interpreter on PATH; a bare PATH
    # without python3 is what made this test pass alone and fail in a full suite run.
    path = os.pathsep.join([str(Path(PYTHON).parent), env["PATH"]])
    full = {**env, "PATH": path, "PYTHONPATH": str(MCP_SRC)}
    return subprocess.Popen(
        # -u matters: the bridge answers on stdout and only then keeps the connection open,
        # so a block-buffered stream would hold the answer back instead of sending it.
        [PYTHON, "-u", "-m", "mcp_ssh"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        bufsize=1,
        env=full,
    )


def _exchange(proc: subprocess.Popen[str], request: dict, timeout: float = 180.0) -> dict:
    import time

    assert proc.stdin is not None and proc.stdout is not None
    proc.stdin.write(json.dumps(request) + "\n")
    proc.stdin.flush()
    deadline = time.time() + timeout
    while time.time() < deadline:
        line = proc.stdout.readline()
        if not line:
            stderr = proc.stderr.read() if proc.stderr is not None else ""
            raise AssertionError(f"the bridge closed stdout before answering; stderr:\n{stderr[-2000:]}")
        message = json.loads(line)
        if str(message.get("id")) == str(request["id"]):
            return message
    raise AssertionError(f"no answer for {request['id']}")


def _initialize(proc: subprocess.Popen[str]) -> dict:
    result = _exchange(
        proc,
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "bridge-test", "version": "1"},
            },
        },
    )
    assert proc.stdin is not None
    proc.stdin.write(json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}) + "\n")
    proc.stdin.flush()
    return result


def _shutdown(proc: subprocess.Popen[str]) -> None:
    if proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=30)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=30)


def test_bridge_relays_tools_and_advertises_only_tools(tmp_path: Path) -> None:
    proc = _spawn_bridge(_bridge_env(tmp_path, tmp_path / "logs"))
    try:
        init = _initialize(proc)
        capabilities = init["result"]["capabilities"]
        # xverif exposes tools only; the bridge must not advertise what it cannot serve.
        assert "tools" in capabilities
        assert "resources" not in capabilities
        assert "prompts" not in capabilities

        listed = _exchange(proc, {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
        assert "result" in listed, listed
        tools = listed["result"]["tools"]
        names = [tool["name"] for tool in tools]
        assert "xverif_ping" in names and "xverif_debug_query" in names
        ping = next(tool for tool in tools if tool["name"] == "xverif_ping")
        # Schemas are relayed, not rebuilt.
        assert isinstance(ping["inputSchema"], dict) and ping["inputSchema"]

        called = _exchange(
            proc,
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {"name": "xverif_ping", "arguments": {}},
            },
        )
        assert "result" in called, called
        assert called["result"].get("isError") in (False, None)
        assert "pong" in json.dumps(called["result"])
    finally:
        _shutdown(proc)


def test_bridge_reports_an_unreachable_remote_instead_of_faking_success(tmp_path: Path) -> None:
    """A remote that cannot start must produce an error, never an empty successful answer.

    The bridge answers the handshake itself, because that is protocol metadata; the failure
    therefore has to surface on the first request that needs the remote, and it has to name
    the remote rather than looking like an empty tool result.
    """
    env = _bridge_env(tmp_path, tmp_path / "logs")
    env["XVERIF_MCP_SSH_REMOTE_COMMAND"] = json.dumps(["-m", "mcp_ssh.does_not_exist"])
    proc = _spawn_bridge(env)
    try:
        _initialize(proc)
        answer = _exchange(proc, {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
        assert "error" in answer, answer
        assert answer["error"]["message"], answer
        assert "result" not in answer, answer
    finally:
        _shutdown(proc)


def test_bridge_reports_an_unreachable_host_as_an_error(tmp_path: Path) -> None:
    env = _bridge_env(tmp_path, tmp_path / "logs")
    env["XVERIF_MCP_SSH_REMOTE_PYTHON"] = str(tmp_path / "no-such-python")
    proc = _spawn_bridge(env)
    try:
        _initialize(proc)
        answer = _exchange(proc, {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
        assert "error" in answer, answer
        assert answer["error"]["code"] == -32603, answer
        assert "upstream" in answer["error"]["message"], answer
    finally:
        _shutdown(proc)


def test_bridge_check_exits_two_without_configuration_and_prints_no_values() -> None:
    env = {"PATH": os.environ["PATH"], "PYTHONPATH": str(MCP_SRC)}
    result = subprocess.run(
        [PYTHON, "-m", "mcp_ssh", "--check"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=180,
        env=env,
    )
    assert result.returncode == 2
    assert result.stdout == ""
    assert "XVERIF_MCP_SSH_HOST" in result.stderr


def test_bridge_check_never_prints_a_forwarded_value(tmp_path: Path) -> None:
    secret = "site-value-that-must-not-be-printed"
    env = _bridge_env(tmp_path, tmp_path / "logs", SITE_TAG=secret)
    result = subprocess.run(
        [PYTHON, "-m", "mcp_ssh", "--check"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=240,
        env=env,
    )
    assert secret not in result.stdout
    assert secret not in result.stderr
    assert result.stdout == ""


# ---------------------------------------------------------------------------
# Repository hygiene
# ---------------------------------------------------------------------------


def test_repository_contains_no_ssh_key_material() -> None:
    forbidden = {"id_rsa", "id_ed25519", "id_ecdsa", "id_dsa", "authorized_keys", "known_hosts"}
    offenders: list[str] = []
    for path in ROOT.rglob("*"):
        if not path.is_file():
            continue
        if {".git", ".conda-xverif", ".xverif-test-cache", "third_party"} & set(path.parts):
            continue
        if path.name in forbidden:
            offenders.append(str(path.relative_to(ROOT)))
    assert not offenders, f"SSH key material must never live in the repository: {offenders}"
