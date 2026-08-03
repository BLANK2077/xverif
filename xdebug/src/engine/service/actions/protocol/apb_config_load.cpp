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
#include "waveform/service/action_support.h"
#include "core/value/logic_value.h"

#include "npi_fsdb.h"

#include <fstream>
#include <memory>
#include <ctime>
#include <sstream>

namespace xdebug_design {
namespace {
class ApbConfigLoadHandler : public EngineActionHandler {
public:
    const char* action_name() const override { return "apb.config.load"; }
    bool needs_design() const override { return false; }
    bool needs_waveform() const override { return true; }
    Json run(
        ContractBoundRequest& request,
        EngineActionContext& ctx) const override {
        using namespace xdebug_waveform;
        auto args = request.args();
        std::string name = args.value("name", "");
        if (name.empty()) return protocol_missing_name_error(action_name(), "apb");

        Json config_args = Json::object();
        if (args["config"].exists()) {
            config_args["config"] = args["config"].consume_subtree(
                "apb_config_document_parser");
        }
        if (args["config_path"].exists()) {
            config_args["config_path"] =
                args["config_path"].get<std::string>();
        }
        nlohmann::json cfg_j; std::string err_str;
        if (!load_config_from_args(config_args, cfg_j, err_str))
            return protocol_invalid_arg_error(action_name(), "args.config",
                                              err_str,
                                              "inline args.config object or readable args.config_path");

        ApbConfig cfg;
        if (!xdebug_waveform::parse_apb_config(cfg_j, cfg, err_str))
            return protocol_invalid_arg_error(
                action_name(),
                "args.config",
                err_str,
                "strict APB config with only canonical fields and non-empty signal paths");
        cfg.name = name;
        npiFsdbSigHandle reset_handle = npi_fsdb_sig_by_name(g_fsdb_file, cfg.reset.signal.c_str(), nullptr);
        NPI_INT32 reset_width = 0;
        if (!reset_handle || !npi_fsdb_sig_property(npiFsdbSigRangeSize, reset_handle, &reset_width) || reset_width != 1)
            return protocol_invalid_arg_error(action_name(), "config.reset.signal",
                                              "APB reset signal must resolve to one bit",
                                              "one-bit waveform signal path");

        ApbManager am;
        StoreResult created = am.create_apb(g_session_id, cfg);
        if (!created.ok()) return make_config_store_error(created);

        Json out;
        out["summary"] = {{"name", name}, {"status", "loaded"}};
        out["config"] = xdebug_design::apb_config_json(cfg);
        return out;
    }
};

}  // namespace

std::unique_ptr<EngineActionHandler> make_apb_config_load_handler() {
    return std::unique_ptr<EngineActionHandler>(new ApbConfigLoadHandler);
}

}  // namespace xdebug_design
