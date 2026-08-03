#pragma once

namespace xdebug_design {

struct TraceCompletenessFacts {
    constexpr TraceCompletenessFacts(bool ok_value = true,
                                     bool truncated_value = false,
                                     bool statement_only_value = false,
                                     bool unknown_expr_value = false,
                                     bool incomplete_evidence_value = false)
        : ok(ok_value),
          truncated(truncated_value),
          has_statement_only(statement_only_value),
          has_unknown_expr(unknown_expr_value),
          has_incomplete_evidence(incomplete_evidence_value) {}

    bool ok;
    bool truncated;
    bool has_statement_only;
    bool has_unknown_expr;
    bool has_incomplete_evidence;
};

constexpr bool trace_analysis_complete(const TraceCompletenessFacts& facts) {
    return facts.ok &&
           !facts.truncated &&
           !facts.has_statement_only &&
           !facts.has_unknown_expr &&
           !facts.has_incomplete_evidence;
}

}  // namespace xdebug_design
