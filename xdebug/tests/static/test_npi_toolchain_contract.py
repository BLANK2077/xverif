from __future__ import annotations

import importlib.util
import re
from pathlib import Path


XDEBUG = Path(__file__).resolve().parents[2]


def _toolchain_module():
    path = XDEBUG / "tools" / "check_npi_toolchain.py"
    spec = importlib.util.spec_from_file_location(
        "xdebug_check_npi_toolchain", path
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_fixed_width_integer_headers_include_cstdint_directly() -> None:
    fixed_width_type = re.compile(
        r"\b(?:u?int(?:8|16|32|64)_t|std::u?int(?:8|16|32|64)_t)\b"
    )
    missing: list[str] = []
    for header in sorted((XDEBUG / "src").rglob("*.h")):
        text = header.read_text(encoding="utf-8")
        if fixed_width_type.search(text) and "#include <cstdint>" not in text:
            missing.append(str(header.relative_to(XDEBUG)))
    assert missing == []


def test_npi_toolchain_probe_reports_compiler_dual_abi() -> None:
    module = _toolchain_module()
    assert module.extract_dual_abi(
        "#define __GLIBCXX__ 20250101\n"
        "#define _GLIBCXX_USE_CXX11_ABI 1\n"
    ) == "1"
    assert module.extract_dual_abi("#define SOMETHING_ELSE 1\n") == "unknown"


def test_npi_toolchain_probe_classifies_l1_string_abi_link_failure() -> None:
    module = _toolchain_module()
    hint = module.abi_failure_hint(
        "undefined reference to `npi_fsdb_sig_value_at(void*, char const*, "
        "unsigned long long, std::string&, npiFsdbValType)'",
        "0",
    )
    assert hint is not None
    assert "libstdc++ dual ABI" in hint
    assert "_GLIBCXX_USE_CXX11_ABI=0" in hint
    assert module.abi_failure_hint("cannot find -lz", "1") is None


def test_internal_engine_runs_npi_toolchain_check_first() -> None:
    makefile = (XDEBUG / "Makefile").read_text(encoding="utf-8")
    assert "npi-toolchain-check:" in makefile
    assert re.search(
        r"^internal-engines:\s+npi-toolchain-check\s+"
        r"\$\(LIBEXEC\)/xdebug-engine$",
        makefile,
        re.MULTILINE,
    )
    assert "--cxxflags \"$(CXXFLAGS)\"" in makefile
    assert "--ldflags \"$(LDFLAGS)\"" in makefile
