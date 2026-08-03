from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from runner.raw_cli import RawCliResult


REPORT_PATH = Path("doc/XDEBUG_XOUT_REAL_OUTPUT_REVIEW_2026-08-03.md")
SPECIAL_XOUT_ACTIONS = {
    "apb.query", "apb.statistics", "axi.query", "axi.statistics",
    "scope.list", "scope.roots", "stream.query", "trace.active_driver",
    "trace.active_driver_chain", "trace.driver", "trace.load",
    "trace.x_origin", "value.at",
}
MARKER = re.compile(
    rb"<!-- XOUT_BODY phase=([^ ]+) action=([^ ]+) role=([^ ]+) "
    rb"bytes=([0-9]+) sha256=([0-9a-f]{64}) -->\n(`{3,})xout\n"
)


@dataclass(frozen=True)
class ReportBody:
    phase: str
    action: str
    role: str
    body: bytes
    stdout_bytes: int
    stdout_sha256: str

    @property
    def has_trailing_newline(self) -> bool:
        return self.body.endswith(b"\n")


def _fence(body: bytes) -> bytes:
    longest = max((len(item) for item in re.findall(rb"`+", body)), default=0)
    return b"`" * max(3, longest + 1)


def _action_has_value_format(report_path: Path, action: str) -> bool:
    schema_path = (
        report_path.resolve().parents[1] / "xdebug/schemas/v1/actions" /
        f"{action}.request.schema.json"
    )
    if not schema_path.is_file():
        return False
    schema = json.loads(schema_path.read_text(encoding="utf-8"))

    def contains(node: object) -> bool:
        if isinstance(node, dict):
            properties = node.get("properties")
            if isinstance(properties, dict) and "value_format" in properties:
                return True
            return any(contains(value) for value in node.values())
        if isinstance(node, list):
            return any(contains(value) for value in node)
        return False

    return contains(schema)


def write_report(path: Path, results: Iterable[RawCliResult],
                 *, semantic_failures: Iterable[str] = ()) -> None:
    rows = list(results)
    assert rows
    phase = rows[0].phase
    assert all(item.phase == phase for item in rows)
    primary = [item for item in rows if item.role == "primary"]
    assert phase in {"baseline", "final"}
    header = "# XDEBUG Native XOUT 真实输出审查（重建分支）\n\n"
    failures = list(semantic_failures)
    header += (
        f"# 阶段：{phase}\n\n"
        f"- runtime action 数：{len({item.action for item in primary})}\n"
        f"- primary 成功数：{sum(item.returncode == 0 for item in primary)}\n"
        f"- 捕获调用总数：{len(rows)}\n"
        f"- 布局 review 失败数：{len(failures)}\n"
        "- 完整性：每个 body 均按原始 stdout bytes 计数并计算 SHA-256。\n\n"
    )
    if failures:
        header += "布局 review 差异（不影响本阶段继续采集）：\n\n"
        header += "".join(f"- {item}\n" for item in failures) + "\n"
    if phase == "final":
        header += (
            f"## {len(primary)} 个 primary action 最终逐项 review\n\n"
            "评审标准：输出只保留 action 结论所需内容；同一事实不重复；"
            "所有 LogicValue 默认紧凑十六进制，显式进制服从请求，"
            "仅 X/Z 十六进制补充逐 bit 诊断；受保护的 APB/AXI/Stream "
            "query 与 value.at 专用布局必须保留。\n\n"
            "| action | runtime | 必要且不重复 | 数值格式 | renderer | 最终 |\n"
            "|---|---:|---:|---:|---|---:|\n"
        )
        for item in primary:
            failed = item.returncode != 0 or any(
                failure.startswith(item.action + ":")
                for failure in failures
            )
            header += (
                f"| `{item.action}` | "
                f"{'PASS' if item.returncode == 0 else 'FAIL'} | "
                f"{'PASS' if not failed else 'FAIL'} | "
                f"{'PASS' if _action_has_value_format(path, item.action) else 'N/A'} | "
                f"{'handler override' if item.action in SPECIAL_XOUT_ACTIONS else '基类'} | "
                f"{'PASS' if not failed else 'FAIL'} |\n"
            )
        header += "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    # Every phase is a self-contained report produced from this branch's own
    # raw invocations.  In particular, final never copies or appends a
    # historical baseline/final report.
    with path.open("wb") as stream:
        stream.write(header.encode("utf-8"))
        for index, item in enumerate(rows, 1):
            fence = _fence(item.stdout)
            stream.write(f"## {index:03d}. `{item.action}` / `{item.role}`\n\n".encode())
            stream.write(f"- returncode: {item.returncode}\n".encode())
            stream.write(f"- elapsed_ms: {item.elapsed_ms}\n".encode())
            stream.write(f"- bytes: {item.stdout_bytes}\n".encode())
            stream.write(f"- sha256: `{item.stdout_sha256}`\n".encode())
            request = json.dumps(item.request, ensure_ascii=False, sort_keys=True)
            stream.write(("- request: `" + request.replace("`", "\\`") + "`\n\n").encode("utf-8"))
            stream.write(
                f"<!-- XOUT_BODY phase={item.phase} action={item.action} role={item.role} "
                f"bytes={item.stdout_bytes} sha256={item.stdout_sha256} -->\n".encode()
            )
            stream.write(fence + b"xout\n")
            stream.write(item.stdout)
            if not item.stdout.endswith(b"\n"):
                stream.write(b"\n")
            stream.write(fence + b"\n\n")


def read_report_bodies(path: Path) -> list[ReportBody]:
    payload = path.read_bytes()
    bodies: list[ReportBody] = []
    cursor = 0
    while True:
        match = MARKER.search(payload, cursor)
        if match is None:
            break
        phase = match.group(1).decode("ascii")
        action = match.group(2).decode("ascii")
        role = match.group(3).decode("ascii")
        size = int(match.group(4))
        expected_hash = match.group(5).decode("ascii")
        fence = match.group(6)
        begin = match.end()
        body = payload[begin:begin + size]
        assert len(body) == size
        assert hashlib.sha256(body).hexdigest() == expected_hash
        suffix = payload[begin + size:]
        if body.endswith(b"\n"):
            assert suffix.startswith(fence + b"\n")
            cursor = begin + size + len(fence) + 1
        else:
            assert suffix.startswith(b"\n" + fence + b"\n")
            cursor = begin + size + len(fence) + 2
        bodies.append(ReportBody(
            phase=phase,
            action=action,
            role=role,
            body=body,
            stdout_bytes=size,
            stdout_sha256=expected_hash,
        ))
    return bodies


def verify_report(path: Path, *, expected_primary_by_phase: dict[str, int]) -> None:
    found_primary: dict[str, set[str]] = {}
    bodies = read_report_bodies(path)
    for item in bodies:
        if item.role != "primary":
            continue
        phase_actions = found_primary.setdefault(item.phase, set())
        assert item.action not in phase_actions
        phase_actions.add(item.action)
    assert len(bodies) > sum(expected_primary_by_phase.values())
    for phase, expected_count in expected_primary_by_phase.items():
        assert len(found_primary.get(phase, set())) == expected_count
