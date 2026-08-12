from __future__ import annotations

import os
import re
from functools import lru_cache
from pathlib import Path

from testinfra.xverif_test.catalog import Catalog


ROOT = Path(__file__).resolve().parents[2]
IGNORED_TREE_PARTS = {".conda-xverif", ".xverif-test-cache", ".xverif-test-results", "tmp"}
GENERATED_TREE_PARTS = {
    ".git",
    ".pytest_cache",
    "artifacts",
    "build",
    "csrc",
    "dist",
    "npiLog",
    "out",
}
SOURCE_TREE_PRUNES = IGNORED_TREE_PARTS | GENERATED_TREE_PARTS
MACHINE_PATH_SOURCE_SUFFIXES = {
    ".c",
    ".cc",
    ".cpp",
    ".f",
    ".h",
    ".hpp",
    ".json",
    ".md",
    ".py",
    ".sh",
    ".sv",
    ".svh",
    ".toml",
    ".yaml",
    ".yml",
}
MACHINE_LOCAL_PATHS = (
    re.compile(r"(?<![A-Za-z0-9_.$})-])/" + "home/"),
    re.compile(
        r"(?<![A-Za-z0-9_.$})-])/(?:" + "root|opt|eda|proj|mnt|data|scratch|work|tools" + r")/"
    ),
    re.compile(r"(?<!<repo>)(?<![A-Za-z0-9_.$})-])/tmp/"),
    re.compile("~" + r"/(?!\.)"),
    re.compile(r"\$\{HOME\}/mini" + "conda3(?:/|\b)"),
    re.compile(r"(?<![A-Za-z0-9_.$})-])/bin/" + r"(?:tar|sh|false)(?:\b|/)"),
)
EXACT_RUNTIME_EVIDENCE_PATHS = {
    Path("doc/XDEBUG_XOUT_REAL_OUTPUT_REVIEW_2026-08-03.md"),
}
FORBIDDEN_TARGET = re.compile(
    r"^(?:test|check|full-test|unit-test|smoke|vim-test|pytest-[A-Za-z0-9_.-]+|mcp-[A-Za-z0-9_.-]+|[A-Za-z0-9_.-]+-test):"
)


def _catalog() -> Catalog:
    return Catalog.load(
        ROOT / "testinfra/catalog.v1.yaml",
        ROOT / "testinfra/schemas/catalog.v1.schema.json",
    )


def _walk_files(root: Path, pruned_names: frozenset[str]) -> tuple[Path, ...]:
    files: list[Path] = []
    for directory, dirnames, filenames in os.walk(root, topdown=True):
        dirnames[:] = sorted(
            name for name in dirnames
            if name not in pruned_names
        )
        base = Path(directory)
        files.extend(base / name for name in sorted(filenames))
    return tuple(files)


@lru_cache(maxsize=1)
def _source_files() -> tuple[Path, ...]:
    return _walk_files(ROOT, frozenset(SOURCE_TREE_PRUNES))


def test_every_collected_python_test_has_catalog_owner() -> None:
    catalog = _catalog()
    leaf_paths = {
        Path(value)
        for suite in catalog.suites
        for value in suite.runner.get("leaf_paths", [])
    }
    missing: list[str] = []
    for path in _source_files():
        if not path.name.startswith("test_") or path.suffix != ".py":
            continue
        relative = path.relative_to(ROOT)
        if not catalog.owners_for_path(path, ROOT) and relative not in leaf_paths:
            missing.append(relative.as_posix())
    assert missing == []


def test_legacy_pytest_configs_and_gate_scripts_are_absent() -> None:
    files = _source_files()
    assert [path for path in files if path.name == "pytest.ini"] == []
    nested_pytest_configs: list[Path] = []
    for path in files:
        if path.name != "pyproject.toml":
            continue
        if path == ROOT / "pyproject.toml":
            continue
        if "[tool.pytest.ini_options]" in path.read_text(encoding="utf-8"):
            nested_pytest_configs.append(path.relative_to(ROOT))
    assert nested_pytest_configs == []
    assert not (ROOT / "regression/run_xdebug_regression.sh").exists()
    assert not (ROOT / "regression/run_full_regression.sh").exists()


def test_makefiles_do_not_reintroduce_public_test_targets() -> None:
    violations: list[str] = []
    for path in _source_files():
        if not path.name.startswith("Makefile"):
            continue
        relative = path.relative_to(ROOT)
        if relative.parts and relative.parts[0] == "third_party":
            continue
        for number, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            if FORBIDDEN_TARGET.match(line):
                violations.append(f"{relative}:{number}:{line}")
    assert violations == []


