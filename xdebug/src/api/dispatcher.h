#pragma once

#include "api/json_types.h"
#include "api/action_spec.h"
#include "backend/engine_adapter.h"
#include "session/session_catalog.h"

#include <string>

namespace xdebug {

class Dispatcher {
public:
    explicit Dispatcher(const std::string& executable_dir);
    Json dispatch(const Json& request,
                  const Json& observability = Json::object());
    const std::string& last_xout() const { return last_xout_; }

private:
    Json dispatch_impl(const Json& request, const Json& observability,
                       std::string& session_open_cleanup_token);
    Json handle_session(const Json& request, const std::string& action,
                        const Json& observability,
                        std::string& session_open_cleanup_token);
    Json handle_batch(const Json& request, const Json& observability);
    Json invoke_engine(const Json& request, const Json& resolved_target,
                       const Json& observability);
    Json compensate_failed_session_open(
        const Json& request,
        const std::string& session_id,
        const std::string& ownership_token,
        const Json& observability,
        const std::string& failure_code,
        const std::string& failure_message);
    Json handle_engine_forward(const Json& request, const ActionSpec& spec,
                               const Json& observability);
    bool kill_session_record(const Json& request,
                             const SessionRecord& record,
                             const Json& observability,
                             std::string& backend_code);
    bool cleanup_expired_sessions(const Json& request, Json& removed,
                                  Json& error_response,
                                  const Json& observability);
    Json resource_error(const Json& request, const ActionSpec& spec, const Json& target) const;
    bool resolve_target(const Json& request, Json& target,
                        Json& error_response) const;
    std::string mode_for_target(const Json& target) const;
    EngineAdapter adapter_;
    SessionCatalog sessions_;
    std::string last_xout_;
};

} // namespace xdebug
