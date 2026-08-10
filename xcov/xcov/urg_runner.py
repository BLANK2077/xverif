"""URG process runner: direct or bsub, with environment inheritance.

All URG invocations go through this module so that LSF/bsub configuration
is applied uniformly.
"""
from __future__ import annotations

import os
import shlex
import subprocess
from dataclasses import dataclass
from typing import List, Optional, Sequence

from .eda import get_urg_path


@dataclass
class UrgRunResult:
    returncode: int
    stdout: str
    stderr: str
    argv: List[str]


class UrgRunner:
    def __init__(
        self,
        *,
        bsub_cmd: Optional[str] = None,
        queue: Optional[str] = None,
        resource: Optional[str] = None,
    ) -> None:
        self._bsub_cmd = bsub_cmd or os.environ.get("XVERIF_LSF_BSUB")
        self._queue = queue
        self._resource = resource

    @property
    def use_bsub(self) -> bool:
        return bool(self._bsub_cmd)

    def build_argv(self, urg_args: Sequence[str]) -> List[str]:
        argv = list(urg_args)
        if argv and argv[0] == "urg":
            argv[0] = get_urg_path()
        if not self.use_bsub:
            return argv

        base = shlex.split(self._bsub_cmd)
        interactive = {"-I", "-Is", "-Ip"}
        if not any(flag in base for flag in interactive):
            base.append("-I")
        if self._queue:
            base.extend(["-q", self._queue])
        if self._resource:
            base.extend(["-R", self._resource])
        base.extend(argv)
        return base

    def run(
        self,
        urg_args: Sequence[str],
        *,
        timeout: Optional[float] = None,
        cwd: Optional[str] = None,
        env: Optional[dict] = None,
    ) -> UrgRunResult:
        argv = self.build_argv(urg_args)
        proc = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=cwd,
            env=env if env is not None else os.environ,
            check=False,
        )
        return UrgRunResult(
            returncode=proc.returncode,
            stdout=proc.stdout,
            stderr=proc.stderr,
            argv=argv,
        )
