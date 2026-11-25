#pragma once

#include "coverage/ucapi_backend.h"
#include "exclusion/el_parser.h"

#include <json.hpp>

#include <map>
#include <memory>
#include <string>

namespace xcov {

struct ExclusionRecord {
    std::string kind;  // code / functional / assertion / container
    std::string coverage_ref;
    std::string reason;
    std::string scope;
    std::string metric;
    std::string name;
    std::string full_name;
};

struct Session {
    std::string session_id;
    std::string vdb;
    std::string cache_dir;
    std::string exclusion_policy = "default";
    std::string worker = "ucapi";
    std::unique_ptr<UcapiBackend> backend;
    std::map<std::string, ExclusionRecord> exclusion_records;
    std::vector<ElEntry> loaded_el_entries;
};

class SessionManager {
public:
    Session& open(const std::string& name,
                  const std::string& vdb,
                  const std::string& cache_dir,
                  const std::string& exclusion_policy);

    Session& get(const std::string& session_id);
    void close(const std::string& session_id);
    bool contains(const std::string& session_id) const;
    std::size_t size() const { return sessions_.size(); }

private:
    std::map<std::string, std::unique_ptr<Session>> sessions_;
};

} // namespace xcov
