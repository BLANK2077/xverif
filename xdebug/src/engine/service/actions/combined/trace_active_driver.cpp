#include "service/engine_action_handler.h"
#include "service/engine_globals.h"
#include "service/trace_source_path_formatter.h"

#include "combined/active_trace_service.h"
#include "combined/active_trace_chain.h"
#include "core/ai/common_blocks.h"

#include <memory>
#include <string>

namespace xdebug_design {
namespace {

Json active_driver_domain_request(
    ContractBoundRequest& request,
    const std::string& signal,
    const std::string& time) {
    Json projected = {
        {"args", {
            {"signal", signal},
            {"time", time},
        }},
        {"limits", Json::object()},
    };
    auto limits = request.limits();
    for (const char* key : {
             "max_depth",
             "max_nodes",
             "max_time_steps",
             "max_trace_signals",
         }) {
        ContractJsonView value = limits[key];
        if (value.exists()) {
            projected["limits"][key] = value.get<int>();
        }
    }
    return projected;
}

class ActiveDriverHandler : public EngineActionHandler {
public:
    const char* action_name() const override { return "trace.active_driver"; }
    bool needs_design() const override { return true; }
    bool needs_waveform() const override { return true; }
    Json run(ContractBoundRequest& request, EngineActionContext& ctx) const override {
        auto args = request.args();
        std::string signal = args.value("signal", std::string());
        std::string requested_time = args.value("time", std::string());
        Json domain_request = active_driver_domain_request(
            request,
            signal,
            requested_time);
        Json raw = xdebug::build_active_driver_payload(
            domain_request,
            g_daidir_path,
            g_fsdb_path,
            g_fsdb_file,
            true);
        if (raw.contains("error")) return raw;
        Json out = simplify_active_driver_payload(raw,
                                                  signal,
                                                  requested_time,
                                                  trace_result_limit_from_request(request));
        xdebug::append_common_blocks_to_payload(out);
        return out;
    }

    std::string render_xout(const Json& response) const override {
        return append_common_blocks_xout(
            render_source_path_xout(action_name(), response), response);
    }

};

} // namespace

std::unique_ptr<EngineActionHandler> make_trace_active_driver_handler() {
    return std::unique_ptr<EngineActionHandler>(new ActiveDriverHandler);
}

} // namespace xdebug_design
