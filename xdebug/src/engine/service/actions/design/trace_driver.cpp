#include "service/engine_action_handler.h"
#include "service/engine_action_registry.h"
#include "service/engine_globals.h"
#include "service/design_postprocess.h"
#include "service/trace_bfs_engine.h"
#include "service/trace_source_path_formatter.h"
#include "design_action_helpers.h"

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
    // limits.max_results is a response projection limit.  The static trace
    // must run without that cap so summary.analysis_complete describes real
    // analysis.
    opts.limit = 0;
    opts.role = args.value("role", std::string());
    opts.no_statement_only = args.value("no_statement_only", false);
    return opts;
}

class TraceDriverHandler : public EngineActionHandler {
public:
    const char* action_name() const override { return "trace.driver"; }
    bool needs_design() const override { return true; }
    bool needs_waveform() const override { return false; }

    Json run(ContractBoundRequest& request, EngineActionContext& ctx) const override {
        auto args = request.args();
        std::string signal = args.value("signal", std::string());
        if (signal.empty()) return design_missing_signal_error(action_name());
        SignalResolveResult resolved;
        Json failure;
        if (!resolve_design_signal(action_name(), signal, resolved, failure)) return failure;
        TraceEngine engine;
        TraceResult result = engine.trace(signal, TraceMode::Driver, parse_trace_opts(args));
        Json raw = Json::parse(engine.render_ai_json(result));
        Json out = simplify_trace_driver_load_payload(raw,
                                                      action_name(),
                                                      signal,
                                                      "driver",
                                                      trace_result_limit_from_request(request));
        xdebug::append_common_blocks_to_payload(out);
        return out;
    }

    std::string render_xout(const Json& response) const override {
        return append_common_blocks_xout(
            render_source_path_xout(action_name(), response), response);
    }

};

}  // namespace

std::unique_ptr<EngineActionHandler> make_trace_driver_handler() {
    return std::unique_ptr<EngineActionHandler>(new TraceDriverHandler);
}

}  // namespace xdebug_design
