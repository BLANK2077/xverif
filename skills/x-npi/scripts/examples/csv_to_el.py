#!/usr/bin/env python3
"""Compile strict xcov CSV sidecars into opaque EL with the built-in resolver."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from x_npi.coverage import (
    close_covdb,
    compile_csv_to_el,
    merged_test_handle,
    open_covdb,
)
from x_npi.exclusion_csv import validate_directory
from x_npi.jsonio import error, ok, print_json
from x_npi.runtime import json_stdout_quarantine, pynpi_lifecycle

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--vdb", required=True)
    parser.add_argument("--csv-directory", required=True)
    parser.add_argument("--output-directory", required=True)
    parser.add_argument("--strict", action="store_true")
    args = parser.parse_args()
    with json_stdout_quarantine() as output:
        try:
            csv_status = validate_directory(args.csv_directory)
            with pynpi_lifecycle([sys.argv[0]]):
                db = open_covdb(args.vdb, strict=args.strict)
                try:
                    test = merged_test_handle(db)
                    published = compile_csv_to_el(
                        db,
                        test,
                        args.csv_directory,
                        args.output_directory,
                    )
                finally:
                    close_covdb(db)
            print_json(ok(
                "csv_to_el",
                {"items": published},
                {
                    "csv": csv_status,
                    "published_count": len(published),
                    "resolver": "builtin_indexed",
                    "npi_usage": "exclusion_only",
                    "complexity_contract": "exact-instance O(U), functional request-pruned",
                    "traversal_passes": sum(
                        item["preflight_passes"] + item["apply_passes"]
                        for item in published
                    ),
                    "visited_handle_count": sum(
                        item["visited_handle_count"] for item in published
                    ),
                    "reason_storage": "csv_sidecar_only",
                    "el_to_csv_lossless_supported": False,
                },
            ), output)
            return 0
        except Exception as exc:
            print_json(error("csv_to_el", "FAILED", str(exc)), output)
            return 1


if __name__ == "__main__":
    raise SystemExit(main())
