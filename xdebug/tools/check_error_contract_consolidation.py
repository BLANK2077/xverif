#!/usr/bin/env python3
"""Prevent diagnostic ownership from splitting across xdebug layers."""

from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]


def require(path: str, needle: str) -> list[str]:
    text = (ROOT / path).read_text(encoding="utf-8")
    return [] if needle in text else [f"{path}: missing required consolidation marker: {needle}"]


def forbid(path: str, needle: str) -> list[str]:
    text = (ROOT / path).read_text(encoding="utf-8")
    return [f"{path}: forbidden duplicate diagnostic path remains: {needle}"] if needle in text else []


def main() -> int:
    errors: list[str] = []
    errors += require("src/core/schema/runtime_schema_validator.h", "OrderedJson error")
    errors += require("src/api/request_validator.h", "Json error")
    errors += require("src/core/diagnostic_error.h", "class DiagnosticErrorBuilder")
    errors += require("src/engine/service/engine_action_handler.cpp", 'return Json{{"error", error}};')
    errors += forbid("src/engine/server.cpp", 'response["details"]')
    errors += forbid("src/api/dispatcher.cpp", 'value("details"')
    errors += forbid("src/api/dispatcher.cpp", "public_error_keys")
    errors += forbid("src/api/request_validator.h", "Json data")
    errors += forbid("src/api/request_validator.h", "Json summary")
    errors += forbid("src/core/schema/runtime_schema_validator.h", "OrderedJson data")
    errors += forbid("src/core/schema/runtime_schema_validator.h", "OrderedJson summary")
    if errors:
        print("error contract consolidation check failed:")
        for error in errors:
            print(f"- {error}")
        return 1
    print("error contract consolidation check passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
