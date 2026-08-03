from __future__ import annotations

import pytest

from xsva.ir.common import LoweringStatus
from xsva.util.json import dump_json, to_jsonable


def test_supported_values_are_serialized_without_string_coercion():
    payload = {"status": LoweringStatus.EXACT, "items": (1, True, None)}
    assert to_jsonable(payload) == {"status": "exact", "items": [1, True, None]}
    assert '"status": "exact"' in dump_json(payload)


def test_unknown_type_is_rejected_instead_of_stringified():
    class Unsupported:
        def __str__(self) -> str:
            return "would-have-hidden-the-type-error"

    with pytest.raises(TypeError, match=r"unsupported JSON value type: .*Unsupported"):
        to_jsonable(Unsupported())


def test_non_string_object_key_is_rejected_instead_of_stringified():
    with pytest.raises(TypeError, match=r"unsupported JSON object key type: builtins.int"):
        to_jsonable({1: "would-have-become-a-string-key"})


def test_non_finite_float_is_rejected_as_non_json():
    with pytest.raises(ValueError, match="Out of range float values"):
        dump_json({"value": float("nan")})
