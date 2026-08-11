#!/usr/bin/env python3
"""Compile strict xcov CSV sidecars into opaque EL through an exact resolver."""
from __future__ import annotations

import argparse
import importlib
import sys
from pathlib import Path
from typing import Any, Callable

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


def _resolver_factory(spec: str) -> Callable[[Any, Any], Any]:
    if ":" not in spec:
        raise ValueError("--resolver must be MODULE:FACTORY")
    module_name, function_name = spec.split(":", 1)
    module = importlib.import_module(module_name)
    factory = getattr(module, function_name)
    if not callable(factory):
        raise TypeError("resolver factory is not callable")
    return factory


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--vdb", required=True)
    parser.add_argument("--csv-directory", required=True)
    parser.add_argument("--output-directory", required=True)
    parser.add_argument(
        "--resolver", required=True, metavar="MODULE:FACTORY",
        help=(
            "Factory(db,test)->resolver; resolver(kind,source_file,row) must return "
            "a context manager yielding one freshly traversed exact NPI score handle"
        ),
    )
    parser.add_argument("--strict", action="store_true")
    args = parser.parse_args()
    with json_stdout_quarantine() as output:
        try:
            csv_status = validate_directory(args.csv_directory)
            factory = _resolver_factory(args.resolver)
            with pynpi_lifecycle([sys.argv[0]]):
                db = open_covdb(args.vdb, strict=args.strict)
                try:
                    test = merged_test_handle(db)
                    resolver = factory(db, test)
                    if not callable(resolver):
                        raise TypeError("resolver factory did not return a callable")
                    published = compile_csv_to_el(
                        test,
                        args.csv_directory,
                        args.output_directory,
                        resolver,
                    )
                finally:
                    close_covdb(db)
            print_json(ok(
                "csv_to_el",
                {"items": published},
                {
                    "csv": csv_status,
                    "published_count": len(published),
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
