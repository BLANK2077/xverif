#include "core/logging.h"

#include "core/fs.h"

#include <cstdlib>
#include <ctime>
#include <fstream>
#include <mutex>
#include <sys/stat.h>
#include <unistd.h>

namespace xcov {

namespace {

std::mutex g_mutex;

bool truthy_disabled(const char* value) {
    if (value == nullptr) return false;
    const std::string text(value);
    return text == "0" || text == "false" || text == "no" || text == "off";
}

std::string env_or_empty(const char* name) {
    const char* value = std::getenv(name);
    return value == nullptr ? std::string() : std::string(value);
}

void ensure_directories(const std::string& path) {
    std::string current;
    for (std::size_t index = 0; index < path.size(); ++index) {
        current.push_back(path[index]);
        if (path[index] == '/' && current.size() > 1) {
            ::mkdir(current.c_str(), 0755);
        }
    }
    if (!path.empty()) ::mkdir(path.c_str(), 0755);
}

} // namespace

bool logging_enabled() {
    return !truthy_disabled(std::getenv("XVERIF_XCOV_LOG"));
}

std::string log_root() {
    const std::string override_dir = env_or_empty("XVERIF_XCOV_LOG_DIR");
    if (!override_dir.empty()) return override_dir;
    const std::string test_tmp = env_or_empty("XVERIF_TEST_TMPDIR");
    if (!test_tmp.empty()) return test_tmp + "/.xverif/xcov";
    const std::string home = env_or_empty("HOME");
    return (home.empty() ? std::string(".") : home) + "/.xverif/xcov";
}

void log_event(const std::string& kind,
               const std::string& session_id,
               const std::string& action,
               bool ok,
               long elapsed_ms,
               const nlohmann::json& detail) {
    if (!logging_enabled()) return;
    try {
        std::lock_guard<std::mutex> lock(g_mutex);
        const std::string root = log_root() + "/backend/sessions/" +
                                 (session_id.empty() ? "adhoc" : session_id) + "/logs";
        ensure_directories(root);
        std::ofstream out(root + "/" + kind + ".ndjson", std::ios::app);
        if (!out) return;
        nlohmann::json record = {
            {"ts", static_cast<long long>(std::time(nullptr))},
            {"kind", kind},
            {"session_id", session_id},
            {"action", action},
            {"ok", ok},
            {"elapsed_ms", elapsed_ms},
            {"detail", detail},
            {"pid", static_cast<long long>(::getpid())},
        };
        out << record.dump() << "\n";
    } catch (...) {
        // Observability must never break a request.
    }
}

} // namespace xcov
