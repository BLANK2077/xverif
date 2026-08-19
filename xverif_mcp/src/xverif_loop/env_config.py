"""Secure SDK-free LSF environment configuration and capture CLI."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys
import tempfile
from typing import Mapping, Sequence


SCHEMA_VERSION = "xverif-lsf-env.v1"
DEFAULT_CONFIG_NAME = "xverif_lsf.env.json"
CONFIG_PATH_ENV = "XVERIF_LSF_CLI_CONFIG"
ENTRY_DIR_ENV = "XVERIF_LSF_CLI_ENTRY_DIR"
LOADED_CONFIG_PATH_ENV = "XVERIF_LSF_CLI_LOADED_CONFIG_PATH"
CONFIG_FINGERPRINT_ENV = "XVERIF_LSF_CLI_CONFIG_FINGERPRINT"
ENV_KEYS_ENV = "XVERIF_LSF_ENV_KEYS"
ENV_FINGERPRINT_ENV = "XVERIF_LSF_ENV_FINGERPRINT"
VERIFIED_FINGERPRINT_ENV = "XVERIF_LSF_ENV_VERIFIED_FINGERPRINT"

_ENV_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_EXACT_CAPTURE = frozenset({
    "PATH",
    "LD_LIBRARY_PATH",
    "PYTHONPATH",
    "VERDI_HOME",
    "VCS_HOME",
    "LM_LICENSE_FILE",
    "SNPSLMD_LICENSE_FILE",
})
_CAPTURE_PREFIXES = ("XVERIF_", "XDEBUG_", "XCOV_", "LSF_")
_SENSITIVE_FRAGMENTS = ("TOKEN", "PASSWORD", "SECRET", "COOKIE")
_VOLATILE_EXACT = frozenset({
    "PWD", "OLDPWD", "SHLVL", "_", "LS_JOBPID", "LSF_VERSION",
})
_VOLATILE_PREFIXES = ("LSB_",)
_RESERVED = frozenset({
    ENTRY_DIR_ENV,
    LOADED_CONFIG_PATH_ENV,
    CONFIG_FINGERPRINT_ENV,
    ENV_KEYS_ENV,
    ENV_FINGERPRINT_ENV,
    VERIFIED_FINGERPRINT_ENV,
    "XVERIF_LOOP_BACKEND",
})


class EnvironmentConfigError(ValueError):
    """An SDK-free LSF environment configuration is invalid or unsafe."""


def _reject_duplicate_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise EnvironmentConfigError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _strict_config_loads(text: str) -> object:
    def reject_constant(value: str) -> None:
        raise EnvironmentConfigError(f"non-finite JSON constant is forbidden: {value}")

    return json.loads(
        text,
        parse_constant=reject_constant,
        object_pairs_hook=_reject_duplicate_pairs,
    )


def entry_directory(argv0: str | None = None) -> Path:
    configured = os.environ.get(ENTRY_DIR_ENV)
    if configured:
        return Path(configured).expanduser().resolve()
    raw = argv0 if argv0 is not None else sys.argv[0]
    return Path(raw).expanduser().resolve().parent


def _absolute_path(raw: str | os.PathLike[str]) -> Path:
    return Path(os.path.abspath(os.path.expanduser(os.fspath(raw))))


def default_config_path(argv0: str | None = None) -> Path:
    configured = os.environ.get(CONFIG_PATH_ENV)
    if configured:
        return _absolute_path(configured)
    return entry_directory(argv0) / DEFAULT_CONFIG_NAME


def _validate_config_file(path: Path) -> None:
    try:
        info = path.lstat()
    except FileNotFoundError:
        raise
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
        raise EnvironmentConfigError(f"LSF environment config must be a regular file: {path}")
    if info.st_uid != os.getuid():
        raise EnvironmentConfigError(f"LSF environment config must be owned by uid {os.getuid()}: {path}")
    mode = stat.S_IMODE(info.st_mode)
    if mode != 0o600:
        raise EnvironmentConfigError(
            f"LSF environment config mode must be 0600, got {mode:04o}: {path}"
        )


def _validate_variables(value: object) -> dict[str, str]:
    if type(value) is not dict or not value:
        raise EnvironmentConfigError("variables must be a non-empty object")
    variables: dict[str, str] = {}
    for name, raw in value.items():
        if type(name) is not str or not _ENV_NAME_RE.fullmatch(name):
            raise EnvironmentConfigError(f"invalid environment variable name: {name!r}")
        if name in _RESERVED:
            raise EnvironmentConfigError(f"reserved environment variable is not configurable: {name}")
        if type(raw) is not str:
            raise EnvironmentConfigError(f"environment variable {name} must be a string")
        if "\x00" in raw:
            raise EnvironmentConfigError(f"environment variable {name} contains NUL")
        variables[name] = raw
    return variables


def _fingerprint_payload(
    names: Sequence[str],
    environ: Mapping[str, str],
) -> bytes:
    payload = bytearray()
    for name in sorted(names):
        name_bytes = name.encode("utf-8")
        payload.extend(str(len(name_bytes)).encode("ascii"))
        payload.extend(b":")
        payload.extend(name_bytes)
        if name not in environ:
            payload.extend(b"0")
            continue
        value_bytes = environ[name].encode("utf-8")
        payload.extend(b"1")
        payload.extend(str(len(value_bytes)).encode("ascii"))
        payload.extend(b":")
        payload.extend(value_bytes)
    return bytes(payload)


def environment_fingerprint(variables: Mapping[str, str]) -> str:
    return hashlib.sha256(
        _fingerprint_payload(tuple(variables), variables)
    ).hexdigest()


def observed_environment_fingerprint(
    names: Sequence[str],
    environ: Mapping[str, str],
) -> str:
    return hashlib.sha256(_fingerprint_payload(names, environ)).hexdigest()


def load_environment_config(
    *,
    environ: dict[str, str] | None = None,
    argv0: str | None = None,
) -> tuple[Path | None, tuple[str, ...], str | None]:
    target = os.environ if environ is None else environ
    path = default_config_path(argv0)
    if not path.exists() and not path.is_symlink():
        return None, (), None
    _validate_config_file(path)
    try:
        document = _strict_config_loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, TypeError, ValueError) as exc:
        raise EnvironmentConfigError(f"invalid LSF environment config {path}: {exc}") from exc
    if type(document) is not dict:
        raise EnvironmentConfigError("LSF environment config must be one JSON object")
    unknown = sorted(set(document) - {"schema_version", "variables"})
    if unknown:
        raise EnvironmentConfigError(f"unknown LSF environment config fields: {', '.join(unknown)}")
    if document.get("schema_version") != SCHEMA_VERSION:
        raise EnvironmentConfigError(f"schema_version must be {SCHEMA_VERSION}")
    variables = _validate_variables(document.get("variables"))
    fingerprint = environment_fingerprint(variables)
    config_identity = hashlib.sha256(
        (f"{path}\0{fingerprint}").encode("utf-8")
    ).hexdigest()
    target.update(variables)
    names = tuple(sorted(variables))
    target[LOADED_CONFIG_PATH_ENV] = str(path)
    target[CONFIG_FINGERPRINT_ENV] = config_identity
    target[ENV_KEYS_ENV] = ",".join(names)
    target[ENV_FINGERPRINT_ENV] = fingerprint
    return path, names, config_identity


def _is_default_capture_name(name: str) -> bool:
    if name in _VOLATILE_EXACT or any(name.startswith(prefix) for prefix in _VOLATILE_PREFIXES):
        return False
    if any(fragment in name.upper() for fragment in _SENSITIVE_FRAGMENTS):
        return False
    if name in _RESERVED or name == CONFIG_PATH_ENV:
        return False
    return name in _EXACT_CAPTURE or any(name.startswith(prefix) for prefix in _CAPTURE_PREFIXES)


def capture_variables(
    environ: Mapping[str, str],
    includes: Sequence[str] = (),
) -> dict[str, str]:
    include_set: set[str] = set()
    for name in includes:
        if not _ENV_NAME_RE.fullmatch(name):
            raise EnvironmentConfigError(f"invalid --include variable name: {name!r}")
        if name in _RESERVED:
            raise EnvironmentConfigError(f"reserved variable cannot be included: {name}")
        if name not in environ:
            raise EnvironmentConfigError(f"--include variable is not set: {name}")
        include_set.add(name)
    names = sorted(name for name in environ if _is_default_capture_name(name) or name in include_set)
    variables: dict[str, str] = {}
    for name in names:
        value = environ[name]
        if not value or "\x00" in value:
            continue
        variables[name] = value
    if not variables:
        raise EnvironmentConfigError("no eligible environment variables are set")
    return variables


def write_environment_config(path: Path, variables: Mapping[str, str], *, force: bool) -> None:
    path = _absolute_path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() or path.is_symlink():
        if not force:
            raise EnvironmentConfigError(f"config already exists; use --force to replace: {path}")
        _validate_config_file(path)
    document = {"schema_version": SCHEMA_VERSION, "variables": dict(sorted(variables.items()))}
    data = json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    fd, staging_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    staging = Path(staging_name)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(staging, path)
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        try:
            staging.unlink()
        except FileNotFoundError:
            pass


def capture_main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="xverif_lsf_env_capture")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--include", action="append", default=[])
    parser.add_argument("--output")
    parser.add_argument("--force", action="store_true")
    ns = parser.parse_args(argv)
    try:
        variables = capture_variables(dict(os.environ), ns.include)
        output = _absolute_path(ns.output) if ns.output else default_config_path()
        if ns.dry_run:
            for name in variables:
                print(name)
            return 0
        write_environment_config(output, variables, force=ns.force)
        print(f"wrote {len(variables)} environment variables to {output}")
        return 0
    except (OSError, EnvironmentConfigError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(capture_main())
