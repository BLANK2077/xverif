#include "service/engine_action_handler.h"
#include "service/engine_action_registry.h"
#include "service/engine_globals.h"
#include "service/config_store_error.h"
#include "list_action_helpers.h"

#include "waveform/list/list_manager.h"
#include "waveform/list/signal_list.h"

#include "npi_fsdb.h"

#include <memory>
#include <set>
#include <string>
#include <vector>

namespace xdebug_design {
namespace {

Json load_error(
    const std::string& code,
    const std::string& message,
    const std::string& invalid_arg,
    const std::string& expected) {
    return make_handler_error(
        code,
        message,
        {{"invalid_arg", invalid_arg},
         {"expected", expected},
         {"correct_example", list_action_example("list.load")},
         {"example_note", "Example only; use final leaf paths from the active FSDB."}});
}

bool parse_config(
    const Json& root,
    std::vector<xdebug_waveform::SignalList>& lists,
    Json& validation,
    Json& error) {
    if (!root.is_object() || root.size() != 1 ||
        !root.contains("lists") || !root["lists"].is_array() ||
        root["lists"].empty()) {
        error = load_error(
            "INVALID_ARGUMENT",
            "list config must contain exactly one non-empty lists array",
            "args.config",
            "{\"lists\":[{\"name\":\"...\",\"signals\":[\"...\"]}]}");
        return false;
    }
    std::set<std::string> names;
    lists.clear();
    validation = Json::array();
    for (size_t list_index = 0; list_index < root["lists"].size();
         ++list_index) {
        const Json& item = root["lists"][list_index];
        const std::string prefix =
            "args.config.lists[" + std::to_string(list_index) + "]";
        if (!item.is_object() || item.size() != 2 ||
            !item.contains("name") || !item["name"].is_string() ||
            item["name"].get<std::string>().empty() ||
            !item.contains("signals") || !item["signals"].is_array() ||
            item["signals"].empty()) {
            error = load_error(
                "INVALID_ARGUMENT",
                prefix + " must contain only non-empty name and signals",
                prefix,
                "object with non-empty name and non-empty signals array");
            return false;
        }
        xdebug_waveform::SignalList list;
        list.name = item["name"].get<std::string>();
        if (!names.insert(list.name).second) {
            error = load_error(
                "INVALID_ARGUMENT",
                "duplicate list name in config: " + list.name,
                prefix + ".name",
                "unique list name");
            return false;
        }
        std::set<std::string> signals;
        Json signal_validation = Json::array();
        for (size_t signal_index = 0;
             signal_index < item["signals"].size();
             ++signal_index) {
            const Json& value = item["signals"][signal_index];
            const std::string signal_arg =
                prefix + ".signals[" + std::to_string(signal_index) + "]";
            if (!value.is_string() || value.get<std::string>().empty()) {
                error = load_error(
                    "INVALID_ARGUMENT",
                    signal_arg + " must be a non-empty string",
                    signal_arg,
                    "final leaf waveform signal path");
                return false;
            }
            const std::string signal = value.get<std::string>();
            if (!signals.insert(signal).second) {
                error = load_error(
                    "INVALID_ARGUMENT",
                    "duplicate signal in list " + list.name + ": " + signal,
                    signal_arg,
                    "unique signal path within the list");
                return false;
            }
            if (!npi_fsdb_sig_by_name(
                    xdebug_waveform::g_fsdb_file,
                    signal.c_str(),
                    nullptr)) {
                error = load_error(
                    "SIGNAL_NOT_FOUND",
                    "signal not found: " + signal,
                    signal_arg,
                    "existing final leaf waveform signal path");
                return false;
            }
            list.signals.push_back(signal);
            signal_validation.push_back(
                {{"signal", signal}, {"status", "ok"}});
        }
        lists.push_back(list);
        validation.push_back(
            {{"name", list.name},
             {"status", "ok"},
             {"signals", signal_validation}});
    }
    return true;
}

class ListLoadHandler : public EngineActionHandler {
public:
    const char* action_name() const override { return "list.load"; }
    bool needs_design() const override { return false; }
    bool needs_waveform() const override { return true; }

    Json run(
        ContractBoundRequest& request,
        EngineActionContext& ctx) const override {
        auto args = request.args();
        Json config_args = Json::object();
        if (args["config"].exists()) {
            config_args["config"] = args["config"].consume_subtree(
                "list_load_config_parser");
        }
        if (args["config_path"].exists()) {
            config_args["config_path"] =
                args["config_path"].get<std::string>();
        }
        nlohmann::json loaded_config;
        std::string load_message;
        if (!load_config_from_args(
                config_args,
                loaded_config,
                load_message)) {
            return load_error(
                "INVALID_ARGUMENT",
                load_message,
                config_args.contains("config_path")
                    ? "args.config_path"
                    : "args.config",
                "inline args.config object or readable args.config_path");
        }
        Json root = Json::parse(loaded_config.dump());
        Json error;
        std::vector<xdebug_waveform::SignalList> lists;
        Json validation;
        if (!parse_config(root, lists, validation, error)) return error;
        const std::string mode =
            args.value("mode", std::string("replace"));
        xdebug_waveform::ListManager manager;
        xdebug_waveform::StoreResult stored =
            manager.load_lists(
                xdebug_waveform::g_session_id,
                lists,
                mode);
        if (!stored.ok()) return make_config_store_error(stored);
        Json names = Json::array();
        for (const auto& list : lists) names.push_back(list.name);
        Json out;
        out["summary"] = {
            {"loaded", static_cast<int>(lists.size())},
            {"mode", mode}
        };
        out["lists"] = names;
        out["validation"] = validation;
        return out;
    }
};

}  // namespace

std::unique_ptr<EngineActionHandler> make_list_load_handler() {
    return std::unique_ptr<EngineActionHandler>(new ListLoadHandler);
}

}  // namespace xdebug_design
