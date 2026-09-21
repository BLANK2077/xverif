"""Configuration, ssh argv construction and the remote bootstrap for the SSH bridge.

This module is deliberately free of MCP SDK imports so it can be unit tested
without a transport. Everything here is a pure function of the process
environment, which keeps the bridge's behaviour inspectable.
"""

from __future__ import annotations

import base64
import json
import os
import shlex
from dataclasses import dataclass, replace
from typing import Mapping

# Environment variables this program consumes. They configure the bridge and are never
# forwarded to the remote side. Only these exact names are excluded: a deployment may
# still forward its own variable that happens to share the prefix.
CONFIG_PREFIX = "XVERIF_MCP_SSH_"

ENV_HOST = CONFIG_PREFIX + "HOST"
ENV_REMOTE_ROOT = CONFIG_PREFIX + "REMOTE_ROOT"
ENV_REMOTE_PYTHON = CONFIG_PREFIX + "REMOTE_PYTHON"
ENV_PORT = CONFIG_PREFIX + "PORT"
ENV_IDENTITY = CONFIG_PREFIX + "IDENTITY"
ENV_OPTIONS = CONFIG_PREFIX + "OPTIONS"
ENV_SSH_BIN = CONFIG_PREFIX + "SSH_BIN"
ENV_ENV_DENY = CONFIG_PREFIX + "ENV_DENY"
ENV_REMOTE_COMMAND = CONFIG_PREFIX + "REMOTE_COMMAND"

DEFAULT_REMOTE_PYTHON = "python3"
DEFAULT_SSH_BIN = "ssh"
DEFAULT_REMOTE_COMMAND = ["-m", "xverif_mcp.server"]

# The exact bridge configuration keys. Only these are kept off the wire; a site variable
# that merely shares the XVERIF_MCP_SSH_ prefix is forwarded like any other.
CONFIG_KEYS = frozenset(
    {
        CONFIG_PREFIX + "HOST",
        CONFIG_PREFIX + "REMOTE_ROOT",
        CONFIG_PREFIX + "REMOTE_PYTHON",
        CONFIG_PREFIX + "PORT",
        CONFIG_PREFIX + "IDENTITY",
        CONFIG_PREFIX + "OPTIONS",
        CONFIG_PREFIX + "SSH_BIN",
        CONFIG_PREFIX + "ENV_DENY",
        CONFIG_PREFIX + "REMOTE_COMMAND",
    }
)

# The remote MCP server requires python >= 3.11 (xverif_mcp/pyproject.toml), so the
# bootstrap refuses to start it on anything older instead of failing obscurely later.
MIN_REMOTE_PYTHON = (3, 11)

# The name the remote trampoline reports as $0; it also appears in bootstrap diagnostics.
SERVER_NAME = "xverif-mcp-ssh"

SSH_CONNECT_TIMEOUT_SEC = "10"
FRAME_LIMIT_BYTES = 1024 * 1024
FRAME_VERSION_KEY = "xverif_ssh_env_v1"

# A remote environment is not inherited by ssh, so the frame travels as one
# base64 argument. Values with a sensitive-looking name are dropped, never forwarded.
SENSITIVE_FRAGMENTS = ("TOKEN", "PASSWORD", "SECRET", "COOKIE")

# The remote bootstrap reads the base64 frame from this variable, then removes it so
# the value never lands in the MCP server's own environment.
FRAME_ENV_NAME = CONFIG_PREFIX + "ENV_FRAME_B64"

# Names that describe this machine rather than the session being configured. Forwarding
# them would not configure the remote MCP server, it would misdescribe the remote host:
# HOME in particular decides where xdebug keeps its engine registry and sessions
# (``$HOME/.xdebug/engine``), so forwarding it would redirect the remote server's state
# into a path that only exists here.
LOCAL_ONLY_EXACT = frozenset(
    {"HOME", "LOGNAME", "USER", "SSH_AUTH_SOCK", "SSH_AGENT_PID", "SSH_CONNECTION", "SSH_TTY"}
)

