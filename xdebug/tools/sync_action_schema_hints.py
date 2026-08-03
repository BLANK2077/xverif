#!/usr/bin/env python3
"""Sync AI-facing action descriptions from the xverif skill into schemas."""

from __future__ import annotations

import argparse
import copy
import json
import re
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "specs"))
from action_contracts import guidance_for


XDEBUG_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = XDEBUG_ROOT.parent
SPEC_PATH = XDEBUG_ROOT / "specs" / "actions" / "actions.yaml"
REFERENCE_PATH_CANDIDATES = [
    REPO_ROOT / "skills" / "xverif" / "references" / "xdebug" / "action-reference.md",
]


PARAM_DESCRIPTIONS = {
    "clock": "采样、统计或协议检查使用的 clock 信号路径。",
    "cnt": "计数器统计使用的 counter 信号路径。",
    "conditions": "需要验证的条件列表。",
    "config": "内联配置对象。",
    "config_path": "输入配置文件路径。",
    "edge": "clock sampling 使用的边沿：posedge、negedge 或 dual。",
    "expr": "需要求值或匹配的布尔表达式。",
    "expected_state": "窗口内要求持续满足的四态逻辑值：x 或 z。",
    "file": "源码文件路径。",
    "from_signal": "路径查询的起点信号。",
    "index": "列表中要删除的信号序号。",
    "kind": "导出或查询的结果类型。",
    "line": "源码行号。",
    "line_limit": "控制 response/xout 中 item、finding、event、transaction 或 row 的最大返回行数。",
    "match_mode": "X/Z 向量匹配方式：exact 要求每一位均为目标态，contains 要求至少一位为目标态。",
    "name": "已保存配置、游标、列表或接口配置名称。",
    "op": "游标移动或协议浏览操作。",
    "output": "导出配置对象；路径统一使用 output.path。",
    "ownership_token": "managed wrapper 可选提供并复用的 64 个小写十六进制字符（256 bit）conditional-cleanup token，不是授权；session.open 省略时 frontend 仍会 fail-closed 地生成内部 token 并绑定 digest；session.kill 提供时必须匹配，省略时不改变既有显式管理语义；禁止记录、回显或人工构造。",
    "query": "stream 查询条件。",
    "ready": "valid-ready 握手中的 ready 信号路径。",
    "requests": "batch action 中按顺序执行的 request 列表。",
    "sample_point": "posedge/dual 时的采样点：before 或 after；posedge 默认推荐 before。",
    "session_id": "目标 xdebug session 标识。",
    "signal": "目标信号路径。",
    "signals": "信号列表，或 alias 到信号路径的映射。",
    "stream": "已保存 stream 配置名称。",
    "streams": "需要加载的 stream 配置列表。",
    "time": "查询或验证的目标时间点。",
    "times": "按请求顺序查询的一个或多个目标时间点。",
    "time_range": "查询或分析的时间窗口。",
    "to_signal": "路径查询的终点信号。",
    "valid": "valid-ready 握手或采样检查中的 valid 信号路径。",
    "vld": "计数器统计使用的 valid 信号路径。",
}


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def dump_json(value: Any) -> str:
    return json.dumps(value, indent=2, ensure_ascii=False) + "\n"


def clean_cell(text: str) -> str:
    text = text.strip()
    text = text.replace("<br>", "; ")
    text = re.sub(r"`([^`]+)`", r"\1", text)
    return text.strip()


def parse_action_reference(path: Path) -> dict[str, dict[str, str]]:
    hints: dict[str, dict[str, str]] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.startswith("| `"):
            continue
        cells = [clean_cell(cell) for cell in line.strip().strip("|").split("|")]
        if len(cells) != 7:
            continue
        action, _status, _resource, purpose, how_it_works, objective, contract = cells
        if not action:
            continue
        hints[action] = {
            "purpose": purpose,
            "how_it_works": how_it_works,
            "when_to_use": objective,
            "arg_contract_notes": contract,
        }
    return hints


def action_reference_path() -> Path:
    for path in REFERENCE_PATH_CANDIDATES:
        if path.is_file():
            return path
    searched = ", ".join(str(path) for path in REFERENCE_PATH_CANDIDATES)
    raise FileNotFoundError(f"action-reference.md not found; searched: {searched}")


