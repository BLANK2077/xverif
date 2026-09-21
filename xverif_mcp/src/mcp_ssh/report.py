"""Remote-side reporter: print what the bootstrap actually handed to the MCP server.

Run on the remote host through the same path the bridge uses::

    bash -c <launcher> xverif-mcp-ssh env XVERIF_MCP_SSH_ENV_FRAME_B64=<frame> \\
        python3 -m mcp_ssh.report <remote-root>

It is a diagnostic, not part of the forwarding path. Values are never printed: the
frame can carry site configuration that a log or a bug report must not capture. Use it
to confirm that an MCP client's ``env`` block reaches the remote process, and to check
the interpreter and repository location the server would start from.
"""

from __future__ import annotations

import os
import sys

# The names injected by the bootstrap rather than by the client.
BOOTSTRAP_NAMES = ("XVERIF_HOME", "PYTHONPATH")


def report(argv: list[str] | None = None, environ: dict[str, str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    env = dict(os.environ) if environ is None else dict(environ)
    root = args[0] if args else env.get("XVERIF_HOME", "")

    print(f"remote python: {sys.version.split()[0]} ({sys.executable})")
    print(f"remote root: {root} (directory={os.path.isdir(root)})")
    forwarded = sorted(name for name in env if name not in BOOTSTRAP_NAMES)
    print(f"forwarded environment: {len(forwarded)} variables")
    for name in forwarded:
        print(f"  {name}")
    print("bootstrap environment:")
    for name in BOOTSTRAP_NAMES:
        shown = env.get(name, "")
        if name == "PYTHONPATH":
            shown = os.pathsep.join(
                part for part in shown.split(os.pathsep) if part
            )
        print(f"  {name}={shown}")
    frame_kept = "XVERIF_MCP_SSH_ENV_FRAME_B64" in env
    print(f"environment frame removed: {not frame_kept}")
    return 0


def main() -> int:
    return report()


if __name__ == "__main__":
    raise SystemExit(main())
