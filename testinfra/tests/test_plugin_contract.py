from pathlib import Path
import tomllib

from testinfra.xverif_test.catalog import Catalog
from testinfra.xverif_test.dependencies import (
    load_default_dependency_registry,
    validate_suite_dependencies,
)


ROOT = Path(__file__).resolve().parents[2]


def test_all_declared_pytest_paths_exist() -> None:
    catalog = Catalog.load(
        ROOT / "testinfra/catalog.v1.yaml",
        ROOT / "testinfra/schemas/catalog.v1.schema.json",
    )
    missing = [
        path
        for suite in catalog.suites
        for path in suite.pytest_paths()
        if not (ROOT / path).exists()
    ]
    assert missing == []


def test_all_suite_dependencies_are_registered() -> None:
    catalog = Catalog.load(
        ROOT / "testinfra/catalog.v1.yaml",
        ROOT / "testinfra/schemas/catalog.v1.schema.json",
    )
    validate_suite_dependencies(catalog, load_default_dependency_registry(ROOT))


def test_pytest_defaults_to_live_tee_capture_for_progress() -> None:
    config = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    addopts = config["tool"]["pytest"]["ini_options"]["addopts"].split()
    assert "--capture=tee-sys" in addopts