def required_related_args(spec: dict[str, Any]) -> set[str]:
    keys = set(spec.get("required_args", []))
    for group in spec.get("required_arg_groups", []):
        keys.update(group)
    for conditional in spec.get("conditional_required_args", []):
        keys.update(conditional.get("when", {}).keys())
        keys.update(conditional.get("required", []))
    return keys


def arg_contract_notes(spec: dict[str, Any]) -> str:
    parts: list[str] = []
    required = list(spec.get("required_args", []))
    if required:
        parts.append("required: " + ", ".join(required))

    groups = spec.get("required_arg_groups", [])
    if groups:
        choices = [" + ".join(group) for group in groups]
        parts.append("also one of: " + " / ".join(choices))

    for conditional in spec.get("conditional_required_args", []):
        when = conditional.get("when", {})
        required_when = conditional.get("required", [])
        if not when or not required_when:
            continue
        when_text = ", ".join(f"{key}={value}" for key, value in when.items())
        parts.append(f"when {when_text}: " + ", ".join(required_when))

    return "; ".join(parts) if parts else "no required args"


def update_request_schema(schema: dict[str, Any], spec: dict[str, Any], hint: dict[str, str]) -> None:
    name = spec["name"]
    schema["description"] = spec["description_en"]
    schema["x-description-zh"] = spec["description_zh"]
    schema["x-purpose"] = hint["purpose"]
    schema["x-how_it_works"] = hint["how_it_works"]
    schema["x-when_to_use"] = hint["when_to_use"]
    schema["x-arg_contract_notes"] = hint.get("arg_contract_notes") or arg_contract_notes(spec)

    args = schema.get("properties", {}).get("args")
    if not isinstance(args, dict):
        raise ValueError(f"{name}: request schema missing properties.args")
    props = args.get("properties")
    if not isinstance(props, dict):
        raise ValueError(f"{name}: request schema missing args.properties")

    for key in sorted(required_related_args(spec)):
        if key not in props:
            raise ValueError(f"{name}: request schema missing args.properties.{key}")
        props[key].setdefault("description", PARAM_DESCRIPTIONS.get(
            key, f"{key} parameter for {name}."
        ))
    guidance = guidance_for(name)
    schema["x-agent"] = {
        "use_when": guidance["use_when"],
        "do_not_use_when": guidance["do_not_use_when"],
        "alternatives": guidance["alternatives"],
        "constraints": [hint.get("arg_contract_notes") or arg_contract_notes(spec)],
    }


def update_response_schema(schema: dict[str, Any], spec: dict[str, Any], hint: dict[str, str]) -> None:
    schema["description"] = spec["description_en"]
    schema["x-description-zh"] = spec["description_zh"]
    # x-output_notes is action-shape data owned by sync_response_schemas.py.
    # This hint synchronizer must not replace it with a generic tautology.


def sync(check: bool, selected_actions: set[str] | None = None) -> list[str]:
    specs = load_json(SPEC_PATH)["actions"]
    hints = parse_action_reference(action_reference_path())
    errors: list[str] = []

    for spec in specs:
        name = spec["name"]
        if selected_actions and name not in selected_actions:
            continue
        hint = hints.get(name)
        if hint is None:
            errors.append(f"{name}: missing action reference row")
            continue

        for kind, updater in (
            ("request", update_request_schema),
            ("response", update_response_schema),
        ):
            rel = spec["schemas"][kind]
            path = XDEBUG_ROOT / rel
            schema = load_json(path)
            updated = copy.deepcopy(schema)
            try:
                updater(updated, spec, hint)
            except ValueError as exc:
                errors.append(str(exc))
                continue
            if schema != updated:
                if check:
                    errors.append(f"{rel}: schema hints are not synced")
                else:
                    path.write_text(dump_json(updated), encoding="utf-8")
    return errors


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="only check, do not update files")
    parser.add_argument("--action", action="append", default=[], help="sync only the named action; repeatable")
    args = parser.parse_args(argv)

    errors = sync(check=args.check, selected_actions=set(args.action) or None)
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print("action schema hints are synced")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
