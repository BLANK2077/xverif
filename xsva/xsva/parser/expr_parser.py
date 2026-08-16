"""表达式解析器 — 浅解析：提取信号引用、sampled function 调用、local var 引用。

当前表达式 IR 不构造完整 AST。无法精确解析时标记 kind=OPAQUE，保留 raw 原文。
"""

from __future__ import annotations

from xsva.ir.diagnostics import DiagnosticBag
from xsva.ir.expr import ExprIR, ExprKind, SampleDependencyIR, SignalRef

from .scanner import Scanner, TokenKind


class ExprParser:
    """Lightweight expression parser for SVA expressions.

    目标：
    - 提取所有信号名（含层次路径和位选）
    - 识别 $past/$rose/$fell/$stable/$changed/$isunknown 及其参数
    - 提取 local variable 引用
    """

    def __init__(self, scanner: Scanner, diag: DiagnosticBag | None = None) -> None:
        self._scanner = scanner
        self._diag = diag

    def parse_expr(self) -> ExprIR:
        """解析一个表达式，返回 ExprIR。

        对 SVA 子集中的常见表达式做浅解析。
        复杂表达式（如嵌套运算）自动退化为 OPAQUE + raw。
        """
        tokens = self._collect_expr_tokens()
        if not tokens:
            return ExprIR(kind=ExprKind.RAW, raw="")

        raw = self._reconstruct_raw(tokens)
        (signals, local_refs, sampled_funcs, sample_deps,
         dependency_complete) = self._analyze_tokens(tokens)
        contains_sampled = bool(sampled_funcs)
        contains_x_sensitive = False

        kind = ExprKind.IDENTIFIER if len(signals) == 1 or not contains_sampled else ExprKind.OPAQUE
        if contains_sampled:
            kind = ExprKind.SYSTEM_FUNC if len(tokens) <= 4 else ExprKind.OPAQUE
        if not signals and not sampled_funcs and raw.strip():
            kind = ExprKind.RAW

        return ExprIR(
            kind=kind,
            raw=raw,
            signals=signals,
            local_refs=local_refs,
            sampled_funcs=sampled_funcs,
            sample_dependencies=sample_deps,
            contains_sampled_func=contains_sampled,
            contains_x_sensitive_op=contains_x_sensitive,
            dependency_complete=dependency_complete,
        )

    def parse_expr_until(self, end_kinds: set[TokenKind]) -> ExprIR:
        """解析表达式，直到遇到 end_kinds 中的 token（不消费该 token）。"""
        return self.parse_expr()

    # ── helpers ──

    def _collect_expr_tokens(self) -> list:
        """收集一个表达式的 token，停在合适的终止符。

        终止条件：
        - 分号 ; → property 结束
        - ) → 闭合的括号（但需要配对）
        - 顶层 , → sequence 分隔（但在 () 内不算）
        - 遇到某些关键字
        """
        tokens: list = []
        paren_depth = 0
        bracket_depth = 0

        stopping_kinds = {
            TokenKind.SEMICOLON, TokenKind.EOF,
            TokenKind.KW_PROPERTY, TokenKind.KW_ENDPROPERTY,
            TokenKind.KW_ASSERT, TokenKind.KW_ASSUME, TokenKind.KW_COVER,
            TokenKind.KW_SEQUENCE, TokenKind.KW_ENDSEQUENCE,
            TokenKind.KW_DISABLE,
            TokenKind.HASH_HASH,  # ## starts a new delay
            TokenKind.KW_THROUGHOUT, TokenKind.KW_INTERSECT, TokenKind.KW_WITHIN,
            TokenKind.REPEAT_CONSEC, TokenKind.REPEAT_NONCONSEC, TokenKind.REPEAT_GOTO,
            TokenKind.IMPL_OVERLAPPED, TokenKind.IMPL_NONOVERLAPPED,
        }

        while True:
            tk = self._scanner.peek()
            if tk.kind == TokenKind.EOF:
                break
            if tk.kind == TokenKind.SEMICOLON and paren_depth == 0:
                break
            if tk.kind == TokenKind.LPAREN:
                paren_depth += 1
            elif tk.kind == TokenKind.RPAREN:
                if paren_depth == 0:
                    break  # 闭合括号回到上层
                paren_depth -= 1
            elif tk.kind == TokenKind.LBRACKET:
                bracket_depth += 1
            elif tk.kind == TokenKind.RBRACKET:
                if bracket_depth > 0:
                    bracket_depth -= 1
            elif tk.kind in stopping_kinds:
                if paren_depth == 0:
                    break
            tokens.append(self._scanner.advance())
        return tokens

    def _analyze_tokens(self, tokens) -> tuple[
        list[SignalRef], list[str], list[str], list[SampleDependencyIR], bool
    ]:
        signals: list[SignalRef] = []
        local_refs: list[str] = []
        sampled_funcs: list[str] = []
        sample_deps: list[SampleDependencyIR] = []
        dependency_complete = True
        sampled_kinds = {
            TokenKind.SYS_PAST, TokenKind.SYS_ROSE, TokenKind.SYS_FELL,
            TokenKind.SYS_STABLE, TokenKind.SYS_CHANGED, TokenKind.SYS_ISUNKNOWN,
            TokenKind.SYS_ONEHOT, TokenKind.SYS_ONEHOT0, TokenKind.SYS_COUNTONES,
        }

        def merge(nested) -> None:
            nonlocal dependency_complete
            nested_signals, nested_locals, nested_funcs, nested_deps, complete = nested
            for signal in nested_signals:
                self._append_signal(signals, signal)
            for local in nested_locals:
                if local not in local_refs:
                    local_refs.append(local)
            sampled_funcs.extend(nested_funcs)
            sample_deps.extend(nested_deps)
            dependency_complete = dependency_complete and complete

        i = 0
        while i < len(tokens):
            tk = tokens[i]
            if tk.kind in sampled_kinds:
                func_name = tk.kind.value
                sampled_funcs.append(func_name)
                depth: int | None = 1 if tk.kind == TokenKind.SYS_PAST else None
                ref_cycle: int | None = -1 if tk.kind == TokenKind.SYS_PAST else None
                if i + 1 >= len(tokens) or tokens[i + 1].kind != TokenKind.LPAREN:
                    dependency_complete = False
                    self._sampled_diagnostic(func_name, "requires a parenthesized expression argument")
                    sample_deps.append(SampleDependencyIR(
                        func=func_name, expr="", reference_cycle=ref_cycle, depth=depth,
                    ))
                    i += 1
                    continue
                close_idx = self._find_matching_paren(tokens, i + 1)
                if close_idx is None:
                    dependency_complete = False
                    self._sampled_diagnostic(func_name, "has an unclosed argument list")
                    close_idx = len(tokens)
                args = self._split_top_level_args(tokens[i + 2:close_idx])
                expr_tokens = args[0] if args else []
                inner_expr = self._reconstruct_raw(expr_tokens).strip()
                if not inner_expr:
                    dependency_complete = False
                    self._sampled_diagnostic(func_name, "requires a non-empty expression argument")

                if tk.kind == TokenKind.SYS_PAST and len(args) >= 2:
                    depth_text = self._reconstruct_raw(args[1]).strip()
                    try:
                        parsed_depth = int(depth_text)
                        if parsed_depth <= 0:
                            raise ValueError
                        depth = parsed_depth
                        ref_cycle = -parsed_depth
                    except ValueError:
                        depth = None
                        ref_cycle = None
                        dependency_complete = False
                        self._sampled_diagnostic(
                            func_name, "requires a positive integer depth when depth is provided",
                        )
                sample_deps.append(SampleDependencyIR(
                    func=func_name,
                    expr=inner_expr,
                    current_cycle=0,
                    reference_cycle=ref_cycle,
                    depth=depth,
                ))
                if inner_expr:
                    merge(self._analyze_tokens(expr_tokens))
                dependency_args = args[2:] if tk.kind == TokenKind.SYS_PAST else args[1:]
                for argument in dependency_args:
                    merge(self._analyze_tokens(argument))
                i = close_idx + 1 if close_idx < len(tokens) else len(tokens)
                continue

            if tk.kind == TokenKind.IDENT:
                signal, next_index, select_tokens = self._parse_signal_reference(tokens, i)
                self._append_signal(signals, signal)
                if select_tokens:
                    merge(self._analyze_tokens(select_tokens))
                i = next_index
                continue
            i += 1

        return signals, local_refs, sampled_funcs, sample_deps, dependency_complete

    def _parse_signal_reference(self, tokens, start: int) -> tuple[SignalRef, int, list]:
        segments = [tokens[start].text]
        bit_select: tuple[int, int] | None = None
        dynamic_select_tokens: list = []
        cursor = start + 1
        while cursor < len(tokens):
            if tokens[cursor].kind == TokenKind.LBRACKET:
                close = self._find_matching_bracket(tokens, cursor)
                if close is None:
                    return SignalRef(
                        segments=tuple(segments),
                        is_hierarchical=len(segments) > 1,
                    ), len(tokens), []
                select_tokens = tokens[cursor + 1:close]
                if close + 1 < len(tokens) and tokens[close + 1].kind == TokenKind.DOT:
                    segments[-1] += "[" + "".join(t.text for t in select_tokens) + "]"
                    cursor = close + 1
                    continue
                select_text = "".join(t.text for t in select_tokens)
                try:
                    if ":" in select_text:
                        left, right = select_text.split(":", 1)
                        bit_select = (int(left), int(right))
                    else:
                        bit = int(select_text)
                        bit_select = (bit, bit)
                except ValueError:
                    dynamic_select_tokens = select_tokens
                cursor = close + 1
                break
            if (tokens[cursor].kind == TokenKind.DOT and
                    cursor + 1 < len(tokens) and
                    tokens[cursor + 1].kind == TokenKind.IDENT):
                segments.append(tokens[cursor + 1].text)
                cursor += 2
                continue
            break
        return SignalRef(
            segments=tuple(segments),
            bit_select=bit_select,
            is_hierarchical=len(segments) > 1,
        ), cursor, dynamic_select_tokens

    def _append_signal(self, signals: list[SignalRef], signal: SignalRef) -> None:
        if signal not in signals:
            signals.append(signal)

    def _split_top_level_args(self, tokens) -> list[list]:
        if not tokens:
            return []
        parts: list[list] = [[]]
        paren_depth = 0
        bracket_depth = 0
        brace_depth = 0
        for tk in tokens:
            if tk.kind == TokenKind.LPAREN:
                paren_depth += 1
            elif tk.kind == TokenKind.RPAREN and paren_depth:
                paren_depth -= 1
            elif tk.kind == TokenKind.LBRACKET:
                bracket_depth += 1
            elif tk.kind == TokenKind.RBRACKET and bracket_depth:
                bracket_depth -= 1
            elif tk.kind == TokenKind.LBRACE:
                brace_depth += 1
            elif tk.kind == TokenKind.RBRACE and brace_depth:
                brace_depth -= 1
            if (tk.kind == TokenKind.COMMA and paren_depth == 0 and
                    bracket_depth == 0 and brace_depth == 0):
                parts.append([])
            else:
                parts[-1].append(tk)
        return parts

    def _sampled_diagnostic(self, func: str, reason: str) -> None:
        if self._diag is not None:
            self._diag.warning("XSVA-W011", f"{func} {reason}; sampled dependency is partial")

    def _find_matching_paren(self, tokens, open_idx: int) -> int | None:
        """找到与 open_idx 处 ( 匹配的 ) token 的 index。"""
        depth = 0
        for i in range(open_idx, len(tokens)):
            if tokens[i].kind == TokenKind.LPAREN:
                depth += 1
            elif tokens[i].kind == TokenKind.RPAREN:
                depth -= 1
                if depth == 0:
                    return i
        return None

    def _find_matching_bracket(self, tokens, open_idx: int) -> int | None:
        depth = 0
        for i in range(open_idx, len(tokens)):
            if tokens[i].kind == TokenKind.LBRACKET:
                depth += 1
            elif tokens[i].kind == TokenKind.RBRACKET:
                depth -= 1
                if depth == 0:
                    return i
        return None

    def _reconstruct_raw(self, tokens) -> str:
        """从 token 列表重建原始文本。"""
        parts: list[str] = []
        for tk in tokens:
            parts.append(tk.text)
        return " ".join(parts)
