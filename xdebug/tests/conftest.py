from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from runner import (
    ArtifactWriter,
    CliRunner,
    CommandRunner,
    HybridCliRunner,
    StdioLoopRunner,
)


TESTS_ROOT = Path(__file__).resolve().parent
XDEBUG_ROOT = TESTS_ROOT.parent
REPO_ROOT = XDEBUG_ROOT.parent

if str(TESTS_ROOT) not in sys.path:
    sys.path.insert(0, str(TESTS_ROOT))


def _kill_all_sessions_for_home(xdebug_bin: Path, home: Path) -> None:
    request = {
        "api_version": "xdebug.v1",
        "action": "session.close",
        "target": {"session_id": "all"},
        "args": {"mode": "force"},
    }
    env = dict(os.environ)
    env.update({"HOME": str(home), "XVERIF_HOME": str(REPO_ROOT)})
    try:
        subprocess.run(
            [str(xdebug_bin), "--json", "-"],
            input=json.dumps(request) + "\n",
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=30,
            check=False,
            cwd=str(REPO_ROOT),
            env=env,
        )
    except (OSError, subprocess.TimeoutExpired):
        pass


def pytest_addoption(parser: pytest.Parser) -> None:
    group = parser.getgroup("xdebug")
    group.addoption(
        "--xdebug-bin",
        default=os.environ.get("XDEBUG_BIN", str(REPO_ROOT / "tools" / "xdebug")),
        help="xdebug wrapper/binary path",
    )
    group.addoption(
        "--xdebug-artifacts",
        default=os.environ.get(
            "XDEBUG_TEST_ARTIFACTS",
            str(XDEBUG_ROOT / "tests" / "artifacts"),
        ),
        help="failure artifact root",
    )


@pytest.fixture(scope="session")
def repo_root() -> Path:
    return REPO_ROOT


@pytest.fixture(scope="session")
def xdebug_root() -> Path:
    return XDEBUG_ROOT


@pytest.fixture(scope="session")
def xdebug_bin(pytestconfig: pytest.Config) -> Path:
    return Path(pytestconfig.getoption("--xdebug-bin")).expanduser().resolve()


@pytest.fixture
def complex_wave_fsdb(xverif_fixture) -> Path:
    return xverif_fixture("xdebug.ai_complex_wave") / "out/waves.fsdb"


@pytest.fixture
def stream_wave_fsdb(xverif_fixture) -> Path:
    return xverif_fixture("xdebug.stream_v1") / "out/waves.fsdb"


@pytest.fixture(scope="session")
def artifact_root(pytestconfig: pytest.Config) -> Path:
    return Path(pytestconfig.getoption("--xdebug-artifacts")).expanduser().resolve()


@pytest.fixture
def isolated_home(tmp_path: Path) -> Path:
    home = tmp_path / "home"
    home.mkdir()
    return home


@pytest.fixture(autouse=True)
def cleanup_xdebug_sessions_after_test(request: pytest.FixtureRequest) -> None:
    yield
    home = getattr(request.node, "funcargs", {}).get("isolated_home")
    if home is None:
        return
    xdebug_bin = Path(request.config.getoption("--xdebug-bin")).expanduser().resolve()
    _kill_all_sessions_for_home(xdebug_bin, home)


@pytest.fixture
def cli_runner(
    xdebug_bin: Path,
    repo_root: Path,
    isolated_home: Path,
) -> CliRunner:
    return CliRunner(
        xdebug_bin,
        cwd=repo_root,
        base_env={"HOME": str(isolated_home), "XVERIF_HOME": str(repo_root)},
    )


@pytest.fixture
def persistent_cli_runner(
    xdebug_bin: Path,
    repo_root: Path,
    isolated_home: Path,
) -> HybridCliRunner:
    runner = HybridCliRunner(
        xdebug_bin,
        cwd=repo_root,
        base_env={"HOME": str(isolated_home), "XVERIF_HOME": str(repo_root)},
    )
    try:
        yield runner
    finally:
        runner.close()


@pytest.fixture(scope="module")
def stateless_stdio_loop(
    xdebug_bin: Path,
    repo_root: Path,
    tmp_path_factory: pytest.TempPathFactory,
) -> StdioLoopRunner:
    home = tmp_path_factory.mktemp("stateless-stdio-loop-home")
    loop = StdioLoopRunner(
        xdebug_bin,
        cwd=repo_root,
        env={"HOME": str(home), "XVERIF_HOME": str(repo_root)},
        default_json=True,
        wait_for_stderr_idle=False,
    )
    loop.start()
    try:
        yield loop
    finally:
        loop.quit()
        loop.terminate()


@pytest.fixture
def command_runner(repo_root: Path, isolated_home: Path) -> CommandRunner:
    return CommandRunner(
        cwd=repo_root,
        base_env={"HOME": str(isolated_home), "XVERIF_HOME": str(repo_root)},
    )


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item: pytest.Item, call: pytest.CallInfo):
    outcome = yield
    report = outcome.get_result()
    if report.when != "call" or not report.failed:
        return

    artifact_root = Path(item.config.getoption("--xdebug-artifacts")).expanduser()
    writer = ArtifactWriter(artifact_root, run_id="pytest-failures")
    seen_results: set[int] = set()
    written: list[str] = []
    errors: list[str] = []

    for fixture_name, fixture_value in item.funcargs.items():
        history = getattr(fixture_value, "history", None)
        if not history:
            continue
        transcript = getattr(fixture_value, "transcript", None)
        for index, result in enumerate(history, start=1):
            if id(result) in seen_results:
                continue
            seen_results.add(id(result))
            extra = {}
            if transcript is not None:
                extra["session_log"] = transcript
            case_name = "%s/%s-%02d" % (item.nodeid, fixture_name, index)
            try:
                case_dir = writer.write(case_name, result, extra=extra)
                written.append(str(case_dir))
            except Exception as exc:  # pragma: no cover - best-effort on failure path
                errors.append("%s: %s" % (fixture_name, exc))

    if written or errors:
        text = ""
        if written:
            text += "artifact_dirs:\n" + "\n".join(written)
        if errors:
            text += ("\n" if text else "") + "artifact_errors:\n" + "\n".join(errors)
        item.add_report_section("call", "xdebug artifacts", text)
