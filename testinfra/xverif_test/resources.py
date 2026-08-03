from __future__ import annotations

import pytest

from .catalog import Suite


def apply_xdist_resource_group(item: pytest.Item, suite: Suite) -> None:
    tokens = {str(value) for value in suite.resources.get("tokens", [])}
    # Explicit catalog tokens are authoritative for the complete suite. For
    # capability-derived NPI serialization, constrain only pytest items that
    # actually consume a catalog fixture. Pytest's fixturenames includes
    # transitive dependencies, so wrapper fixtures remain covered while pure
    # schema/static tests in mixed suites can run in parallel.
    fixturenames = {
        str(value) for value in getattr(item, "fixturenames", ())
    }
    if "npi" in suite.capabilities and "xverif_fixture" in fixturenames:
        tokens.add("verdi_npi")
    if not tokens:
        return
    # loadgroup keeps all suites that claim the same normalized token set on one
    # worker, providing deterministic serialization without replacing xdist.
    group = "xverif-resource-" + "-".join(sorted(tokens))
    item.add_marker(pytest.mark.xdist_group(name=group))
