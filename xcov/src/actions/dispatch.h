#pragma once

#include "actions/catalog.h"
#include "session/session.h"

#include <json.hpp>

namespace xcov {

class Dispatcher {
public:
    nlohmann::json dispatch(const nlohmann::json& req);

private:
    nlohmann::json handle(const ActionContract& contract,
                          const nlohmann::json& req);
    nlohmann::json action_actions(const nlohmann::json& req);
    nlohmann::json action_schema(const nlohmann::json& req);
    nlohmann::json action_session_open(const nlohmann::json& req);
    nlohmann::json action_session_status(const nlohmann::json& req);
    nlohmann::json action_session_close(const nlohmann::json& req);
    nlohmann::json action_tests_list(const nlohmann::json& req);
    nlohmann::json action_metrics_list(const nlohmann::json& req);
    nlohmann::json action_scope(const nlohmann::json& req);
    nlohmann::json action_code_coverage(const nlohmann::json& req);
    nlohmann::json action_functional(const nlohmann::json& req);
    nlohmann::json action_assert(const nlohmann::json& req);
    nlohmann::json action_export(const nlohmann::json& req);
    nlohmann::json action_exclude(const nlohmann::json& req);
    nlohmann::json action_export_exclude(const nlohmann::json& req);
    nlohmann::json action_csv_export(const nlohmann::json& req);
    nlohmann::json action_csv_compile(const nlohmann::json& req);
    nlohmann::json action_exclude_container(const nlohmann::json& req);
    nlohmann::json action_csv_validate(const nlohmann::json& req);
    nlohmann::json action_csv_apply(const nlohmann::json& req);
    nlohmann::json action_csv_format(const nlohmann::json& req);

    Session& session(const nlohmann::json& req);

    SessionManager sessions_;
};

} // namespace xcov
