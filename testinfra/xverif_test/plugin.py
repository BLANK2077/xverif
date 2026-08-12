from __future__ import annotations

from pathlib import Path
import shutil
import json
import os
import subprocess
import sys
from typing import Any

import pytest

from .catalog import Catalog, CatalogError
from .gates import ExecutionPlan, build_plan, changed_paths, filter_changed, filter_plan
from .items import ExternalSuiteItem
from .fixtures import FixtureError, FixtureStore, load_default_registry
from .reports import ResultManager, create_run_dir
from .progress import ProgressReporter
from .resources import apply_xdist_resource_group
from .environment import write_snapshot
from .engine_cleanup import EngineProcessGuard, OWNER_ENV
from .dependencies import (
    DependencyError,
    load_default_dependency_registry,
    probe_dependencies,
    validate_suite_dependencies,
)


DEFAULT_CATALOG = Path("testinfra/catalog.v1.yaml")
DEFAULT_SCHEMA = Path("testinfra/schemas/catalog.v1.schema.json")
_RESULT_MANAGER: ResultManager | None = None
_ENGINE_GUARD: EngineProcessGuard | None = None
_PROGRESS_REPORTER: ProgressReporter | None = None
_ITEM_OUTCOMES: dict[str, str] = {}


def pytest_addoption(parser: pytest.Parser) -> None:
    group = parser.getgroup("xverif", "catalog-driven xverif test orchestration")
    group.addoption("--xverif-gate", choices=("fast", "regression", "nightly"))
    group.addoption("--xverif-suite", action="append", default=[])
    group.addoption("--xverif-plan", action="store_true", default=False)
    group.addoption("--xverif-catalog", default=str(DEFAULT_CATALOG))
    group.addoption("--xverif-prepare", action="append", default=[])
    group.addoption("--xverif-fixture-validation", action="store_true", default=False)
    group.addoption("--xverif-all-fixtures", action="store_true", default=False)
    group.addoption("--xverif-changed")
    group.addoption("--rerun-failed", dest="xverif_rerun_failed")
    group.addoption("--xverif-fixture-clean", action="store_true", default=False)
    group.addoption("--xverif-results-clean", action="store_true", default=False)
    group.addoption(
        "--xverif-progress-interval",
        type=float,
        default=30.0,
        help="seconds between durable progress heartbeats (default: 30)",
    )


def _repo_root(config: pytest.Config) -> Path:
    return Path(str(config.rootpath)).resolve()


def _load_catalog(config: pytest.Config) -> Catalog:
    root = _repo_root(config)
    configured = Path(config.getoption("--xverif-catalog"))
    catalog_path = configured if configured.is_absolute() else root / configured
    schema_path = root / DEFAULT_SCHEMA
    return Catalog.load(catalog_path, schema_path)


def _requested_operation(config: pytest.Config) -> str | None:
    operations: list[str] = []
    if config.getoption("--xverif-gate"):
        operations.append("gate")
    if config.getoption("--xverif-prepare"):
        operations.append("prepare")
    if config.getoption("--xverif-fixture-validation"):
        operations.append("fixture-validation")
    if config.getoption("xverif_rerun_failed"):
        operations.append("rerun-failed")
    if config.getoption("--xverif-fixture-clean"):
        operations.append("fixture-clean")
    if config.getoption("--xverif-results-clean"):
        operations.append("results-clean")
    if len(operations) > 1:
        raise pytest.UsageError(
            "xverif operations are mutually exclusive: " + ", ".join(operations)
        )
    return operations[0] if operations else None


