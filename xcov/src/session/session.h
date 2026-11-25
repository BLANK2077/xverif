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
    // CSV identity for container / functional rows.
    std::string target_kind;
    std::string covergroup;
    std::string item;
    std::string bin;
    std::string line;
    std::string source_file;
    bool recursive = false;
};

/// Canonical session-map key for an exclusion reason record. Every mutation
/// path (exclude.*, csv.apply, csv.compile and the remove branches) must use
/// this helper so a later remove/export addresses the same entry.
std::string exclusion_record_key(const ExclusionRecord& record);

struct Session {
    std::string session_id;
    std::string vdb;
    std::string cache_dir;
    std::string exclusion_policy = "default";
    std::string worker = "ucapi";
    std::unique_ptr<UcapiBackend> backend;
    std::map<std::string, ExclusionRecord> exclusion_records;
    std::vector<ElEntry> loaded_el_entries;
    // Python's contract: exclusion reasons are "dirty" until a CSV export or
    // compile persists them. session.close must not silently drop them.
    std::size_t reason_revision = 0;
    std::size_t persisted_reason_revision = 0;

    bool reason_dirty() const {
        return reason_revision != persisted_reason_revision;
    }
    void mark_reason_mutation() { ++reason_revision; }
    void mark_reasons_persisted() {
        persisted_reason_revision = reason_revision;
    }
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
