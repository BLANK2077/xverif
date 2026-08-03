#include "service/engine_action_handler.h"
#include "service/engine_action_registry.h"
#include "service/engine_globals.h"
#include "service/design_postprocess.h"
#include "service/trace_bfs_engine.h"

#include "core/ai/common_blocks.h"

#include "design/trace/trace_engine.h"
#include "design/signal/signal_finder.h"
#include "design/service/action_support.h"

#include "npi.h"
#include "npi_fsdb.h"
#include "npi_L1.h"

#include <fstream>
#include <map>
#include <memory>
#include <set>

namespace xdebug_design {
namespace {

static TraceOptions parse_trace_opts(const ContractJsonView& args) {
    TraceOptions opts;
    opts.limit = args.value("line_limit", 0);
    opts.role = args.value("role", std::string());
    opts.no_statement_only = args.value("no_statement_only", false);
    return opts;
}
static nlohmann::json trace_one_signal(const std::string& signal,
                                        TraceMode mode,
                                        const TraceOptions& opts) {
    TraceEngine engine;
    TraceResult r = engine.trace(signal, mode, opts);
    return nlohmann::json::parse(engine.render_ai_json(r));
}

class ExprNormalizeHandler : public EngineActionHandler {
public:
    const char* action_name() const override { return "expr.normalize"; }
    bool needs_design() const override { return false; }
    bool needs_waveform() const override { return false; }
    Json run(ContractBoundRequest& request, EngineActionContext& ctx) const override {
        auto args = request.args();
        std::string signal = args.value("signal", "");
        std::string expr = args.value("expr", "");
        if (!signal.empty() && !expr.empty()) {
            return make_handler_error(
                "INVALID_REQUEST",
                "args.expr and args.signal are mutually exclusive",
                {{"invalid_arg", "args"},
                 {"expected", "exactly one of args.expr or args.signal"},
                 {"required_any_of", Json::array({"args.expr", "args.signal"})}});
        }

        Json out;
        if (!signal.empty()) {
            if (!g_has_design) {
                return make_handler_error(
                    "DESIGN_NOT_LOADED",
                    "expr.normalize signal variant requires a design resource",
                    {{"invalid_arg", "target"},
                     {"expected", "target.daidir or a design session"}});
            }
            TraceOptions opts = parse_trace_opts(args);
            nlohmann::json trace = trace_one_signal(signal, TraceMode::Driver, opts);
            nlohmann::json assignment = trace.value("assignment", nlohmann::json::object());
            out["summary"] = {{"signal",signal},{"source","npi_trace_assignment"},
                {"confidence",trace.value("confidence","unknown")}};
            out["expr"] = Json::parse(
                assignment.value("rhs", nlohmann::json::object()).dump());
            out["assignment"] = Json::parse(assignment.dump());
            out["rhs_signals"] = Json::parse(
                assignment.value("rhs_signals", nlohmann::json::array()).dump());
            return out;
        }
        if (!expr.empty() && args.contains("line_limit"))
            return make_handler_error("INVALID_REQUEST",
                                      "expr.normalize args.line_limit is only valid with args.signal",
                                      {{"invalid_arg", "args.line_limit"},
                                       {"expected", "omit line_limit for direct expression parsing"}});
        if (expr.empty()) return make_handler_error(
            "MISSING_FIELD",
            "args.expr or args.signal is required",
            {{"invalid_arg", "args.expr"},
             {"expected", "either args.expr or args.signal"},
             {"required_any_of", Json::array({"args.expr", "args.signal"})},
             {"correct_example", {{"api_version", "xdebug.v1"},
                                  {"action", "expr.normalize"},
                                  {"args", {{"expr", "valid && ready"}}}}}});
        ExprSyntaxValidation syntax = validate_expr_syntax(expr);
        if (!syntax.ok) {
            return make_handler_error(
                "EXPR_SYNTAX_INVALID",
                syntax.message,
                {{"invalid_arg", "args.expr"},
                 {"received", expr},
                 {"expected", "balanced expression with complete operands and operators"},
                 {"correct_example", {{"api_version", "xdebug.v1"},
                                       {"action", "expr.normalize"},
                                       {"args", {{"expr", "valid && ready"}}}}},
                 {"next_actions", Json::array({"Fix the expression syntax before using it for debug queries."})}});
        }
        out["summary"] = {
            {"status", "parsed"},
            {"source", "deterministic_syntax_parser"},
            {"confidence", "syntax_validated"}
        };
        out["expr"] = Json::parse(parse_expr_ast(expr).dump());
        out["parsed"] = true;
        out["confidence_reason"] =
            "expression syntax was validated and parsed without design-resource semantics";
        return out;
    }
};

}  // namespace

std::unique_ptr<EngineActionHandler> make_expr_normalize_handler() {
    return std::unique_ptr<EngineActionHandler>(new ExprNormalizeHandler);
}

}  // namespace xdebug_design
