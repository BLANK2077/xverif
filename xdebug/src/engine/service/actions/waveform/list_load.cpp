#include "service/engine_action_handler.h"
#include "service/engine_action_registry.h"
#include "service/engine_globals.h"

#include "waveform/list/list_manager.h"
#include "waveform/list/signal_list.h"

#include "npi_fsdb.h"

#include <memory>
#include <set>
#include <vector>

namespace xdebug_design {
namespace {

Json list_load_error(const std::string& code,
                     const std::string& message,
                     const std::string& invalid_arg,
                     const std::string& expected) {
    return make_handler_error(code, message,
                              {{"invalid_arg", invalid_arg},
                               {"expected", expected}});
}

bool parse_lists(const Json& root,
                 std::vector<xdebug_waveform::SignalList>& lists,
                 Json& validation,
                 Json& error) {
    if (!root.is_object() || root.size() != 1 ||
        !root.contains("lists") || !root["lists"].is_array() ||
        root["lists"].empty()) {
        error = list_load_error(
            "INVALID_ARGUMENT",
            "list config must contain exactly one non-empty lists array",
            "args.config",
            "{\"lists\":[{\"name\":\"...\",\"signals\":[\"...\"]}]}");
        return false;
    }
    std::set<std::string> names;
    validation = Json::array();
    for (size_t i = 0; i < root["lists"].size(); ++i) {
        const Json& item = root["lists"][i];
        const std::string prefix =
            "args.config.lists[" + std::to_string(i) + "]";
        if (!item.is_object() || item.size() != 2 ||
            !item.contains("name") || !item["name"].is_string() ||
            item["name"].get<std::string>().empty() ||
            !item.contains("signals") || !item["signals"].is_array() ||
            item["signals"].empty()) {
            error = list_load_error(
                "INVALID_ARGUMENT", prefix + " must contain only name and signals",
                prefix, "non-empty name and non-empty signals array");
            return false;
        }
        xdebug_waveform::SignalList list;
        list.name = item["name"].get<std::string>();
        if (!names.insert(list.name).second) {
            error = list_load_error("INVALID_ARGUMENT",
                                    "duplicate list name: " + list.name,
                                    prefix + ".name", "unique list name");
            return false;
        }
        std::set<std::string> unique_signals;
        Json checked = Json::array();
        for (size_t j = 0; j < item["signals"].size(); ++j) {
            const Json& value = item["signals"][j];
            const std::string path = prefix + ".signals[" +
                                     std::to_string(j) + "]";
            if (!value.is_string() || value.get<std::string>().empty()) {
                error = list_load_error("INVALID_ARGUMENT",
                                        path + " must be a non-empty string",
                                        path, "final leaf waveform signal path");
                return false;
            }
            const std::string signal = value.get<std::string>();
            if (!unique_signals.insert(signal).second) {
                error = list_load_error("INVALID_ARGUMENT",
                                        "duplicate signal: " + signal,
                                        path, "unique signal path within the list");
                return false;
            }
            if (!npi_fsdb_sig_by_name(xdebug_waveform::g_fsdb_file,
                                      signal.c_str(), nullptr)) {
                error = list_load_error("SIGNAL_NOT_FOUND",
                                        "signal not found: " + signal,
                                        path, "existing final leaf waveform signal path");
                return false;
            }
            list.signals.push_back(signal);
            checked.push_back({{"signal", signal}, {"status", "ok"}});
        }
        lists.push_back(list);
        validation.push_back({{"name", list.name},
                              {"status", "ok"},
                              {"signals", checked}});
    }
    return true;
}

class ListLoadHandler : public EngineActionHandler {
public:
    const char* action_name() const override { return "list.load"; }
    bool needs_design() const override { return false; }
    bool needs_waveform() const override { return true; }

    Json run(const Json& request, EngineActionContext&) const override {
        const Json args = request.value("args", Json::object());
        nlohmann::json loaded;
        std::string load_error;
        if (!load_config_from_args(args, loaded, load_error)) {
            return list_load_error(
                "INVALID_ARGUMENT", load_error,
                args.contains("config_path") ? "args.config_path" : "args.config",
                "inline args.config object or readable args.config_path");
        }
        Json root = Json::parse(loaded.dump());
        std::vector<xdebug_waveform::SignalList> lists;
        Json validation;
        Json error;
        if (!parse_lists(root, lists, validation, error)) return error;
        const std::string mode = args.value("mode", std::string("replace"));
        xdebug_waveform::ListManager manager;
        std::string store_error;
        if (!manager.load_lists(xdebug_waveform::g_session_id,
                                lists, mode, store_error)) {
            return list_load_error("CONFIG_STORE_ERROR", store_error,
                                   "args.mode", "replace or append");
        }
        Json names = Json::array();
        for (const auto& list : lists) names.push_back(list.name);
        return Json{{"summary", {{"loaded", lists.size()}, {"mode", mode}}},
                    {"lists", names},
                    {"validation", validation}};
    }
};

}  // namespace

std::unique_ptr<EngineActionHandler> make_list_load_handler() {
    return std::unique_ptr<EngineActionHandler>(new ListLoadHandler);
}

}  // namespace xdebug_design
