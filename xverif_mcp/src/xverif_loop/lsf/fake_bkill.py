"""Explicit fake ``bkill`` command used only by the LSF doctor fake mode."""

from __future__ import annotations

import sys
from typing import Sequence


def main(argv: Sequence[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) == 1 and args[0]:
        return 0
    if len(args) == 2 and args[0] == "-J" and args[1]:
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
