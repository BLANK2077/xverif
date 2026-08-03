#include "service/engine_action_handler.h"
#include "service/engine_action_registry.h"
#include "service/engine_globals.h"

#include "design/protocol/protocol.h"
#include "waveform/server/fsdb_value_reader.h"
#include "waveform/event/event_manager.h"
#include "waveform/event/event_analyzer.h"
#include "waveform/list/list_manager.h"
#include "waveform/list/signal_list.h"
#include "waveform/export/waveform_exporter.h"
#include "waveform/common/xdebug_waveform_paths.h"
#include "waveform/service/action_support.h"
#include "waveform/service/rc_generator.h"
#include "core/value/logic_value.h"
#include "core/npi/time_contract.h"

#include "npi.h"
#include "npi_fsdb.h"
#include "npi_L1.h"
#include "npi_hdl.h"

#include <fstream>
#include <memory>
#include <algorithm>
#include <map>
#include <sstream>
#include <vector>

namespace xdebug_design {
namespace {
class AiActionHandler : public EngineActionHandler {
    std::string name_;
    bool nd_, nw_;
public:
    AiActionHandler(const char* name, bool needs_design, bool needs_waveform)
        : name_(name), nd_(needs_design), nw_(needs_waveform) {}
    const char* action_name() const override { return name_.c_str(); }
    bool needs_design() const override { return nd_; }
    bool needs_waveform() const override { return nw_; }
    Json run(ContractBoundRequest& request, EngineActionContext& ctx) const override {
        std::string error;
        Json effective_request = request.consume_args_request(
            "xdebug_waveform::ai_dispatch_query/" + name_);
        Json result = xdebug_waveform::ai_dispatch_query(effective_request, error);
        if (!error.empty()) {
            return make_handler_error_from_message(error);
        }
        // Fix statistics end time: ai functions may return FSDB max time
        // instead of the requested window end.
        auto args = request.args();
        if (args.contains("time_range") && args["time_range"].is_object() &&
            args["time_range"].contains("end")) {
            std::string req_end = args["time_range"]["end"].get<std::string>();
            if (!req_end.empty() && result.contains("end") &&
                result["end"].is_string() && result["end"] != req_end) {
                npiFsdbTime parsed_end = 0;
                std::string parse_error;
                if (xdebug_waveform::parse_user_time(req_end.c_str(), true, parsed_end, parse_error)) {
                    result["end"] = xdebug_core::format_time(g_fsdb_file, parsed_end);
                }
            }
        }
        return result;
    }
};

}  // namespace

std::unique_ptr<EngineActionHandler> make_signal_statistics_handler() {
    return std::unique_ptr<EngineActionHandler>(new AiActionHandler("signal.statistics", false, true));
}

}  // namespace xdebug_design