def _ensure_xverif_state(config: pytest.Config) -> str | None:
    existing = getattr(config, "_xverif_operation", None)
    if existing is not None:
        return existing
    operation = _requested_operation(config)
    if operation is None:
        return None
    try:
        catalog = _load_catalog(config)
        validate_suite_dependencies(
            catalog, load_default_dependency_registry(_repo_root(config))
        )
    except (CatalogError, DependencyError) as exc:
        raise pytest.UsageError(str(exc)) from exc
    config._xverif_catalog = catalog  # type: ignore[attr-defined]
    root = _repo_root(config)
    if operation == "gate":
        gate = config.getoption("--xverif-gate")
        try:
            plan = build_plan(catalog, gate)
            changed = config.getoption("--xverif-changed")
            if changed:
                plan = filter_changed(plan, changed_paths(root, changed))
            plan = filter_plan(plan, list(config.getoption("--xverif-suite")))
        except ValueError as exc:
            raise pytest.UsageError(str(exc)) from exc
        config._xverif_plan = plan  # type: ignore[attr-defined]
        _apply_plan_environment(plan)
    elif config.getoption("--xverif-plan"):
        raise pytest.UsageError("--xverif-plan requires --xverif-gate")
    config._xverif_operation = operation  # type: ignore[attr-defined]
    return operation


def _apply_plan_environment(plan: ExecutionPlan) -> None:
    requested: dict[str, tuple[str, str]] = {}
    for selected in plan.suites:
        for name, value in selected.suite.runner_env().items():
            previous = requested.get(name)
            if previous is not None and previous[0] != value:
                raise pytest.UsageError(
                    f"selected suites require conflicting {name} values: "
                    f"{previous[1]}={previous[0]!r}, "
                    f"{selected.suite.id}={value!r}"
                )
            requested[name] = (value, selected.suite.id)
    for name, (value, suite_id) in requested.items():
        current = os.environ.get(name)
        if current is not None and current != value:
            raise pytest.UsageError(
                f"suite {suite_id} requires {name}={value!r}, "
                f"but the environment contains {current!r}"
            )
        os.environ[name] = value


@pytest.hookimpl(tryfirst=True)
def pytest_configure(config: pytest.Config) -> None:
    global _RESULT_MANAGER, _ENGINE_GUARD, _PROGRESS_REPORTER
    os.environ["XVERIF_TEST_TMPDIR"] = str(_repo_root(config) / "tmp")
    if hasattr(config, "workerinput"):
        token = config.workerinput.get("xdebug_engine_owner_token")  # type: ignore[attr-defined]
        if token:
            os.environ[OWNER_ENV] = str(token)
    elif _ENGINE_GUARD is None:
        _ENGINE_GUARD = EngineProcessGuard(_repo_root(config) / "xdebug/libexec/xdebug-engine")
        _ENGINE_GUARD.start()
    operation = _ensure_xverif_state(config)
    if operation is None:
        raise pytest.UsageError(
            "bare pytest is not an xverif test operation; use --xverif-gate "
            "fast|regression|nightly, --xverif-plan with a gate, or an explicit "
            "fixture/results operation"
        )
    if (
        operation == "gate"
        and not config.getoption("--xverif-plan")
        and not config.getoption("collectonly")
        and not hasattr(config, "workerinput")
    ):
        plan: ExecutionPlan = config._xverif_plan  # type: ignore[attr-defined]
        catalog: Catalog = config._xverif_catalog  # type: ignore[attr-defined]
        progress_interval = _progress_interval(config)
        _RESULT_MANAGER = ResultManager(_repo_root(config), plan.gate, catalog.version)
        config._xverif_results = _RESULT_MANAGER  # type: ignore[attr-defined]
        _PROGRESS_REPORTER = ProgressReporter(
            f"gate:{plan.gate}",
            _RESULT_MANAGER.run_dir,
            interval_sec=progress_interval,
            print_item_events=False,
            owns_running_marker=False,
        )
        if getattr(config.option, "xmlpath", None) is None:
            config.option.xmlpath = str(_RESULT_MANAGER.run_dir / "junit.xml")
        _PROGRESS_REPORTER.start()
        try:
            _run_gate_preflight(config)
        except BaseException:
            _PROGRESS_REPORTER.finish(outcome="failed")
            _RESULT_MANAGER.finish(int(pytest.ExitCode.USAGE_ERROR))
            raise
    elif operation == "gate" and hasattr(config, "workerinput"):
        worker_run_dir = config.workerinput.get("xverif_run_dir")  # type: ignore[attr-defined]
        if worker_run_dir:
            config._xverif_results = ResultManager.attach(  # type: ignore[attr-defined]
                _repo_root(config), Path(worker_run_dir)
            )
        config._xverif_unavailable = dict(  # type: ignore[attr-defined]
            config.workerinput.get("xverif_unavailable", {})  # type: ignore[attr-defined]
        )


