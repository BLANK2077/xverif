"""MCP SDK xcov 全链路集成测试.

通过真实 ``tools/xcov --stdio-loop`` 子进程测试 MCP transport 链路。
需要 Verdi/VCS 环境和有效的 coverage VDB。

运行方式：
  XVERIF_TEST_EXECUTION_ENV=host pytest --xverif-gate regression \\
      --xverif-suite xcov.mcp_integration -v
"""

from __future__ import annotations

import importlib
import json
import os
import sys
from pathlib import Path
from typing import Any

import anyio
import pytest

XDEBUG_DIR = Path(__file__).resolve().parents[2] / "xdebug"
sys.path = [
    path for path in sys.path
    if Path(path or os.getcwd()).resolve() != XDEBUG_DIR
]

sys.modules.pop("mcp", None)
pytest.importorskip("mcp")

POLICY_ENV = [
    "XVERIF_MCP_ENABLE_COMMON",
    "XVERIF_MCP_ENABLE_DEBUG",
    "XVERIF_MCP_ENABLE_COV",
    "XVERIF_MCP_ENABLE_BIT",
    "XVERIF_MCP_ENABLE_ENTRY",
    "XVERIF_MCP_ENABLE_LOC",
    "XVERIF_MCP_ENABLE_SVA",
]


def _server(monkeypatch, overrides=None):
    for name in POLICY_ENV:
        monkeypatch.delenv(name, raising=False)
    for name, value in (overrides or {}).items():
        monkeypatch.setenv(name, value)
    if "xverif_mcp.server" in sys.modules:
        return importlib.reload(sys.modules["xverif_mcp.server"])
    return importlib.import_module("xverif_mcp.server")


def _call_tool(server, name, args=None):
    async def _run():
        result = await server.mcp.call_tool(name, args or {})
        return result if isinstance(result, tuple) else (result, None)
    return anyio.run(_run)


def _resolve_test_vdb() -> str:
    env = os.environ.get("XVERIF_TEST_VDB")
    if env and os.path.isdir(env):
        return env

    xverif_home = os.environ.get("XVERIF_HOME") or str(
        Path(__file__).resolve().parents[2]
    )
    candidates = [
        os.path.join(xverif_home, "xcov", "fixtures", "comprehensive", "out", "comprehensive.vdb"),
    ]
    for c in candidates:
        if os.path.isdir(c):
            return c
    pytest.skip("XVERIF_TEST_VDB not set and no default VDB found; run: pytest --xverif-prepare xcov.comprehensive")


@pytest.fixture(scope="module")
def test_vdb():
    return _resolve_test_vdb()


@pytest.fixture(scope="module")
def exclusion_vdb():
    xverif_home = os.environ.get("XVERIF_HOME") or str(Path(__file__).resolve().parents[2])
    versions_dir = os.path.join(xverif_home, ".xverif-test-cache", "fixtures", "xcov.exclusion", "versions")
    if os.path.isdir(versions_dir):
        for vhash in sorted(os.listdir(versions_dir), reverse=True):
            vdb = os.path.join(versions_dir, vhash, "resources", "exclusion.vdb")
            if os.path.isdir(vdb):
                return vdb
    pytest.skip("exclusion VDB not found; run: pytest --xverif-prepare xcov.exclusion")


@pytest.fixture(scope="module")
def xverif_home():
    return os.environ.get("XVERIF_HOME") or str(
        Path(__file__).resolve().parents[2]
    )


# ── 测试 ──


def test_cov_list_actions(monkeypatch):
    """xverif_cov_list_actions 返回所有 xcov action."""
    overrides = {
        "XVERIF_HOME": str(Path(__file__).resolve().parents[2]),
    }
    server = _server(monkeypatch, overrides)
    content, _ = _call_tool(server, "xverif_cov_list_actions")
    payload = json.loads(content[0].text)
    assert payload["ok"] is True
    actions = payload["data"]["items"]
    assert len(actions) >= 20
    names = {a["name"] for a in actions}
    assert "session.open" in names
    assert "code_coverage.summary" in names
    assert "scope.summary" in names


