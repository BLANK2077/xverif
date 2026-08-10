from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import jsonschema
import yaml


LEVELS = {"static", "unit", "component", "integration", "system"}
COST_ORDER = {"fast": 0, "medium": 1, "slow": 2}
GATE_ORDER = {"fast": 0, "regression": 1, "nightly": 2}


class CatalogError(ValueError):
    """Raised when the catalog is structurally or semantically invalid."""


@dataclass(frozen=True)
class Suite:
    id: str
    owner: str
    level: str
    intent: tuple[str, ...]
    domains: tuple[str, ...]
    runner: dict[str, Any]
    fixtures: tuple[str, ...]
    capabilities: tuple[str, ...]
    hermetic: bool
    deterministic: bool
    availability: str
    cost_class: str
    estimate_sec: int
    resources: dict[str, Any]
    timeouts: dict[str, int]
    impact: dict[str, Any]
    enabled: bool
    gates: tuple[str, ...]

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> "Suite":
        cost = data.get("cost", {})
        return cls(
            id=data["id"],
            owner=data["owner"],
            level=data["level"],
            intent=tuple(data.get("intent", [])),
            domains=tuple(data.get("domains", [])),
            runner=dict(data["runner"]),
            fixtures=tuple(data.get("fixtures", [])),
            capabilities=tuple(data.get("capabilities", [])),
            hermetic=bool(data.get("hermetic", False)),
            deterministic=bool(data.get("deterministic", True)),
            availability=data.get("availability", "required"),
            cost_class=cost.get("class", "fast"),
            estimate_sec=int(cost.get("estimate_sec", 1)),
            resources=dict(data.get("resources", {})),
            timeouts={key: int(value) for key, value in data.get("timeouts", {}).items()},
            impact=dict(data.get("impact", {})),
            enabled=bool(data.get("enabled", True)),
            gates=tuple(data.get("gates", [])),
        )

    def pytest_paths(self) -> tuple[str, ...]:
        if self.runner.get("kind") != "pytest":
            return ()
        paths = self.runner.get("paths")
        if paths is None:
            paths = [self.runner["path"]]
        return tuple(str(path).rstrip("/") for path in paths)

    def pytest_marker(self) -> str | None:
        value = self.runner.get("marker")
        return str(value) if value else None

    def runner_env(self) -> dict[str, str]:
        return {
            str(name): str(value)
            for name, value in self.runner.get("env", {}).items()
        }


@dataclass(frozen=True)
class SelectedSuite:
    suite: Suite
    required: bool
    reason: str


@dataclass(frozen=True)
class Catalog:
    version: str
    suites: tuple[Suite, ...]
    path: Path

    @classmethod
    def load(cls, path: Path, schema_path: Path) -> "Catalog":
        try:
            raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError) as exc:
            raise CatalogError(f"cannot load catalog {path}: {exc}") from exc
        try:
            schema = yaml.safe_load(schema_path.read_text(encoding="utf-8"))
            jsonschema.Draft202012Validator(schema).validate(raw)
        except (OSError, yaml.YAMLError, jsonschema.ValidationError) as exc:
            raise CatalogError(f"catalog schema validation failed: {exc}") from exc
        suites = tuple(Suite.from_json(item) for item in raw["suites"])
        cls._validate_semantics(suites)
        return cls(version=raw["version"], suites=suites, path=path)

    @staticmethod
    def _validate_semantics(suites: Iterable[Suite]) -> None:
        ids: set[str] = set()
        path_owners: dict[tuple[str, str | None], str] = {}
        for suite in suites:
            if suite.id in ids:
                raise CatalogError(f"duplicate suite id: {suite.id}")
            ids.add(suite.id)
            if suite.level not in LEVELS:
                raise CatalogError(f"invalid level for {suite.id}: {suite.level}")
            if suite.cost_class not in COST_ORDER:
                raise CatalogError(f"invalid cost class for {suite.id}: {suite.cost_class}")
            if suite.gates:
                gate_indexes = {GATE_ORDER[gate] for gate in suite.gates}
                first = min(gate_indexes)
                if gate_indexes != set(range(first, len(GATE_ORDER))):
                    raise CatalogError(f"non-monotonic explicit gates for {suite.id}: {suite.gates}")
            for path in suite.pytest_paths():
                key = (path, suite.pytest_marker())
                previous = path_owners.get(key)
                if previous is not None:
                    raise CatalogError(
                        f"pytest path/marker {key} is owned by both {previous} and {suite.id}"
                    )
                path_owners[key] = suite.id

    def suite_by_id(self, suite_id: str) -> Suite:
        for suite in self.suites:
            if suite.id == suite_id:
                return suite
        raise CatalogError(f"unknown suite id: {suite_id}")

    def select_gate(self, gate: str) -> tuple[SelectedSuite, ...]:
        if gate not in {"fast", "regression", "nightly"}:
            raise CatalogError(f"unknown gate: {gate}")
        selected: list[SelectedSuite] = []
        for suite in self.suites:
            if not suite.enabled:
                continue
            if suite.gates:
                include = gate in suite.gates
                reason = "explicit suite gate membership selected by catalog"
            elif gate == "fast":
                include = suite.hermetic and suite.level in {"static", "unit", "component"}
                reason = "hermetic execution boundary selected by fast"
            elif gate == "regression":
                include = suite.deterministic and COST_ORDER[suite.cost_class] <= COST_ORDER["medium"]
                reason = "deterministic fast/medium suite selected by regression"
            else:
                include = True
                reason = "enabled suite selected by nightly"
            if include:
                selected.append(
                    SelectedSuite(
                        suite=suite,
                        required=suite.availability == "required",
                        reason=reason,
                    )
                )
        return tuple(selected)

    def owner_for_path(self, path: Path, repo_root: Path) -> Suite | None:
        owners = self.owners_for_path(path, repo_root)
        return owners[0] if len(owners) == 1 else None

    def owners_for_path(self, path: Path, repo_root: Path) -> tuple[Suite, ...]:
        try:
            relative = path.resolve().relative_to(repo_root.resolve()).as_posix()
        except ValueError:
            return ()
        candidates: list[tuple[int, Suite]] = []
        for suite in self.suites:
            for prefix in suite.pytest_paths():
                if relative == prefix or relative.startswith(prefix + "/"):
                    candidates.append((len(prefix), suite))
        if not candidates:
            return ()
        candidates.sort(key=lambda item: item[0], reverse=True)
        longest = candidates[0][0]
        return tuple(suite for length, suite in candidates if length == longest)
