#!/usr/bin/env python3
"""Expand URG hierarchy targets and atomically compile standalone container exclusions."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from x_npi.container import plan_container_records, write_csv_set
from x_npi.coverage import close_covdb, compile_csv_to_el, merged_test_handle, open_covdb
from x_npi.jsonio import error, ok, print_json
from x_npi.runtime import json_stdout_quarantine, pynpi_lifecycle
from x_npi.urg import export_summary, parse_summary


def _pair(value: str) -> tuple[str, str]:
    parts = value.split(",")
    if len(parts) != 2 or not all(parts):
        raise argparse.ArgumentTypeError("expected SCOPE,COVERGROUP")
    return parts[0], parts[1]


def _triple(value: str) -> tuple[str, str, str]:
    parts = value.split(",")
    if len(parts) != 3 or not all(parts):
        raise argparse.ArgumentTypeError("expected SCOPE,COVERGROUP,ITEM")
    return parts[0], parts[1], parts[2]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--vdb", required=True)
    reports = parser.add_mutually_exclusive_group(required=True)
    reports.add_argument("--urg-report")
    reports.add_argument("--report-output")
    parser.add_argument("--csv-directory", required=True)
    parser.add_argument("--output-directory", required=True)
    parser.add_argument("--reason", required=True)
    parser.add_argument("--instance", action="append", default=[])
    parser.add_argument("--recursive-instance", action="append", default=[])
    parser.add_argument("--covergroup", action="append", type=_pair, default=[])
    parser.add_argument("--coverpoint", action="append", type=_triple, default=[])
    parser.add_argument("--cross", action="append", type=_triple, default=[])
    parser.add_argument("--strict", action="store_true")
    args = parser.parse_args()
    with json_stdout_quarantine() as output:
        try:
            summary = (
                parse_summary(args.urg_report)
                if args.urg_report
                else export_summary(args.vdb, args.report_output)
            )
            records = plan_container_records(
                summary, instances=args.instance,
                recursive_instances=args.recursive_instance,
                covergroups=args.covergroup, coverpoints=args.coverpoint,
                crosses=args.cross, reason=args.reason,
            )
            csv_paths = write_csv_set(args.csv_directory, records)
            with pynpi_lifecycle([sys.argv[0]]):
                db = open_covdb(args.vdb, strict=args.strict)
                try:
                    published = compile_csv_to_el(
                        db, merged_test_handle(db),
                        args.csv_directory, args.output_directory,
                    )
                finally:
                    close_covdb(db)
            print_json(ok("container_exclude", {"items": published}, {
                "requested_exact_target_count": len(records),
                "csv_paths": csv_paths,
                "npi_usage": "exclusion_only",
                "instance_traversal": "handle_by_name_no_hierarchy_scan",
                "functional_apply": "locator_trie_replay",
            }), output)
            return 0
        except Exception as exc:
            print_json(error("container_exclude", "FAILED", str(exc)), output)
            return 1


if __name__ == "__main__":
    raise SystemExit(main())