def _run_gate_preflight(config: pytest.Config) -> None:
    plan: ExecutionPlan = config._xverif_plan  # type: ignore[attr-defined]
    root = _repo_root(config)
    registry = load_default_dependency_registry(root)
    capabilities = probe_dependencies(
        (name for selected in plan.suites for name in selected.suite.capabilities),
        root,
        registry=registry,
    )
    unavailable: dict[str, str] = {}
    required_errors: list[str] = []
    host_dependencies = {"npi", "mcp_process", "real_lsf"}
    requires_host = any(
        host_dependencies & set(selected.suite.capabilities)
        for selected in plan.suites
    )
    if requires_host and os.environ.get("XVERIF_TEST_EXECUTION_ENV") != "host":
        required_errors.append(
            "selected suites require XVERIF_TEST_EXECUTION_ENV=host"
        )
    store = FixtureStore(root, load_default_registry(root))
    for selected in plan.suites:
        reasons = [
            f"dependency {name}: {capabilities[name].reason}"
            for name in selected.suite.capabilities
            if not capabilities[name].available
        ]
        for fixture_id in selected.suite.fixtures:
            try:
                store.resolve(fixture_id)
            except FixtureError as exc:
                reasons.append(str(exc))
        if reasons:
            message = "; ".join(reasons)
            if selected.required:
                required_errors.append(f"{selected.suite.id}: {message}")
            else:
                unavailable[selected.suite.id] = message
    config._xverif_unavailable = unavailable  # type: ignore[attr-defined]
    manager = getattr(config, "_xverif_results", None)
    if manager is not None:
        write_snapshot(manager.environment_path(), capabilities)
    if required_errors:
        raise pytest.UsageError(
            "xverif required suite preflight failed:\n  "
            + "\n  ".join(required_errors)
        )


def _check_fixture_build_dependencies(root: Path, store: FixtureStore, fixture_id: str) -> None:
    spec = store.registry.by_id(fixture_id)
    if {"vcs", "vcs_uvm", "npi", "vip_apb", "vip_axi"} & set(
        spec.build_capabilities
    ) and os.environ.get("XVERIF_TEST_EXECUTION_ENV") != "host":
        raise FixtureError(
            f"fixture {fixture_id} requires XVERIF_TEST_EXECUTION_ENV=host"
        )
    statuses = probe_dependencies(
        spec.build_capabilities,
        root,
        effective_env=store.effective_builder_env(spec),
    )
    missing = [
        f"{name}: {status.reason}"
        for name, status in statuses.items()
        if not status.available
    ]
    if missing:
        raise FixtureError(
            f"fixture {fixture_id} build dependencies unavailable: "
            + "; ".join(missing)
        )


