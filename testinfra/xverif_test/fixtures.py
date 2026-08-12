from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import fnmatch
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable

import jsonschema
import yaml


class FixtureError(RuntimeError):
    pass


@dataclass(frozen=True)
class FixtureOutput:
    name: str
    path: str
    kind: str
    min_bytes: int


@dataclass(frozen=True)
class FixtureSpec:
    id: str
    source_dir: str
    inputs: tuple[str, ...]
    extra_inputs: tuple[str, ...]
    builder: dict[str, Any]
    outputs: tuple[FixtureOutput, ...]
    tool_env: tuple[str, ...]
    build_capabilities: tuple[str, ...]
    probes: tuple[dict[str, Any], ...] = ()

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> "FixtureSpec":
        return cls(
            id=data["id"],
            source_dir=data["source_dir"],
            inputs=tuple(data["inputs"]),
            extra_inputs=tuple(data.get("extra_inputs", [])),
            builder=dict(data["builder"]),
            outputs=tuple(
                FixtureOutput(
                    name=item["name"],
                    path=item["path"],
                    kind=item["kind"],
                    min_bytes=int(item.get("min_bytes", 1)),
                )
                for item in data["outputs"]
            ),
            tool_env=tuple(data.get("tool_env", [])),
            build_capabilities=tuple(data.get("build_capabilities", [])),
            probes=tuple(dict(item) for item in data.get("probes", [])),
        )


@dataclass(frozen=True)
class FixtureRegistry:
    version: str
    fixtures: tuple[FixtureSpec, ...]

    @classmethod
    def load(cls, path: Path, schema_path: Path) -> "FixtureRegistry":
        try:
            raw = yaml.safe_load(path.read_text(encoding="utf-8"))
            schema = json.loads(schema_path.read_text(encoding="utf-8"))
            jsonschema.Draft202012Validator(schema).validate(raw)
        except (OSError, yaml.YAMLError, json.JSONDecodeError, jsonschema.ValidationError) as exc:
            raise FixtureError(f"fixture registry validation failed: {exc}") from exc
        specs = tuple(FixtureSpec.from_json(item) for item in raw["fixtures"])
        ids = [spec.id for spec in specs]
        if len(ids) != len(set(ids)):
            raise FixtureError("fixture registry contains duplicate ids")
        return cls(version=raw["version"], fixtures=specs)

    def by_id(self, fixture_id: str) -> FixtureSpec:
        for spec in self.fixtures:
            if spec.id == fixture_id:
                return spec
        raise FixtureError(f"unknown fixture id: {fixture_id}")


