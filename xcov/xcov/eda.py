"""EDA toolchain path resolution and safe vendor import.

Resolves Verdi/VCS installation paths from environment variables and provides
safe, idempotent import of the Synopsys pynpi Python bindings.  All xcov
modules and tests should go through this module instead of writing their own
sys.path manipulation.
"""

from __future__ import annotations

import os
import shutil
import sys

from .errors import XcovError


def resolve_verdi_home() -> str:
    """Return VERDI_HOME path, preferring XVERIF_XCOV_VERDI_HOME override."""
    verdi_home = os.environ.get("XVERIF_XCOV_VERDI_HOME") or os.environ.get("VERDI_HOME")
    if not verdi_home:
        raise XcovError("NPI_INIT_FAILED", "VERDI_HOME is required")
    return verdi_home


def get_npi_python_path() -> str:
    """Return the absolute path to $VERDI_HOME/share/NPI/python.

    Validates that the directory exists.
    """
    verdi_home = resolve_verdi_home()
    npi_path = os.path.abspath(os.path.join(verdi_home, "share", "NPI", "python"))
    if not os.path.isdir(npi_path):
        raise XcovError(
            "NPI_INIT_FAILED",
            f"NPI Python path does not exist: {npi_path}",
            verdi_home=verdi_home,
        )
    return npi_path


def get_urg_path() -> str:
    """Return the path to the urg binary.

    Derivation: $VCS_HOME/bin/urg.  If VCS_HOME is not set, falls back to
    "urg" (relying on PATH).  Validates reachability via shutil.which.
    """
    vcs_home = os.environ.get("VCS_HOME")
    if vcs_home:
        urg = os.path.join(vcs_home, "bin", "urg")
        if os.path.isfile(urg) and os.access(urg, os.X_OK):
            return urg
    # Fallback: rely on PATH
    which = shutil.which("urg")
    if which:
        return which
    raise XcovError(
        "URG_NOT_FOUND",
        "urg binary not found; set VCS_HOME or ensure urg is on PATH",
        vcs_home=vcs_home or "(not set)",
    )


def import_pynpi():
    """Safely import pynpi (cov, npisys).  Idempotent.

    Adds the NPI Python path to sys.path if not already present, then imports
    and returns (cov, npisys).  Raises XcovError("NPI_INIT_FAILED", ...) on
    failure.
    """
    npi_path = get_npi_python_path()
    if npi_path not in sys.path:
        sys.path.append(npi_path)
    try:
        from pynpi import cov, npisys  # type: ignore
    except Exception as exc:
        raise XcovError(
            "NPI_INIT_FAILED",
            f"failed to import pynpi: {exc}",
        ) from exc
    return cov, npisys
