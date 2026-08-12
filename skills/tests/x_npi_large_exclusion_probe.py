from __future__ import annotations

import argparse
import csv
import io
import json
from pathlib import Path
import sys
from typing import Any

from x_npi.coverage import (
    close_covdb,
    compile_csv_to_el,
    merged_test_handle,
    open_covdb,
)
from x_npi.runtime import json_stdout_quarantine, pynpi_lifecycle


def _release(cov: Any, handle: Any) -> None:
    if handle:
        cov.release_handle(handle)


def _first_line(cov: Any, parent: Any, test: Any,
                source: str = "", line: int = 0) -> tuple[str, int] | None:
    own_source = parent.file_name()
    own_line = parent.line_no(test)
    source = own_source if isinstance(own_source, str) and own_source else source
    line = own_line if isinstance(own_line, int) and own_line > 0 else line
    if parent.type() == "npiCovStmtBin" and source and line > 0:
        return source, line
    for child in list(parent.child_handles() or []):
        try:
            found = _first_line(cov, child, test, source, line)
            if found:
                return found
        finally:
            _release(cov, child)
    return None


def _target_line(cov: Any, db: Any, test: Any, scope: str) -> tuple[str, int]:
    pending = list(db.instance_handles() or [])
    while pending:
        instance = pending.pop()
        try:
            full_name = instance.full_name()
            if full_name == scope:
                metric = instance.line_metric_handle()
                if not metric:
                    raise RuntimeError(f"scope has no line metric: {scope}")
                try:
                    found = _first_line(cov, metric, test)
                finally:
                    _release(cov, metric)
                if not found:
                    raise RuntimeError(f"scope has no line score target: {scope}")
                return found
            if scope.startswith(str(full_name) + "."):
                pending.extend(list(instance.instance_handles() or []))
        finally:
            _release(cov, instance)
    raise RuntimeError(f"coverage scope is missing: {scope}")


def _write_csv(root: Path, source: str, line: int, scope: str) -> None:
    root.mkdir(parents=True)
    record = io.StringIO()
    csv.writer(record, lineterminator="\n").writerow(
        [scope, "line", str(line), "", "", "large fixture linear guard"]
    )
    (root / "code_exclusions.csv").write_text(
        "# schema_version=xcov-code-exclusions.v1\n"
        "# coverage_kind=code\n"
        "scope,metric,line,object,bin,reason\n"
        f"# source_file={Path(source).name}\n" + record.getvalue(),
        encoding="utf-8",
    )
    (root / "functional_exclusions.csv").write_text(
        "# schema_version=xcov-functional-exclusions.v1\n"
        "# coverage_kind=functional\n"
        "scope,line,covergroup,coverpoint,cross,bin,reason\n",
        encoding="utf-8",
    )
    (root / "assertion_exclusions.csv").write_text(
        "# schema_version=xcov-assertion-exclusions.v1\n"
        "# coverage_kind=assertion\n"
        "scope,line,assertion,assertion_kind,reason\n",
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--vdb", required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--scope", default="top.u_leaf_0000")
    args = parser.parse_args()
    with json_stdout_quarantine() as output:
        with pynpi_lifecycle([sys.argv[0]]):
            from pynpi import cov  # type: ignore

            db = open_covdb(args.vdb)
            try:
                test = merged_test_handle(db)
                source, line = _target_line(cov, db, test, args.scope)
                csv_root = args.output_root / "csv"
                _write_csv(csv_root, source, line, args.scope)
                published = compile_csv_to_el(
                    db, test, csv_root, args.output_root / "el",
                )
            finally:
                close_covdb(db)
        json.dump({"source": source, "line": line, "items": published}, output,
                  sort_keys=True)
        output.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
