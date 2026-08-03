#include "service/engine_action_handler.h"
#include "service/engine_action_registry.h"
#include "service/config_store_error.h"
#include "service/engine_globals.h"
#include "list_action_helpers.h"

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
class ListCreateHandler : public EngineActionHandler {
public:
    const char* action_name() const override { return "list.create"; }
    bool needs_design() const override { return false; }
    bool needs_waveform() const override { return true; }
    Json run(ContractBoundRequest& r, EngineActionContext& ctx) const override {
        auto a = r.args();
        std::string n = a.value("name", "");
        if (n.empty())
            return list_missing_field_error("list.create", "args.name", "non-empty list name");
        ContractJsonView requested_signals_view = a["signals"];
        Json requested_signals = requested_signals_view.exists()
            ? requested_signals_view.consume_subtree(
                  "list_create_signal_array_parser")
            : Json::array();
        std::vector<std::string> signals;
        for (size_t index = 0; index < requested_signals.size(); ++index) {
            if (!requested_signals[index].is_string() ||
                requested_signals[index].get<std::string>().empty()) {
                return list_invalid_arg_error(
                    action_name(),
                    "args.signals",
                    "array of non-empty waveform signal paths",
                    requested_signals[index]);
            }
            const std::string signal =
                requested_signals[index].get<std::string>();
            if (!npi_fsdb_sig_by_name(
                    xdebug_waveform::g_fsdb_file,
                    signal.c_str(),
                    nullptr)) {
                return list_signal_not_found_error(action_name(), signal);
            }
            signals.push_back(signal);
        }
        xdebug_waveform::ListManager lm;
        xdebug_waveform::StoreResult created =
            lm.create_list(xdebug_waveform::g_session_id, n, signals);
        if (!created.ok()) return make_config_store_error(created);
        Json out;
        out["summary"] = {{"name", n}, {"status", "created"}, {"created", true},
                          {"signal_count", signals.size()}};
        out["signals"] = signals;
        return out;
    }
};

}  // namespace

std::unique_ptr<EngineActionHandler> make_list_create_handler() {
    return std::unique_ptr<EngineActionHandler>(new ListCreateHandler);
}

}  // namespace xdebug_design
