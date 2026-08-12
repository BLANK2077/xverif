from __future__ import annotations

from pathlib import Path
from typing import Any, Iterator

import pytest

from runner import CliRunner, HybridCliRunner
from synthetic.test_stream_v1_real_waveform import (
    test_stream_v1_cache_scope_repository_contract as run_cache_contract,
)
from synthetic.test_stream_v1_real_waveform import (
    test_stream_v1_real_waveform_actions as run_action_matrix,
)


@pytest.fixture
def differential_cli_runner(
    repo_root: Path,
    isolated_home: Path,
    xverif_fixture: Any,
) -> Iterator[HybridCliRunner]:
    resources = xverif_fixture("xdebug.stream_differential_tool")
    binary = resources / "out" / "xdebug"
    assert binary.is_file()
    runner = HybridCliRunner(
        binary,
        cwd=repo_root,
        base_env={
            "HOME": str(isolated_home),
            "XVERIF_HOME": str(repo_root),
            "XVERIF_TEST_TMPDIR": str(isolated_home.parent),
        },
    )
    try:
        yield runner
    finally:
        runner.close()


@pytest.mark.synthetic
@pytest.mark.waveform
@pytest.mark.stream
@pytest.mark.regression
@pytest.mark.slow
def test_stream_differential_action_matrix(
    differential_cli_runner: CliRunner,
    xdebug_root: Path,
    artifact_root: Path,
    tmp_path: Path,
    xverif_fixture: Any,
) -> None:
    run_action_matrix(
        differential_cli_runner,
        xdebug_root,
        artifact_root,
        tmp_path,
        xverif_fixture,
    )


@pytest.mark.synthetic
@pytest.mark.waveform
@pytest.mark.stream
@pytest.mark.regression
@pytest.mark.slow
def test_stream_differential_cache_contract(
    differential_cli_runner: CliRunner,
    xdebug_root: Path,
    artifact_root: Path,
    tmp_path: Path,
    xverif_fixture: Any,
) -> None:
    run_cache_contract(
        differential_cli_runner,
        xdebug_root,
        artifact_root,
        tmp_path,
        xverif_fixture,
    )