@pytest.hookimpl(tryfirst=True)
def pytest_cmdline_main(config: pytest.Config) -> int | None:
    operation = _ensure_xverif_state(config)
    if operation == "gate" and config.getoption("--xverif-plan"):
        plan: ExecutionPlan = config._xverif_plan  # type: ignore[attr-defined]
        print(plan.render())
        return pytest.ExitCode.OK
    if operation is None:
        return None
    if operation != "gate":
        root = _repo_root(config)
        progress: ProgressReporter | None = None
        try:
            store = FixtureStore(root, load_default_registry(root))
            if operation == "prepare":
                requested = list(config.getoption("--xverif-prepare"))
                fixture_ids = (
                    [spec.id for spec in store.registry.fixtures]
                    if requested == ["all-generated"]
                    else requested
                )
                progress = _operation_progress(
                    root, "fixture-prepare", len(fixture_ids), config
                )
                try:
                    for fixture_id in fixture_ids:
                        progress.item_start(fixture_id, detail="dependencies")
                        try:
                            _check_fixture_build_dependencies(root, store, fixture_id)
                            try:
                                store.resolve(fixture_id)
                                cache_hit = True
                            except FixtureError:
                                cache_hit = False
                            path = store.prepare(
                                fixture_id,
                                progress=lambda phase, item=fixture_id: progress.item_phase(
                                    item, phase
                                ),
                            )
                        except BaseException:
                            progress.item_finish(fixture_id, outcome="failed")
                            raise
                        progress.item_finish(fixture_id)
                        status = "cache hit" if cache_hit else "prepared"
                        print(f"{status} {fixture_id}: {path.relative_to(root)}")
                except BaseException:
                    progress.finish(outcome="failed")
                    raise
                timing = progress.finish(outcome="passed")
                _print_operation_summary(root, progress.run_dir, timing)
                return pytest.ExitCode.OK
            if operation == "fixture-validation":
                changed = config.getoption("--xverif-changed")
                if not config.getoption("--xverif-all-fixtures") and not changed:
                    raise pytest.UsageError(
                        "fixture-validation requires --xverif-all-fixtures or --xverif-changed BASE"
                    )
                fixture_ids = [spec.id for spec in store.registry.fixtures]
                if changed:
                    fixture_ids = list(store.affected_fixture_ids(changed_paths(root, changed)))
                progress = _operation_progress(
                    root, "fixture-validation", len(fixture_ids), config
                )
                try:
                    for fixture_id in fixture_ids:
                        progress.item_start(fixture_id, detail="dependencies")
                        try:
                            _check_fixture_build_dependencies(root, store, fixture_id)
                            path = store.prepare(
                                fixture_id,
                                rebuild=True,
                                progress=lambda phase, item=fixture_id: progress.item_phase(
                                    item, phase
                                ),
                            )
                        except BaseException:
                            progress.item_finish(fixture_id, outcome="failed")
                            raise
                        progress.item_finish(fixture_id)
                        print(f"validated {fixture_id}: {path.relative_to(root)}")
                except BaseException:
                    progress.finish(outcome="failed")
                    raise
                timing = progress.finish(outcome="passed")
                _print_operation_summary(root, progress.run_dir, timing)
                return pytest.ExitCode.OK
            if operation == "fixture-clean":
                store.clean()
                print("xverif fixture cache removed")
                return pytest.ExitCode.OK
            if operation == "results-clean":
                results = root / ".xverif-test-results"
                if results.exists():
                    shutil.rmtree(results)
                print("xverif test results removed")
                return pytest.ExitCode.OK
            if operation == "rerun-failed":
                report_path = Path(config.getoption("xverif_rerun_failed")).resolve()
                payload = json.loads(report_path.read_text(encoding="utf-8"))
                suites = sorted(
                    {
                        item["suite_id"]
                        for item in payload.get("items", [])
                        if item.get("outcome") == "failed" and item.get("suite_id") != "unmapped"
                    }
                )
                if not suites:
                    raise pytest.UsageError("report contains no failed suites")
                argv = [sys.executable, "-m", "pytest", "--xverif-gate", payload["gate"]]
                for suite_id in suites:
                    argv.extend(["--xverif-suite", suite_id])
                env = dict(os.environ)
                env["XVERIF_PARENT_REPORT"] = str(report_path)
                return subprocess.run(argv, cwd=root, env=env, check=False).returncode
        except FixtureError as exc:
            raise pytest.UsageError(str(exc)) from exc
        raise pytest.UsageError(f"xverif operation {operation!r} is not implemented")
    return None


