#!/usr/bin/env python3
"""Semantic probe for the generated large-summary VDB and fixed URG contract."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import xml.etree.ElementTree as ET


EXPECTED = {
    "leaf_count": 3000,
    "expected_instance_scope_count": 3001,
    "port_count_per_leaf": 25,
    "data_port_count_per_leaf": 10,
    "data_width_bits": 128,
    "simulation_cycles": 256,
    "rtl_line_count": 375_053,
}
REQUIRED_ARTIFACTS = (
    "session.xml", "tests.txt", "dashboard.txt", "modlist.txt",
    "groups.txt", "asserts.txt",
)
CODE_METRICS = {"Line", "Cond", "Toggle", "FSM", "Branch", "Assert"}


def _urg() -> Path:
    raw = os.environ.get("VCS_HOME")
    if not raw or raw != raw.strip():
        raise RuntimeError("VCS_HOME is required for the large-summary probe")
    home = Path(raw).resolve(strict=True)
    urg = (home / "bin" / "urg").resolve(strict=True)
    urg.relative_to(home)
    if not urg.is_file() or not os.access(urg, os.X_OK):
        raise RuntimeError("VCS_HOME/bin/urg is not executable")
    return urg


def probe(resources: Path) -> dict[str, object]:
    metadata_path = resources / "fixture_metadata.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    for key, expected in EXPECTED.items():
        if metadata.get(key) != expected:
            raise RuntimeError(
                f"fixture metadata mismatch for {key}: {metadata.get(key)!r} != {expected!r}"
            )
    vdb = (resources / "large_summary.vdb").resolve(strict=True)
    if not (vdb / ".vdb_version").is_file():
        raise RuntimeError("large_summary.vdb is missing .vdb_version")
    report = resources / ".probe-large-summary"
    argv = [
        str(_urg()), "-full64", "-dir", str(vdb), "-report", str(report),
        "-xml_verbose", "-format", "text", "-show", "summary",
    ]
    completed = subprocess.run(
        argv, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        timeout=1200, check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            f"URG probe failed with {completed.returncode}: {completed.stdout[-2000:]}"
        )
    for name in REQUIRED_ARTIFACTS:
        path = report / name
        if not path.is_file() or path.stat().st_size == 0:
            raise RuntimeError(f"fixed URG summary artifact is missing or empty: {name}")

    instance_scopes = 0
    functional_nodes = 0
    assertion_nodes = 0
    root_metrics: set[str] = set()
    scope_stack: list[tuple[str, str]] = []
    command = ""
    for event, elem in ET.iterparse(report / "session.xml", events=("start", "end")):
        if event == "start" and elem.tag == "scope":
            scope_type = elem.get("type", "")
            scope_name = elem.get("name", "")
            scope_stack.append((scope_type, scope_name))
            if scope_type == "instance":
                instance_scopes += 1
            if scope_type in {
                "Cover Group", "Covergroup Variant", "Coverage Instance",
                "Coverage Point", "Cross Coverage",
            }:
                functional_nodes += 1
            if scope_type in {"Assertion", "Cover Property"}:
                assertion_nodes += 1
        elif event == "end" and elem.tag == "metric" and scope_stack:
            if scope_stack[-1] == ("instance", "top"):
                root_metrics.add(elem.get("name", ""))
        elif event == "end" and elem.tag == "attr":
            if elem.get("name") == "command":
                command = elem.get("value", "")
        elif event == "end" and elem.tag == "scope":
            scope_stack.pop()
            elem.clear()

    if instance_scopes != EXPECTED["expected_instance_scope_count"]:
        raise RuntimeError(
            f"instance scope count mismatch: {instance_scopes} != 3001"
        )
    if not CODE_METRICS.issubset(root_metrics):
        raise RuntimeError(f"root code/assert SCORE metrics are incomplete: {root_metrics}")
    if functional_nodes == 0 or assertion_nodes == 0:
        raise RuntimeError(
            f"typed coverage missing: functional={functional_nodes} assertion={assertion_nodes}"
        )
    for token in ("-full64", "-xml_verbose", "-format text", "-show summary"):
        if token not in command:
            raise RuntimeError(f"session.xml command is missing fixed option {token!r}")
    result = {
        "instance_scope_count": instance_scopes,
        "functional_node_count": functional_nodes,
        "assertion_node_count": assertion_nodes,
        "root_metrics": sorted(root_metrics),
        "urg_options": [
            "-full64", "-xml_verbose", "-format", "text", "-show", "summary",
        ],
    }
    (resources / "large_summary_probe.json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--resources", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(probe(args.resources.resolve(strict=True)), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
