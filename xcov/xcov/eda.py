"""Strict EDA toolchain provenance and vendor module loading."""
from __future__ import annotations

import importlib
import os
from pathlib import Path
import sys
import threading
from types import ModuleType

from .errors import XcovError

_IMPORT_LOCK = threading.RLock()


def _strict_home(env_name: str) -> Path:
    raw = os.environ.get(env_name)
    if not raw or raw != raw.strip():
        raise XcovError(
            "EDA_PROVENANCE_INVALID",
            f"{env_name} must be set to a non-empty installation directory",
        )
    try:
        home = Path(raw).resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise XcovError(
            "EDA_PROVENANCE_INVALID",
            f"{env_name} cannot be resolved",
        ) from exc
    if not home.is_dir():
        raise XcovError(
            "EDA_PROVENANCE_INVALID",
            f"{env_name} is not an installation directory",
        )
    return home


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def resolve_verdi_home() -> str:
    """Return a canonical, existing VERDI_HOME installation root."""

    override = os.environ.get("XVERIF_XCOV_VERDI_HOME")
    if override is not None:
        if not override or override != override.strip():
            raise XcovError(
                "EDA_PROVENANCE_INVALID",
                "XVERIF_XCOV_VERDI_HOME must be a non-empty installation directory",
            )
        try:
            home = Path(override).resolve(strict=True)
        except (OSError, RuntimeError) as exc:
            raise XcovError(
                "EDA_PROVENANCE_INVALID",
                "XVERIF_XCOV_VERDI_HOME cannot be resolved",
            ) from exc
        if not home.is_dir():
            raise XcovError(
                "EDA_PROVENANCE_INVALID",
                "XVERIF_XCOV_VERDI_HOME is not an installation directory",
            )
        return str(home)
    return str(_strict_home("VERDI_HOME"))


def get_npi_python_path() -> str:
    """Return the canonical vendor ``share/NPI/python`` directory."""

    home = Path(resolve_verdi_home())
    candidate = home / "share" / "NPI" / "python"
    try:
        npi_path = candidate.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise XcovError(
            "EDA_PROVENANCE_INVALID",
            "VERDI_HOME does not contain share/NPI/python",
        ) from exc
    if not npi_path.is_dir() or not _is_within(npi_path, home):
        raise XcovError(
            "EDA_PROVENANCE_INVALID",
            "NPI Python directory escapes the configured VERDI_HOME",
        )
    return str(npi_path)


def get_urg_path() -> str:
    """Return the verified ``VCS_HOME/bin/urg`` executable.

    PATH is intentionally never consulted.  An invalid or missing VCS_HOME is
    a provenance failure, not a reason to execute another binary.
    """

    home = _strict_home("VCS_HOME")
    candidate = home / "bin" / "urg"
    try:
        urg = candidate.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise XcovError(
            "EDA_PROVENANCE_INVALID",
            "VCS_HOME does not contain bin/urg",
        ) from exc
    if (
        not urg.is_file()
        or not os.access(urg, os.X_OK)
        or not _is_within(urg, home)
    ):
        raise XcovError(
            "EDA_PROVENANCE_INVALID",
            "VCS_HOME/bin/urg is not an executable within VCS_HOME",
        )
    return str(urg)


def _module_path(module: ModuleType, vendor_root: Path) -> Path:
    raw = getattr(module, "__file__", None)
    if not isinstance(raw, str) or not raw:
        raise XcovError(
            "EDA_PROVENANCE_INVALID",
            f"vendor module {module.__name__} has no verifiable __file__",
        )
    try:
        actual = Path(raw).resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise XcovError(
            "EDA_PROVENANCE_INVALID",
            f"vendor module {module.__name__} cannot be resolved",
        ) from exc
    if not _is_within(actual, vendor_root):
        raise XcovError(
            "EDA_PROVENANCE_INVALID",
            f"vendor module {module.__name__} was loaded outside VERDI_HOME",
        )
    return actual


def import_pynpi():
    """Import pynpi from the exact configured vendor root and verify origin."""

    vendor_root = Path(get_npi_python_path())
    with _IMPORT_LOCK:
        for name, module in tuple(sys.modules.items()):
            if name != "pynpi" and not name.startswith("pynpi."):
                continue
            if isinstance(module, ModuleType):
                _module_path(module, vendor_root)

        original_path = list(sys.path)
        try:
            sys.path.insert(0, str(vendor_root))
            importlib.invalidate_caches()
            package = importlib.import_module("pynpi")
            cov = importlib.import_module("pynpi.cov")
            npisys = importlib.import_module("pynpi.npisys")
        except XcovError:
            raise
        except Exception as exc:
            raise XcovError(
                "NPI_INIT_FAILED",
                f"failed to import pynpi from configured VERDI_HOME: {exc}",
            ) from exc
        finally:
            sys.path[:] = original_path

        _module_path(package, vendor_root)
        _module_path(cov, vendor_root)
        _module_path(npisys, vendor_root)
        return cov, npisys
