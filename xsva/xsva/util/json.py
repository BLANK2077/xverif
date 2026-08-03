"""JSON 序列化工具。对齐 spec 第二十三章。

统一处理 dataclass、Enum、list、dict 递归序列化。
所有 CLI JSON 输出必须走这个模块。
"""

from __future__ import annotations

import json as _json
from dataclasses import asdict, is_dataclass
from enum import Enum


def to_jsonable(obj):
    """递归转换对象为 JSON 可序列化形式。

    处理：dataclass → dict, Enum → value, list → list, dict → dict。
    """
    if obj is None:
        return None
    if isinstance(obj, Enum):
        return to_jsonable(obj.value)
    if isinstance(obj, (str, int, float, bool)):
        return obj
    if is_dataclass(obj):
        return {k: to_jsonable(v) for k, v in asdict(obj).items()}
    if isinstance(obj, dict):
        result = {}
        for key, value in obj.items():
            if not isinstance(key, str):
                raise TypeError(
                    "unsupported JSON object key type: "
                    f"{type(key).__module__}.{type(key).__qualname__}"
                )
            result[key] = to_jsonable(value)
        return result
    if isinstance(obj, (list, tuple)):
        return [to_jsonable(x) for x in obj]
    raise TypeError(
        "unsupported JSON value type: "
        f"{type(obj).__module__}.{type(obj).__qualname__}"
    )


def dump_json(obj, indent: int = 2) -> str:
    """将对象序列化为 JSON 字符串。"""
    return _json.dumps(
        to_jsonable(obj),
        indent=indent,
        ensure_ascii=False,
        allow_nan=False,
    )
