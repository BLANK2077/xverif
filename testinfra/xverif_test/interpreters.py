"""Interpreter markers used by catalog runners, fixture builders and fixture probes."""

from __future__ import annotations

import sys

PYTHON_MARKER = "python3"


def resolve_interpreter_argv(raw: object) -> tuple[str, ...]:
    """Resolve a command argv whose interpreter is spelled ``python3``.

    Catalog runners, fixture builders and fixture probes spell the interpreter as
    ``python3`` because that is the *concept* they mean - the Python that owns this test
    environment. Resolved through ``PATH`` it can instead be a system Python unrelated to
    the running suite, which made ``xloc.vim``/``xloc.nvim``/``xdebug.cpp_unit`` and the
    fixture semantic probes fail with
    ``SyntaxError: future feature annotations is not defined`` whenever the Conda
    environment was not active. The interpreter running this suite is by definition the
    right one (``python_test_runtime`` already guarantees it is 3.11+), so bind that
    name to it rather than to whatever ``PATH`` happens to hold.
    """
    argv = [str(value) for value in raw] if isinstance(raw, (list, tuple)) else []
    if argv and argv[0] == PYTHON_MARKER:
        argv[0] = sys.executable
    return tuple(argv)
