#include "trace_engine.h"
#include "../ast/ast_extractor.h"
#include "../control_dep/control_dep.h"

#include "json.hpp"

#include <algorithm>
#include <cctype>
#include <cstdio>
#include <cstring>
#include <set>
#include <sstream>

#include "npi_L1.h"
#include "npi_hdl.h"
#include "npi_util_basic.h"

namespace xdebug_design {

using json = nlohmann::json;

static std::string mode_name(TraceMode mode) {
    return mode == TraceMode::Driver ? "driver" : "load";
}

static bool is_signal_type(int type) {
    return type == npiNet || type == npiReg || type == npiBitVar || type == npiPort;
}

static bool is_select_type(int type, const char* name) {
    return type == npiPartSelect || type == npiBitSelect || (name && strchr(name, '['));
}

static void record_internal_json_failure(TraceResult& result,
                                         const std::string& stage,
                                         const std::string& artifact_kind,
                                         size_t index) {
    result.internal_json_parse_failed = true;
    for (auto& diagnostic : result.diagnostics) {
        if (diagnostic.stage == stage &&
            diagnostic.artifact_kind == artifact_kind) {
            diagnostic.failure_count++;
            return;
        }
    }
    TraceDiagnostic diagnostic;
    diagnostic.stage = stage;
    diagnostic.artifact_kind = artifact_kind;
    diagnostic.first_index = index;
    diagnostic.failure_count = 1;
    result.diagnostics.push_back(diagnostic);
}

static json parse_internal_json(const std::string& text,
                                TraceResult& result,
                                const std::string& stage,
                                const std::string& artifact_kind,
                                size_t index) {
    if (text.empty()) {
        record_internal_json_failure(
            result, stage, artifact_kind, index);
        return json::object();
    }
    try {
        return json::parse(text);
    } catch (...) {
        record_internal_json_failure(
            result, stage, artifact_kind, index);
        return json::object();
    }
}

static json trace_diagnostics_json(const TraceResult& result) {
    json diagnostics = json::array();
    for (const auto& diagnostic : result.diagnostics) {
        diagnostics.push_back({
            {"code", diagnostic.code},
            {"stage", diagnostic.stage},
            {"artifact_kind", diagnostic.artifact_kind},
            {"first_index", diagnostic.first_index},
            {"failure_count", diagnostic.failure_count},
            {"message", diagnostic.message},
        });
    }
    return diagnostics;
}

static void add_unique_string(std::vector<std::string>& values, const std::string& value) {
    if (value.empty()) return;
    if (std::find(values.begin(), values.end(), value) == values.end()) {
        values.push_back(value);
    }
}

static bool contains_unknown_expression(const json& node) {
    if (node.is_object()) {
        const std::string kind = node.value("kind", "");
        if (kind == "unknown" ||
            (kind == "operation" && node.value("op", "") == "unknown")) {
            return true;
        }
        for (const auto& item : node.items()) {
            if (contains_unknown_expression(item.value())) return true;
        }
    } else if (node.is_array()) {
        for (const auto& item : node) {
            if (contains_unknown_expression(item)) return true;
        }
    }
    return false;
}

TraceResult TraceEngine::trace(const std::string& signal, TraceMode mode, const TraceOptions& options) {
    TraceResult result;
    if (mode == TraceMode::Driver) {
        result = trace_driver(signal);
    } else {
        result = trace_load(signal);
    }
    apply_options(result, options);
    finalize_ai_metadata(result);
    return result;
}

TraceResult TraceEngine::trace_driver(const std::string& signal) {
    TraceResult result;
    result.query = signal;
    result.mode = mode_name(TraceMode::Driver);

    npiHandle sig = npi_handle_by_name(signal.c_str(), NULL);
    if (!sig) {
        result.error = "Signal not found: " + signal;
        result.ok = false;
        return result;
    }

    drvLoadStmtVec_t trace_results;
    int rc = npi_trace_driver_by_hdl2(sig, trace_results, true, NULL, trcOptionDefault);
    npi_release_handle(sig);

    if (rc <= 0 || trace_results.empty()) {
        return result;
    }

    for (const auto& drv : trace_results) {
        npiHandle stmt = drv.useHdl;
        if (stmt) {
            int stmt_type = npi_get(npiType, stmt);
            if (stmt_type == npiIf || stmt_type == npiIfElse) {
                npiHandle condition = npi_handle(npiCondition, stmt);
                if (condition) {
                    extract_condition_deps(condition, stmt, result.control_dependencies);
                    npi_release_handle(condition);
                }
            }
        }

        std::vector<std::string> driver_signals;
        for (npiHandle sig_hdl : drv.sigHdlVec) {
            std::string name = normalize_signal(sig_hdl);
            if (!name.empty()) {
                driver_signals.push_back(name);
            }
        }

        if (driver_signals.empty() && stmt) {
            npiHandle rhs = npi_handle(npiRhs, stmt);
            if (rhs) {
                extract_expr_signals(rhs, driver_signals);
                npi_release_handle(rhs);
            }
        }

        if (driver_signals.empty()) {
            add_unique(result.results, make_statement_record(stmt, "driver", "statement_only"));
            enrich_driver_result(result, stmt, driver_signals);
            continue;
        }

        for (const auto& name : driver_signals) {
            if (!should_skip_signal_name(name)) {
                add_unique(result.results, make_record(name, "driver", stmt, "signal"));
            }
        }
        enrich_driver_result(result, stmt, driver_signals);
    }

    ControlDepTracer control_dep_tracer;
    std::vector<ControlDepInfo> deps = control_dep_tracer.trace_control_deps_with_info(signal.c_str());
    for (const auto& dep : deps) {
        if (should_skip_signal_name(dep.signal_name)) {
            continue;
        }
        TraceRecord record;
        record.signal = dep.signal_name;
        record.role = "control_dependency";
        record.file = dep.file_name;
        record.line = dep.line_no;
        record.source = dep.source_line;
        record.resolution =
            dep.evidence_complete ? "signal" : "signal_without_use_location";
        record.evidence_kind = dep.evidence_kind;
        record.evidence_complete = dep.evidence_complete;
        if (!dep.evidence_complete) {
            result.has_incomplete_evidence = true;
        }
        add_unique(result.control_dependencies, record);
        json edge = {
            {"from", dep.signal_name},
            {"to", result.query},
            {"type", "control_dependency"},
            {"relation", "controls_assignment"},
            {"file", dep.file_name},
            {"line", dep.line_no},
            {"source", dep.source_line},
            {"resolution", record.resolution},
            {"evidence_kind", dep.evidence_kind},
            {"evidence_complete", dep.evidence_complete},
            {"confidence", dep.evidence_complete ? "medium" : "low"}
        };
        result.dependency_edges_json.push_back(edge.dump());
    }

    return result;
}

TraceResult TraceEngine::trace_load(const std::string& signal) {
    TraceResult result;
    result.query = signal;
    result.mode = mode_name(TraceMode::Load);

    drvLoadStmtVec_t trace_results;
    int rc = npi_trace_load2(signal.c_str(), trace_results, true, NULL, trcOptionDefault);
    if (rc <= 0 || trace_results.empty()) {
        return result;
    }

    for (const auto& load : trace_results) {
        npiHandle stmt = load.useHdl;
        bool added_signal = false;

        if (stmt) {
            npiHandle rhs = npi_handle(npiRhs, stmt);
            if (rhs) {
                std::vector<std::string> signals;
                extract_expr_signals(rhs, signals);
                for (const auto& name : signals) {
                    if (!should_skip_signal_name(name)) {
                        add_unique(result.results, make_record(name, "rhs_use", stmt, "signal"));
                        added_signal = true;
                    }
                }
                npi_release_handle(rhs);
            }

            npiHandle lhs = npi_handle(npiLhs, stmt);
            if (lhs) {
                std::vector<std::string> signals;
                extract_expr_signals(lhs, signals);
                for (const auto& name : signals) {
                    if (!should_skip_signal_name(name)) {
                        add_unique(result.results, make_record(name, "lhs_target", stmt, "signal"));
                        added_signal = true;
                    }
                }
                npi_release_handle(lhs);
            }

            npiHandle condition = npi_handle(npiCondition, stmt);
            if (condition) {
                std::vector<std::string> signals;
                extract_expr_signals(condition, signals);
                for (const auto& name : signals) {
                    if (!should_skip_signal_name(name)) {
                        add_unique(result.results, make_record(name, "condition_use", stmt, "signal"));
                        added_signal = true;
                    }
                }
                npi_release_handle(condition);
            }
        }

        if (!added_signal) {
            for (npiHandle sig_hdl : load.sigHdlVec) {
                std::string name = normalize_signal(sig_hdl);
                if (!name.empty() && !should_skip_signal_name(name)) {
                    add_unique(result.results, make_record(name, "load", stmt, "signal"));
                    added_signal = true;
                }
            }
        }

        if (!added_signal) {
            add_unique(result.results, make_statement_record(stmt, "statement_only", "statement_only"));
        }
        enrich_load_result(result, stmt, signal);
    }

    return result;
}

void TraceEngine::enrich_driver_result(TraceResult& result,
                                       npiHandle stmt,
                                       const std::vector<std::string>& driver_signals) const {
    AstExtractor ast;
    json assignment = ast.assignment_to_json(stmt, result.query);
    result.assignments_json.push_back(assignment.dump());

    std::vector<std::string> signals = driver_signals;
    if (signals.empty() && assignment.contains("rhs_signals")) {
        for (const auto& item : assignment["rhs_signals"]) {
            if (item.is_string()) signals.push_back(item.get<std::string>());
        }
    }
    for (const auto& name : signals) {
        if (should_skip_signal_name(name)) continue;
        add_unique_string(result.rhs_signals, name);
        std::string edge_type = assignment.value("kind", "") == "continuous_assignment"
                                    ? "continuous_assignment"
                                    : assignment.value("kind", "") == "procedural_assignment"
                                          ? "procedural_assignment"
                                          : "data_dependency";
        json loc = assignment.value("location", json::object());
        json edge = {
            {"from", name},
            {"to", result.query},
            {"type", "data_dependency"},
            {"assignment_type", edge_type},
            {"role", "driver"},
            {"file", loc.value("file", "")},
            {"line", loc.value("line", 0)},
            {"source", assignment.value("source", "")},
            {"resolution", "signal"},
            {"expr", assignment.value("rhs", json::object())},
            {"confidence", assignment["rhs"].value("kind", "") == "unknown" ? "medium" : "high"}
        };
        result.dependency_edges_json.push_back(edge.dump());
    }
    if (signals.empty()) {
        json loc = assignment.value("location", json::object());
        json edge = {
            {"from", ""},
            {"to", result.query},
            {"type", "statement_only"},
            {"role", "driver"},
            {"file", loc.value("file", "")},
            {"line", loc.value("line", 0)},
            {"source", assignment.value("source", "")},
            {"resolution", "statement_only"},
            {"confidence", "low"}
        };
        result.dependency_edges_json.push_back(edge.dump());
    }
}

void TraceEngine::enrich_load_result(TraceResult& result,
                                     npiHandle stmt,
                                     const std::string& query_signal) const {
    AstExtractor ast;
    json assignment = ast.assignment_to_json(stmt, "");
    result.assignments_json.push_back(assignment.dump());

    auto add_edges_from_expr = [&](npiHandle expr, const std::string& role, const std::string& edge_type) {
        if (!expr) return;
        std::vector<std::string> signals = ast.collect_signal_names(expr);
        for (const auto& name : signals) {
            if (should_skip_signal_name(name)) continue;
            json loc = ast.source_location(stmt);
            json edge = {
                {"from", role == "lhs_target" ? query_signal : name},
                {"to", role == "lhs_target" ? name : query_signal},
                {"type", edge_type},
                {"role", role},
                {"file", loc.value("file", "")},
                {"line", loc.value("line", 0)},
                {"source", ast.decompile(stmt)},
                {"resolution", "signal"},
                {"expr", ast.expr_to_json(expr)},
                {"confidence", "high"}
            };
            result.dependency_edges_json.push_back(edge.dump());
            add_unique_string(result.rhs_signals, name);
        }
    };

    npiHandle rhs = npi_handle(npiRhs, stmt);
    add_edges_from_expr(rhs, "rhs_use", "load_dependency");
    if (rhs) npi_release_handle(rhs);
    npiHandle lhs = npi_handle(npiLhs, stmt);
    add_edges_from_expr(lhs, "lhs_target", "load_dependency");
    if (lhs) npi_release_handle(lhs);
    npiHandle condition = npi_handle(npiCondition, stmt);
    add_edges_from_expr(condition, "condition_use", "control_dependency");
    if (condition) npi_release_handle(condition);
}

void TraceEngine::finalize_ai_metadata(TraceResult& result) const {
    bool has_source = false;
    bool has_unknown_expr = false;
    bool has_statement_only = false;
    for (const auto& record : result.results) {
        if (!record.source.empty()) has_source = true;
        if (record.resolution == "statement_only") has_statement_only = true;
    }
    for (const auto& record : result.control_dependencies) {
        if (!record.source.empty()) has_source = true;
        if (record.resolution == "statement_only") has_statement_only = true;
        if (!record.evidence_complete) result.has_incomplete_evidence = true;
    }
    for (size_t index = 0; index < result.assignments_json.size(); ++index) {
        json assignment = parse_internal_json(
            result.assignments_json[index], result,
            "finalize_assignment", "assignment", index);
        if (assignment.value("kind", "") == "statement_only") has_statement_only = true;
        if (contains_unknown_expression(assignment)) {
            has_unknown_expr = true;
        }
        if (!assignment.value("source", "").empty()) has_source = true;
    }
    result.has_statement_only = has_statement_only;
    result.has_unknown_expr = has_unknown_expr;
    result.analysis_complete = trace_analysis_complete({
        result.ok && result.error.empty(),
        result.truncated,
        result.has_statement_only,
        result.has_unknown_expr,
        result.has_incomplete_evidence,
        result.internal_json_parse_failed
    });
    if (!result.ok || !result.error.empty()) {
        result.confidence = "unknown";
        result.confidence_reason = "trace failed";
    } else if (result.internal_json_parse_failed) {
        result.confidence = "low";
        result.confidence_reason =
            "internal trace evidence could not be decoded";
    } else if (has_statement_only) {
        result.confidence = "low";
        result.confidence_reason = "trace contains unresolved statement_only records";
    } else if (result.has_incomplete_evidence) {
        result.confidence = "low";
        result.confidence_reason =
            "control dependency use-site evidence is incomplete";
    } else if (!result.results.empty() && has_source && !has_unknown_expr) {
        result.confidence = "high";
        result.confidence_reason = "exact signal references, source locations, and structured expressions were resolved";
    } else if (!result.results.empty() && has_source) {
        result.confidence = "medium";
        result.confidence_reason = "source locations were resolved but some expression nodes are unknown";
    } else if (!result.results.empty()) {
        result.confidence = "medium";
        result.confidence_reason = "signal references were resolved without complete source expression metadata";
    } else {
        result.confidence = "unknown";
        result.confidence_reason = "no reliable trace result was resolved";
    }
    result.resolution = has_statement_only
        ? "statement_only"
        : result.has_incomplete_evidence
              ? "signal_without_use_location"
              : (!result.results.empty() ? "signal" : "unknown");
}

void TraceEngine::apply_options(TraceResult& result, const TraceOptions& options) const {
    auto filter_records = [&](std::vector<TraceRecord>& records) {
        std::vector<TraceRecord> filtered;
        for (const auto& record : records) {
            if (!options.role.empty() && record.role != options.role) {
                continue;
            }
            if (options.no_statement_only && record.resolution == "statement_only") {
                continue;
            }
            filtered.push_back(record);
        }
        if (options.limit > 0 && (int)filtered.size() > options.limit) {
            filtered.resize(options.limit);
            result.truncated = true;
        }
        records.swap(filtered);
    };

    filter_records(result.results);
    filter_records(result.control_dependencies);

}

void TraceEngine::extract_expr_signals(npiHandle expr, std::vector<std::string>& signals) const {
    if (!expr) return;

    int type = npi_get(npiType, expr);
    if (type == npiParameter || type == npiConstant) {
        return;
    }

    std::string name = normalize_signal(expr);
    if (!name.empty()) {
        signals.push_back(name);
        return;
    }

    npiHandle operand_iter = npi_iterate(npiOperand, expr);
    if (operand_iter) {
        npiHandle operand;
        while ((operand = npi_scan(operand_iter)) != NULL) {
            extract_expr_signals(operand, signals);
            npi_release_handle(operand);
        }
        npi_release_handle(operand_iter);
    }
}

void TraceEngine::extract_condition_deps(npiHandle condition,
                                         npiHandle stmt,
                                         std::vector<TraceRecord>& deps) const {
    std::vector<std::string> signals;
    extract_expr_signals(condition, signals);
    for (const auto& name : signals) {
        if (!should_skip_signal_name(name)) {
            TraceRecord record =
                make_record(name, "control_dependency", stmt, "signal");
            record.evidence_kind = "control_condition_use";
            record.evidence_complete =
                !record.file.empty() && record.line > 0 && !record.source.empty();
            if (!record.evidence_complete) {
                record.resolution = "signal_without_use_location";
            }
            add_unique(deps, record);
        }
    }
}

TraceRecord TraceEngine::make_record(const std::string& signal,
                                     const std::string& role,
                                     npiHandle stmt,
                                     const std::string& resolution) const {
    TraceRecord record;
    record.signal = signal;
    record.role = role;
    record.resolution = resolution;
    record.line = 0;
    if (stmt) {
        record.line = npi_get(npiLineNo, stmt);
        const char* file = npi_get_str(npiFile, stmt);
        if (file) {
            record.file = file;
            record.source = source_line(record.file, record.line);
        }
    }
    return record;
}

TraceRecord TraceEngine::make_statement_record(npiHandle stmt,
                                               const std::string& role,
                                               const std::string& resolution) const {
    std::string display;
    if (stmt) {
        const char* info = npi_ut_get_hdl_info(stmt, true, false);
        if (info) {
            display = info;
        }
    }
    return make_record(display, role, stmt, resolution);
}

std::string TraceEngine::normalize_signal(npiHandle hdl) const {
    if (!hdl) return "";

    int type = npi_get(npiType, hdl);
    if (type == npiParameter || type == npiConstant) {
        return "";
    }

    const char* raw_name = npi_get_str(npiFullName, hdl);

    if (is_select_type(type, raw_name)) {
        npiHandle parent = npi_handle(npiParent, hdl);
        if (parent) {
            const char* parent_name = npi_get_str(npiFullName, parent);
            std::string normalized = parent_name ? parent_name : "";
            npi_release_handle(parent);
            if (!normalized.empty()) {
                return normalized;
            }
        }
    }

    if (is_signal_type(type) || type == npiOperation || type == npiRefObj) {
        return raw_name ? raw_name : "";
    }

    return "";
}

std::string TraceEngine::source_line(const std::string& file, int line) const {
    if (file.empty() || line <= 0) {
        return "";
    }
    const stringVec_t* lines = npi_util_text_get_file_line_vec(const_cast<char*>(file.c_str()));
    if (!lines || line > (int)lines->size()) {
        return "";
    }
    std::string text = (*lines)[line - 1];
    while (!text.empty() &&
           (text.back() == '\n' || text.back() == '\r' || text.back() == ' ' || text.back() == '\t')) {
        text.pop_back();
    }
    return text;
}

bool TraceEngine::should_skip_signal_name(const std::string& name) const {
    if (name.empty()) return true;
    std::string lower;
    lower.reserve(name.size());
    for (char c : name) {
        lower.push_back((char)std::tolower((unsigned char)c));
    }
    return lower.find("clk") != std::string::npos ||
           lower.find("clock") != std::string::npos ||
           lower.find("rst") != std::string::npos ||
           lower.find("reset") != std::string::npos;
}

void TraceEngine::add_unique(std::vector<TraceRecord>& records, const TraceRecord& record) const {
    auto same = [&](const TraceRecord& existing) {
        return existing.signal == record.signal &&
               existing.role == record.role &&
               existing.file == record.file &&
               existing.line == record.line &&
               existing.resolution == record.resolution;
    };
    if (std::find_if(records.begin(), records.end(), same) == records.end()) {
        records.push_back(record);
    }
}

std::string TraceEngine::render_text(const TraceResult& result) const {
    std::ostringstream out;
    out << "=== " << (result.mode == "driver" ? "Driver" : "Load") << " Tracing ===\n";
    out << "Signal: " << result.query << "\n";

    if (!result.error.empty()) {
        out << "ERROR: " << result.error << "\n";
        return out.str();
    }

    if (result.results.empty()) {
        out << "(no " << result.mode << "s found)\n";
    } else {
        int idx = 1;
        for (const auto& record : result.results) {
            out << "[" << idx++ << "] " << record.signal << "\n";
            out << "    role: " << record.role << "\n";
            out << "    resolution: " << record.resolution << "\n";
            if (!record.file.empty() || record.line > 0) {
                out << "    location: " << record.file << ":" << record.line << "\n";
            }
            if (!record.source.empty()) {
                out << "    source: " << record.source << "\n";
            }
        }
    }

    if (result.mode == "driver") {
        out << "=== Control Dependency Tracing ===\n";
        if (result.control_dependencies.empty()) {
            out << "(no control dependencies found)\n";
        } else {
            int idx = 1;
            for (const auto& record : result.control_dependencies) {
                out << "[" << idx++ << "] " << record.signal << "\n";
                out << "    role: " << record.role << "\n";
                out << "    resolution: " << record.resolution << "\n";
                if (!record.file.empty() || record.line > 0) {
                    out << "    location: " << record.file << ":" << record.line << "\n";
                }
                if (!record.source.empty()) {
                    out << "    source: " << record.source << "\n";
                }
            }
        }
    }

    return out.str();
}

std::string TraceEngine::render_json(const TraceResult& result) const {
    auto record_to_json = [](const TraceRecord& record) {
        json out = {
            {"signal", record.signal},
            {"role", record.role},
            {"file", record.file},
            {"line", record.line},
            {"source", record.source},
            {"resolution", record.resolution}
        };
        if (!record.evidence_kind.empty()) {
            out["evidence_kind"] = record.evidence_kind;
            out["evidence_complete"] = record.evidence_complete;
        }
        return out;
    };

    json payload;
    payload["ok"] = result.ok && result.error.empty();
    payload["query"] = result.query;
    payload["mode"] = result.mode;
    payload["results"] = json::array();
    for (const auto& record : result.results) {
        payload["results"].push_back(record_to_json(record));
    }
    payload["control_dependencies"] = json::array();
    for (const auto& record : result.control_dependencies) {
        payload["control_dependencies"].push_back(record_to_json(record));
    }
    payload["result_count"] = result.results.size();
    payload["scan_complete"] = result.ok && result.error.empty();
    payload["analysis_complete"] = result.analysis_complete;
    payload["truncation_scopes"] = json::array();
    if (result.internal_json_parse_failed) {
        payload["truncation_scopes"].push_back("analysis_internal_json");
    }
    if (!result.analysis_complete &&
        (result.has_statement_only || result.has_unknown_expr ||
         result.has_incomplete_evidence || !result.ok || !result.error.empty())) {
        payload["truncation_scopes"].push_back(
            "analysis_trace_resolution");
    }
    payload["has_statement_only"] = result.has_statement_only;
    payload["has_unknown_expr"] = result.has_unknown_expr;
    payload["has_incomplete_evidence"] = result.has_incomplete_evidence;
    payload["diagnostics"] = trace_diagnostics_json(result);

    std::set<std::string> roles;
    std::set<std::string> files;
    for (const auto& record : result.results) {
        if (!record.role.empty()) roles.insert(record.role);
        if (!record.file.empty()) files.insert(record.file);
    }
    for (const auto& record : result.control_dependencies) {
        if (!record.role.empty()) roles.insert(record.role);
        if (!record.file.empty()) files.insert(record.file);
    }
    payload["roles"] = json::array();
    for (const auto& role : roles) payload["roles"].push_back(role);
    payload["files"] = json::array();
    for (const auto& file : files) payload["files"].push_back(file);

    if (!result.error.empty()) {
        payload["error"] = result.error;
        payload["status"] = "trace_error";
    }
    return payload.dump(2) + "\n";
}

std::string TraceEngine::render_ai_json(TraceResult& result) const {
    json payload = json::parse(render_json(result));
    payload["rhs_signals"] = json::array();
    for (const auto& name : result.rhs_signals) {
        payload["rhs_signals"].push_back(name);
    }
    payload["assignments"] = json::array();
    for (size_t index = 0; index < result.assignments_json.size(); ++index) {
        json assignment = parse_internal_json(
            result.assignments_json[index], result,
            "render_assignment", "assignment", index);
        if (!assignment.empty()) payload["assignments"].push_back(assignment);
    }
    if (!payload["assignments"].empty()) {
        payload["assignment"] = payload["assignments"][0];
    }
    payload["dependency_edges"] = json::array();
    std::set<std::string> seen_edges;
    for (size_t index = 0; index < result.dependency_edges_json.size(); ++index) {
        json edge = parse_internal_json(
            result.dependency_edges_json[index], result,
            "render_dependency_edge", "dependency_edge", index);
        if (edge.empty()) continue;
        std::string key = edge.dump();
        if (seen_edges.insert(key).second) {
            payload["dependency_edges"].push_back(edge);
        }
    }
    payload["resolution"] = result.resolution;
    if (result.internal_json_parse_failed) {
        result.analysis_complete = false;
        result.confidence = "low";
        result.confidence_reason =
            "internal trace evidence could not be decoded";
        payload["analysis_complete"] = false;
        json scopes = payload.value("truncation_scopes", json::array());
        if (std::find(scopes.begin(), scopes.end(),
                      json("analysis_internal_json")) == scopes.end()) {
            scopes.push_back("analysis_internal_json");
        }
        payload["truncation_scopes"] = scopes;
        payload["diagnostics"] = trace_diagnostics_json(result);
    }
    payload["confidence"] = result.confidence;
    payload["confidence_reason"] = result.confidence_reason;
    return payload.dump(2) + "\n";
}

} // namespace xdebug_design
