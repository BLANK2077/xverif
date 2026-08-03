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
class CursorActionHandler : public EngineActionHandler {
    std::string name_;
public:
    explicit CursorActionHandler(const char* name) : name_(name) {}
    const char* action_name() const override { return name_.c_str(); }
    bool needs_design() const override { return false; }
    bool needs_waveform() const override { return true; }
    Json run(ContractBoundRequest& request, EngineActionContext& ctx) const override {
        std::string action = request.action();
        auto args = request.args();
        std::string error;
        Json raw_args = args.consume_subtree(
            "xdebug_waveform::ai_cursor_action/" + action);
        Json result = xdebug_waveform::ai_cursor_action(action, raw_args, error);
        if (!error.empty()) {
            return make_handler_error_from_message(error);
        }
        return result;
    }
};

}  // namespace

std::unique_ptr<EngineActionHandler> make_cursor_get_handler() {
    return std::unique_ptr<EngineActionHandler>(new CursorActionHandler("waveform.cursor.get"));
}

}  // namespace xdebug_design
