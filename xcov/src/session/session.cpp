#include "session/session.h"

#include "core/errors.h"
#include "core/fs.h"

#include <sys/stat.h>
#include <unistd.h>

namespace xcov {

namespace {

bool is_directory(const std::string& path) {
    struct stat info;
    return ::stat(path.c_str(), &info) == 0 && S_ISDIR(info.st_mode);
}

bool is_writable_directory(const std::string& path) {
    return is_directory(path) && ::access(path.c_str(), W_OK) == 0;
}

} // namespace

std::string exclusion_record_key(const ExclusionRecord& record) {
    if (!record.coverage_ref.empty()) {
        return record.kind + ":ref:" + record.coverage_ref;
    }
    // One formula for every non-ref record: remove/export/compile all address
    // the same entry even when only the CSV identity (covergroup/item/bin) is
    // available.
    return record.kind + ":" + record.scope + "|" + record.metric + "|" +
           record.name + "|" + record.target_kind + "|" + record.covergroup +
           "|" + record.item + "|" + record.bin;
}

Session& SessionManager::open(const std::string& name,
                              const std::string& vdb,
                              const std::string& cache_dir,
                              const std::string& exclusion_policy) {
    if (name.empty()) {
        throw Error("SCHEMA_INVALID", "session name is required",
                    {{"path", "$.args.name"}});
    }
    if (sessions_.find(name) != sessions_.end()) {
        throw Error("SESSION_EXISTS", "coverage session already exists",
                    {{"session_id", name}});
    }
    if (!sessions_.empty()) {
        throw Error("SESSION_CAPACITY_EXCEEDED",
                    "only one live session is allowed per process",
                    {{"capacity", 1},
                     {"live_session_id", sessions_.begin()->first}});
    }
    if (exclusion_policy != "default" && exclusion_policy != "strict") {
        throw Error("SCHEMA_INVALID", "unsupported exclusion_policy",
                    {{"path", "$.args.exclusion_policy"}});
    }
    if (!cache_dir.empty()) {
        if (!is_directory(cache_dir)) {
            throw Error("CACHE_DIR_NOT_FOUND",
                        "cache_dir does not exist; create it before session.open",
                        {{"cache_dir", cache_dir}});
        }
        if (!is_writable_directory(cache_dir)) {
            throw Error("CACHE_DIR_NOT_WRITABLE", "cache_dir is not writable",
                        {{"cache_dir", cache_dir}});
        }
    }
    auto session = std::make_unique<Session>();
    session->session_id = name;
    session->vdb = vdb;
    session->cache_dir = cache_dir;
    session->exclusion_policy = exclusion_policy;
    session->backend = std::make_unique<UcapiBackend>(vdb, exclusion_policy);
    // Force one summary read so a broken backend fails at open time.
    session->backend->summary();
    Session& ref = *session;
    sessions_[name] = std::move(session);
    return ref;
}

Session& SessionManager::get(const std::string& session_id) {
    auto it = sessions_.find(session_id);
    if (it == sessions_.end()) {
        throw Error("SESSION_NOT_FOUND", "coverage session not found",
                    {{"session_id", session_id}});
    }
    return *it->second;
}

void SessionManager::close(const std::string& session_id) {
    auto it = sessions_.find(session_id);
    if (it == sessions_.end()) {
        throw Error("SESSION_NOT_FOUND", "coverage session not found",
                    {{"session_id", session_id}});
    }
    sessions_.erase(it);
}

bool SessionManager::contains(const std::string& session_id) const {
    return sessions_.find(session_id) != sessions_.end();
}

} // namespace xcov
