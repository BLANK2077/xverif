"""bsub -I command construction and startup."""

from __future__ import annotations

import os
import re
import shlex
from dataclasses import dataclass
from typing import Iterable, List, Optional

from .protocol import JsonlProcess
from xverif_loop.config import RuntimeConfig
from xverif_loop.logging import StructuredLogger, argv_hash


# LSF typical output: "Job <123456> is submitted to queue <interactive>."
_JOB_RE = re.compile(r"Job\s+<(?P<job_id>\d+)>\s+is\s+submitted")
_SCHEDULER_FRAMING = (
    re.compile(r"^Job\s+<\d+>\s+is\s+submitted(?:\s+to\s+queue\s+<[^>]+>)?\.?$"),
    re.compile(r"^<<(?:Waiting for dispatch|Starting on|Job is finished).*>>$"),
)


def parse_lsf_job_id(text: str) -> Optional[str]:
    """Parse job ID from bsub stderr/stdout output."""
    m = _JOB_RE.search(text)
    return m.group("job_id") if m else None


def is_lsf_scheduler_framing(text: str) -> bool:
    """Return true only for known bsub interactive scheduler framing."""
    return any(pattern.fullmatch(text.strip()) for pattern in _SCHEDULER_FRAMING)


@dataclass
class BsubOptions:
    queue: Optional[str] = None
    resource: Optional[str] = None
    job_name: Optional[str] = None
    propagate_environment: bool = False

    def extra_args(self) -> List[str]:
        """Extra flags to pass to bsub before the command."""
        extras: List[str] = []
        if self.job_name:
            extras.extend(["-J", self.job_name])
        if self.queue:
            extras.extend(["-q", self.queue])
        if self.resource:
            extras.extend(["-R", self.resource])
        if self.propagate_environment:
            extras.extend(["-env", "all"])
        return extras


class BsubRunner:
    def __init__(self, bsub_cmd: Optional[str] = None) -> None:
        self.bsub_cmd = bsub_cmd or os.environ.get("XVERIF_LSF_BSUB", "bsub")

    def build(self, command: Iterable[str], opts: Optional[BsubOptions] = None) -> List[str]:
        opts = opts or BsubOptions()
        base = shlex.split(self.bsub_cmd)
        # Default to -I (interactive).  -Is is allowed when user explicitly sets it via
        # XVERIF_LSF_BSUB, but we default to -I for cleaner machine-protocol output.
        interactive = {"-I", "-Is", "-Ip"}
        if not any(flag in base for flag in interactive):
            base.append("-I")
        if opts.propagate_environment and "-env" in base:
            raise ValueError(
                "XVERIF_LSF_BSUB must not set -env; xverif requires explicit '-env all'"
            )
        base.extend(opts.extra_args())
        base.extend(list(command))
        return base

    def start(self, command: Iterable[str], opts: Optional[BsubOptions] = None,
              *,
              runtime: RuntimeConfig,
              logger: StructuredLogger,
              log_context: Optional[dict] = None) -> JsonlProcess:
        opts = opts or BsubOptions()
        argv = self.build(command, opts)
        alias = (log_context or {}).get("alias")
        logger.lsf(alias, "bsub.start", True,
                   argv_hash=argv_hash(argv), queue=opts.queue,
                   resource=opts.resource, job_name=opts.job_name)
        proc = JsonlProcess.start(
            argv,
            runtime=runtime,
            logger=logger,
            log_context=log_context,
        )
        proc.job_name = opts.job_name
        proc.submitted_queue = opts.queue
        proc.submitted_resource = opts.resource
        return proc