@pytest.fixture
def xverif_fixture_store(request: pytest.FixtureRequest) -> FixtureStore:
    root = _repo_root(request.config)
    return FixtureStore(root, load_default_registry(root))


@pytest.fixture
def xverif_fixture(xverif_fixture_store: FixtureStore) -> Any:
    return xverif_fixture_store.resolve


@pytest.hookimpl(tryfirst=True)
def pytest_collection_modifyitems(
    config: pytest.Config, items: list[pytest.Item]
) -> None:
    catalog: Catalog = config._xverif_catalog  # type: ignore[attr-defined]
    plan: ExecutionPlan = config._xverif_plan  # type: ignore[attr-defined]
    selected_ids = plan.selected_ids()
    repo_root = _repo_root(config)
    unavailable: dict[str, str] = dict(
        getattr(config, "_xverif_unavailable", {})
    )
    selected_commands = [
        selected.suite
        for selected in plan.suites
        if selected.suite.runner.get("kind") == "command"
    ]
    kept: list[pytest.Item] = []
    deselected: list[pytest.Item] = []
    unmapped: list[str] = []
    for item in items:
        owners = catalog.owners_for_path(Path(str(item.path)), repo_root)
        if len(owners) == 1:
            suite = owners[0]
        else:
            markers = {marker.name for marker in item.iter_markers()}
            matched = [suite for suite in owners if suite.pytest_marker() in markers]
            suite = matched[0] if len(matched) == 1 else None
        if suite is None:
            unmapped.append(item.nodeid)
            continue
        item.user_properties.append(("xverif_suite", suite.id))
        setattr(item, "_xverif_suite_id", suite.id)
        if suite.id in selected_ids:
            if suite.id in unavailable:
                item.add_marker(pytest.mark.skip(reason=unavailable[suite.id]))
            apply_xdist_resource_group(item, suite)
            kept.append(item)
        else:
            deselected.append(item)
    if unmapped:
        raise pytest.UsageError(
            "collected pytest items are missing catalog ownership:\n  "
            + "\n  ".join(sorted(unmapped))
        )
    if selected_commands:
        if not items:
            raise pytest.UsageError("cannot attach external suite items without a pytest session")
        parent = items[0].session
        for suite in selected_commands:
            external = ExternalSuiteItem.from_suite(parent, suite)
            if suite.id in unavailable:
                external.add_marker(pytest.mark.skip(reason=unavailable[suite.id]))
            apply_xdist_resource_group(external, suite)
            kept.append(external)
    items[:] = kept
    if deselected:
        config.hook.pytest_deselected(items=deselected)
    if _PROGRESS_REPORTER is not None and not hasattr(config, "workerinput"):
        _PROGRESS_REPORTER.set_total(len(kept))


def pytest_runtest_logstart(nodeid: str, location: tuple[str, int | None, str]) -> None:
    if _PROGRESS_REPORTER is not None:
        _PROGRESS_REPORTER.item_start(nodeid)


def pytest_runtest_logreport(report: pytest.TestReport) -> None:
    if _RESULT_MANAGER is not None:
        _RESULT_MANAGER.record_report(report)
    if _PROGRESS_REPORTER is not None:
        previous = _ITEM_OUTCOMES.get(report.nodeid, "passed")
        if report.failed:
            _ITEM_OUTCOMES[report.nodeid] = "failed"
        elif report.skipped and previous != "failed":
            _ITEM_OUTCOMES[report.nodeid] = "skipped"
        else:
            _ITEM_OUTCOMES.setdefault(report.nodeid, "passed")
    if _PROGRESS_REPORTER is not None and report.when == "teardown":
        outcome = _ITEM_OUTCOMES.pop(report.nodeid, "passed")
        _PROGRESS_REPORTER.item_finish(report.nodeid, outcome=outcome)


