"""表达式解析器 — 浅解析：提取信号引用、sampled function 调用、local var 引用。

当前表达式 IR 不构造完整 AST。无法精确解析时标记 kind=OPAQUE，保留 raw 原文。
"""

from __future__ import annotations

from xsva.ir.expr import ExprIR, ExprKind, SampleDependencyIR, SignalRef

from .scanner import Scanner, TokenKind


class ExprParser:
    """Lightweight expression parser for SVA expressions.

    目标：
    - 提取所有信号名（含层次路径和位选）
    - 识别 $past/$rose/$fell/$stable/$changed/$isunknown 及其参数
    - 提取 local variable 引用
    """

    def __init__(self, scanner: Scanner) -> None:
        self._scanner = scanner

    def parse_expr(self) -> ExprIR:
        """解析一个表达式，返回 ExprIR。

        对 SVA 子集中的常见表达式做浅解析。
        复杂表达式（如嵌套运算）自动退化为 OPAQUE + raw。
        """
        tokens = self._collect_expr_tokens()
        if not tokens:
            return ExprIR(kind=ExprKind.RAW, raw="")

        raw = self._reconstruct_raw(tokens)
        signals: list[SignalRef] = []
        local_refs: list[str] = []
        sampled_funcs: list[str] = []
        sample_deps: list[SampleDependencyIR] = []
        contains_sampled = False
        contains_x_sensitive = False

        i = 0
        while i < len(tokens):
            tk = tokens[i]

            # 跳过单目运算符
            if tk.kind in (TokenKind.NOT, TokenKind.TILDE, TokenKind.AMP,
                           TokenKind.PIPE, TokenKind.CARET, TokenKind.STAR):
                # 但 & / | 可能是双目，这里保守处理
                i += 1
                continue

            # 跳过比较运算符
            if tk.kind in (TokenKind.EQ_EQ, TokenKind.NOT_EQ,
                           TokenKind.LT, TokenKind.GT):
                i += 1
                continue

            # 跳过括号 / 逗号 / 冒号 / 数字 / 等
            if tk.kind in (TokenKind.LPAREN, TokenKind.RPAREN,
                           TokenKind.LBRACKET, TokenKind.RBRACKET,
                           TokenKind.LBRACE, TokenKind.RBRACE,
                           TokenKind.COMMA, TokenKind.COLON, TokenKind.SEMICOLON,
                           TokenKind.NUMBER, TokenKind.QUESTION,
                           TokenKind.DOT, TokenKind.EQ,
                           TokenKind.PLUS, TokenKind.MINUS, TokenKind.SLASH,
                           TokenKind.PERCENT, TokenKind.AT):
                i += 1
                continue

            # 系统函数
            if tk.kind in (TokenKind.SYS_PAST, TokenKind.SYS_ROSE, TokenKind.SYS_FELL,
                           TokenKind.SYS_STABLE, TokenKind.SYS_CHANGED, TokenKind.SYS_ISUNKNOWN,
                           TokenKind.SYS_ONEHOT, TokenKind.SYS_ONEHOT0, TokenKind.SYS_COUNTONES):
                func_name = tk.kind.value
                sampled_funcs.append(func_name)
                contains_sampled = True

                # 解析参数
                depth: int | None = None
                ref_cycle: int | None = None
                if tk.kind == TokenKind.SYS_PAST:
                    depth = 1  # default $past(x) = $past(x, 1)
                    ref_cycle = -1

                inner_expr = ""
                # 跳过 ( 和 )
                if i + 1 < len(tokens) and tokens[i + 1].kind == TokenKind.LPAREN:
                    inner_start = i + 2
                    inner_end = self._find_matching_paren(tokens, i + 1)
                    inner_expr = self._reconstruct_raw(tokens[inner_start:inner_end])

                    # 检查 $past(x, N) 的第二个参数
                    if tk.kind == TokenKind.SYS_PAST:
                        inner_tokens = tokens[inner_start:inner_end]
                        comma_idx = None
                        for j, itk in enumerate(inner_tokens):
                            if itk.kind == TokenKind.COMMA:
                                comma_idx = j
                                break
                        if comma_idx is not None:
                            depth_tokens = inner_tokens[comma_idx + 1:]
                            depth_str = self._reconstruct_raw(depth_tokens).strip()
                            try:
                                depth = int(depth_str)
                                ref_cycle = -depth
                            except ValueError:
                                depth = None
                                ref_cycle = None

                    i = inner_end + 1  # skip past )
                else:
                    i += 1

                if inner_expr:
                    sd = SampleDependencyIR(
                        func=func_name,
                        expr=inner_expr,
                        current_cycle=0,
                        reference_cycle=ref_cycle,
                        depth=depth,
                    )
                    sample_deps.append(sd)
                continue

            # 标识符 — 区分信号 vs local var
            if tk.kind == TokenKind.IDENT:
                name = tk.text

                # 检查位选：ident [ ... ]
                bit_select: tuple[int, int] | None = None
                if i + 2 < len(tokens) and tokens[i + 1].kind == TokenKind.LBRACKET:
                    j = i + 2
                    sel_parts: list[str] = []
                    while j < len(tokens) and tokens[j].kind != TokenKind.RBRACKET:
                        sel_parts.append(tokens[j].text)
                        j += 1
                    if j < len(tokens):
                        sel_text = "".join(sel_parts)
                        if ":" in sel_text:
                            left, right = sel_text.split(":", 1)
                            try:
                                bit_select = (int(left.strip()), int(right.strip()))
                            except ValueError:
                                pass
                        else:
                            try:
                                b = int(sel_text.strip())
                                bit_select = (b, b)
                            except ValueError:
                                pass
                        i = j  # skip to ]

                # 检查层次化路径
                segments: list[str] = [name]
                is_hierarchical = False
                j = i + 1 + (1 if bit_select is not None else 0)  # rough
                while j < len(tokens) - 1 and tokens[j].kind == TokenKind.DOT:
                    if j + 1 < len(tokens) and tokens[j + 1].kind == TokenKind.IDENT:
                        segments.append(tokens[j + 1].text)
                        is_hierarchical = True
                        j += 2
                    else:
                        break

                # 简单启发式：local var 通常短小写名
                if not is_hierarchical and name.islower() and not bit_select:
                    # 不能完全确定是 local var，这里保守放 signals
                    pass

                sr = SignalRef(
                    segments=tuple(segments),
                    bit_select=bit_select,
                    is_hierarchical=is_hierarchical,
                )
                signals.append(sr)
                i += 1
                continue

            i += 1

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

    def _find_matching_paren(self, tokens, open_idx: int) -> int:
        """找到与 open_idx 处 ( 匹配的 ) token 的 index。"""
        depth = 0
        for i in range(open_idx, len(tokens)):
            if tokens[i].kind == TokenKind.LPAREN:
                depth += 1
            elif tokens[i].kind == TokenKind.RPAREN:
                depth -= 1
                if depth == 0:
                    return i
        return len(tokens) - 1

    def _reconstruct_raw(self, tokens) -> str:
        """从 token 列表重建原始文本。"""
        parts: list[str] = []
        for tk in tokens:
            parts.append(tk.text)
        return " ".join(parts)
