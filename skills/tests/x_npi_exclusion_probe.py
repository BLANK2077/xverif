from __future__ import annotations

import json
from pathlib import Path
import sys
from typing import Any, Callable

from x_npi.coverage import (
    close_covdb,
    load_exclusion_files,
    merged_test_handle,
    open_covdb,
    save_exclusion_file,
    set_report_time_excluded,
    unload_exclusions,
)
from x_npi.runtime import json_stdout_quarantine, pynpi_lifecycle


def _walk_children(
    cov: Any,
    parent: Any,
    callback: Callable[[Any], dict[str, Any] | None],
) -> dict[str, Any] | None:
    for child in list(parent.child_handles() or []):
        try:
            result = callback(child)
            if result is not None:
                return result
            result = _walk_children(cov, child, callback)
            if result is not None:
                return result
        finally:
            cov.release_handle(child)
    return None


def _exercise_line_exclusion(
    cov: Any,
    db: Any,
    test: Any,
    output: Path,
) -> dict[str, Any]:
    def exercise(item: Any) -> dict[str, Any] | None:
        if item.type() != "npiCovStmtBin" or int(item.coverable(test) or 0) <= 0:
            return None
        added = set_report_time_excluded(item, test, True)
        repeated = set_report_time_excluded(item, test, True)
        save_exclusion_file(test, output)
        removed = set_report_time_excluded(item, test, False)
        loaded = load_exclusion_files(test, [output])
        after_load = bool(item.has_status_excluded_at_report_time(test))
        unload_exclusions(test)
        after_unload = bool(item.has_status_excluded_at_report_time(test))
        return {
            "statuses": [added["status"], repeated["status"], removed["status"]],
            "loaded": loaded,
            "after_load": after_load,
            "after_unload": after_unload,
        }

    for inst in list(db.instance_handles() or []):
        try:
            metric = inst.line_metric_handle()
            if metric:
                try:
                    result = _walk_children(cov, metric, exercise)
                    if result is not None:
                        return result
                finally:
                    cov.release_handle(metric)
        finally:
            cov.release_handle(inst)
    raise RuntimeError("coverage fixture has no line score object")


def main() -> int:
    vdb = sys.argv[1]
    output = Path(sys.argv[2])
    with json_stdout_quarantine() as json_stream:
        with pynpi_lifecycle([sys.argv[0]]):
            from pynpi import cov  # type: ignore

            db = open_covdb(vdb)
            try:
                test = merged_test_handle(db)
                result = _exercise_line_exclusion(cov, db, test, output)
            finally:
                close_covdb(db)
        json.dump(result, json_stream, sort_keys=True)
        json_stream.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
