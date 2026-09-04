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
class AxiConfigListHandler : public EngineActionHandler {
public:
    const char* action_name() const override { return "axi.config.list"; }
    bool needs_design() const override { return false; }
    bool needs_waveform() const override { return true; }
    bool include_xout_summary() const override { return false; }
    Json run(
        ContractBoundRequest& request,
        EngineActionContext& ctx) const override {
        auto args = request.args();
        std::string name = args.value("name", "");
        xdebug_waveform::AxiManager am;
        if (name.empty()) {
            std::vector<xdebug_waveform::AxiConfig> configs;
            xdebug_waveform::StoreResult listed =
                am.list_all(xdebug_waveform::g_session_id, configs);
            if (!listed.ok()) return make_config_store_error(listed);
            Json arr = Json::array();
            for (const auto& cfg : configs) {
                arr.push_back(axi_config_json(cfg));
            }
            return Json{{"summary", {{"count", configs.size()}}}, {"configs", arr}};
        }
        xdebug_waveform::AxiConfig cfg;
        xdebug_waveform::StoreResult loaded =
            am.get_axi(xdebug_waveform::g_session_id, name, cfg);
        if (loaded.status == xdebug_waveform::StoreStatus::NotFound)
            return protocol_config_not_found_error(action_name(), "axi", name);
        if (!loaded.ok()) return make_config_store_error(loaded);
        Json out;
        out["summary"] = {{"name", name}, {"status", "found"}};
        out["config"] = axi_config_json(cfg);
        return out;
    }
};

}  // namespace

std::unique_ptr<EngineActionHandler> make_axi_config_list_handler() {
    return std::unique_ptr<EngineActionHandler>(new AxiConfigListHandler);
}

}  // namespace xdebug_design
