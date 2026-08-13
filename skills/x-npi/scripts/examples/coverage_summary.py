#!/usr/bin/env python3
"""Export a typed coverage summary through URG; this script never loads pynpi."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from x_npi.jsonio import error, ok, print_json, split_limited
from x_npi.urg import export_summary


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Export fixed full64 URG typed coverage summary without pynpi traversal."
    )
    parser.add_argument("--vdb", required=True)
    parser.add_argument("--report", required=True, help="New directory for fixed URG artifacts")
    parser.add_argument("--elfile", help="Optional existing native EL applied by URG")
    parser.add_argument(
        "--metric", action="append",
        choices=[
            "line", "toggle", "branch", "condition", "fsm", "assert", "functional",
        ],
    )
    parser.add_argument("--scope", help="Exact scope or descendant prefix")
    parser.add_argument("--limit", type=int, default=200)
    parser.add_argument("--output", help="Optional JSON file containing all typed rows")
    args = parser.parse_args()
    try:
        if args.limit < 0:
            raise ValueError("--limit must be non-negative")
        summary = export_summary(args.vdb, args.report, elfile=args.elfile)
        rows = summary.rows(metrics=args.metric, scope=args.scope)
        shown, truncated = split_limited(rows, args.limit)
        roots = [row for row in summary.scopes if row["parent"] is None]
        selected_metrics = list(args.metric or sorted({
            metric for root in roots for metric in root["metrics"]
        }))
        pct_values = []
        for metric in selected_metrics:
            metric_roots = [
                root["metrics"][metric]
                for root in roots if metric in root["metrics"]
            ]
            covered = sum(int(value["covered"]) for value in metric_roots)
            coverable = sum(int(value["coverable"]) for value in metric_roots)
            if coverable > 0:
                pct_values.append(round(100.0 * covered / coverable, 4))
        result_summary = {
            "data_source": "urg_fixed_summary",
            "npi_initialized": False,
            "tests": list(summary.tests),
            "scope_count": len(summary.scopes),
            "root_scopes": [root["full_name"] for root in roots],
            "functional_row_count": len(summary.functional),
            "assertion_row_count": len(summary.assertions),
            "row_count": len(rows),
            "returned": len(shown),
            "truncated": truncated,
            "root_score_pct": (
                round(sum(pct_values) / len(pct_values), 4) if pct_values else None
            ),
            "root_score_basis": "arithmetic_mean_selected_metric_pct",
            "report_dir": str(summary.report_dir),
        }
        if args.output:
            output = Path(args.output)
            if output.exists() or output.is_symlink():
                raise ValueError("--output must not already exist")
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(
                json.dumps(
                    ok("coverage_summary", {"items": rows}, result_summary),
                    ensure_ascii=False, indent=2, sort_keys=True,
                ) + "\n",
                encoding="utf-8",
            )
            result_summary["output"] = str(output.resolve())
            shown = []
        print_json(ok("coverage_summary", {"items": shown}, result_summary))
        return 0
    except Exception as exc:
        print_json(error("coverage_summary", "FAILED", str(exc)))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