# Shell bookkeeping and exported bash functions. Forwarding these would both bloat the
# frame (a login shell exports functions) and confuse the remote shell.
SHELL_BOOKKEEPING_EXACT = frozenset({"PWD", "OLDPWD", "SHLVL", "_", "LS_JOBPID"})
SHELL_BOOKKEEPING_PREFIXES = ("BASH_FUNC_", "LSB_")

# Variables that only describe a python/conda process or a local test run on this machine.
# They are dropped by default because forwarding them into the remote interpreter breaks
# its own paths - XVERIF_TEST_TMPDIR in particular would redirect the remote server's log
# root into a directory that only exists here. A deployment that really wants one can
# remove it from the default deny list by setting XVERIF_MCP_SSH_ENV_DENY to a list that
# omits it.
PROCESS_LOCAL_EXACT = frozenset(
    {
        "CONDA_PREFIX",
        "CONDA_DEFAULT_ENV",
        "CONDA_EXE",
        "CONDA_PYTHON_EXE",
        "CONDA_PROMPT_MODIFIER",
        "CONDA_SHLVL",
        "NODE",
        "NODE_PATH",
        "NPM_CONFIG_PREFIX",
        "N_PREFIX",
        "OLDPWD",
        "PYTHONHOME",
        "TERM_PROGRAM",
        "TERM_PROGRAM_VERSION",
        "TMUX",
        "TMUX_PANE",
        "VIRTUAL_ENV",
        "XVERIF_TEST_TMPDIR",
        "_CE_CONDA",
        "_CE_M",
        "_CONDA_EXE",
        "_CONDA_ROOT",
    }
)


class ConfigError(ValueError):
    """The bridge configuration is missing or invalid."""


@dataclass(frozen=True)
class BridgeConfig:
    host: str
    remote_root: str
    remote_python: str
    port: str | None
    identity: str | None
    ssh_options: tuple[str, ...]
    ssh_bin: str
    env_deny: frozenset[str]
    remote_command: tuple[str, ...]


def _required(environ: Mapping[str, str], name: str) -> str:
    value = (environ.get(name) or "").strip()
    if not value:
        raise ConfigError(_missing_message(name))
    return value


def _missing_message(name: str) -> str:
    return (
        f"{name} is not set; the SSH bridge needs it.\n"
        f"Set at least {ENV_HOST} and {ENV_REMOTE_ROOT} in the MCP client's env block, "
        "for example:\n"
        '  "env": {\n'
        f'    "{ENV_HOST}": "user@eda-host",\n'
        f'    "{ENV_REMOTE_ROOT}": "<xverif repository on the remote host>"\n'
        "  }"
    )


def _remote_command(environ: Mapping[str, str]) -> tuple[str, ...]:
    raw = (environ.get(ENV_REMOTE_COMMAND) or "").strip()
    if not raw:
        return tuple(DEFAULT_REMOTE_COMMAND)
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ConfigError(f"{ENV_REMOTE_COMMAND} must be a JSON array of strings: {exc}") from exc
    if not isinstance(parsed, list) or not all(isinstance(item, str) and item for item in parsed):
        raise ConfigError(f"{ENV_REMOTE_COMMAND} must be a JSON array of non-empty strings")
    return tuple(parsed)


def _csv_names(raw: str) -> frozenset[str]:
    return frozenset(part.strip() for part in raw.split(",") if part.strip())


def load_config(environ: Mapping[str, str] | None = None) -> BridgeConfig:
    """Read the bridge configuration from the process environment."""
    env = os.environ if environ is None else environ
    port = (env.get(ENV_PORT) or "").strip() or None
    if port is not None and not port.isdigit():
        raise ConfigError(f"{ENV_PORT} must be a decimal port number, got {port!r}")
    try:
        ssh_options = tuple(shlex.split(env.get(ENV_OPTIONS) or ""))
    except ValueError as exc:
        raise ConfigError(f"cannot parse {ENV_OPTIONS}: {exc}") from exc
    return BridgeConfig(
        host=_required(env, ENV_HOST),
        remote_root=_required(env, ENV_REMOTE_ROOT),
        remote_python=(env.get(ENV_REMOTE_PYTHON) or "").strip() or DEFAULT_REMOTE_PYTHON,
        port=port,
        identity=(env.get(ENV_IDENTITY) or "").strip() or None,
        ssh_options=ssh_options,
        ssh_bin=(env.get(ENV_SSH_BIN) or "").strip() or DEFAULT_SSH_BIN,
        env_deny=_csv_names(env.get(ENV_ENV_DENY) or ""),
        remote_command=_remote_command(env),
    )


