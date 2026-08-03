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
    // New handlers consume fields through ContractBoundRequest.  The raw-JSON
    // overload remains temporarily as a migration bridge for the 53a handlers;
    // its default bound implementation explicitly assigns the complete args
    // subtree to that legacy parser, so request ownership is still auditable.
    virtual Json run(ContractBoundRequest& request,
                     EngineActionContext& ctx) const;
    virtual Json run(const Json& request,
                     EngineActionContext& ctx) const;

    // XOUT text rendering.  Default recursively renders summary + data tree.
    // Subclasses may override additively:
    //   std::string render_xout(const Json& r) const override {
    //       std::string base = EngineActionHandler::render_xout(r);
    //       // ... append custom sections ...
    //       return base;
    //   }
    virtual std::string render_xout(const Json& response) const;
};

std::string append_common_blocks_xout(std::string text, const Json& response);
Json make_handler_error(const std::string& code, const std::string& message);
Json make_handler_error(const std::string& code, const std::string& message,
                        const Json& details);
Json make_handler_error_from_message(const std::string& message);
Json make_analysis_cache_error(
    const xdebug_waveform::AnalysisCacheError& error);

} // namespace xdebug_design