def test_cov_session_open_close(monkeypatch, test_vdb, xverif_home):
    """xverif_cov_session_open/close 完整生命周期."""
    overrides = {
        "XVERIF_HOME": xverif_home,
        "XVERIF_MCP_BACKEND": "direct",
    }
    server = _server(monkeypatch, overrides)

    # Open
    content, _ = _call_tool(server, "xverif_cov_session_open", {
        "name": "mcp_int_open_close",
        "vdb": test_vdb,
    })
    opened = json.loads(content[0].text)
    assert opened["ok"] is True, f"session.open failed: {opened.get('error')}"
    assert opened["session"]["session_id"] == "mcp_int_open_close"
    assert opened["session"]["state"] == "alive"

    # Close
    content, _ = _call_tool(server, "xverif_cov_session_close", {
        "session_id": "mcp_int_open_close",
    })
    closed = json.loads(content[0].text)
    assert closed["ok"] is True


def test_cov_code_coverage_summary(monkeypatch, test_vdb, xverif_home):
    """xverif_cov_query(code_coverage.summary) 按 metric 汇总."""
    overrides = {
        "XVERIF_HOME": xverif_home,
        "XVERIF_MCP_BACKEND": "direct",
    }
    server = _server(monkeypatch, overrides)

    _call_tool(server, "xverif_cov_session_open", {
        "name": "mcp_int_summary", "vdb": test_vdb,
    })

    content, _ = _call_tool(server, "xverif_cov_query", {
        "session_id": "mcp_int_summary",
        "action": "code_coverage.summary",
        "args": {"group_by": "metric"},
        "output_format": "json",
    })
    payload = json.loads(content[0].text)
    assert payload["ok"] is True, f"query failed: {payload.get('error')}"

    items = payload["data"]["items"]
    assert len(items) >= 5, f"expected >=5 metrics, got {len(items)}"

    metrics = {item["metric"] for item in items}
    for expected in ("line", "toggle", "branch", "condition", "fsm"):
        assert expected in metrics, f"missing metric: {expected}"

    for item in items:
        assert isinstance(item["covered"], int)
        assert isinstance(item["coverable"], int)
        assert item["coverable"] > 0
        assert "coverage_pct" in item

    _call_tool(server, "xverif_cov_session_close", {
        "session_id": "mcp_int_summary",
    })


def test_cov_code_coverage_holes(monkeypatch, test_vdb, xverif_home):
    """xverif_cov_query(code_coverage.holes) 返回未覆盖项列表."""
    overrides = {
        "XVERIF_HOME": xverif_home,
        "XVERIF_MCP_BACKEND": "direct",
    }
    server = _server(monkeypatch, overrides)

    _call_tool(server, "xverif_cov_session_open", {
        "name": "mcp_int_holes", "vdb": test_vdb,
    })

    content, _ = _call_tool(server, "xverif_cov_query", {
        "session_id": "mcp_int_holes",
        "action": "code_coverage.holes",
        "args": {"metrics": ["toggle"], "limits": {"max_items": 10}},
        "output_format": "json",
    })
    payload = json.loads(content[0].text)
    assert payload["ok"] is True

    items = payload["data"]["items"]
    assert payload["summary"]["returned_count"] <= 10

    # holes items have coverage_pct and per-metric pct fields
    for item in items:
        assert "coverage_pct" in item
        assert "full_name" in item
        # at least one metric-specific pct field should be present
        metric_pcts = [item.get(k) for k in (
            "line_pct", "toggle_pct", "branch_pct", "condition_pct", "fsm_pct", "assert_pct"
        )]
        assert any(v is not None for v in metric_pcts), \
            f"no metric_pct in hole item: {list(item.keys())}"

    _call_tool(server, "xverif_cov_session_close", {
        "session_id": "mcp_int_holes",
    })


def test_cov_scope_summary(monkeypatch, test_vdb, xverif_home):
    """xverif_cov_query(scope.summary) 返回指定 scope 的覆盖率."""
    overrides = {
        "XVERIF_HOME": xverif_home,
        "XVERIF_MCP_BACKEND": "direct",
    }
    server = _server(monkeypatch, overrides)

    _call_tool(server, "xverif_cov_session_open", {
        "name": "mcp_int_scope", "vdb": test_vdb,
    })

    content, _ = _call_tool(server, "xverif_cov_query", {
        "session_id": "mcp_int_scope",
        "action": "scope.summary",
        "args": {"scope": "top"},
        "output_format": "json",
    })
    payload = json.loads(content[0].text)
    assert payload["ok"] is True

    items = payload["data"]["items"]
    assert len(items) >= 1

    top_item = next((i for i in items if i.get("full_name") == "top"), None)
    assert top_item is not None, f"no 'top' scope in items: {[i.get('full_name') for i in items]}"

    _call_tool(server, "xverif_cov_session_close", {
        "session_id": "mcp_int_scope",
    })


