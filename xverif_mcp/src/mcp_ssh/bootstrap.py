"""Remote-side bootstrap: apply the forwarded environment, then run the MCP server.

The bridge sends this process one argument, a base64 payload produced by
:func:`mcp_ssh.config.build_payload`. Because the payload is pure base64 the remote shell
cannot misread it, and because it is JSON the payload can carry the environment frame and
the command words without any further shell quoting.

This runs as ``python -m mcp_ssh.bootstrap <payload>`` and replaces itself with the MCP
server, so the JSON-RPC byte stream on stdin/stdout is never proxied through a wrapper.
"""

from __future__ import annotations

import os
import sys

from .config import decode_payload, expand_frame


def apply_payload(payload_b64: str) -> list[str]:
    """Apply the payload to this process and return the command words to execute.

    The forwarded names are applied before anything else so that the server sees exactly
    what the MCP client configured, while the repository settings are derived from the
    payload rather than from the caller's environment.
    """
    payload = decode_payload(payload_b64)
    env = expand_frame(str(payload["frame"]))
    os.environ.update(env)

    root = str(payload["root"])
    if not os.path.isdir(root):
        raise SystemExit(f"xverif-mcp-ssh: remote root is not a directory: {root!r}")
    os.environ["XVERIF_HOME"] = root
    existing = os.environ.get("PYTHONPATH", "")
    parts = [os.path.join(root, "xverif_mcp", "src"), root]
    if existing:
        parts.append(existing)
    os.environ["PYTHONPATH"] = os.pathsep.join(parts)

    argv = [str(word) for word in payload["argv"]]
    if not argv:
        raise SystemExit("xverif-mcp-ssh: the remote command is empty")
    return argv


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 1:
        print("usage: python -m mcp_ssh.bootstrap <payload>", file=sys.stderr)
        return 2
    command = apply_payload(args[0])
    os.execvp(sys.executable, [sys.executable, *command])
    return 1  # unreachable: execvp replaces this process


if __name__ == "__main__":
    raise SystemExit(main())
