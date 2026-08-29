from pathlib import Path

import pytest

from testinfra.xverif_test.catalog import Catalog, CatalogError
from testinfra.xverif_test.gates import build_plan, filter_plan
from testinfra.xverif_test.resources import apply_xdist_resource_group


ROOT = Path(__file__).resolve().parents[2]


def load_catalog() -> Catalog:
    return Catalog.load(
        ROOT / "testinfra/catalog.v1.yaml",
        ROOT / "testinfra/schemas/catalog.v1.schema.json",
    )


def test_catalog_loads_and_ids_are_unique() -> None:
    catalog = load_catalog()
    ids = [suite.id for suite in catalog.suites]
    assert len(ids) == len(set(ids))
    assert "xdebug.axi_vip" in ids
    assert "xsva.core" in ids
    assert "xdebug.cpp_unit" in ids
    assert {
        "skills.xverif", "skills.xverif_admin", "skills.xsimdebug",
        "skills.public_docs", "skills.x_npi", "skills.xwiki",
    } <= set(ids)


def test_gate_selection_is_monotonic() -> None:
    catalog = load_catalog()
    fast = build_plan(catalog, "fast").selected_ids()
    regression = build_plan(catalog, "regression").selected_ids()
    nightly = build_plan(catalog, "nightly").selected_ids()
    assert fast <= regression
    assert regression <= nightly
    assert "xdebug.apb_vip" not in regression
    assert "xdebug.apb_vip" in nightly
    assert "xdebug.apb_xamba_vip" not in regression
    assert "xdebug.apb_xamba_vip" in nightly
    assert "xdebug.axi_xamba_vip" not in regression
    assert "xdebug.axi_xamba_vip" in nightly
    assert "xdebug.cpp_unit" in regression
    assert "skills.x_npi_real" in regression
    assert "skills.x_npi_real" in nightly
    assert "skills.x_npi_perf" not in regression
    assert "skills.x_npi_perf" in nightly
    assert "xcov.urg_backend" in regression
    assert "xcov.urg_backend" in nightly
    assert "xcov.large_summary" in regression
    assert "xcov.large_summary" in nightly
    assert "xcov.edge_cases" in regression
    assert "xcov.edge_cases" in nightly


def test_optional_real_lsf_identity_is_preserved_in_nightly() -> None:
    plan = build_plan(load_catalog(), "nightly")
    optional = {
        item.suite.id for item in plan.suites if not item.required
    }
    assert {"xdebug.mcp_real_lsf", "xverif_mcp.real_lsf_jobid"} <= optional


def test_unknown_gate_is_rejected() -> None:
    with pytest.raises(CatalogError, match="unknown gate"):
        load_catalog().select_gate("everything")


def test_suite_filter_can_only_narrow_a_gate() -> None:
    regression = build_plan(load_catalog(), "regression")
    narrowed = filter_plan(regression, ["xloc.vim"])
    assert narrowed.selected_ids() == {"xloc.vim"}
    with pytest.raises(ValueError, match="not part of gate"):
        filter_plan(build_plan(load_catalog(), "fast"), ["xloc.vim"])


class TestResourceItem:
    __test__ = False

    def __init__(self, fixturenames: tuple[str, ...] = ()) -> None:
        self.fixturenames = fixturenames
        self.marker = None

    def add_marker(self, marker: object) -> None:
        self.marker = marker


def test_npi_capability_and_fixture_imply_common_xdist_resource_group() -> None:
    catalog = load_catalog()
    suite = next(item for item in catalog.suites if item.id == "xdebug.stream")

    item = TestResourceItem(("artifact_root", "xverif_fixture"))
    apply_xdist_resource_group(item, suite)  # type: ignore[arg-type]
    assert item.marker is not None
    assert item.marker.kwargs["name"] == "xverif-resource-verdi_npi"


def test_npi_capability_without_fixture_does_not_serialize_item() -> None:
    catalog = load_catalog()
    suite = next(item for item in catalog.suites if item.id == "xdebug.contract")

    item = TestResourceItem(("artifact_root",))
    apply_xdist_resource_group(item, suite)  # type: ignore[arg-type]
    assert item.marker is None


def test_explicit_resource_token_serializes_complete_suite() -> None:
    catalog = load_catalog()
    suite = next(item for item in catalog.suites if item.id == "skills.x_npi_real")

    item = TestResourceItem()
    apply_xdist_resource_group(item, suite)  # type: ignore[arg-type]
    assert item.marker is not None
    assert item.marker.kwargs["name"] == "xverif-resource-verdi_npi"


def test_native_xout_suite_declares_final_phase() -> None:
    suite = load_catalog().suite_by_id("xdebug.native_xout_all")
    assert suite.runner_env() == {"XDEBUG_XOUT_PHASE": "final"}
