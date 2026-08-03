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
class NwaveRcGenerateHandler : public EngineActionHandler {
public:
    const char* action_name() const override { return "nwave.rc.generate"; }
    bool needs_design() const override { return false; }
    bool needs_waveform() const override { return true; }
    Json run(ContractBoundRequest& r, EngineActionContext& ctx) const override {
        auto a = r.args();
        std::string config_path = a.value("config_path", "");
        ContractJsonView output = a["output"];
        std::string rc_path = output.value("path", "");
        bool allow_invalid = a.value("allow_invalid", false);
        if (config_path.empty() || rc_path.empty())
            return make_handler_error(
                "MISSING_FIELD",
                "args.config_path and args.output.path are required",
                {{"invalid_arg", config_path.empty() ? "args.config_path" : "args.output.path"},
                 {"expected", "input config_path and output.path"},
                 {"required_any_of", Json::array({"args.config_path", "args.output.path"})},
                 {"correct_example", {{"api_version", "xdebug.v1"},
                                      {"action", "nwave.rc.generate"},
                                      {"target", {{"session_id", "case_a"}}},
                                      {"args", {{"config_path", "xdebug/configs/wave.rc.json"},
                                                {"output", {{"path", "wave.rc"}}}}}}},
                 {"example_note", "Example only; replace config_path and output.path with project paths."}});

        // Read config file
        std::ifstream in(config_path);
        if (!in) return make_handler_error(
            "CONFIG_NOT_FOUND",
            "config file not found: " + config_path,
            {{"invalid_arg", "args.config_path"},
             {"missing_name", config_path},
             {"missing_resource", "rc config file"},
             {"expected", "readable rc config JSON file"}});
        std::string content((std::istreambuf_iterator<char>(in)), std::istreambuf_iterator<char>());
        nlohmann::json doc;
        try { doc = nlohmann::json::parse(content); }
        catch (...) { return make_handler_error(
            "INVALID_JSON",
            "failed to parse config file",
            {{"invalid_arg", "args.config_path"},
             {"expected", "valid JSON rc config file"}}); }

        xdebug_waveform::RcConfig cfg;
        std::string err;
        if (!xdebug_waveform::parse_rc_config_json(doc, cfg, err))
            return make_handler_error(
                "INVALID_ARGUMENT",
                err,
                 {{"invalid_arg", "args.config_path"},
                  {"expected", "rc config JSON matching nwave.rc.generate schema"},
                  {"cause_code", "PARSE_FAILED"}});

        if (!xdebug_waveform::validate_rc_time_refs(cfg, g_fsdb_file, err) ||
            !xdebug_waveform::normalize_rc_user_marker_times(cfg, g_fsdb_file, err)) {
            return make_handler_error(
                "INVALID_ARGUMENT",
                err,
                {{"invalid_arg", "args.config_path"},
                 {"expected", "valid rc time values; user_markers[].time requires an explicit unit"},
                 {"cause_code", "TIME_PARSE_FAILED"}});
        }

        auto refs = xdebug_waveform::collect_rc_signal_refs(cfg);

        // Validate signals exist in FSDB
        if (!allow_invalid) {
            for (auto& ref : refs) {
                if (ref.kind != "signal") continue;
                if (!npi_fsdb_sig_by_name(g_fsdb_file, ref.input_path.c_str(), NULL)) {
                    return make_handler_error(
                        "SIGNAL_NOT_FOUND",
                        "signal not in FSDB: " + ref.input_path,
                        {{"invalid_arg", "args.config_path"},
                         {"missing_name", ref.input_path},
                         {"missing_resource", "signal"},
                         {"expected", "rc config signals that exist in the active FSDB"}});
                }
            }
        }

        std::string rc_text = xdebug_waveform::render_signal_rc(cfg);
        if (!xdebug_waveform::write_text_file_creating_dirs(rc_path, rc_text, err))
            return make_handler_error("ACTION_FAILED", err, {{"cause_code", "WRITE_FAILED"}});

        Json counts = Json::parse(xdebug_waveform::rc_config_counts(cfg).dump());
        Json out;
        out["summary"] = {{"written", true}, {"config_path", config_path},
            {"output", {{"path", rc_path}}}, {"valid", true}};
        if (counts.contains("group_count")) out["summary"]["group_count"] = counts["group_count"];
        if (counts.contains("signal_count")) out["summary"]["signal_count"] = counts["signal_count"];
        out["validation"] = {{"signals", refs.size()},
                               {"times", xdebug_waveform::collect_rc_time_refs(cfg).size()}};
        out["rc_preview"] = xdebug_waveform::rc_preview_lines(rc_text, 20);
        return out;
    }
};

}  // namespace

std::unique_ptr<EngineActionHandler> make_nwave_rc_generate_handler() {
    return std::unique_ptr<EngineActionHandler>(new NwaveRcGenerateHandler);
}

}  // namespace xdebug_design
