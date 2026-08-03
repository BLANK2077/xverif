#include "service/engine_action_handler.h"
#include "service/engine_action_registry.h"
#include "service/engine_globals.h"
#include "waveform_action_support.h"
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
class ListValidateHandler : public EngineActionHandler {
public:
    const char* action_name() const override { return "list.validate"; }
    bool needs_design() const override { return false; }
    bool needs_waveform() const override { return true; }
    Json run(ContractBoundRequest& r, EngineActionContext& ctx) const override {
        auto a = r.args();
        std::string n = a.value("name", "");
        if (n.empty())
            return list_missing_field_error("list.validate", "args.name", "name of a list created in this session");
        xdebug_waveform::SignalList lst;
        xdebug_waveform::StoreResult loaded = read_list_storage(n, lst);
        if (loaded.status == xdebug_waveform::StoreStatus::NotFound)
            return list_not_found_error("list.validate", n);
        if (!loaded.ok()) return make_config_store_error(loaded);
        Json arr = Json::array();
        for (auto& sig : lst.signals) {
            Json item; item["signal"] = sig;
            item["status"] = npi_fsdb_sig_by_name(xdebug_waveform::g_fsdb_file, sig.c_str(), NULL)
                ? "ok" : "not_found";
            arr.push_back(item);
        }
        Json out; out["signals"] = arr;
        bool all_found = true;
        for (const auto& item : arr) {
            if (item.value("status", "") != "ok") all_found = false;
        }
        out["summary"] = {{"name", n}, {"all_found", all_found}};
        return out;
    }
};

}  // namespace

std::unique_ptr<EngineActionHandler> make_list_validate_handler() {
    return std::unique_ptr<EngineActionHandler>(new ListValidateHandler);
}

}  // namespace xdebug_design
