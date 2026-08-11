"""Stateful xcov adapter for VCS/Verdi coverage database queries."""
from __future__ import annotations

from typing import Any, Dict, Optional

from xverif_loop.config import RuntimeConfig, default_xcov_bin, resolve_mcp_runtime_config
from xverif_loop.json_contract import strict_json_dumps
from xverif_loop.logging import StructuredLogger, resolve_logger
from xverif_loop.sessions.session_manager import McpSessionManager

Json = Dict[str, Any]


class XverifCoverageAdapter:
    def __init__(
        self,
        mode: Optional[str] = None,
        startup_timeout_sec: Optional[float] = None,
        request_timeout_sec: Optional[float] = None,
        *,
        session_manager: Any = None,
        runtime: RuntimeConfig | None = None,
        logger: StructuredLogger | None = None,
    ) -> None:
        self.runtime = (runtime or resolve_mcp_runtime_config()).with_overrides(
            backend=mode,
            startup_timeout_sec=startup_timeout_sec,
            request_timeout_sec=request_timeout_sec,
        )
        self.logger = logger or resolve_logger(self.runtime)
        self.mode = self.runtime.backend
        self._sessions = session_manager
        if self._sessions is None:
            self._sessions = McpSessionManager(
                runtime=self.runtime,
                xdebug_bin=default_xcov_bin(),
                backend="xcov",
                api_version="xcov.v1",
                ready_protocol="xcov-stdio-loop",
                target_key="vdb",
                recovery_tool="xverif_cov_session_open",
                logger=self.logger,
            )

    def actions(self) -> Json:
        return self._one_shot({"api_version": "xcov.v1", "action": "actions"})

    def schema(self, action: str, kind: str = "request") -> Json:
        return self._one_shot({
            "api_version": "xcov.v1", "action": "schema",
            "args": {"action": action, "kind": kind},
        })

    def request(self, request: Json, output_format: str = "xout") -> Any:
        from xverif_mcp.runner import StatelessCliRunner
        req = dict(request)
        req.setdefault("api_version", "xcov.v1")
        runner = StatelessCliRunner()
        input_text = strict_json_dumps(req)
        if output_format == "xout":
            return runner.run_xout("xcov", ["-"], input_text)
        if output_format == "json":
            return runner.run_json("xcov", ["--json", "-"], input_text)
        return {
            "ok": False,
            "error": {
                "code": "INVALID_ARGUMENT",
                "message": "output_format='envelope' requires a managed stdio-loop session; one-shot xcov requests support xout or json",
                "recoverable": True,
                "error_layer": "wrapper",
            },
        }

    def _one_shot(self, req: Json) -> Json:
        from xverif_mcp.runner import StatelessCliRunner
        req = dict(req)
        return StatelessCliRunner().run_json(
            "xcov", ["--json", "-"], strict_json_dumps(req)
        )

    def session_open(self, name: str, vdb: str, run_manifest: Optional[str] = None, **kwargs: Any) -> Json:
        return self._sessions.open_session(
            name=name, fsdb=vdb, run_manifest=run_manifest, **kwargs
        )

    def session_list(self, **kwargs: Any) -> Json:
        return self._sessions.list_sessions(**kwargs)

    def session_close(
        self,
        session_id: str,
        *,
        confirm_discard_reasons: bool = False,
    ) -> Json:
        return self._sessions.close_session(
            session_id,
            confirm_discard_reasons=confirm_discard_reasons,
        )

    def session_doctor(self, session_id: str, verbose: bool = False) -> Json:
        return self._sessions.doctor_session(session_id, verbose=verbose)

    def session_kill(self, session_id: str) -> Json:
        return self._sessions.kill_session(session_id)

    def session_gc(self, verbose: bool = False) -> Json:
        return self._sessions.gc_sessions(verbose=verbose)

    def close_all(self) -> None:
        self._sessions.close_all()

    def query(self, **kwargs: Any) -> Any:
        return self._sessions.query(**kwargs)
