"""SDK-free shared loop backend support for xverif stateful wrappers."""

from .config import (
    RuntimeConfig,
    resolve_loop_wrapper_runtime_config,
    resolve_mcp_runtime_config,
)

__all__ = [
    "RuntimeConfig",
    "resolve_loop_wrapper_runtime_config",
    "resolve_mcp_runtime_config",
]
