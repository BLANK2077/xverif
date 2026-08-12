"""Stateful xdebug adapter for design/wave sessions."""
from __future__ import annotations

from typing import Any, Dict, Optional

from xverif_loop.config import RuntimeConfig, default_xdebug_bin, resolve_mcp_runtime_config
from xverif_loop.json_contract import strict_json_dumps
from xverif_loop.logging import StructuredLogger, resolve_logger
from xverif_loop.sessions.session_manager import McpSessionManager

Json = Dict[str, Any]


class XverifDebugAdapter:
    def __init__(
        self,
        mode: Optional[str] = None,
        startup_timeout_sec: Optional[float] = None,
        request_timeout_sec: Optional[float] = None,
        *,
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
        self._sessions = McpSessionManager(
            runtime=self.runtime,
            xdebug_bin=default_xdebug_bin(),
            logger=self.logger,
        )

    def ping(self) -> str:
        return "pong"

    def actions(
        self,
        verbose: bool = False,
        category: Optional[list[str]] = None,
        requires: Optional[list[str]] = None,
        purposes: Optional[list[str]] = None,
        keyword: Optional[str] = None,
    ) -> Json:
        args: Json = {"output": {"verbose": True}} if verbose else {}
        filters: Json = {}
        if category is not None:
            filters["category"] = category
        if requires is not None:
            filters["requires"] = requires
        if purposes is not None:
            filters["purposes"] = purposes
        if keyword is not None:
            filters["keyword"] = keyword
        if filters:
            args["filter"] = filters
        return self._one_shot({"api_version": "xdebug.v1", "action": "actions", "args": args})

    def schema(
        self,
        action: str,
        kind: str = "request",
        view: str = "mcp",
        include_examples: bool = True,
    ) -> Json:
        from xverif_mcp.schema_projection import project
        native = self._one_shot({
            "api_version": "xdebug.v1", "action": "schema",
            "args": {"action": action, "kind": kind},
        })
        return project(action, kind, view, native, include_examples)

    def _one_shot(self, req: Json) -> Json:
        from xverif_mcp.runner import StatelessCliRunner
        return StatelessCliRunner().run_json(
            "xdebug", ["--json", "-"], strict_json_dumps(dict(req))
        )

    def query_one_shot(
        self,
        *,
        action: str,
        args: Optional[Json] = None,
        limits: Optional[Json] = None,
        output_format: str = "xout",
    ) -> Any:
        from xverif_mcp.runner import StatelessCliRunner
        from xverif_loop.xdebug_errors import translate_native_example_for_query

        request: Json = {"api_version": "xdebug.v1", "action": action}
        if args is not None:
            request["args"] = args
        if limits is not None:
            request["limits"] = limits
        input_text = strict_json_dumps(request)
        runner = StatelessCliRunner()
        if output_format == "json":
            result = runner.run_json("xdebug", ["--json", "-"], input_text)
            return translate_native_example_for_query(result, session_id=None) if not result.get("ok", True) else result
        if output_format == "xout":
            result = runner.run_xout("xdebug", ["-"], input_text)
            if isinstance(result, dict) and not result.get("ok", True):
                return translate_native_example_for_query(result, session_id=None)
            return result
        return {
            "ok": False,
            "error": {
                "code": "INVALID_ARGUMENT",
                "message": "output_format='envelope' requires a managed stdio-loop session; resource-free one-shot queries support xout or json",
                "recoverable": True,
                "error_layer": "wrapper",
            },
        }

    def session_open(self, name: str, **kwargs: Any) -> Json:
        return self._sessions.open_session(name=name, **kwargs)

    def session_list(self, **kwargs: Any) -> Json:
        return self._sessions.list_sessions(**kwargs)

    def session_close(self, session_id: str, mode: str = "graceful") -> Json:
        if mode == "force":
            return self._sessions.kill_session(session_id)
        return self._sessions.close_session(session_id)

    def session_doctor(self, session_id: str, verbose: bool = False) -> Json:
        return self._sessions.doctor_session(session_id, verbose=verbose)

    def session_gc(self, verbose: bool = False) -> Json:
        return self._sessions.gc_sessions(verbose=verbose)

    def close_all(self) -> None:
        self._sessions.close_all()

    def query(self, **kwargs: Any) -> Any:
        if kwargs.get("output_format", "xout") != "xout":
            return self._sessions.query(**kwargs)
        response = self._sessions.query(**kwargs, retain_transport_envelope=True)
        if not isinstance(response, dict) or response.get("ok") is not True:
            if isinstance(response, dict) and isinstance(response.get("json"), dict):
                return response["json"]
            return response
        from xverif_mcp.framing import frame_transport_xout
        return frame_transport_xout(response)
