#!/usr/bin/env python3
"""Prevent response deduplication patches from returning to transport layers."""

from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]


def forbid(path: str, needle: str) -> list[str]:
    text = (ROOT / path).read_text()
    if needle not in text:
        return []
    return [f"{path}: forbidden response-layer repair remains: {needle}"]


def main() -> int:
    errors: list[str] = []
    errors += forbid("src/api/dispatcher.cpp", "*data_it == it.value()")
    errors += forbid("src/api/dispatcher.cpp", "data_payload.erase(data_it)")
    for path in (
        "src/engine/service/actions/waveform/expr_eval_at.cpp",
        "src/engine/service/actions/waveform/signal_sampled_pulse_inspect.cpp",
        "src/engine/service/actions/waveform/signal_changes.cpp",
        "src/engine/service/actions/waveform/signal_stability.cpp",
        "src/engine/service/actions/waveform/window_verify.cpp",
    ):
        errors += forbid(path, "Fix statistics end time")
        errors += forbid(path, 'name_ == "signal.changes"')
    for path in (
        "src/engine/service/actions/waveform/value_at.cpp",
        "src/engine/service/actions/waveform/verify_conditions.cpp",
    ):
        errors += forbid(path, 'out["sample_rows"]')
        errors += forbid(path, 'out["samples"]')
    if errors:
        print("response contract consolidation check failed:")
        for error in errors:
            print(f"- {error}")
        return 1
    print("response contract consolidation check passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
