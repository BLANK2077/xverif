from __future__ import annotations

from dataclasses import dataclass

from .bitvector import BitVector
from .errors import EvalError, ParseError, UnknownVariable
from .literal import parse_value
from .ops import (
    binary_arithmetic,
    binary_bitwise,
    compare,
    concat,
    index_bit,
    repeat,
    shift,
    slice_bits,
)


@dataclass(frozen=True)
class Token:
    kind: str
    text: str
    pos: int


MULTI_OPS = ["<<<", ">>>", "&&", "||", "==", "!=", "<=", ">=", "<<", ">>"]
SINGLE = set("()+-*/%~!&|^<>=?:{},[]")


def tokenize(expr: str) -> list[Token]:
    tokens: list[Token] = []
    i = 0
    while i < len(expr):
        ch = expr[i]
        if ch.isspace():
            i += 1
            continue
        matched = False
        for op in MULTI_OPS:
            if expr.startswith(op, i):
                tokens.append(Token("op", op, i))
                i += len(op)
                matched = True
                break
        if matched:
            continue
        if ch in SINGLE:
            tokens.append(Token("op", ch, i))
            i += 1
            continue
        start = i
        if ch.isalpha() or ch == "_":
            i += 1
            while i < len(expr) and (expr[i].isalnum() or expr[i] in "_.$"):
                i += 1
            # Sized literals such as hff are not valid without apostrophe; keep as identifier.
            tokens.append(Token("ident", expr[start:i], start))
            continue
        if ch.isdigit():
            while i < len(expr) and (expr[i].isdigit() or expr[i] == "_"):
                i += 1
            if i < len(expr) and expr[i] == "'":
                i += 1
                if i < len(expr) and expr[i] in "sS":
                    i += 1
                if i >= len(expr) or expr[i] not in "bBoOdDhH":
                    raise ParseError("based literal is missing base", pos=start)
                i += 1
                if i < len(expr) and expr[i] in "+-":
                    i += 1
                while i < len(expr) and (expr[i].isalnum() or expr[i] in "_?"):
                    i += 1
            tokens.append(Token("number", expr[start:i], start))
            continue
        if ch == "'":
            i += 1
            while i < len(expr) and (expr[i].isalnum() or expr[i] in "_?"):
                i += 1
            tokens.append(Token("number", expr[start:i], start))
            continue
        raise ParseError("unexpected character in expression", char=ch, pos=i)
    tokens.append(Token("eof", "", len(expr)))
    return tokens


def _resize_pair(a: BitVector, b: BitVector) -> tuple[BitVector, BitVector]:
    width = max(a.width, b.width)
    return a.resize(width), b.resize(width)


