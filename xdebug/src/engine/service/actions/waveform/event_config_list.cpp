#include "service/engine_action_handler.h"
#include "service/engine_action_registry.h"
#include "service/config_store_error.h"
#include "service/engine_globals.h"
#include "event_action_helpers.h"

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
#include "core/output/completeness.h"
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
class EventConfigListHandler : public EngineActionHandler {
public:
    const char* action_name() const override { return "event.config.list"; }
    bool needs_design() const override { return false; }
    bool needs_waveform() const override { return true; }
    bool include_xout_summary() const override { return false; }
    Json run(ContractBoundRequest& request, EngineActionContext& ctx) const override {
        using namespace xdebug_waveform;
        auto args = request.args();
        std::string name = args.value("name", "");
        EventManager em;
        if (name.empty()) {
            std::vector<std::string> names;
            StoreResult listed =
                em.list_events(g_session_id, g_fsdb_file_path, names);
            if (!listed.ok()) return make_config_store_error(listed);
            Json arr = Json::array();
            const int line_limit = args.value("line_limit", 100);
            for (size_t i = 0; i < names.size() &&
                 (line_limit < 0 || static_cast<int>(i) < line_limit); i++) arr.push_back(names[i]);
            Json out = {{"summary", Json::object()}, {"events", arr}};
            const bool response_truncated = arr.size() < names.size();
            xdebug_core::set_completeness(
                out["summary"],
                true,
                true,
                response_truncated,
                names.size(),
                arr.size(),
                response_truncated
                    ? std::vector<std::string>{"response_events"}
                    : std::vector<std::string>{});
            return out;
        }
        if (args.contains("line_limit"))
            return event_invalid_arg_error(action_name(), "args.line_limit",
                                           "line_limit is only valid when listing all event configs",
                                           "omit line_limit when args.name is present");
        EventConfig cfg;
        StoreResult loaded =
            em.get_event(g_session_id, g_fsdb_file_path, name, cfg);
        if (loaded.status == StoreStatus::NotFound)
            return event_config_not_found_error("event.config.list", name);
        if (!loaded.ok()) return make_config_store_error(loaded);
        Json out;
        out["summary"] = {{"status", "found"}};
        out["config"] = event_config_json(cfg);
        return out;
    }
};

}  // namespace

std::unique_ptr<EngineActionHandler> make_event_config_list_handler() {
    return std::unique_ptr<EngineActionHandler>(new EventConfigListHandler);
}

}  // namespace xdebug_design