def test_cov_scope_children(monkeypatch, test_vdb, xverif_home):
    """xverif_cov_query(scope.children) 返回子 scope 列表."""
    overrides = {
        "XVERIF_HOME": xverif_home,
        "XVERIF_MCP_BACKEND": "direct",
    }
    server = _server(monkeypatch, overrides)

    _call_tool(server, "xverif_cov_session_open", {
        "name": "mcp_int_children", "vdb": test_vdb,
    })

    content, _ = _call_tool(server, "xverif_cov_query", {
        "session_id": "mcp_int_children",
        "action": "scope.children",
        "args": {"scope": "top"},
        "output_format": "json",
    })
    payload = json.loads(content[0].text)
    assert payload["ok"] is True

    items = payload["data"]["items"]
    child_names = {c["name"] for c in items}
    # comprehensive fixture has u_core0 and u_core1 under top
    assert "u_core0" in child_names or "u_core1" in child_names, \
        f"expected u_core0/u_core1 under top, got: {child_names}"

    _call_tool(server, "xverif_cov_session_close", {
        "session_id": "mcp_int_children",
    })


def test_cov_export_code_coverage(monkeypatch, test_vdb, xverif_home, tmp_path):
    """xverif_cov_query(export.code_coverage) 导出 URG modinfo."""
    overrides = {
        "XVERIF_HOME": xverif_home,
        "XVERIF_MCP_BACKEND": "direct",
    }
    server = _server(monkeypatch, overrides)

    _call_tool(server, "xverif_cov_session_open", {
        "name": "mcp_int_export", "vdb": test_vdb,
    })

    output_dir = str(tmp_path / "export_code")
    content, _ = _call_tool(server, "xverif_cov_query", {
        "session_id": "mcp_int_export",
        "action": "export.code_coverage",
        "args": {
            "output": {"path": output_dir},
        },
        "output_format": "json",
    })
    payload = json.loads(content[0].text)
    assert payload["ok"] is True

    # Check output files exist
    found = list(Path(output_dir).glob("*.modinfo")) + list(Path(output_dir).glob("*"))
    assert len(found) > 0, f"no export output in {output_dir}"

    _call_tool(server, "xverif_cov_session_close", {
        "session_id": "mcp_int_export",
    })


def test_cov_export_functional(monkeypatch, test_vdb, xverif_home, tmp_path):
    """xverif_cov_query(export.functional_coverage) 导出 URG grpinfo."""
    overrides = {
        "XVERIF_HOME": xverif_home,
        "XVERIF_MCP_BACKEND": "direct",
    }
    server = _server(monkeypatch, overrides)

    _call_tool(server, "xverif_cov_session_open", {
        "name": "mcp_int_export_func", "vdb": test_vdb,
    })

    output_dir = str(tmp_path / "export_func")
    content, _ = _call_tool(server, "xverif_cov_query", {
        "session_id": "mcp_int_export_func",
        "action": "export.functional_coverage",
        "args": {
            "output": {"path": output_dir},
        },
        "output_format": "json",
    })
    payload = json.loads(content[0].text)
    assert payload["ok"] is True

    found = list(Path(output_dir).glob("*"))
    assert len(found) > 0, f"no export output in {output_dir}"

    _call_tool(server, "xverif_cov_session_close", {
        "session_id": "mcp_int_export_func",
    })