class FixtureStore:
    def __init__(self, repo_root: Path, registry: FixtureRegistry) -> None:
        self.repo_root = repo_root.resolve()
        self.registry = registry
        self.root = self.repo_root / ".xverif-test-cache" / "fixtures"

    def fingerprint(self, spec: FixtureSpec) -> tuple[str, dict[str, str]]:
        digest = hashlib.sha256()
        digest.update(b"xverif-fixture-fingerprint.v1\0")
        source_files = self._source_files(spec)
        if not source_files:
            raise FixtureError(f"fixture {spec.id} has no fingerprint input files")
        for path in source_files:
            relative = path.relative_to(self.repo_root).as_posix()
            digest.update(relative.encode("utf-8") + b"\0")
            digest.update(hashlib.sha256(path.read_bytes()).digest())
        digest.update(
            json.dumps(spec.builder, sort_keys=True, separators=(",", ":")).encode("utf-8")
        )
        digest.update(
            json.dumps(spec.probes, sort_keys=True, separators=(",", ":")).encode("utf-8")
        )
        tool_identity = {
            name: _compatibility_identity(os.environ.get(name, ""))
            for name in spec.tool_env
        }
        # Builder defaults are resolved at execution time.  They must therefore
        # participate in cache identity; otherwise a changed VIP/reference root
        # can silently reuse resources produced with another environment.
        values = {"repo": str(self.repo_root), "home": str(Path.home())}
        effective_env = {
            key: os.environ.get(key, str(value).format(**values))
            for key, value in spec.builder.get("default_env", {}).items()
        }
        digest.update(
            json.dumps(tool_identity, sort_keys=True, separators=(",", ":")).encode("utf-8")
        )
        digest.update(
            json.dumps(effective_env, sort_keys=True, separators=(",", ":")).encode("utf-8")
        )
        return digest.hexdigest(), tool_identity

    def effective_builder_env(self, spec: FixtureSpec) -> dict[str, str]:
        values = {"repo": str(self.repo_root), "home": str(Path.home())}
        env = os.environ.copy()
        for key, value in spec.builder.get("env", {}).items():
            env[str(key)] = str(value).format(**values)
        for key, value in spec.builder.get("default_env", {}).items():
            env.setdefault(str(key), str(value).format(**values))
        return env

    def resolve(self, fixture_id: str) -> Path:
        spec = self.registry.by_id(fixture_id)
        fingerprint, _ = self.fingerprint(spec)
        target = self._published_target(spec, fingerprint)
        self._validate_published(spec, target, fingerprint)
        return target / "resources"

    def prepare(
        self,
        fixture_id: str,
        *,
        rebuild: bool = False,
        progress: Callable[[str], None] | None = None,
    ) -> Path:
        notify = progress or (lambda _phase: None)
        spec = self.registry.by_id(fixture_id)
        notify("fingerprint")
        fingerprint, tool_identity = self.fingerprint(spec)
        fixture_root = self.root / spec.id
        fixture_root.mkdir(parents=True, exist_ok=True)
        lock_path = fixture_root / ".prepare.lock"
        notify("lock")
        with lock_path.open("a+", encoding="utf-8") as lock_stream:
            fcntl.flock(lock_stream.fileno(), fcntl.LOCK_EX)
            if not rebuild:
                try:
                    target = self._published_target(spec, fingerprint)
                except FixtureError:
                    target = None
                if target is not None:
                    notify("cache_validation")
                    self._validate_published(spec, target, fingerprint)
                    return target / "resources"
            staging_root = fixture_root / ".staging"
            staging_root.mkdir(parents=True, exist_ok=True)
            staging = Path(tempfile.mkdtemp(prefix="prepare-", dir=staging_root))
            (staging / "resources").mkdir(parents=True, exist_ok=True)
            try:
                notify("builder")
                self._run_builder(spec, staging)
                notify("output_validation")
                self._validate_outputs(spec, staging / "resources")
                self._run_probes(
                    spec,
                    staging / "resources",
                    staging,
                    progress=notify,
                )
                notify("publish")
                manifest = {
                    "schema_version": "xverif-fixture-manifest.v1",
                    "fixture_id": spec.id,
                    "fingerprint": fingerprint,
                    "tool_identity": tool_identity,
                    "tool_provenance": {
                        name: os.environ.get(name, "") for name in spec.tool_env
                    },
                    "outputs": [output.__dict__ for output in spec.outputs],
                }
                (staging / "manifest.json").write_text(
                    json.dumps(manifest, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8",
                )
                versions = fixture_root / "versions"
                versions.mkdir(parents=True, exist_ok=True)
                version = f"{fingerprint}-{staging.name}"
                target = versions / version
                os.replace(staging, target)
                self._write_current(fixture_root, fingerprint, version)
                return target / "resources"
            except BaseException:
                shutil.rmtree(staging, ignore_errors=True)
                raise

    def clean(self) -> None:
        if self.root.exists():
            shutil.rmtree(self.root)

    def affected_fixture_ids(self, changed: Iterable[str]) -> tuple[str, ...]:
        paths = tuple(changed)
        if any(path.startswith("testinfra/xverif_test/fixtures") for path in paths):
            return tuple(spec.id for spec in self.registry.fixtures)
        affected: list[str] = []
        for spec in self.registry.fixtures:
            prefix = spec.source_dir.rstrip("/") + "/"
            for path in paths:
                if any(fnmatch.fnmatch(path, pattern) for pattern in spec.extra_inputs):
                    affected.append(spec.id)
                    break
                if not path.startswith(prefix):
                    continue
                relative = path[len(prefix):]
                if any(fnmatch.fnmatch(relative, pattern) for pattern in spec.inputs):
                    affected.append(spec.id)
                    break
        return tuple(affected)

    def _source_files(self, spec: FixtureSpec) -> tuple[Path, ...]:
        files: set[Path] = set()
        source = self.repo_root / spec.source_dir
        for pattern in spec.inputs:
            for path in source.glob(pattern):
                if path.is_file():
                    files.add(path.resolve())
        for pattern in spec.extra_inputs:
            for path in self.repo_root.glob(pattern):
                if path.is_file():
                    files.add(path.resolve())
        for probe in spec.probes:
            for value in probe.get("argv", []):
                candidate = str(value).replace("{repo}/", "")
                path = self.repo_root / candidate
                if path.is_file():
                    files.add(path.resolve())
        return tuple(sorted(files))

    def _run_builder(self, spec: FixtureSpec, staging: Path) -> None:
        values = {
            "repo": str(self.repo_root),
            "source": str((self.repo_root / spec.source_dir).resolve()),
            "staging": str(staging),
            "resources": str(staging / "resources"),
            "home": str(Path.home()),
        }
        argv = [str(value).format(**values) for value in spec.builder["argv"]]
        cwd = Path(str(spec.builder.get("cwd", "{repo}")).format(**values))
        env = self.effective_builder_env(spec)
        log_path = staging / "builder.log"
        with log_path.open("w", encoding="utf-8") as log:
            result = subprocess.run(
                argv,
                cwd=cwd,
                env=env,
                text=True,
                stdout=log,
                stderr=subprocess.STDOUT,
                timeout=int(spec.builder.get("timeout_sec", 1200)),
                check=False,
            )
        if result.returncode != 0:
            tail = log_path.read_text(encoding="utf-8", errors="replace")[-4000:]
            raise FixtureError(
                f"fixture builder failed for {spec.id}: rc={result.returncode}\n{tail}"
            )

    def _run_probes(
        self,
        spec: FixtureSpec,
        resources: Path,
        staging: Path,
        *,
        progress: Callable[[str], None] | None = None,
    ) -> None:
        notify = progress or (lambda _phase: None)
        values = {
            "repo": str(self.repo_root),
            "source": str((self.repo_root / spec.source_dir).resolve()),
            "staging": str(staging),
            "resources": str(resources),
            "home": str(Path.home()),
        }
        for index, probe in enumerate(spec.probes):
            notify(f"probe_{index + 1}_of_{len(spec.probes)}")
            argv = [str(value).format(**values) for value in probe["argv"]]
            cwd = Path(str(probe.get("cwd", "{repo}")).format(**values))
            env = os.environ.copy()
            for key, value in probe.get("env", {}).items():
                env[str(key)] = str(value).format(**values)
            log_path = staging / f"probe-{index}.log"
            with log_path.open("w", encoding="utf-8") as log:
                result = subprocess.run(
                    argv,
                    cwd=cwd,
                    env=env,
                    text=True,
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    timeout=int(probe.get("timeout_sec", 1200)),
                    check=False,
                )
            if result.returncode != 0:
                tail = log_path.read_text(encoding="utf-8", errors="replace")[-4000:]
                raise FixtureError(
                    f"fixture semantic probe failed for {spec.id}: rc={result.returncode}\n{tail}"
                )

    def _validate_published(self, spec: FixtureSpec, target: Path, fingerprint: str) -> None:
        manifest_path = target / "manifest.json"
        if not manifest_path.is_file():
            raise FixtureError(
                f"fixture cache miss for {spec.id}; run: pytest --xverif-prepare {spec.id}"
            )
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise FixtureError(f"invalid fixture manifest for {spec.id}: {exc}") from exc
        if manifest.get("fingerprint") != fingerprint:
            raise FixtureError(f"fixture fingerprint mismatch for {spec.id}")
        self._validate_outputs(spec, target / "resources")

    def _validate_outputs(self, spec: FixtureSpec, resources: Path) -> None:
        for output in spec.outputs:
            path = resources / output.path
            if output.kind == "file":
                if not path.is_file() or path.stat().st_size < output.min_bytes:
                    raise FixtureError(f"fixture {spec.id} missing file output {output.name}")
            elif output.kind == "dir":
                if not path.is_dir() or not any(path.iterdir()):
                    raise FixtureError(f"fixture {spec.id} missing directory output {output.name}")
            else:
                raise FixtureError(f"fixture {spec.id} has unknown output kind {output.kind}")

    def _published_target(self, spec: FixtureSpec, fingerprint: str) -> Path:
        fixture_root = self.root / spec.id
        current_path = fixture_root / "current.json"
        try:
            current = json.loads(current_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise FixtureError(
                f"fixture cache miss for {spec.id}; run: pytest --xverif-prepare {spec.id}"
            ) from exc
        if current.get("fingerprint") != fingerprint or not current.get("version"):
            raise FixtureError(
                f"fixture cache miss for {spec.id}; run: pytest --xverif-prepare {spec.id}"
            )
        target = fixture_root / "versions" / str(current["version"])
        if not target.is_dir():
            raise FixtureError(f"fixture current generation missing for {spec.id}")
        return target

    @staticmethod
    def _write_current(fixture_root: Path, fingerprint: str, version: str) -> None:
        temporary = fixture_root / ".current.tmp"
        temporary.write_text(
            json.dumps(
                {"fingerprint": fingerprint, "version": version}, sort_keys=True
            )
            + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, fixture_root / "current.json")


def _compatibility_identity(value: str) -> str:
    match = re.search(r"([A-Z]?[-_]?\d{4}\.\d{2})", value)
    if match:
        return match.group(1).lstrip("-_")
    if not value:
        return "unset"
    return Path(value).name


def load_default_registry(repo_root: Path) -> FixtureRegistry:
    return FixtureRegistry.load(
        repo_root / "testinfra/fixtures.v1.yaml",
        repo_root / "testinfra/schemas/fixtures.v1.schema.json",
    )
