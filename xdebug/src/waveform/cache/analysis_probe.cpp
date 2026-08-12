#include "analysis_probe.h"

#include "json.hpp"

#include <cstdlib>
#include <fcntl.h>
#include <iomanip>
#include <limits.h>
#include <sstream>
#include <sys/stat.h>
#include <utility>
#include <unistd.h>

namespace xdebug_waveform {
namespace {

std::string key_summary(const std::string& material) {
    std::uint64_t hash = 1469598103934665603ULL;
    for (unsigned char byte : material) {
        hash ^= static_cast<std::uint64_t>(byte);
        hash *= 1099511628211ULL;
    }
    std::ostringstream out;
    out << std::hex << std::setw(16) << std::setfill('0') << hash;
    return out.str();
}

bool append_private_line(const std::string& path, const std::string& line) {
    const int fd = open(path.c_str(), O_WRONLY | O_CREAT | O_APPEND | O_CLOEXEC, 0600);
    if (fd < 0) return false;
    // open(..., 0600) only controls newly-created files. Reassert the test
    // probe contract when a caller deliberately reuses an existing path.
    if (fchmod(fd, 0600) != 0) {
        close(fd);
        return false;
    }
    const std::string payload = line + "\n";
    std::size_t offset = 0;
    while (offset < payload.size()) {
        const ssize_t written = write(fd, payload.data() + offset, payload.size() - offset);
        if (written <= 0) {
            close(fd);
            return false;
        }
        offset += static_cast<std::size_t>(written);
    }
    close(fd);
    return true;
}

bool path_is_below(const std::string& path, const std::string& directory) {
    return path.size() > directory.size() &&
           path.compare(0, directory.size(), directory) == 0 &&
           path[directory.size()] == '/';
}

}  // namespace

std::string analysis_probe_path_from_environment() {
    const char* test_tmpdir = std::getenv("XVERIF_TEST_TMPDIR");
    if (test_tmpdir == nullptr || test_tmpdir[0] == '\0') return std::string();
    const char* value = std::getenv("XDEBUG_TEST_ANALYSIS_PROBE_PATH");
    if (value == nullptr || value[0] == '\0') return std::string();

    char canonical_root[PATH_MAX];
    if (realpath(test_tmpdir, canonical_root) == nullptr) return std::string();
    const std::string requested(value);
    const std::size_t separator = requested.find_last_of('/');
    if (separator == std::string::npos || separator + 1 == requested.size())
        return std::string();
    const std::string parent = separator == 0
        ? std::string("/") : requested.substr(0, separator);
    char canonical_parent[PATH_MAX];
    if (realpath(parent.c_str(), canonical_parent) == nullptr)
        return std::string();
    const std::string root(canonical_root);
    const std::string resolved_parent(canonical_parent);
    if (resolved_parent != root && !path_is_below(resolved_parent, root))
        return std::string();

    struct stat info {};
    if (lstat(requested.c_str(), &info) == 0) {
        char canonical_target[PATH_MAX];
        if (realpath(requested.c_str(), canonical_target) == nullptr ||
            !path_is_below(canonical_target, root))
            return std::string();
    }
    return requested;
}

AnalysisProbe::AnalysisProbe(std::string path) : path_(std::move(path)) {}

bool AnalysisProbe::enabled() const {
    return !path_.empty();
}

void AnalysisProbe::record(const std::string& event,
                           const std::string& protocol,
                           const std::string& key_material,
                           const AnalysisProbeMetrics& metrics) {
    if (!enabled()) return;

    scanner_invocations_ += metrics.scanner_delta;
    if (event == "hit") ++hits_;
    if (event == "miss") ++misses_;
    if (event == "evict") ++evictions_;
    ++access_sequence_;

    nlohmann::ordered_json row = {
        {"schema", "xdebug.analysis-probe.v1"},
        {"event", event},
        {"protocol", protocol},
        {"key_summary", key_summary(key_material)},
        {"pid", static_cast<int>(getpid())},
        {"scanner_invocations", scanner_invocations_},
        {"entry_count", metrics.entry_count},
        {"index_count", metrics.index_count},
        {"hits", hits_},
        {"misses", misses_},
        {"evictions", evictions_},
        {"resident_bytes", metrics.resident_bytes},
        {"build_bytes", metrics.build_bytes},
        {"access_sequence", access_sequence_},
    };
    (void)append_private_line(path_, row.dump());
}

AnalysisProbe& analysis_probe() {
    static AnalysisProbe probe(analysis_probe_path_from_environment());
    return probe;
}

}  // namespace xdebug_waveform