def test_active_trace_cases_use_the_shared_builder_profile() -> None:
    root = ROOT / "xdebug/tests/active_trace_chain"
    assert list(root.glob("p0_composability/*/Makefile")) == []
    assert list(root.glob("composite/*/Makefile")) == []
    assert list(root.glob("timing/*/Makefile")) == []
    assert list(root.glob("phase4/*/Makefile")) == []
    assert not (root / "phase5/Makefile").exists()


def test_product_test_consumers_do_not_prepare_fixtures() -> None:
    forbidden = ('["make", "clean"]', '["make", "run"]', '["make", "fixture"]', "build_p3_db")
    violations: list[str] = []
    tests_root = ROOT / "xdebug/tests"
    for path in _source_files():
        if tests_root not in path.parents:
            continue
        if path.suffix not in {".py", ".sh"}:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for token in forbidden:
            if token in text:
                violations.append(f"{path.relative_to(ROOT)}:{token}")
    assert violations == []


def test_cross_process_flock_is_limited_to_session_lifecycle_lease() -> None:
    allowed = Path(
        "xdebug/src/engine/session/session_lifecycle_lease.h"
    )
    product_roots = (
        ROOT / "xdebug/src",
        ROOT / "xcov/xcov",
        ROOT / "xverif_mcp/src",
        ROOT / "testinfra/xverif_test",
    )
    call = re.compile(r"\b" + "flo" + r"ck\s*\(")
    python_call = "fcn" + "tl." + "flo" + "ck"
    violations: list[str] = []
    for product_root in product_roots:
        for path in _walk_files(product_root, frozenset(SOURCE_TREE_PRUNES)):
            if path.suffix not in {".c", ".cc", ".cpp", ".h", ".hpp", ".py"}:
                continue
            relative = path.relative_to(ROOT)
            text = path.read_text(encoding="utf-8", errors="replace")
            if relative == allowed:
                continue
            if call.search(text) or python_call in text:
                violations.append(relative.as_posix())
    assert violations == []


def test_cpp_unit_runner_matches_every_cpp_test_binary() -> None:
    from testinfra.leaf.run_xdebug_cpp_units import BINARIES

    sources = {
        path.stem for path in (ROOT / "xdebug/tests/unit").glob("test_*.cpp")
    }
    assert set(BINARIES) == sources


def test_every_testinfra_leaf_is_declared_by_catalog_or_fixture_registry() -> None:
    declared = (ROOT / "testinfra/catalog.v1.yaml").read_text(encoding="utf-8")
    declared += (ROOT / "testinfra/fixtures.v1.yaml").read_text(encoding="utf-8")
    leaves = {
        path.relative_to(ROOT).as_posix()
        for path in (ROOT / "testinfra/leaf").glob("*.py")
        if path.name != "__init__.py"
    }
    assert all(path in declared for path in leaves)


def test_repository_has_no_machine_specific_local_paths() -> None:
    violations: list[str] = []
    for path in _source_files():
        relative = path.relative_to(ROOT)
        # 这份报告逐字固化真实请求与 XOUT；路径脱敏会破坏 byte/SHA 证据合同。
        # 它的范围由下面的精确集合断言锁定，并由 native XOUT 报告测试独立验真。
        if relative in EXACT_RUNTIME_EVIDENCE_PATHS:
            continue
        if path.name != "Makefile" and path.suffix not in MACHINE_PATH_SOURCE_SUFFIXES:
            continue
        for number, line in enumerate(
            path.read_text(encoding="utf-8", errors="replace").splitlines(), 1
        ):
            if any(pattern.search(line) for pattern in MACHINE_LOCAL_PATHS):
                violations.append(f"{relative}:{number}:{line.strip()}")
    assert violations == []


def test_machine_path_exception_is_limited_to_exact_xout_evidence() -> None:
    assert EXACT_RUNTIME_EVIDENCE_PATHS == {
        Path("doc/XDEBUG_XOUT_REAL_OUTPUT_REVIEW_2026-08-03.md"),
    }
    assert all((ROOT / path).is_file() for path in EXACT_RUNTIME_EVIDENCE_PATHS)


def test_source_walk_prunes_generated_trees_before_descent(tmp_path: Path) -> None:
    source = tmp_path / "src/test_visible.py"
    ignored = tmp_path / "build/nested/test_hidden.py"
    source.parent.mkdir()
    ignored.parent.mkdir(parents=True)
    source.write_text("visible = True\n", encoding="utf-8")
    ignored.write_text("hidden = True\n", encoding="utf-8")

    files = _walk_files(tmp_path, frozenset({"build"}))

    assert source in files
    assert ignored not in files
