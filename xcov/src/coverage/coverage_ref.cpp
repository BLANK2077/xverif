#include "coverage/coverage_ref.h"

#include "core/sha256.h"

namespace xcov {

std::string coverage_type_for_metric(const std::string& metric) {
    if (metric == "line") return "npiCovStmtBin";
    if (metric == "toggle") return "npiCovToggleBin";
    if (metric == "branch") return "npiCovBranchBin";
    if (metric == "condition") return "npiCovConditionBin";
    if (metric == "fsm") return "npiCovTransBin";
    if (metric == "assert") return "npiCovAssert";
    if (metric == "functional") return "npiCovCoverBin";
    return "unknown";
}

nlohmann::json coverage_identity(const nlohmann::json& row) {
    nlohmann::json identity = nlohmann::json::object();
    for (const char* key : {"metric", "scope", "type", "full_name", "name",
                            "toggle_bit", "toggle_transition", "branch",
                            "branch_bin", "condition", "condition_bin", "fsm",
                            "assert_kind", "assert_object", "covergroup",
                            "coverpoint", "cross", "bin"}) {
        identity[key] = row.contains(key) ? row.at(key) : nlohmann::json(nullptr);
    }
    if (row.contains("evidence") && row.at("evidence").is_object()) {
        const nlohmann::json& evidence = row.at("evidence");
        identity["evidence"] = {
            {"file", evidence.contains("file") ? evidence.at("file")
                                               : nlohmann::json(nullptr)},
            {"line", evidence.contains("line") ? evidence.at("line")
                                               : nlohmann::json(nullptr)},
        };
    } else {
        identity["evidence"] = nullptr;
    }
    return identity;
}

std::string coverage_ref(const nlohmann::json& row) {
    const std::string payload = coverage_identity(row).dump();
    return "xcovref.v1:" + sha256_hex(payload);
}

} // namespace xcov