def test_cov_export_assert(monkeypatch, test_vdb, xverif_home, tmp_path):
    """xverif_cov_query(export.assert) 导出 URG assert 数据."""
    overrides = {
        "XVERIF_HOME": xverif_home,
        "XVERIF_MCP_BACKEND": "direct",
    }
    server = _server(monkeypatch, overrides)

    _call_tool(server, "xverif_cov_session_open", {
        "name": "mcp_int_export_assert", "vdb": test_vdb,
    })

    output_dir = str(tmp_path / "export_assert")
    content, _ = _call_tool(server, "xverif_cov_query", {
        "session_id": "mcp_int_export_assert",
        "action": "export.assert",
        "args": {
            "output": {"path": output_dir},
        },
        "output_format": "json",
    })
    payload = json.loads(content[0].text)
    assert payload["ok"] is True

    found = list(Path(output_dir).glob("*"))
    assert len(found) > 0, f"no export output in {output_dir}"

    _call_tool(server, "xverif_cov_session_close", {
        "session_id": "mcp_int_export_assert",
    })


def test_cov_assert_summary(monkeypatch, test_vdb, xverif_home):
    """xverif_cov_query(assert.summary) 返回 assertion 汇总."""
    overrides = {
        "XVERIF_HOME": xverif_home,
        "XVERIF_MCP_BACKEND": "direct",
    }
    server = _server(monkeypatch, overrides)

    _call_tool(server, "xverif_cov_session_open", {
        "name": "mcp_int_assert", "vdb": test_vdb,
    })

    content, _ = _call_tool(server, "xverif_cov_query", {
        "session_id": "mcp_int_assert",
        "action": "assert.summary",
        "args": {},
        "output_format": "json",
    })
    payload = json.loads(content[0].text)
    assert payload["ok"] is True

    _call_tool(server, "xverif_cov_session_close", {
        "session_id": "mcp_int_assert",
    })


def test_cov_functional_summary(monkeypatch, test_vdb, xverif_home):
    """xverif_cov_query(functional_coverage.summary) 返回 functional 汇总."""
    overrides = {
        "XVERIF_HOME": xverif_home,
        "XVERIF_MCP_BACKEND": "direct",
    }
    server = _server(monkeypatch, overrides)

    _call_tool(server, "xverif_cov_session_open", {
        "name": "mcp_int_func_summary", "vdb": test_vdb,
    })

    content, _ = _call_tool(server, "xverif_cov_query", {
        "session_id": "mcp_int_func_summary",
        "action": "functional_coverage.summary",
        "args": {"group_by": "covergroup"},
        "output_format": "json",
    })
    payload = json.loads(content[0].text)
    assert payload["ok"] is True

    _call_tool(server, "xverif_cov_session_close", {
        "session_id": "mcp_int_func_summary",
    })


def test_cov_metrics_list(monkeypatch, test_vdb, xverif_home):
    """xverif_cov_query(metrics.list) 返回可用 metric 列表."""
    overrides = {
        "XVERIF_HOME": xverif_home,
        "XVERIF_MCP_BACKEND": "direct",
    }
    server = _server(monkeypatch, overrides)

    _call_tool(server, "xverif_cov_session_open", {
        "name": "mcp_int_metrics", "vdb": test_vdb,
    })

    content, _ = _call_tool(server, "xverif_cov_query", {
        "session_id": "mcp_int_metrics",
        "action": "metrics.list",
        "args": {},
        "output_format": "json",
    })
    payload = json.loads(content[0].text)
    assert payload["ok"] is True

    _call_tool(server, "xverif_cov_session_close", {
        "session_id": "mcp_int_metrics",
    })


def test_cov_tests_list(monkeypatch, test_vdb, xverif_home):
    """xverif_cov_query(tests.list) 返回 test 列表."""
    overrides = {
        "XVERIF_HOME": xverif_home,
        "XVERIF_MCP_BACKEND": "direct",
    }
    server = _server(monkeypatch, overrides)

    _call_tool(server, "xverif_cov_session_open", {
        "name": "mcp_int_tests", "vdb": test_vdb,
    })

    content, _ = _call_tool(server, "xverif_cov_query", {
        "session_id": "mcp_int_tests",
        "action": "tests.list",
        "args": {},
        "output_format": "json",
    })
    payload = json.loads(content[0].text)
    assert payload["ok"] is True

    _call_tool(server, "xverif_cov_session_close", {
        "session_id": "mcp_int_tests",
    })


