#include "service/engine_action_handler.h"
#include "service/engine_action_registry.h"
#include "service/config_store_error.h"
#include "service/engine_globals.h"
#include "protocol_action_helpers.h"

#include "waveform/apb/apb_manager.h"
#include "waveform/apb/apb_analyzer.h"
#include "waveform/axi/axi_manager.h"
#include "waveform/axi/axi_analyzer.h"
#include "waveform/axi/axi_exporter.h"
#include "waveform/common/xdebug_waveform_paths.h"
#include "core/value/logic_value.h"

#include <fstream>
#include <memory>
#include <ctime>
#include <sstream>

namespace xdebug_design {
namespace {
class ApbConfigListHandler : public EngineActionHandler {
public:
    const char* action_name() const override { return "apb.config.list"; }
    bool needs_design() const override { return false; }
    bool needs_waveform() const override { return true; }
    bool include_xout_summary() const override { return false; }
    Json run(
        ContractBoundRequest& request,
        EngineActionContext& ctx) const override {
        auto args = request.args();
        std::string name = args.value("name", "");
        xdebug_waveform::ApbManager am;
        if (name.empty()) {
            std::vector<xdebug_waveform::ApbConfig> configs;
            xdebug_waveform::StoreResult listed =
                am.list_all(xdebug_waveform::g_session_id, configs);
            if (!listed.ok()) return make_config_store_error(listed);
            Json arr = Json::array();
            for (const auto& cfg : configs) {
                arr.push_back(apb_config_json(cfg));
            }
            return Json{{"summary", {{"count", configs.size()}}}, {"configs", arr}};
        }
        xdebug_waveform::ApbConfig cfg;
        xdebug_waveform::StoreResult loaded =
            am.get_apb(xdebug_waveform::g_session_id, name, cfg);
        if (loaded.status == xdebug_waveform::StoreStatus::NotFound)
            return protocol_config_not_found_error(action_name(), "apb", name);
        if (!loaded.ok()) return make_config_store_error(loaded);
        Json out;
        out["summary"] = {{"name", name}, {"status", "found"}};
        out["config"] = apb_config_json(cfg);
        return out;
    }
};

}  // namespace

std::unique_ptr<EngineActionHandler> make_apb_config_list_handler() {
    return std::unique_ptr<EngineActionHandler>(new ApbConfigListHandler);
}

}  // namespace xdebug_design
