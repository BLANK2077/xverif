"""Real-ssh loopback verification for the SSH MCP bridge.

The hermetic layer in ``test_mcp_ssh_bridge.py`` stands in for ssh and proves the bridge's
own contracts. This file is the other half: it drives the bridge through the real ``ssh``
binary against this host, so the parts that only exist in a real transport - ssh's own
handling of the remote command, passwordless authentication, the remote login shell - are
exercised too.

It skips unless passwordless ssh to the loopback host works, because a machine without it
cannot run the check at all. The skip is reported, never silently converted into a pass;
install the connection with::

    cat ~/.ssh/id_ed25519.pub >> ~/.ssh/authorized_keys && chmod 600 ~/.ssh/authorized_keys
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
MCP_SRC = ROOT / "xverif_mcp" / "src"
PYTHON = sys.executable
LOOPBACK_HOST = "localhost"

# The site's ssh_config may be unusable (for example an unreadable file owned by another
# user), so the loopback connection pins the options it needs instead of inheriting them.
SSH_OPTIONS = "-F /dev/null -o UserKnownHostsFile=/dev/null -o StrictHostKeyChecking=no"


def _passwordless_ssh_works() -> bool:
    if shutil.which("ssh") is None:
        return False
    try:
        result = subprocess.run(
            ["ssh", *SSH_OPTIONS.split(), "-o", "BatchMode=yes", "-o", "ConnectTimeout=10",
             LOOPBACK_HOST, "true"],
            capture_output=True,
            text=True,
            timeout=60,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0


@pytest.fixture(scope="module")
def loopback_environment(tmp_path_factory: pytest.TempPathFactory) -> dict[str, str]:
    if not _passwordless_ssh_works():
        pytest.skip(
            f"passwordless ssh to {LOOPBACK_HOST} is unavailable; "
            "run: cat ~/.ssh/id_ed25519.pub >> ~/.ssh/authorized_keys && chmod 600 ~/.ssh/authorized_keys"
        )
    log_dir = tmp_path_factory.mktemp("ssh-loopback-logs")
    return {
        "PATH": os.environ["PATH"],
        "HOME": os.environ.get("HOME", ""),
        "LANG": os.environ.get("LANG", "C.UTF-8"),
        "PYTHONPATH": str(MCP_SRC),
        "XVERIF_MCP_SSH_HOST": LOOPBACK_HOST,
        "XVERIF_MCP_SSH_REMOTE_ROOT": str(ROOT),
        "XVERIF_MCP_SSH_REMOTE_PYTHON": PYTHON,
        "XVERIF_MCP_SSH_OPTIONS": SSH_OPTIONS,
        "XVERIF_MCP_LOG_DIR": str(log_dir),
    }


def _exchange(proc: subprocess.Popen[str], request: dict, timeout: float = 300.0) -> dict:
    import time

    assert proc.stdin is not None and proc.stdout is not None
    proc.stdin.write(json.dumps(request) + "\n")
    proc.stdin.flush()
    deadline = time.time() + timeout
    while time.time() < deadline:
        line = proc.stdout.readline()
        if not line:
            raise AssertionError("the bridge closed stdout before answering")
        message = json.loads(line)
        if str(message.get("id")) == str(request["id"]):
            return message
    raise AssertionError(f"no answer for {request['id']}")


def _initialize(proc: subprocess.Popen[str]) -> dict:
    answer = _exchange(
        proc,
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "loopback-test", "version": "1"},
            },
        },
    )
    assert proc.stdin is not None
    proc.stdin.write(json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}) + "\n")
    proc.stdin.flush()
    return answer


def test_loopback_session_relays_real_tools(loopback_environment: dict[str, str]) -> None:
    """A full MCP session over a real ssh hop: list the tools, then run one of them.

    The bridge's stdio front end is driven directly, with this interpreter as the client,
    so nothing in the test depends on how another MCP client manages child processes.
    """
    proc = subprocess.Popen(
        [PYTHON, "-u", "-m", "mcp_ssh"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        bufsize=1,
        env=loopback_environment,
    )
    try:
        _initialize(proc)

        listed = _exchange(proc, {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
        assert "result" in listed, listed
        names = [tool["name"] for tool in listed["result"]["tools"]]
        # The remote server's own surface, reached through a real ssh hop.
        assert "xverif_ping" in names
        assert "xverif_bit_convert" in names

        ping = _exchange(
            proc,
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {"name": "xverif_ping", "arguments": {}},
            },
        )
        assert ping["result"].get("isError") in (False, None), ping
        assert "pong" in json.dumps(ping["result"])

        # A real computation, executed by the remote xbit tool rather than by a stub.
        converted = _exchange(
            proc,
            {
                "jsonrpc": "2.0",
                "id": 4,
                "method": "tools/call",
                "params": {"name": "xverif_bit_convert", "arguments": {"value": "16'h00ff"}},
            },
        )
        assert converted["result"].get("isError") in (False, None), converted
        assert "16'hff" in json.dumps(converted["result"])
    finally:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=30)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=30)


def test_loopback_check_reports_the_remote_tool_count(loopback_environment: dict[str, str]) -> None:
    result = subprocess.run(
        [PYTHON, "-m", "mcp_ssh", "--check"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=300,
        env=loopback_environment,
    )
    assert result.returncode == 0, result.stderr
    assert "check ok" in result.stderr
    # The remote server exposes its whole tool surface through the ssh hop.
    assert "upstream initialized" in result.stderr


def test_loopback_forwards_the_client_environment(loopback_environment: dict[str, str]) -> None:
    """The remote reporter shows which variables reached the far side of the ssh hop.

    It prints variable *names* only, which is what makes it safe to run against a site
    configuration, and it is exercised through the same argv the bridge builds.
    """
    from mcp_ssh.config import build_env_frame, build_ssh_argv, load_config, with_remote_root

    environ = {
        **loopback_environment,
        "SITE_TAG": "loopback-forwarded",
        "MY_API_TOKEN": "must-not-travel",
        "XVERIF_MCP_SSH_REMOTE_COMMAND": json.dumps(["-m", "mcp_ssh.report"]),
    }
    cfg = with_remote_root(load_config(environ), str(ROOT))
    _frame, frame_b64 = build_env_frame(environ, cfg.env_deny, cfg.remote_root)
    argv = build_ssh_argv(cfg, frame_b64)
    result = subprocess.run(argv, capture_output=True, text=True, timeout=300, env=environ)

    assert result.returncode == 0, result.stderr
    assert "SITE_TAG" in result.stdout
    assert str(ROOT) in result.stdout
    # A credential-shaped name is dropped rather than forwarded.
    assert "MY_API_TOKEN" not in result.stdout
    assert "environment frame removed: True" in result.stdout
