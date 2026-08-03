"""Path expand 单元测试。"""

import pytest

from xsva.ir.expr import ExprIR, ExprKind
from xsva.ir.sequence import SeqNode, SeqNodeKind
from xsva.lower.path_expand import expand_paths


def _expr(raw: str) -> SeqNode:
    expr = ExprIR(kind=ExprKind.IDENTIFIER, raw=raw)
    return SeqNode.expr_node(raw, expr)


def test_no_expand_fixed_delay():
    """固定延迟 ##3 不应展开。"""
    nodes = [
        SeqNode.delay_cycles(3),
        _expr("ack"),
    ]
    result = expand_paths(nodes)
    assert len(result.paths) == 1
    assert result.total_path_count == 1
    assert result.truncated is False


def test_expand_range_delay_with_suffix():
    """##[1:3] ack ##1 done → 3 条路径。"""
    nodes = [
        SeqNode.delay_cycles(1, 3),
        _expr("ack"),
        SeqNode.delay_cycles(1),
        _expr("done"),
    ]
    result = expand_paths(nodes)
    paths = result.paths
    assert len(paths) == 3, f"Range delay with suffix should produce 3 paths, got {len(paths)}"
    assert result.total_path_count == 3
    assert result.returned_path_count == 3
    assert result.truncated is False
    assert result.enumeration_complete is True

    # 路径 0: ##1 ack ##1 done
    assert paths[0][0].min_delay == 1
    assert paths[0][0].max_delay == 1

    # 路径 1: ##2 ack ##1 done
    assert paths[1][0].min_delay == 2

    # 路径 2: ##3 ack ##1 done
    assert paths[2][0].min_delay == 3


def test_no_expand_range_without_suffix():
    """##[1:4] ack → 不展开，保持单路径。"""
    nodes = [
        SeqNode.delay_cycles(1, 4),
        _expr("ack"),
    ]
    result = expand_paths(nodes)
    assert len(result.paths) == 1
    assert result.total_path_count == 1
    assert result.truncated is False


def test_max_paths_reports_exact_total_and_explicit_truncation():
    """达到预算时必须返回精确总数，不能只给一个截断 list。"""
    nodes = [
        SeqNode.delay_cycles(1, 20),
        _expr("x"),
        SeqNode.delay_cycles(1, 10),
        _expr("y"),
        SeqNode.delay_cycles(1),
        _expr("z"),
    ]
    result = expand_paths(nodes, max_paths=5)
    assert result.returned_path_count == 5
    assert result.total_path_count == 200
    assert result.truncated is True
    assert result.enumeration_complete is False


def test_empty_sequence():
    """空 sequence 返回单一空路径。"""
    result = expand_paths([])
    assert result.paths == [[]]
    assert result.total_path_count == 1
    assert result.truncated is False


@pytest.mark.parametrize("limit", [0, -1, True, 1.5])
def test_invalid_max_paths_is_rejected(limit):
    with pytest.raises(ValueError, match="positive integer"):
        expand_paths([_expr("x")], max_paths=limit)
