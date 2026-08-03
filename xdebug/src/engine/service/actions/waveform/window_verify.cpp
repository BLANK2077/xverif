#include "service/engine_action_handler.h"
#include "service/engine_action_registry.h"
#include "service/engine_globals.h"
#include "waveform_action_error_helpers.h"

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

Json expression_alias_error(const std::string& action, const std::string& message) {
    return waveform_expression_alias_error(action, "args.conditions[].expr", message);
}

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
        Json raw_request = request.consume_args_request(
            "xdebug_waveform::ai_dispatch_query/window.verify");
        Json result = xdebug_waveform::ai_dispatch_query(raw_request, error);
        if (!error.empty()) {
            if (error.find("expression operands must be aliases") != std::string::npos) {
                return expression_alias_error(name_, error);
            }
            return make_handler_error_from_message(error);
        }
        return result;
    }
};

}  // namespace

std::unique_ptr<EngineActionHandler> make_window_verify_handler() {
    return std::unique_ptr<EngineActionHandler>(new AiActionHandler("window.verify", false, true));
}

}  // namespace xdebug_design
