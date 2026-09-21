#!/usr/bin/env python3
"""Compile and link a minimal NPI L1 probe with the xdebug toolchain."""

from __future__ import annotations

import argparse
import re
import shlex
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Sequence


PROBE_SOURCE = """\
#include "npi_L1.h"
#include <string>

int main() {
    std::string value;
    return npi_fsdb_sig_value_at(
        nullptr, "", 0, value, npiFsdbBinStrVal);
}
"""


def split_command(value: str, field: str) -> list[str]:
    try:
        result = shlex.split(value)
    except ValueError as exc:
        raise ValueError(f"cannot parse {field}: {exc}") from exc
    if not result:
        raise ValueError(f"{field} must not be empty")
    return result


def split_flags(value: str, field: str) -> list[str]:
    try:
        return shlex.split(value)
    except ValueError as exc:
        raise ValueError(f"cannot parse {field}: {exc}") from exc


def extract_dual_abi(macros: str) -> str:
    match = re.search(
        r"^#define\s+_GLIBCXX_USE_CXX11_ABI\s+([^\s]+)\s*$",
        macros,
        re.MULTILINE,
    )
    return match.group(1) if match else "unknown"


def abi_failure_hint(linker_output: str, dual_abi: str) -> str | None:
    if (
        "npi_fsdb_sig_value_at" not in linker_output
        or "undefined reference" not in linker_output
    ):
        return None
    return (
        "The unresolved npi_fsdb_sig_value_at(std::string&) symbol usually "
        "means that the compiler's libstdc++ dual ABI does not match "
        "libnpiL1.so "
        f"(compiler _GLIBCXX_USE_CXX11_ABI={dual_abi}). Select a compiler "
        "whose C++ standard library ABI matches the local Verdi library; "
        "do not assume that forcing the macro overrides the compiler's "
        "c++config.h."
    )


def run_command(
    command: Sequence[str], source: str
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(command),
        input=source,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )


def check_toolchain(
    cxx: str,
    cxxflags: str,
    ldflags: str,
) -> tuple[bool, str]:
    compiler = split_command(cxx, "--cxx")
    compile_flags = split_flags(cxxflags, "--cxxflags")
    link_flags = split_flags(ldflags, "--ldflags")

    macro_command = [
        *compiler,
        *compile_flags,
        "-dM",
        "-E",
        "-x",
        "c++",
        "-",
    ]
    try:
        macro_result = run_command(macro_command, "#include <string>\n")
    except OSError as exc:
        return False, f"cannot execute compiler {compiler[0]!r}: {exc}"
    dual_abi = (
        extract_dual_abi(macro_result.stdout)
        if macro_result.returncode == 0
        else "unknown"
    )

    with tempfile.TemporaryDirectory(prefix="xdebug-npi-toolchain-") as tmp:
        output = Path(tmp) / "npi-link-probe"
        link_command = [
            *compiler,
            *compile_flags,
            "-x",
            "c++",
            "-",
            "-o",
            str(output),
            *link_flags,
        ]
        try:
            link_result = run_command(link_command, PROBE_SOURCE)
        except OSError as exc:
            return False, f"cannot execute compiler {compiler[0]!r}: {exc}"

    if link_result.returncode == 0:
        return True, f"NPI_TOOLCHAIN_OK cxx11_abi={dual_abi}"

    linker_output = "\n".join(
        part.strip()
        for part in (link_result.stdout, link_result.stderr)
        if part.strip()
    )
    lines = [
        "NPI toolchain preflight failed before the xdebug engine build.",
        f"compiler _GLIBCXX_USE_CXX11_ABI={dual_abi}",
    ]
    hint = abi_failure_hint(linker_output, dual_abi)
    if hint is not None:
        lines.append(hint)
    else:
        lines.append(
            "Verify the local NPI include/library paths, NPI_LDFLAGS, "
            "library order, and system zlib availability."
        )
    if linker_output:
        lines.extend(("compiler/linker output:", linker_output))
    return False, "\n".join(lines)


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(
        description=(
            "Compile and link a minimal npi_fsdb_sig_value_at probe without "
            "running NPI or acquiring a license."
        )
    )
    result.add_argument("--cxx", required=True)
    result.add_argument("--cxxflags", required=True)
    result.add_argument("--ldflags", required=True)
    return result


def main(argv: Sequence[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        ok, message = check_toolchain(
            args.cxx,
            args.cxxflags,
            args.ldflags,
        )
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    stream = sys.stdout if ok else sys.stderr
    print(message, file=stream)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
