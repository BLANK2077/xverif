#include "actions/catalog.h"

#include "core/errors.h"
#include "core/fs.h"

#include <json.hpp>

#include <algorithm>

namespace xcov {

ActionCatalog::ActionCatalog() {
    const nlohmann::json document =
        nlohmann::json::parse(read_file(schema_path("actions.json")));
    if (!document.contains("actions") || !document.at("actions").is_array()) {
        throw Error("SCHEMA_DATA_INVALID", "action catalog lacks actions");
    }
    for (const auto& item : document.at("actions")) {
        ActionContract contract;
        contract.name = item.value("name", std::string());
        contract.handler = item.value("handler", std::string());
        contract.needs_session = item.value("needs_session", false);
        contract.use_when = item.value("use_when", std::string());
        contract.do_not_use_when = item.value("do_not_use_when", std::string());
        if (contract.name.empty()) {
            throw Error("SCHEMA_DATA_INVALID", "action catalog entry lacks a name");
        }
        actions_.push_back(std::move(contract));
    }
    std::sort(actions_.begin(), actions_.end(),
              [](const ActionContract& a, const ActionContract& b) {
                  return a.name < b.name;
              });
}

const ActionCatalog& ActionCatalog::instance() {
    static const ActionCatalog catalog;
    return catalog;
}

bool ActionCatalog::has(const std::string& name) const {
    return std::any_of(actions_.begin(), actions_.end(),
                       [&](const ActionContract& item) { return item.name == name; });
}

const ActionContract& ActionCatalog::get(const std::string& name) const {
    auto it = std::find_if(actions_.begin(), actions_.end(),
                           [&](const ActionContract& item) {
                               return item.name == name;
                           });
    if (it == actions_.end()) {
        throw Error("UNKNOWN_ACTION", "unknown action", {{"action", name}});
    }
    return *it;
}

} // namespace xcov
