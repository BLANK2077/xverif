from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping, Optional, Sequence

from .cli import CliRunner, RunResult
from .normalize import NormalizeOptions
from .stdio_loop import StdioLoopRunner


class HybridCliRunner:
    """Reuse one JSON frontend while preserving real CLI boundary coverage."""

    def __init__(
        self,
        xdebug_bin: Path,
        *,
        cwd: Optional[Path] = None,
        base_env: Optional[Mapping[str, str]] = None,
        normalize_options: Optional[NormalizeOptions] = None,
    ) -> None:
        self.xdebug_bin = Path(xdebug_bin)
        self.cwd = Path(cwd or Path.cwd())
        self.base_env = dict(base_env or {})
        self.normalize_options = normalize_options or NormalizeOptions()
        self.history: list[RunResult] = []
        self.transcript: list[dict[str, Any]] = []
        self._loop: StdioLoopRunner | None = None
        self._cli = CliRunner(
            self.xdebug_bin,
            cwd=self.cwd,
            base_env=self.base_env,
            normalize_options=self.normalize_options,
        )

    def _ensure_loop(self) -> StdioLoopRunner:
        if self._loop is None:
            self._loop = StdioLoopRunner(
                self.xdebug_bin,
                cwd=self.cwd,
                env=self.base_env,
                default_json=True,
                wait_for_stderr_idle=False,
                normalize_options=self.normalize_options,
            )
            self._loop.start()
            self.transcript = self._loop.transcript
        return self._loop

    def run(
        self,
        request: Any,
        *,
        output_format: str = "json",
        input_mode: str = "stdin",
        timeout_sec: float = 60.0,
        env: Optional[Mapping[str, str]] = None,
        cwd: Optional[Path] = None,
        extra_args: Sequence[str] = (),
    ) -> RunResult:
        use_loop = (
            output_format == "json"
            and input_mode == "stdin"
            and isinstance(request, dict)
            and env is None
            and cwd is None
            and not extra_args
        )
        if use_loop:
            result = self._ensure_loop().request(
                request,
                timeout_sec=timeout_sec,
            )
        else:
            result = self._cli.run(
                request,
                output_format=output_format,
                input_mode=input_mode,
                timeout_sec=timeout_sec,
                env=env,
                cwd=cwd,
                extra_args=extra_args,
            )
        self.history.append(result)
        return result

    def close(self) -> None:
        if self._loop is None:
            return
        try:
            self._loop.quit()
        finally:
            self._loop.terminate()

    def restart(self) -> None:
        """Apply an intentional environment boundary before the next request."""
        self.close()
        self._loop = None
        self.transcript = []

    def __enter__(self) -> "HybridCliRunner":
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        self.close()