def pytest_configure_node(node: Any) -> None:
    if _ENGINE_GUARD is not None:
        node.workerinput["xdebug_engine_owner_token"] = _ENGINE_GUARD.token
    if _RESULT_MANAGER is not None:
        node.workerinput["xverif_run_dir"] = str(_RESULT_MANAGER.run_dir)
        node.workerinput["xverif_unavailable"] = dict(
            getattr(node.config, "_xverif_unavailable", {})
        )


@pytest.hookimpl(optionalhook=True)
def pytest_xdist_node_collection_finished(node: Any, ids: list[str]) -> None:
    if _PROGRESS_REPORTER is not None and _PROGRESS_REPORTER.total is None:
        _PROGRESS_REPORTER.set_total(len(ids))


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    if _ENGINE_GUARD is not None and not hasattr(session.config, "workerinput"):
        survivors = _ENGINE_GUARD.cleanup()
        if survivors:
            session.config._xverif_engine_cleanup_survivors = sorted(survivors)  # type: ignore[attr-defined]
            session.exitstatus = pytest.ExitCode.TESTS_FAILED
    if _PROGRESS_REPORTER is not None and not hasattr(session.config, "workerinput"):
        _PROGRESS_REPORTER.finish(
            outcome="passed" if int(session.exitstatus) == 0 else "failed"
        )
    if _RESULT_MANAGER is not None and not hasattr(session.config, "workerinput"):
        _RESULT_MANAGER.finish(int(session.exitstatus))


def pytest_terminal_summary(
    terminalreporter: Any, exitstatus: int, config: pytest.Config
) -> None:
    if _RESULT_MANAGER is not None and not hasattr(config, "workerinput"):
        terminalreporter.write_line(
            "xverif results: "
            + _RESULT_MANAGER.run_dir.relative_to(_repo_root(config)).as_posix()
        )
        timing = json.loads(
            (_RESULT_MANAGER.run_dir / "timing.json").read_text(encoding="utf-8")
        )
        terminalreporter.write_line(
            f"xverif wall time: {timing['duration_sec']:.1f}s; "
            + "slowest: "
            + _slow_items_text(timing.get("items", []))
        )
    survivors = getattr(config, "_xverif_engine_cleanup_survivors", [])
    if survivors:
        terminalreporter.write_line(
            "ERROR: test-owned xdebug engine cleanup failed for pids: "
            + ", ".join(str(pid) for pid in survivors)
        )


def _progress_interval(config: pytest.Config) -> float:
    value = float(config.getoption("--xverif-progress-interval"))
    if value <= 0:
        raise pytest.UsageError("--xverif-progress-interval must be greater than 0")
    return value


def _operation_progress(
    root: Path,
    operation: str,
    total: int,
    config: pytest.Config,
) -> ProgressReporter:
    progress_interval = _progress_interval(config)
    run_dir = create_run_dir(root)
    reporter = ProgressReporter(
        operation,
        run_dir,
        total=total,
        interval_sec=progress_interval,
    )
    reporter.start()
    return reporter


def _print_operation_summary(
    root: Path, run_dir: Path, timing: dict[str, Any]
) -> None:
    print(
        f"xverif {timing['operation']} duration: {timing['duration_sec']:.1f}s; "
        f"slowest: {_slow_items_text(timing.get('items', []))}"
    )
    print(f"xverif results: {run_dir.relative_to(root).as_posix()}")


def _slow_items_text(items: list[dict[str, Any]], limit: int = 5) -> str:
    if not items:
        return "none"
    labels: list[str] = []
    for item in items[:limit]:
        label = f"{item['id']}={float(item['duration_sec']):.1f}s"
        phases = list(item.get("phases", []))
        if phases:
            slowest = max(phases, key=lambda phase: float(phase["duration_sec"]))
            label += (
                f"({slowest['name']}={float(slowest['duration_sec']):.1f}s)"
            )
        labels.append(label)
    return ", ".join(labels)
