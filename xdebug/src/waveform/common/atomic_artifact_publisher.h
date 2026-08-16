#pragma once

#include <cstdint>
#include <functional>
#include <iosfwd>
#include <string>
#include <vector>

namespace xdebug_waveform {

struct AtomicArtifact {
    using Writer = std::function<bool(std::ostream&, std::string&)>;

    AtomicArtifact(const std::string& target, const Writer& write)
        : target_path(target), writer(write) {}

    std::string target_path;
    Writer writer;
    std::uint64_t bytes = 0;
};

// Publish a group of regular files with create-new semantics. All artifacts
// must share one parent directory. On every reported failure, published names
// and temporary files are rolled back before this function returns.
bool publish_atomic_artifact_set(std::vector<AtomicArtifact>& artifacts,
                                 std::string& error);

}  // namespace xdebug_waveform
