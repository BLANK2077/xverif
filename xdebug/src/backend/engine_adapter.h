#pragma once

#include "api/json_types.h"

#include <string>

namespace xdebug {

class EngineAdapter {
public:
    explicit EngineAdapter(const std::string& executable_dir);

    // Invoke the unified xdebug-engine subprocess.
    bool invoke(const Json& public_request,
                const Json& resolved_target,
                const Json& observability,
                Json& response,
                Json& error) const;

private:
    std::string engine_path() const;
    std::string engine_workdir() const;
    std::string executable_dir_;
};

} // namespace xdebug