def with_remote_root(cfg: BridgeConfig, remote_root: str) -> BridgeConfig:
    """Copy of ``cfg`` whose bootstrap validates and exports ``remote_root``.

    The root is carried in the payload rather than on the remote command line: the
    remote server is ``mcp.run()`` with no argv handling, and it resolves its tool
    import paths from ``XVERIF_HOME``, which the bootstrap sets from this value.
    """
    return replace(cfg, remote_root=remote_root)


def build_remote_argv(cfg: BridgeConfig) -> list[str]:
    """Arguments appended after the remote python interpreter."""
    return list(cfg.remote_command)


def decode_payload(payload_b64: str) -> dict:
    """Decode a remote payload into its fields: ``frame``, ``root`` and ``argv``."""
    return json.loads(base64.b64decode(payload_b64.encode("ascii")).decode("utf-8"))


def expand_frame(frame_b64: str) -> dict[str, str]:
    """Decode the environment frame into the NAME=value pairs it carries.

    This is the remote-side half of :func:`build_env_frame`: the caller applies the
    result to its own environment before starting the MCP server.
    """
    decoded = base64.b64decode(frame_b64.encode("ascii"), validate=True)
    if len(decoded) > FRAME_LIMIT_BYTES:
        raise ConfigError(f"environment frame is {len(decoded)} bytes, above the {FRAME_LIMIT_BYTES}-byte limit")
    frame = json.loads(decoded.decode("utf-8"))
    if not isinstance(frame, dict) or frame.get(FRAME_VERSION_KEY) is not True:
        raise ConfigError("environment frame has an unexpected shape")
    env = frame.get("env") or {}
    if not isinstance(env, dict):
        raise ConfigError("environment frame 'env' must be an object")
    return {str(name): str(value) for name, value in env.items()}


def build_payload(cfg: BridgeConfig, frame_b64: str) -> str:
    """Render the remote payload as one base64 word.

    The payload carries everything the remote bootstrap needs and nothing that has to
    survive shell parsing on the way: the frame that was stripped from this side's
    environment, the project directory, and the remote command. Compressing it into a
    single base64 word is what makes the transport robust - ssh joins the remote command
    words with spaces and the remote login shell re-splits and unquotes that string, so
    any token containing quotes, spaces or shell metacharacters would be re-read as shell
    source. The bootstrap program and the frame are full of them.
    """
    payload = {
        "frame": frame_b64,
        "root": cfg.remote_root,
        "argv": build_remote_argv(cfg),
    }
    return base64.b64encode(json.dumps(payload).encode("utf-8")).decode("ascii")


def build_ssh_argv(cfg: BridgeConfig, frame_b64: str) -> list[str]:
    """Build the ssh command that runs the bootstrap on the remote host.

    The frame travels inside the payload argument rather than through stdin, because the
    SDK's stdio client owns the child's stdin/stdout for JSON-RPC framing. That argument
    is visible to other processes on the remote host, so credential-shaped names never
    enter the frame in the first place (see :func:`forwarded_names`): the argument
    exposes site configuration, not keys.

    ``-T`` matters: a pseudo-terminal would translate newlines and echo input, which
    breaks the newline-delimited JSON-RPC framing. ``BatchMode=yes`` makes an interactive
    password prompt fail loudly instead of hanging the client.

    The remote command has to survive ssh joining the words with spaces and the remote
    login shell re-splitting and unquoting that string exactly once. The arrangement
    below therefore only ever unquotes tokens that are inert when unquoted:

    * the launcher (:data:`BOOTSTRAP_LAUNCHER`) is quoted locally by ``shlex.quote`` and
      contains no quote of its own, so that one layer is accounted for;
    * the payload is pure base64 - one word with no shell metacharacter in it, so
      re-splitting cannot touch it, and the module that decodes it reports a malformed
      payload as a python error rather than as a shell exiting on a stray token;
    * the bootstrap module name and the interpreter path are plain words too.

    The remote interpreter is started as ``-m mcp_ssh.bootstrap`` rather than with
    ``-c <code>``: an inline program carries quotes of its own, and each further shell
    layer would need it re-escaped. The bootstrap then starts the MCP server itself.
    """
    argv = [cfg.ssh_bin, "-T", "-o", "BatchMode=yes", "-o", f"ConnectTimeout={SSH_CONNECT_TIMEOUT_SEC}"]
    if cfg.port:
        argv += ["-p", cfg.port]
    if cfg.identity:
        argv += ["-i", cfg.identity]
    argv += list(cfg.ssh_options)
    # $0 of the launcher; then its positional arguments in the order it reads them:
    # interpreter, bootstrap module, payload.
    argv += [cfg.host, "bash", "-c", shlex.quote(BOOTSTRAP_LAUNCHER), f"{SERVER_NAME}-bootstrap"]
    argv += [shlex.quote(cfg.remote_python), BOOTSTRAP_MODULE]
    argv += [shlex.quote(build_payload(cfg, frame_b64))]
    return argv