class Parser:
    def __init__(self, expr: str, variables: dict[str, BitVector] | None = None, *, state: str = "2state"):
        self.expr = expr
        self.tokens = tokenize(expr)
        self.pos = 0
        self.variables = variables or {}
        self.state = state

    def peek(self) -> Token:
        return self.tokens[self.pos]

    def pop(self) -> Token:
        tok = self.tokens[self.pos]
        self.pos += 1
        return tok

    def match(self, text: str) -> bool:
        if self.peek().text == text:
            self.pop()
            return True
        return False

    def expect(self, text: str) -> Token:
        tok = self.peek()
        if tok.text != text:
            raise ParseError("unexpected token", expected=text, actual=tok.text, pos=tok.pos)
        return self.pop()

    def parse(self) -> BitVector:
        value = self.parse_expr(0)
        if self.peek().kind != "eof":
            tok = self.peek()
            raise ParseError("trailing token in expression", token=tok.text, pos=tok.pos)
        return value

    def parse_expr(self, min_prec: int) -> BitVector:
        left = self.parse_prefix()
        left = self.parse_postfix(left)
        while True:
            tok = self.peek()
            if tok.text == "?":
                prec = 1
                if prec < min_prec:
                    break
                self.pop()
                then_value = self.parse_expr(0)
                self.expect(":")
                else_value = self.parse_expr(prec)
                # The two branches are unified to the wider width before the condition selects one
                # (IEEE 1800-2017 11.4.11 and 11.6): `1'b1 ? 4'hf : 8'h0f` is 8 bits wide, not 4.
                width = max(then_value.width, else_value.width)
                both_signed = then_value.signed and else_value.signed
                then_value = then_value.resize(width, signed_extend=both_signed, signed=both_signed)
                else_value = else_value.resize(width, signed_extend=both_signed, signed=both_signed)
                left = then_value if left.truthy() else else_value
                continue
            prec = self.precedence(tok.text)
            if prec < min_prec:
                break
            op = self.pop().text
            right = self.parse_expr(prec + 1)
            left = self.apply_binary(op, left, right)
        return left

    def parse_prefix(self) -> BitVector:
        tok = self.peek()
        if tok.text in {"+", "-", "!", "~"}:
            op = self.pop().text
            value = self.parse_prefix()
            return self.apply_unary(op, value)
        if tok.text == "(":
            self.pop()
            value = self.parse_expr(0)
            self.expect(")")
            return value
        if tok.text == "{":
            return self.parse_braces()
        if tok.kind == "number":
            self.pop()
            return parse_value(tok.text, state=self.state)
        if tok.kind == "ident":
            self.pop()
            if tok.text not in self.variables:
                raise UnknownVariable("unknown variable", name=tok.text)
            return self.variables[tok.text]
        raise ParseError("expected expression", token=tok.text, pos=tok.pos)

    def parse_postfix(self, value: BitVector) -> BitVector:
        while self.match("["):
            msb = self.parse_expr(0)
            msb.require_known("slice index")
            if self.match(":"):
                lsb = self.parse_expr(0)
                lsb.require_known("slice index")
                self.expect("]")
                value = slice_bits(value, msb.value, lsb.value)
            else:
                self.expect("]")
                value = index_bit(value, msb.value)
        return value

    def parse_braces(self) -> BitVector:
        """Parse a brace group: `{a, b}` concatenation or `{count{body}}` replication."""
        self.expect("{")
        value = self.parse_brace_body()
        self.expect("}")
        return value

    def parse_brace_body(self) -> BitVector:
        """Parse the content of a brace group, without its outer `{` / `}`.

        Both brace forms begin with `{`, so the first element is parsed and the following token
        decides the form: another `{` means the first element was a repeat count and the body
        follows, `,` extends a concatenation, and `}` closes a single-element concatenation.

        A nested group such as `{{2'b10}, {2'b01}}` is the ambiguous case, because it can be read
        as a concatenation whose first element is `{2'b10}`. The reading is therefore speculative:
        the concatenation interpretation is tried first and abandoned if it does not reach a
        matching `}`, which is what keeps the replication form reachable.
        """
        open_index = self.pos
        try:
            first = self.parse_expr(0)
            if self.peek().text != "{":
                return self.parse_concatenation_tail(first)
        except ParseError:
            pass

        # The concatenation reading failed; the only other form is `count{body}`.
        self.pos = open_index
        count = self.parse_expr(0)
        count.require_known("repeat count")
        self.expect("{")
        body = self.parse_brace_body()
        self.expect("}")
        return repeat(count.value, body)

    def parse_concatenation_tail(self, first: BitVector) -> BitVector:
        items = [first]
        while self.match(","):
            items.append(self.parse_expr(0))
        return concat(items)

    @staticmethod
    def precedence(op: str) -> int:
        return {
            "||": 2,
            "&&": 3,
            "|": 4,
            "^": 5,
            "&": 6,
            "==": 7,
            "!=": 7,
            "<": 8,
            "<=": 8,
            ">": 8,
            ">=": 8,
            "<<": 9,
            ">>": 9,
            "<<<": 9,
            ">>>": 9,
            "+": 10,
            "-": 10,
            "*": 11,
            "/": 11,
            "%": 11,
        }.get(op, -1)

    @staticmethod
    def apply_unary(op: str, value: BitVector) -> BitVector:
        value.require_known(op)
        if op == "+":
            return value
        if op == "-":
            return BitVector(value.width, -value.as_int(value.signed), signed=True)
        if op == "!":
            return BitVector.bool(not value.truthy())
        if op == "~":
            return BitVector(value.width, ~value.value, signed=False)
        raise EvalError("unsupported unary operator", op=op)

    @staticmethod
    def apply_binary(op: str, left: BitVector, right: BitVector) -> BitVector:
        if op in {"+", "-", "*", "/", "%"}:
            return binary_arithmetic(op, left, right)
        if op in {"&", "|", "^"}:
            return binary_bitwise(op, left, right)
        if op in {"==", "!=", "<", "<=", ">", ">="}:
            return compare(op, left, right)
        if op in {"<<", ">>", "<<<", ">>>"}:
            return shift(op, left, right)
        if op == "&&":
            return BitVector.bool(left.truthy() and right.truthy())
        if op == "||":
            return BitVector.bool(left.truthy() or right.truthy())
        raise EvalError("unsupported binary operator", op=op)


def eval_expr(
    expr: str,
    variables: dict[str, BitVector] | None = None,
    *,
    state: str = "2state",
    width: int | None = None,
    signed: bool | None = None,
) -> BitVector:
    value = Parser(expr, variables, state=state).parse()
    if width is not None:
        value = value.resize(width, signed_extend=bool(signed), signed=value.signed if signed is None else signed)
    if signed is not None:
        value = value.with_signed(signed)
    return value


def parse_vars(items: list[str] | None, *, state: str = "2state") -> dict[str, BitVector]:
    variables: dict[str, BitVector] = {}
    for item in items or []:
        if "=" not in item:
            raise ParseError("--var must be name=value", var=item)
        name, value = item.split("=", 1)
        name = name.strip()
        if not name:
            raise ParseError("--var name cannot be empty", var=item)
        if name in variables:
            raise ParseError("--var name must be unique", var=name)
        variables[name] = parse_value(value.strip(), state=state)
    return variables
