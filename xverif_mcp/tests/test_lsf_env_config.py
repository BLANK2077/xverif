"""Contracts for SDK-free LSF environment files and capture."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from xverif_loop.env_config import (
    CONFIG_FINGERPRINT_ENV,
    ENV_FINGERPRINT_ENV,
    ENV_KEYS_ENV,
    LOADED_CONFIG_PATH_ENV,
    EnvironmentConfigError,
    capture_variables,
    environment_fingerprint,
    load_environment_config,
    write_environment_config,
)


def _write(path: Path, variables: dict[str, object]) -> None:
    path.write_text(json.dumps({
        "schema_version": "xverif-lsf-env.v1",
        "variables": variables,
    }), encoding="utf-8")
    path.chmod(0o600)


def test_environment_config_overrides_environment_and_publishes_fingerprints(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = tmp_path / "xverif_lsf.env.json"
    _write(config, {"PATH": "/captured/bin", "SITE_MARKER": "你好, world"})
    monkeypatch.setenv("XVERIF_LSF_CLI_CONFIG", str(config))
    target = {"PATH": "/ambient/bin"}
    path, names, config_fingerprint = load_environment_config(environ=target)
    assert path == config
    assert names == ("PATH", "SITE_MARKER")
    assert target["PATH"] == "/captured/bin"
    assert target[LOADED_CONFIG_PATH_ENV] == str(config)
    assert target[ENV_KEYS_ENV] == "PATH,SITE_MARKER"
    assert target[ENV_FINGERPRINT_ENV] == environment_fingerprint({
        "PATH": "/captured/bin",
        "SITE_MARKER": "你好, world",
    })
    assert target[CONFIG_FINGERPRINT_ENV] == config_fingerprint


@pytest.mark.parametrize(
    "contents,error",
    [
        ('{"schema_version":"xverif-lsf-env.v1","variables":{"A":"1","A":"2"}}', "duplicate"),
        ('{"schema_version":"xverif-lsf-env.v1","variables":{"A":1}}', "must be a string"),
        ('{"schema_version":"xverif-lsf-env.v1","variables":{"A":"1"},"extra":1}', "unknown"),
        ('{"schema_version":"wrong","variables":{"A":"1"}}', "schema_version"),
    ],
)
def test_environment_config_rejects_invalid_contract(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    contents: str,
    error: str,
) -> None:
    config = tmp_path / "bad.json"
    config.write_text(contents, encoding="utf-8")
    config.chmod(0o600)
    monkeypatch.setenv("XVERIF_LSF_CLI_CONFIG", str(config))
    with pytest.raises(EnvironmentConfigError, match=error):
        load_environment_config(environ={})


def test_environment_config_rejects_unsafe_mode_and_symlink(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = tmp_path / "config.json"
    _write(config, {"A": "1"})
    config.chmod(0o644)
    monkeypatch.setenv("XVERIF_LSF_CLI_CONFIG", str(config))
    with pytest.raises(EnvironmentConfigError, match="0600"):
        load_environment_config(environ={})
    config.chmod(0o600)
    link = tmp_path / "link.json"
    link.symlink_to(config)
    monkeypatch.setenv("XVERIF_LSF_CLI_CONFIG", str(link))
    with pytest.raises(EnvironmentConfigError, match="regular file"):
        load_environment_config(environ={})


def test_capture_filters_sensitive_and_volatile_variables() -> None:
    captured = capture_variables({
        "PATH": "/bin",
        "VERDI_HOME": "/verdi",
        "XVERIF_SITE": "enabled",
        "XVERIF_API_TOKEN": "private",
        "LSB_JOBID": "42",
        "PWD": "/tmp",
        "CUSTOM_LICENSE": "27000@host",
    }, includes=["CUSTOM_LICENSE"])
    assert captured == {
        "CUSTOM_LICENSE": "27000@host",
        "PATH": "/bin",
        "VERDI_HOME": "/verdi",
        "XVERIF_SITE": "enabled",
    }


def test_write_environment_config_is_0600_no_clobber_and_atomic(tmp_path: Path) -> None:
    output = tmp_path / "xverif_lsf.env.json"
    write_environment_config(output, {"PATH": "/one"}, force=False)
    assert output.stat().st_mode & 0o777 == 0o600
    with pytest.raises(EnvironmentConfigError, match="--force"):
        write_environment_config(output, {"PATH": "/two"}, force=False)
    write_environment_config(output, {"PATH": "/two"}, force=True)
    assert json.loads(output.read_text(encoding="utf-8"))["variables"]["PATH"] == "/two"
    assert not list(tmp_path.glob(".xverif_lsf.env.json.*"))


def test_missing_default_config_preserves_environment(tmp_path: Path) -> None:
    target = dict(os.environ)
    original = dict(target)
    assert load_environment_config(environ=target, argv0=str(tmp_path / "xdebug_lsf")) == (
        None, (), None,
    )
    assert target == original


def test_sdk_free_manager_logs_only_config_metadata(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from xverif_loop.config import resolve_loop_wrapper_runtime_config
    from xverif_loop.logging import resolve_logger
    from xverif_loop.wrapper import LoopWrapperService

    monkeypatch.setenv("XVERIF_LOOP_LOG_DIR", str(tmp_path / "logs"))
    monkeypatch.setenv("XVERIF_LSF_CLI_CONFIG_FINGERPRINT", "config-fingerprint")
    monkeypatch.setenv("XVERIF_LSF_CLI_LOADED_CONFIG_PATH", "/safe/config.json")
    monkeypatch.setenv("XVERIF_LSF_ENV_KEYS", "PATH,SITE_MARKER")
    monkeypatch.setenv("SITE_MARKER", "must-not-appear")
    runtime = resolve_loop_wrapper_runtime_config()
    logger = resolve_logger(runtime)
    LoopWrapperService(
        mode="lsf",
        xdebug_bin="false",
        xcov_bin="false",
        runtime=runtime,
        logger=logger,
        sdk_free_lsf_manager=True,
    )
    log_text = logger.server_log_path().read_text(encoding="utf-8")
    event = json.loads(log_text.splitlines()[-1])
    assert "sdk_free.lsf_environment.loaded" in log_text
    assert event["config_path"]["basename"] == "config.json"
    assert "SITE_MARKER" in log_text
    assert "/safe/config.json" not in log_text
    assert "must-not-appear" not in log_text
