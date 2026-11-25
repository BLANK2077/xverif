#pragma once

#include <json.hpp>

#include <cstdint>
#include <string>

namespace xcov {

struct ResourceIdentity {
    std::string kind;  // "file" or "directory"
    std::string hash_version = "sha256-entry-tree-v2";
    std::uint64_t size_bytes = 0;
    std::uint64_t file_count = 0;
    std::uint64_t directory_count = 0;
    std::uint64_t symlink_count = 0;
    std::string sha256;
};

/// Strict v2 identity: unambiguous length-prefixed entry tree hash.
/// Throws Error("RESOURCE_PROVENANCE_MISMATCH") when the resource cannot be
/// hashed or changes mid-traversal.
ResourceIdentity resource_identity(const std::string& path);

/// Validate an optional target.run_manifest against target.vdb.
/// Returns null when no manifest was requested; otherwise the normalized
/// xcov.run-manifest.v2 document plus manifest_path.
/// Throws Error("RESOURCE_PROVENANCE_MISMATCH") on any contract violation.
nlohmann::json validate_run_manifest(const nlohmann::json& target);

} // namespace xcov
