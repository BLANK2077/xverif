from __future__ import annotations

from .bitvector import BitVector
from .errors import DivisionByZero, EvalError, WidthError


def common_width(a: BitVector, b: BitVector) -> int:
    return max(a.width, b.width)


def _coerce_binary_operands(a: BitVector, b: BitVector) -> tuple[int, bool, int, int]:
    """Apply SystemVerilog binary expression width and signedness rules.

    Arithmetic and relational operands are extended to the maximum operand
    width.  The expression is signed only when both operands are signed; a
    mixed signed/unsigned expression is therefore zero-extended and evaluated
    as unsigned.
    """
    width = common_width(a, b)
    signed = a.signed and b.signed
    aa = a.resize(width, signed_extend=signed, signed=signed)
    bb = b.resize(width, signed_extend=signed, signed=signed)
    return width, signed, aa.as_int(signed), bb.as_int(signed)


def _truncating_division(dividend: int, divisor: int) -> int:
    """Return an integer quotient truncated toward zero without using float."""
    quotient = abs(dividend) // abs(divisor)
    return -quotient if (dividend < 0) != (divisor < 0) else quotient


def slice_bits(value: BitVector, msb: int, lsb: int) -> BitVector:
    if lsb < 0 or msb < lsb or msb >= value.width:
        raise WidthError("slice range is invalid for value width", msb=msb, lsb=lsb, width=value.width)
    width = msb - lsb + 1
    mask = (1 << width) - 1
    return BitVector(
        width,
        (value.value >> lsb) & mask,
        state=value.state,
        x_mask=(value.x_mask >> lsb) & mask,
        z_mask=(value.z_mask >> lsb) & mask,
    )


def index_bit(value: BitVector, bit: int) -> BitVector:
    return slice_bits(value, bit, bit)


def concat(values: list[BitVector]) -> BitVector:
    if not values:
        raise EvalError("concat requires at least one value")
    width = 0
    value = 0
    x_mask = 0
    z_mask = 0
    state = "2state"
    for item in values:
        value = (value << item.width) | item.value
        x_mask = (x_mask << item.width) | item.x_mask
        z_mask = (z_mask << item.width) | item.z_mask
        width += item.width
        if item.state == "4state":
            state = "4state"
    return BitVector(width, value, state=state, x_mask=x_mask, z_mask=z_mask)


def repeat(count: int, value: BitVector) -> BitVector:
    if count < 0:
        raise EvalError("repeat count must be non-negative", count=count)
    if count == 0:
        raise EvalError("repeat count must be positive", count=count)
    return concat([value] * count)


def trunc(value: BitVector, width: int) -> BitVector:
    if width > value.width:
        raise WidthError("truncate width cannot exceed value width", from_width=value.width, to_width=width)
    return value.resize(width, signed=False)


def zext(value: BitVector, width: int) -> BitVector:
    if width < value.width:
        raise WidthError("zero extension target width is smaller than value width", from_width=value.width, to_width=width)
    return value.resize(width, signed=False)


def sext(value: BitVector, width: int) -> BitVector:
    if width < value.width:
        raise WidthError("sign extension target width is smaller than value width", from_width=value.width, to_width=width)
    return value.resize(width, signed_extend=True, signed=True)


def reverse_bits(value: BitVector) -> BitVector:
    out = 0
    x_mask = 0
    z_mask = 0
    for src in range(value.width):
        dst = value.width - 1 - src
        if value.value & (1 << src):
            out |= 1 << dst
        if value.x_mask & (1 << src):
            x_mask |= 1 << dst
        if value.z_mask & (1 << src):
            z_mask |= 1 << dst
    return BitVector(value.width, out, signed=value.signed, state=value.state, x_mask=x_mask, z_mask=z_mask)


def mask(width: int, lsb: int = 0) -> BitVector:
    if width <= 0 or lsb < 0:
        raise WidthError("mask width must be positive and lsb must be non-negative", width=width, lsb=lsb)
    return BitVector(width + lsb, ((1 << width) - 1) << lsb)


