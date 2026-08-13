#!/usr/bin/env python3
"""显式校验并发布 native XOUT final 审查报告。"""
from __future__ import annotations

import argparse
from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "xdebug/tests"))

from xdebug.tests.native_xout.report import (  # noqa: E402
    REPORT_PATH,
    publish_final_report,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate one final 73-action native XOUT report and publish it atomically.",
    )
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument(
        "--output",
        type=Path,
        default=REPO_ROOT / REPORT_PATH,
        help="Explicit target; defaults to the tracked native XOUT review document.",
    )
    args = parser.parse_args()
    publish_final_report(args.input, args.output)
    print(args.output.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