def test_cov_xout_output_format(monkeypatch, test_vdb, xverif_home):
    """xverif_cov_query 以 xout 格式返回结构化文本."""
    overrides = {
        "XVERIF_HOME": xverif_home,
        "XVERIF_MCP_BACKEND": "direct",
    }
    server = _server(monkeypatch, overrides)

    _call_tool(server, "xverif_cov_session_open", {
        "name": "mcp_int_xout", "vdb": test_vdb,
    })

    content, _ = _call_tool(server, "xverif_cov_query", {
        "session_id": "mcp_int_xout",
        "action": "code_coverage.summary",
        "args": {"group_by": "metric"},
        "output_format": "xout",
    })
    text = content[0].text
    assert text.startswith("@xcov.code_coverage.summary.v1"), \
        f"unexpected xout header: {text[:80]}"

    _call_tool(server, "xverif_cov_session_close", {
        "session_id": "mcp_int_xout",
    })


# ── exclude.add / exclude.remove with selectors ──


def test_cov_exclude_add_with_selector(monkeypatch, exclusion_vdb, xverif_home):
    """xverif_cov_query(exclude.add) 用 selector 排除一个 line item."""
    overrides = {"XVERIF_HOME": xverif_home, "XVERIF_MCP_BACKEND": "direct"}
    server = _server(monkeypatch, overrides)

    _call_tool(server, "xverif_cov_session_open", {"name": "mcp_excl_add", "vdb": exclusion_vdb})
    content, _ = _call_tool(server, "xverif_cov_query", {
        "session_id": "mcp_excl_add", "action": "exclude.add",
        "args": {"selectors": [{"metric": "line", "scope": "top",
                                "file": "exclusion_fixture.sv", "line": 72}]},
        "output_format": "json",
    })
    payload = json.loads(content[0].text)
    assert payload["ok"] is True
    assert payload["data"]["items"][0]["status"] == "changed"

    _call_tool(server, "xverif_cov_session_close", {"session_id": "mcp_excl_add"})


def test_cov_exclude_add_invalid_selector(monkeypatch, exclusion_vdb, xverif_home):
    """xverif_cov_query(exclude.add) 无效 selector 返回 errors + note."""
    overrides = {"XVERIF_HOME": xverif_home, "XVERIF_MCP_BACKEND": "direct"}
    server = _server(monkeypatch, overrides)

    _call_tool(server, "xverif_cov_session_open", {"name": "mcp_excl_inv", "vdb": exclusion_vdb})
    content, _ = _call_tool(server, "xverif_cov_query", {
        "session_id": "mcp_excl_inv", "action": "exclude.add",
        "args": {"selectors": [{"metric": "unknown", "scope": "top"}]},
        "output_format": "json",
    })
    payload = json.loads(content[0].text)
    assert payload["ok"] is True  # action succeeds; item has status=invalid
    item = payload["data"]["items"][0]
    assert item["status"] == "invalid"
    assert len(item.get("errors", [])) > 0
    assert item.get("errors", [{}])[0]["code"] == "INVALID_METRIC"
    assert "note" in item

    _call_tool(server, "xverif_cov_session_close", {"session_id": "mcp_excl_inv"})


def test_cov_exclude_remove_with_selector(monkeypatch, exclusion_vdb, xverif_home):
    """xverif_cov_query(exclude.add + exclude.remove) 完整排除/恢复流程."""
    overrides = {"XVERIF_HOME": xverif_home, "XVERIF_MCP_BACKEND": "direct"}
    server = _server(monkeypatch, overrides)

    _call_tool(server, "xverif_cov_session_open", {"name": "mcp_excl_rm", "vdb": exclusion_vdb})

    # add
    content, _ = _call_tool(server, "xverif_cov_query", {
        "session_id": "mcp_excl_rm", "action": "exclude.add",
        "args": {"selectors": [{"metric": "line", "scope": "top",
                                "file": "exclusion_fixture.sv", "line": 72}]},
        "output_format": "json",
    })
    assert json.loads(content[0].text)["data"]["items"][0]["status"] == "changed"

    # remove
    content, _ = _call_tool(server, "xverif_cov_query", {
        "session_id": "mcp_excl_rm", "action": "exclude.remove",
        "args": {"selectors": [{"metric": "line", "scope": "top",
                                "file": "exclusion_fixture.sv", "line": 72}]},
        "output_format": "json",
    })
    assert json.loads(content[0].text)["data"]["items"][0]["status"] == "changed"

    _call_tool(server, "xverif_cov_session_close", {"session_id": "mcp_excl_rm"})