def align(value: BitVector, to: int) -> BitVector:
    value.require_known("align")
    if to <= 0:
        raise WidthError("alignment must be positive", to=to)
    aligned = ((value.value + to - 1) // to) * to
    width = max(value.width, aligned.bit_length() or 1)
    return BitVector(width, aligned, signed=value.signed)


def popcount(value: BitVector) -> BitVector:
    value.require_known("popcount")
    count = value.value.bit_count()
    return BitVector.from_int(count, width=max(1, count.bit_length()))


def onehot(value: BitVector) -> BitVector:
    value.require_known("onehot")
    return BitVector.bool(value.value != 0 and value.value.bit_count() == 1)


def onehot0(value: BitVector) -> BitVector:
    value.require_known("onehot0")
    return BitVector.bool(value.value.bit_count() <= 1)


def bin2gray(value: BitVector) -> BitVector:
    value.require_known("bin2gray")
    return BitVector(value.width, value.value ^ (value.value >> 1), signed=False)


def gray2bin(value: BitVector) -> BitVector:
    value.require_known("gray2bin")
    gray = value.value
    out = 0
    while gray:
        out ^= gray
        gray >>= 1
    return BitVector(value.width, out, signed=False)


def binary_arithmetic(op: str, a: BitVector, b: BitVector) -> BitVector:
    a.require_known(op)
    b.require_known(op)
    width, signed, av, bv = _coerce_binary_operands(a, b)
    if op == "+":
        result = av + bv
    elif op == "-":
        result = av - bv
    elif op == "*":
        result = av * bv
    elif op == "/":
        if bv == 0:
            raise DivisionByZero("division by zero")
        result = _truncating_division(av, bv)
    elif op == "%":
        if bv == 0:
            raise DivisionByZero("modulo by zero")
        quotient = _truncating_division(av, bv)
        result = av - quotient * bv
    else:
        raise EvalError("unsupported arithmetic operator", op=op)
    return BitVector(width, result, signed=signed)


def binary_bitwise(op: str, a: BitVector, b: BitVector) -> BitVector:
    width = common_width(a, b)
    aa = a.resize(width)
    bb = b.resize(width)
    state = "4state" if aa.state == "4state" or bb.state == "4state" else "2state"
    if aa.unknown_mask or bb.unknown_mask:
        aa.require_known(op)
        bb.require_known(op)
    if op == "&":
        value = aa.value & bb.value
    elif op == "|":
        value = aa.value | bb.value
    elif op == "^":
        value = aa.value ^ bb.value
    else:
        raise EvalError("unsupported bitwise operator", op=op)
    return BitVector(width, value, signed=False, state=state)


def compare(op: str, a: BitVector, b: BitVector) -> BitVector:
    a.require_known(op)
    b.require_known(op)
    _, _, av, bv = _coerce_binary_operands(a, b)
    table = {
        "==": av == bv,
        "!=": av != bv,
        "<": av < bv,
        "<=": av <= bv,
        ">": av > bv,
        ">=": av >= bv,
    }
    if op not in table:
        raise EvalError("unsupported comparison operator", op=op)
    return BitVector.bool(table[op])


def shift(op: str, a: BitVector, b: BitVector) -> BitVector:
    a.require_known(op)
    b.require_known(op)
    amount = b.value
    mask_value = (1 << a.width) - 1
    if op in {"<<", "<<<"}:
        return BitVector(a.width, (a.value << amount) & mask_value, signed=a.signed)
    if op == ">>":
        return BitVector(a.width, a.value >> amount, signed=a.signed)
    if op == ">>>":
        signed_val = a.signed_value if a.signed else a.value
        assert signed_val is not None
        return BitVector(a.width, signed_val >> amount, signed=a.signed)
    raise EvalError("unsupported shift operator", op=op)
