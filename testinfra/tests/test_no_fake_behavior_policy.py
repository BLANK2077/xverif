from __future__ import annotations

import ast
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
POLICY = ROOT / "testinfra" / "fault_injection_exceptions.v1.json"
TEST_ROOTS = (
    ROOT / "testinfra" / "tests",
    ROOT / "xbit" / "tests",
    ROOT / "xcov" / "tests",
    ROOT / "xdebug" / "tests",
    ROOT / "xentry" / "tests",
    ROOT / "xloc" / "tests",
    ROOT / "xsva" / "tests",
    ROOT / "xverif_mcp" / "tests",
    ROOT / "skills" / "tests",
)
BEHAVIOR_MARKERS = ("fake", "mock", "dummy", "stub")
NON_BEHAVIOR_NAMES = {
    "mock_env",
    "mock_environment",
    "fake_home",
    "fake_path",
}


def _is_behavior_surrogate(name: str) -> bool:
    lowered = name.lower()
    return lowered not in NON_BEHAVIOR_NAMES and any(marker in lowered for marker in BEHAVIOR_MARKERS)


def _test_functions(tree: ast.AST) -> list[ast.FunctionDef | ast.AsyncFunctionDef]:
    return [
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name.startswith("test_")
    ]


def _surrogate_references(node: ast.AST) -> set[str]:
    references: set[str] = set()
    for child in ast.walk(node):
        if isinstance(child, ast.Name) and _is_behavior_surrogate(child.id):
            references.add(child.id)
        elif isinstance(child, ast.Attribute) and _is_behavior_surrogate(child.attr):
            references.add(child.attr)
    return references


def test_behavior_surrogates_are_limited_to_fault_injection_and_lsf() -> None:
    policy = json.loads(POLICY.read_text(encoding="utf-8"))
    file_exceptions = policy["file_exceptions"]
    test_exceptions = policy["test_exceptions"]
    violations: list[str] = []

    for test_root in TEST_ROOTS:
        if not test_root.exists():
            continue
        for path in sorted(test_root.rglob("test_*.py")):
            relative = path.relative_to(ROOT).as_posix()
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=relative)
            if relative in file_exceptions:
                continue
            for test in _test_functions(tree):
                references = _surrogate_references(test)
                if not references or "lsf" in test.name.lower():
                    continue
                qualified = f"{relative}::{test.name}"
                if qualified in test_exceptions:
                    continue
                violations.append(
                    f"{qualified} 引用了行为替身: {', '.join(sorted(references))}"
                )

    assert not violations, (
        "正常测试不得使用 fake/mock/dummy/stub 行为替身；仅允许在精确登记的故障注入测试或 LSF 测试中使用。\n"
        + "\n".join(violations)
    )
