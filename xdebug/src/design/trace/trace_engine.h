#pragma once

#include <string>
#include <vector>

#include "npi_hdl.h"
#include "trace_completeness.h"

namespace xdebug_design {

enum class TraceMode {
    Driver,
    Load
};

struct TraceOptions {
    int limit = 0;
    std::string role;
    bool no_statement_only = false;
};

struct TraceRecord {
    std::string signal;
    std::string role;
    std::string file;
    int line = 0;
    std::string source;
    std::string resolution;
    std::string evidence_kind;
    bool evidence_complete = true;
};

struct TraceDiagnostic {
    std::string code = "TRACE_INTERNAL_JSON_PARSE_FAILED";
    std::string stage;
    std::string artifact_kind;
    size_t first_index = 0;
    size_t failure_count = 0;
    std::string message = "internal trace evidence could not be decoded";
};

struct TraceResult {
    std::string query;
    std::string mode;
    std::vector<TraceRecord> results;
    std::vector<TraceRecord> control_dependencies;
    std::vector<std::string> rhs_signals;
    std::vector<std::string> assignments_json;
    std::vector<std::string> dependency_edges_json;
    std::string confidence = "unknown";
    std::string confidence_reason;
    std::string resolution = "unknown";
    std::string error;
    bool ok = true;
    bool truncated = false;
    bool has_statement_only = false;
    bool has_unknown_expr = false;
    bool has_incomplete_evidence = false;
    bool internal_json_parse_failed = false;
    std::vector<TraceDiagnostic> diagnostics;
    bool analysis_complete = true;
};

class TraceEngine {
public:
    TraceResult trace(const std::string& signal, TraceMode mode, const TraceOptions& options = TraceOptions());

    std::string render_text(const TraceResult& result) const;
    std::string render_json(const TraceResult& result) const;
    std::string render_ai_json(TraceResult& result) const;

private:
    TraceResult trace_driver(const std::string& signal);
    TraceResult trace_load(const std::string& signal);
    void apply_options(TraceResult& result, const TraceOptions& options) const;

    void extract_expr_signals(npiHandle expr, std::vector<std::string>& signals) const;
    void enrich_driver_result(TraceResult& result, npiHandle stmt, const std::vector<std::string>& driver_signals) const;
    void enrich_load_result(TraceResult& result, npiHandle stmt, const std::string& query_signal) const;
    void finalize_ai_metadata(TraceResult& result) const;
    void extract_condition_deps(npiHandle condition,
                                npiHandle stmt,
                                std::vector<TraceRecord>& deps) const;
    TraceRecord make_record(const std::string& signal,
                            const std::string& role,
                            npiHandle stmt,
                            const std::string& resolution) const;
    TraceRecord make_statement_record(npiHandle stmt,
                                      const std::string& role,
                                      const std::string& resolution) const;
    std::string normalize_signal(npiHandle hdl) const;
    std::string source_line(const std::string& file, int line) const;
    bool should_skip_signal_name(const std::string& name) const;
    void add_unique(std::vector<TraceRecord>& records, const TraceRecord& record) const;
};

} // namespace xdebug_design
