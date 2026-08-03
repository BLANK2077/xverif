#!/usr/bin/env python3
"""审计重建工作树的 xdebug action catalog 是否精确达到参考合同。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys
from typing import Any, Iterable, NoReturn


REFERENCE_COMMIT = "1c3ffc85d1bc3859bfa5f75c314cccaecc05e4d5"
SPEC_PATH = "xdebug/specs/actions/actions.yaml"
EXPECTED_ACTION_COUNT = 73

RENAMES = {
    "apb.cursor": "apb.transaction.cursor",
    "axi.cursor": "axi.transaction.cursor",
    "cursor.delete": "waveform.cursor.delete",
    "cursor.get": "waveform.cursor.get",
    "cursor.list": "waveform.cursor.list",
    "cursor.set": "waveform.cursor.set",
    "cursor.use": "waveform.cursor.use",
    "detect_abnormal": "signal.anomaly.inspect",
    "handshake.inspect": "protocol.handshake.inspect",
    "list.diff": "list.first_change",
    "rc.generate": "nwave.rc.generate",
    "sampled_pulse.inspect": "signal.sampled_pulse.inspect",
    "stream.show": "stream.describe",
    "trace.x": "trace.x_origin",
}

ADDITIONS = {
    "list.load",
    "stream.config.get",
}

REMOVED_OR_MERGED = {
    "list.value_at",
    "signal.search",
    "source.context",
    "value.batch_at",
}

MISSING = object()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "比较工作树与 1c3ffc8 的 actions.yaml，审计 73-action、"
            "重命名/新增/删除以及逐字段合同。"
        )
    )
    parser.add_argument(
        "--reference",
        default=REFERENCE_COMMIT,
        help=f"参考提交，默认 {REFERENCE_COMMIT}",
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="待审计仓库根目录，默认由脚本位置推导",
    )
    parser.add_argument(
        "--max-diffs",
        type=int,
        default=200,
        help="最多打印的逐字段差异数；0 表示全部打印",
    )
    return parser.parse_args()


def fail(message: str) -> NoReturn:
    print(f"FAIL: {message}", file=sys.stderr)
    raise SystemExit(2)


def run_git(repo_root: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", "-C", str(repo_root), *args],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if proc.returncode != 0:
        detail = proc.stderr.strip() or proc.stdout.strip() or "未知 git 错误"
        fail(f"git {' '.join(args)} 失败: {detail}")
    return proc.stdout


def load_json_document(text: str, source: str) -> dict[str, Any]:
    try:
        document = json.loads(text)
    except json.JSONDecodeError as exc:
        fail(f"{source} 不是合法 JSON-compatible YAML: {exc}")
    if not isinstance(document, dict):
        fail(f"{source} 顶层必须是 object")
    actions = document.get("actions")
    if not isinstance(actions, list):
        fail(f"{source} 缺少 actions array")
    return document


def load_reference(repo_root: Path, reference: str) -> dict[str, Any]:
    text = run_git(repo_root, "show", f"{reference}:{SPEC_PATH}")
    return load_json_document(text, f"{reference}:{SPEC_PATH}")


def load_worktree(repo_root: Path) -> dict[str, Any]:
    path = repo_root / SPEC_PATH
    if not path.is_file():
        fail(f"工作树缺少 {path}")
    return load_json_document(path.read_text(encoding="utf-8"), str(path))


def action_map(document: dict[str, Any], source: str) -> tuple[dict[str, dict[str, Any]], list[str]]:
    result: dict[str, dict[str, Any]] = {}
    duplicates: list[str] = []
    for index, item in enumerate(document["actions"]):
        if not isinstance(item, dict):
            fail(f"{source} actions[{index}] 必须是 object")
        name = item.get("name")
        if not isinstance(name, str) or not name:
            fail(f"{source} actions[{index}].name 必须是非空 string")
        if name in result:
            duplicates.append(name)
        result[name] = item
    return result, sorted(set(duplicates))


def json_pointer(parts: Iterable[str]) -> str:
    escaped = [part.replace("~", "~0").replace("/", "~1") for part in parts]
    return "/" + "/".join(escaped)


def contract_differences(
    expected: Any,
    actual: Any,
    path: tuple[str, ...] = (),
) -> list[tuple[str, Any, Any]]:
    if isinstance(expected, dict) and isinstance(actual, dict):
        differences: list[tuple[str, Any, Any]] = []
        for key in sorted(set(expected) | set(actual)):
            if key not in expected:
                differences.append((json_pointer((*path, key)), MISSING, actual[key]))
            elif key not in actual:
                differences.append((json_pointer((*path, key)), expected[key], MISSING))
            else:
                differences.extend(
                    contract_differences(expected[key], actual[key], (*path, key))
                )
        return differences
    if isinstance(expected, list) and isinstance(actual, list):
        differences = []
        common = min(len(expected), len(actual))
        for index in range(common):
            differences.extend(
                contract_differences(expected[index], actual[index], (*path, str(index)))
            )
        for index in range(common, len(expected)):
            differences.append((json_pointer((*path, str(index))), expected[index], MISSING))
        for index in range(common, len(actual)):
            differences.append((json_pointer((*path, str(index))), MISSING, actual[index]))
        return differences
    if type(expected) is not type(actual) or expected != actual:
        return [(json_pointer(path), expected, actual)]
    return []


def display_value(value: Any, limit: int = 240) -> str:
    if value is MISSING:
        return "<不存在>"
    text = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    if len(text) > limit:
        return text[: limit - 3] + "..."
    return text


def print_set(label: str, values: set[str]) -> None:
    rendered = ", ".join(sorted(values)) if values else "无"
    print(f"  {label}: {rendered}")


def audit(args: argparse.Namespace) -> int:
    repo_root = args.repo_root.resolve()
    reference_document = load_reference(repo_root, args.reference)
    current_document = load_worktree(repo_root)
    reference_actions, reference_duplicates = action_map(reference_document, "reference")
    current_actions, current_duplicates = action_map(current_document, "worktree")
    reference_names = set(reference_actions)
    current_names = set(current_actions)

    failures: list[str] = []
    print("xdebug rebuilt action contract audit")
    print(f"  reference: {args.reference}:{SPEC_PATH}")
    print(f"  worktree : {repo_root / SPEC_PATH}")

    if len(RENAMES) != 14:
        failures.append(f"门禁常量错误：RENAMES={len(RENAMES)}，预期 14")
    if len(ADDITIONS) != 2:
        failures.append(f"门禁常量错误：ADDITIONS={len(ADDITIONS)}，预期 2")
    if len(REMOVED_OR_MERGED) != 4:
        failures.append(
            f"门禁常量错误：REMOVED_OR_MERGED={len(REMOVED_OR_MERGED)}，预期 4"
        )
    if reference_duplicates:
        failures.append(f"参考 catalog 有重复 action: {', '.join(reference_duplicates)}")
    if current_duplicates:
        failures.append(f"工作树 catalog 有重复 action: {', '.join(current_duplicates)}")
    if len(reference_names) != EXPECTED_ACTION_COUNT:
        failures.append(
            f"参考 action 数为 {len(reference_names)}，不是预期 {EXPECTED_ACTION_COUNT}"
        )
    if len(current_names) != EXPECTED_ACTION_COUNT:
        failures.append(
            f"工作树 action 数为 {len(current_names)}，不是预期 {EXPECTED_ACTION_COUNT}"
        )

    missing_names = reference_names - current_names
    unexpected_names = current_names - reference_names
    print("\n名称集合:")
    print(f"  reference_count: {len(reference_names)}")
    print(f"  worktree_count : {len(current_names)}")
    print_set("missing", missing_names)
    print_set("unexpected", unexpected_names)
    if missing_names:
        failures.append(f"缺少 {len(missing_names)} 个参考 action")
    if unexpected_names:
        failures.append(f"存在 {len(unexpected_names)} 个非参考 action")

    print("\n14 个重命名:")
    for old_name, new_name in RENAMES.items():
        reference_ok = old_name not in reference_names and new_name in reference_names
        current_ok = old_name not in current_names and new_name in current_names
        state = "PASS" if reference_ok and current_ok else "FAIL"
        print(f"  [{state}] {old_name} -> {new_name}")
        if not reference_ok:
            failures.append(f"参考提交不符合重命名映射 {old_name}->{new_name}")
        if not current_ok:
            failures.append(f"工作树未完成重命名 {old_name}->{new_name}")

    print("\n2 个新增:")
    for name in sorted(ADDITIONS):
        state = "PASS" if name in reference_names and name in current_names else "FAIL"
        print(f"  [{state}] {name}")
        if name not in reference_names:
            failures.append(f"参考提交缺少新增 action {name}")
        if name not in current_names:
            failures.append(f"工作树缺少新增 action {name}")

    print("\n4 个删除/合并:")
    for name in sorted(REMOVED_OR_MERGED):
        state = "PASS" if name not in reference_names and name not in current_names else "FAIL"
        print(f"  [{state}] {name}")
        if name in reference_names:
            failures.append(f"参考提交仍含已删除/合并 action {name}")
        if name in current_names:
            failures.append(f"工作树仍含已删除/合并 action {name}")

    forbidden_aliases = set(RENAMES) | REMOVED_OR_MERGED
    leaked_aliases = forbidden_aliases & current_names
    print("\n旧 alias 审计:")
    print_set("leaked", leaked_aliases)
    if leaked_aliases:
        failures.append(f"工作树泄漏 {len(leaked_aliases)} 个旧 alias")

    reference_metadata = {
        key: value for key, value in reference_document.items() if key != "actions"
    }
    current_metadata = {
        key: value for key, value in current_document.items() if key != "actions"
    }
    differences: list[tuple[str, Any, Any]] = [
        (f"/catalog{path}", expected, actual)
        for path, expected, actual in contract_differences(
            reference_metadata, current_metadata
        )
    ]
    for name in sorted(reference_names & current_names):
        for path, expected, actual in contract_differences(
            reference_actions[name], current_actions[name]
        ):
            differences.append((f"/{name}{path}", expected, actual))

    print(f"\n合同字段差异: {len(differences)}")
    max_diffs = args.max_diffs
    visible = differences if max_diffs == 0 else differences[:max_diffs]
    for path, expected, actual in visible:
        print(f"  {path}")
        print(f"    expected: {display_value(expected)}")
        print(f"    actual  : {display_value(actual)}")
    if len(visible) < len(differences):
        print(f"  ... 省略 {len(differences) - len(visible)} 条；使用 --max-diffs 0 查看全部")
    if differences:
        failures.append(f"存在 {len(differences)} 条 action 合同字段差异")

    if failures:
        print("\nRESULT: FAIL")
        for message in failures:
            print(f"  - {message}")
        return 1
    print("\nRESULT: PASS")
    print("  - action 名称集合精确为 73")
    print("  - 14 个重命名、2 个新增、4 个删除/合并全部满足")
    print("  - 旧 alias 全部不存在")
    print("  - actions.yaml 合同字段与参考提交逐字段一致")
    return 0


def main() -> int:
    args = parse_args()
    if args.max_diffs < 0:
        fail("--max-diffs 不能为负数")
    return audit(args)


if __name__ == "__main__":
    raise SystemExit(main())
