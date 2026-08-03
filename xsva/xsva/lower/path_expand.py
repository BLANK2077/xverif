"""路径展开 — 将 ##[m:n] 范围延迟展开为多条候选路径。

- ##[1:3] ack ##1 done → 展开为 3 条路径
- 多个范围延迟组合 → 笛卡尔积
- first_match → 只选最早匹配路径
- 超过 max_paths → 返回精确总数与显式截断状态
"""

from __future__ import annotations

from dataclasses import dataclass

from xsva.ir.sequence import SeqNode, SeqNodeKind


@dataclass(frozen=True)
class PathExpansionResult:
    """有界路径枚举结果。

    total_path_count 是未应用 ``max_paths`` 时的精确候选路径数；调用方不能只消费
    ``paths`` 而忽略 ``truncated``。
    """

    paths: list[list[SeqNode]]
    total_path_count: int

    @property
    def returned_path_count(self) -> int:
        return len(self.paths)

    @property
    def truncated(self) -> bool:
        return self.returned_path_count < self.total_path_count

    @property
    def enumeration_complete(self) -> bool:
        return not self.truncated


def expand_paths(
    seq_nodes: list[SeqNode],
    max_paths: int = 10,
) -> PathExpansionResult:
    """将 SeqNode 列表中的范围延迟展开为多条候选路径。

    每条路径使用固定延迟替换范围延迟。

    展开策略：
    1. ##[m:n] → n-m+1 条不同延迟的路径
    2. 多个范围延迟 → 笛卡尔积
    3. first_match → 只保留最早匹配路径（最短延迟）
    4. 超过 max_paths → 保留前 max_paths 条，但同时返回精确总数和 truncated=true
    """
    if not isinstance(max_paths, int) or isinstance(max_paths, bool) or max_paths <= 0:
        raise ValueError("max_paths must be a positive integer")
    if not seq_nodes:
        return PathExpansionResult(paths=[[]], total_path_count=1)

    # 找到第一个需要展开的范围延迟
    # 规则：只有当范围延迟后还有 suffix（后续节点）时才展开
    # 例：##[1:3] ack ##1 done → 展开（有 suffix）
    # 例：##[1:4] ack → 不展开，保持单 obligation+window
    range_idx = -1
    range_node: SeqNode | None = None
    for i, node in enumerate(seq_nodes):
        if node.is_finite_range_delay():
            # 检查：延迟后面有复杂 suffix 才展开
            # 简单 suffix（单一信号）→ 不展开，保持 window obligation
            # 复杂 suffix（含额外 delay 或 >1 节点）→ 展开
            has_suffix = False
            suffix_count = 0
            for j in range(i + 1, len(seq_nodes)):
                n = seq_nodes[j]
                if n.kind in (
                    SeqNodeKind.EXPR,
                    SeqNodeKind.MATCH_ITEM,
                    SeqNodeKind.DELAY,
                    SeqNodeKind.THROUGHOUT,
                    SeqNodeKind.INTERSECT,
                ):
                    suffix_count += 1
                    if n.kind == SeqNodeKind.DELAY:
                        has_suffix = True
                        break
            # 后缀多于 1 个节点也展开
            if suffix_count > 1:
                has_suffix = True
            if has_suffix:
                range_idx = i
                range_node = node
                break

    # 没有需要展开的范围延迟 → 单一路径
    if range_idx < 0 or range_node is None:
        return PathExpansionResult(paths=[list(seq_nodes)], total_path_count=1)

    # 前缀 + 展开延迟 + 后缀
    prefix = seq_nodes[:range_idx]
    suffix = seq_nodes[range_idx + 1:]

    # 展开后缀中的范围延迟（递归）
    suffix_result = expand_paths(suffix, max_paths)

    # 展开当前延迟
    range_count = range_node.max_delay - range_node.min_delay + 1
    total_path_count = range_count * suffix_result.total_path_count
    paths: list[list[SeqNode]] = []

    for cycle in range(range_node.min_delay, range_node.max_delay + 1):
        # 创建固定延迟节点
        fixed_node = SeqNode.delay_cycles(cycle)

        for suffix_path in suffix_result.paths:
            path = list(prefix) + [fixed_node] + suffix_path
            paths.append(path)
            if len(paths) >= max_paths:
                return PathExpansionResult(
                    paths=paths,
                    total_path_count=total_path_count,
                )

    return PathExpansionResult(paths=paths, total_path_count=total_path_count)


def expand_first_match(
    paths: list[list[SeqNode]],
) -> list[list[SeqNode]]:
    """对 first_match 应用 earliest-match 语义。

    只保留 first_match 内部的最短延迟路径。
    注意：first_match 外的路径不受影响。
    """
    if not paths:
        return paths

    # 检查是否有 first_match 节点
    has_fm = any(
        node.kind == SeqNodeKind.FIRST_MATCH
        for path in paths
        for node in path
    )
    if not has_fm:
        return paths

    result: list[list[SeqNode]] = []
    for path in paths:
        new_path: list[SeqNode] = []
        i = 0
        while i < len(path):
            node = path[i]
            if node.kind == SeqNodeKind.FIRST_MATCH and node.children:
                # 展开 first_match 内部 → 选最短路径
                inner = list(node.children[0].children) if (
                    len(node.children) == 1 and node.children[0].kind == SeqNodeKind.CONCAT
                ) else list(node.children)
                inner_result = expand_paths(inner, max_paths=1)  # first_match 语义只取最短
                if inner_result.paths:
                    # 替换 first_match 节点为展开内容
                    new_path.extend(inner_result.paths[0])
                else:
                    new_path.append(node)
                i += 1
            else:
                new_path.append(node)
                i += 1
        result.append(new_path)

    return result