def forwarded_names(environ: Mapping[str, str], deny: frozenset[str]) -> list[str]:
    """Names that may travel to the remote side, sorted for stable output.

    The intent is "forward what the MCP client configured": everything visible here is
    forwarded except this program's own configuration, local ssh/shell bookkeeping,
    python/conda process locators, credential-shaped names, and an explicit deny list.
    """
    names: list[str] = []
    for name in environ:
        if name in CONFIG_KEYS or name == FRAME_ENV_NAME:
            continue
        if name in LOCAL_ONLY_EXACT or name in deny:
            continue
        if name in SHELL_BOOKKEEPING_EXACT or name in PROCESS_LOCAL_EXACT:
            continue
        if name.startswith(SHELL_BOOKKEEPING_PREFIXES):
            continue
        upper = name.upper()
        if any(fragment in upper for fragment in SENSITIVE_FRAGMENTS):
            continue
        names.append(name)
    return sorted(names)


def build_env_frame(
    environ: Mapping[str, str], deny: frozenset[str], remote_root: str
) -> tuple[bytes, str]:
    """Render the environment frame as (utf-8 json bytes, base64 text argument).

    ``remote_root`` is injected explicitly because the generic forwarding rule strips
    every ``XVERIF_MCP_SSH_*`` name, yet the remote bootstrap needs the repository
    location to put ``xverif_mcp/src`` on the remote ``PYTHONPATH``.
    """
    payload = {name: environ[name] for name in forwarded_names(environ, deny)}
    payload[ENV_REMOTE_ROOT] = remote_root
    frame = json.dumps({FRAME_VERSION_KEY: True, "env": payload}, ensure_ascii=False)
    encoded = frame.encode("utf-8")
    if len(encoded) > FRAME_LIMIT_BYTES:
        raise ConfigError(
            f"environment frame is {len(encoded)} bytes, above the {FRAME_LIMIT_BYTES}-byte limit; "
            f"narrow the MCP client env block or add names to {ENV_ENV_DENY}"
        )
    return encoded, base64.b64encode(encoded).decode("ascii")


# The shell program bash runs, and the only part of the remote command that cannot be
# base64, since it is the shell that would have to run it. It must contain no quote of its
# own: the single layer of quoting ssh strips is exactly the one `shlex.quote` added.
#
# The payload is base64, so it is one word with no shell metacharacter in it and needs no
# quoting here; the bootstrap module does the decoding, where a python exception can report
# a malformed payload instead of a shell exiting on a stray token.
BOOTSTRAP_LAUNCHER = "exec $1 -m $2 $3"

# The module the launcher runs: it applies the payload to its own environment and then
# replaces itself with the MCP server. Kept as a real module rather than as an inline
# `-c` program so that both halves of the remote side are readable, testable python.
BOOTSTRAP_MODULE = "mcp_ssh.bootstrap"


def remote_programs() -> tuple[str, str]:
    """The two programs the remote side runs: the bash launcher and the module it execs."""
    return BOOTSTRAP_LAUNCHER, BOOTSTRAP_MODULE
