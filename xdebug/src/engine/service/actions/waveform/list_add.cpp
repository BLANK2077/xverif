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
class ListAddHandler : public EngineActionHandler {
public:
    const char* action_name() const override { return "list.add"; }
    bool needs_design() const override { return false; }
    bool needs_waveform() const override { return true; }
    Json run(ContractBoundRequest& r, EngineActionContext& ctx) const override {
        auto a = r.args();
        std::string n = a.value("name", ""), sig = a.value("signal", "");
        if (n.empty())
            return list_missing_field_error("list.add", "args.name", "name of a list created in this session");
        if (sig.empty())
            return list_missing_field_error("list.add", "args.signal", "existing waveform signal path");
        if (!npi_fsdb_sig_by_name(xdebug_waveform::g_fsdb_file, sig.c_str(), NULL))
            return list_signal_not_found_error("list.add", sig);
        xdebug_waveform::ListManager lm;
        xdebug_waveform::StoreResult added =
            lm.add_signal(xdebug_waveform::g_session_id, n, sig);
        if (added.status == xdebug_waveform::StoreStatus::NotFound)
            return list_not_found_error("list.add", n);
        if (!added.ok()) return make_config_store_error(added);
        Json out;
        out["summary"] = {{"name", n}, {"signal", sig}, {"status", "added"}, {"added", true}};
        return out;
    }
};

}  // namespace

std::unique_ptr<EngineActionHandler> make_list_add_handler() {
    return std::unique_ptr<EngineActionHandler>(new ListAddHandler);
}

}  // namespace xdebug_design
