#pragma once

#include <string>
#include <vector>

namespace xcov {

struct ActionContract {
    std::string name;
    std::string handler;
    bool needs_session = false;
    std::string use_when;
    std::string do_not_use_when;
};

/// Runtime action catalog loaded from schemas_data/v1/actions.json.
class ActionCatalog {
public:
    static const ActionCatalog& instance();

    bool has(const std::string& name) const;
    const ActionContract& get(const std::string& name) const;
    const std::vector<ActionContract>& all() const { return actions_; }

private:
    ActionCatalog();
    std::vector<ActionContract> actions_;
};

} // namespace xcov
