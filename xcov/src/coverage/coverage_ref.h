#pragma once

#include <json.hpp>

#include <string>

namespace xcov {

/// Canonical readable identity used for session-local coverage references.
nlohmann::json coverage_identity(const nlohmann::json& row);

/// "xcovref.v1:" + sha256(canonical identity JSON).
std::string coverage_ref(const nlohmann::json& row);

/// URG-compatible npi type name for one metric key.
std::string coverage_type_for_metric(const std::string& metric);

} // namespace xcov
