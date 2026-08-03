#pragma once

#include "action_resource_scope.h"
#include "contract_bound_request.h"

#include "json.hpp"

#include <string>

namespace xdebug_waveform { struct AnalysisCacheError; }

namespace xdebug_design {

using Json = nlohmann::ordered_json;

// Unified action handler interface.

class EngineActionHandler {
public:
    virtual ~EngineActionHandler() = default;

    virtual const char* action_name() const = 0;
    virtual bool needs_design() const = 0;
    virtual bool needs_waveform() const = 0;
    virtual Json run(
        ContractBoundRequest& request,
        EngineActionContext& ctx) const = 0;

    // Compact XOUT rendering is deliberately owned by the handler layer.
    // The base implementation covers ordinary summary/data responses; handlers
    // override this method for domain-specific source windows and tables.
    virtual std::string render_xout(const Json& response) const;
};

std::string render_tabular_xout(const std::string& action,
                                const Json& response);

Json make_handler_error(const std::string& code, const std::string& message);
Json make_handler_error(const std::string& code, const std::string& message,
                        const Json& details);
Json make_handler_error_from_message(const std::string& message);
Json make_analysis_cache_error(
    const xdebug_waveform::AnalysisCacheError& error);

} // namespace xdebug_design
