#include "actions/dispatch.h"

#include "api/protocol.h"
#include "api/schema.h"
#include "core/errors.h"
#include "coverage/coverage_ref.h"
#include "exclusion/csv_parser.h"
#include "exclusion/el_parser.h"
#include "core/fs.h"
#include "core/run_manifest.h"
#include <cstdio>
#include <cstdlib>
#include <cctype>
#include <cmath>
#include <deque>
#include <limits>
#include <sys/stat.h>
#include <unistd.h>
#include <optional>
#include <set>
#include <fstream>
#include <sstream>
#include "core/limits.h"

#include <chrono>

namespace xcov {

namespace {

std::string read_source_line(const std::string& path, int line_no) {
    if (line_no <= 0 || path.empty()) return std::string();
    // Cache the whole file once: gap-heavy exports used to reopen and rescan
    // the source for every uncovered line.
    static std::map<std::string, std::vector<std::string>> cache;
    auto it = cache.find(path);
    if (it == cache.end()) {
        std::vector<std::string> lines;
        std::ifstream in(path);
        if (in) {
            std::string line;
            while (std::getline(in, line)) lines.push_back(line);
        }
        it = cache.emplace(path, std::move(lines)).first;
    }
    if (static_cast<std::size_t>(line_no) > it->second.size()) return std::string();
    std::string line = it->second[static_cast<std::size_t>(line_no) - 1];
    while (!line.empty() && (line.back() == '\r' || line.back() == '\n')) {
        line.pop_back();
    }
    return line;
}

std::string lower_copy(std::string text) {
    for (char& ch : text) {
        ch = static_cast<char>(std::tolower(static_cast<unsigned char>(ch)));
    }
    return text;
}


} // namespace


namespace {

std::string target_session_id(const nlohmann::json& req) {
    if (!req.contains("target") || !req.at("target").is_object()) return std::string();
    return req.at("target").value("session_id", std::string());
}

long elapsed_ms(std::chrono::steady_clock::time_point start) {
    return static_cast<long>(
        std::chrono::duration_cast<std::chrono::milliseconds>(
            std::chrono::steady_clock::now() - start)
            .count());
}

} // namespace

nlohmann::json Dispatcher::dispatch(const nlohmann::json& req) {
    const auto start = std::chrono::steady_clock::now();
    std::string action = req.value("action", std::string());
    try {
        validate_action_token(req.contains("action") ? req.at("action")
                                                     : nlohmann::json());
        const ActionContract& contract = ActionCatalog::instance().get(action);
        SchemaCatalog::instance().validate_request(req);
        const nlohmann::json normalized = normalize_request(req);
        action = normalized.value("action", std::string());
        nlohmann::json rsp = handle(contract, normalized);
        SchemaCatalog::instance().validate_response(action, rsp);
        return rsp;
    } catch (const Error& exc) {
        nlohmann::json rsp = error_response(action, req.value("request_id", "req-unknown"), exc);
        try {
            SchemaCatalog::instance().validate_response(action, rsp);
        } catch (const Error& secondary) {
            if (std::getenv("XCOV_CPP_DEBUG")) {
                std::fprintf(stderr, "error rsp invalid: %s\nrsp=%s\n",
                             secondary.message().c_str(), rsp.dump().c_str());
            }
        }
        (void)elapsed_ms(start);
        return rsp;
    } catch (const std::exception& exc) {
        nlohmann::json rsp = error_response(
            action, req.value("request_id", "req-unknown"),
            Error("INTERNAL_ERROR", exc.what()));
        return rsp;
    }
}

nlohmann::json Dispatcher::handle(const ActionContract& contract,
                                  const nlohmann::json& req) {
    // Exclusion mutations mark aggregates dirty; recompute once before any
    // action that reports scope metrics.
    if (contract.handler == "_scope" || contract.handler == "_code_coverage" ||
        contract.handler == "_metrics_list" || contract.handler == "_export" ||
        contract.handler == "_functional" ||
        contract.handler == "_assert_report") {
        try {
            Session& sess = session(req);
            sess.backend->refresh_metrics();
        } catch (const Error&) {
            // Session may be absent (e.g. schema validation errors); the
            // action handler will raise the authoritative error.
        }
    }
    if (contract.handler == "_actions") return action_actions(req);
    if (contract.handler == "_schema") return action_schema(req);
    if (contract.handler == "_session_open") return action_session_open(req);
    if (contract.handler == "_session_status") return action_session_status(req);
    if (contract.handler == "_session_close") return action_session_close(req);
    if (contract.handler == "_tests_list") return action_tests_list(req);
    if (contract.handler == "_metrics_list") return action_metrics_list(req);
    if (contract.handler == "_scope") return action_scope(req);
    if (contract.handler == "_code_coverage") return action_code_coverage(req);
    if (contract.handler == "_functional") return action_functional(req);
    if (contract.handler == "_assert_report") return action_assert(req);
    if (contract.handler == "_export") return action_export(req);
    if (contract.handler == "_exclude_load" || contract.handler == "_exclude_set" ||
        contract.handler == "_exclude_unload_all") {
        return action_exclude(req);
    }
    if (contract.handler == "_export_exclude") return action_export_exclude(req);
    if (contract.handler == "_exclude_csv_export") return action_csv_export(req);
    if (contract.handler == "_exclude_csv_compile") return action_csv_compile(req);
    if (contract.handler == "_exclude_container") return action_exclude_container(req);
    if (contract.handler == "_exclude_csv_validate") return action_csv_validate(req);
    if (contract.handler == "_exclude_csv_apply") return action_csv_apply(req);
    if (contract.handler == "_exclude_csv_format") return action_csv_format(req);
    throw Error("ACTION_NOT_IMPLEMENTED",
                "action is not implemented by the C++ backend yet",
                {{"action", contract.name}});
}

nlohmann::json Dispatcher::action_actions(const nlohmann::json& req) {
    nlohmann::json items = nlohmann::json::array();
    for (const auto& contract : ActionCatalog::instance().all()) {
        items.push_back({
            {"name", contract.name},
            {"status", "p0"},
            {"api_version", kApiVersion},
            {"use_when", contract.use_when},
            {"do_not_use_when", contract.do_not_use_when},
        });
    }
    return ok_response(req, completeness_summary(items.size(), items.size()),
                       {{"items", items}});
}

nlohmann::json Dispatcher::action_schema(const nlohmann::json& req) {
    const nlohmann::json args = req.value("args", nlohmann::json::object());
    const std::string action = args.value("action", std::string());
    const std::string kind = args.value("kind", std::string("request"));
    if (kind != "request" && kind != "response") {
        throw Error("SCHEMA_INVALID", "kind must be request or response",
                    {{"path", "$.args.kind"}});
    }
    const SchemaCatalog& catalog = SchemaCatalog::instance();
    if (!catalog.has_action(action)) {
        throw Error("UNKNOWN_ACTION", "schema action not found",
                    {{"requested_action", action}});
    }
    const nlohmann::json& schema =
        kind == "request" ? catalog.request_schema(action)
                          : catalog.response_schema(action);
    return ok_response(req, completeness_summary(1, 1), {{"schema", schema}});
}

Session& Dispatcher::session(const nlohmann::json& req) {
    const std::string sid = target_session_id(req);
    if (sid.empty()) {
        throw Error("SESSION_NOT_FOUND", "target.session_id is required");
    }
    return sessions_.get(sid);
}

nlohmann::json Dispatcher::action_session_open(const nlohmann::json& req) {
    const nlohmann::json target = req.value("target", nlohmann::json::object());
    const nlohmann::json args = req.value("args", nlohmann::json::object());
    const std::string vdb = target.value("vdb", std::string());
    const std::string name = args.value("name", std::string());
    const std::string cache_dir = args.value("cache_dir", std::string());
    const std::string policy = args.value("exclusion_policy", std::string("default"));
    // Provenance gate: validate the manifest before any backend/session side
    // effect, matching the Python reference (fail closed, no partial session).
    const nlohmann::json manifest_details = validate_run_manifest(target);
    Session& sess = sessions_.open(name, vdb, cache_dir, policy);
    nlohmann::json session_json = {
        {"session_id", sess.session_id},
        {"state", "alive"},
        {"vdb", sess.vdb},
        {"test_count", sess.backend->test_names().size()},
        {"top_scope_count", sess.backend->top_scopes().size()},
        {"top_scopes", sess.backend->top_scopes()},
        {"worker", sess.worker},
        {"exclusion_policy", sess.exclusion_policy},
        {"npi_initialized", false},
        {"observability",
         {{"ok", true},
          {"failure_count", 0},
          {"last_failure_operation", nullptr},
          {"last_failure_type", nullptr}}},
    };
    nlohmann::json snapshot = {
        {"vdb", sess.vdb},
        {"run_manifest", manifest_details},
    };
    return ok_response(req, completeness_summary(1, 1),
                       {{"session", session_json}, {"resource_snapshot", snapshot}});
}

nlohmann::json Dispatcher::action_session_status(const nlohmann::json& req) {
    Session& sess = session(req);
    nlohmann::json session_json = {
        {"session_id", sess.session_id},
        {"state", "alive"},
        {"vdb", sess.vdb},
        {"test_count", sess.backend->test_names().size()},
        {"top_scope_count", sess.backend->top_scopes().size()},
        {"top_scopes", sess.backend->top_scopes()},
        {"worker", sess.worker},
        {"exclusion_policy", sess.exclusion_policy},
        {"npi_initialized", false},
        {"observability",
         {{"ok", true},
          {"failure_count", 0},
          {"last_failure_operation", nullptr},
          {"last_failure_type", nullptr}}},
    };
    nlohmann::json cached = {
        {"state", "ready"},
        {"key", nullptr},
        {"hit", nullptr},
        {"urg_execution", nullptr},
    };
    return ok_response(req, completeness_summary(1, 1),
                       {{"session", session_json}, {"cached_indexes", cached}});
}

nlohmann::json Dispatcher::action_session_close(const nlohmann::json& req) {
    Session& sess = session(req);
    const nlohmann::json args = req.value("args", nlohmann::json::object());
    const bool confirm = args.value("confirm_discard_reasons", false);
    if (sess.reason_dirty() && !confirm) {
        throw Error("UNPERSISTED_EXCLUSION_REASON",
                    "session has exclusion reasons not persisted to CSV; "
                    "export them or close with confirm_discard_reasons=true",
                    {{"unpersisted_reason_count", sess.exclusion_records.size()}});
    }
    const std::size_t discarded =
        sess.reason_dirty() ? sess.exclusion_records.size() : 0;
    const std::string sid = sess.session_id;
    nlohmann::json session_json = {
        {"session_id", sid},
        {"state", "closed"},
        {"vdb", sess.vdb},
        {"test_count", sess.backend->test_names().size()},
        {"top_scope_count", sess.backend->top_scopes().size()},
        {"top_scopes", sess.backend->top_scopes()},
        {"worker", sess.worker},
        {"exclusion_policy", sess.exclusion_policy},
        {"npi_initialized", false},
        {"observability",
         {{"ok", true},
          {"failure_count", 0},
          {"last_failure_operation", nullptr},
          {"last_failure_type", nullptr}}},
    };
    sessions_.close(sid);
    nlohmann::json summary_json = completeness_summary(1, 1);
    summary_json["reasons_discarded"] = discarded > 0;
    summary_json["discarded_reason_count"] = discarded;
    return ok_response(req, summary_json, {{"session", session_json}});
}


namespace {

bool glob_match(const std::string& pattern, const std::string& text) {
    std::size_t p = 0, t = 0;
    std::size_t star = std::string::npos, mark = 0;
    while (t < text.size()) {
        if (p < pattern.size() && (pattern[p] == '?' || pattern[p] == text[t])) {
            ++p; ++t;
        } else if (p < pattern.size() && pattern[p] == '[') {
            const std::size_t close = pattern.find(']', p + 1);
            if (close == std::string::npos) return false;
            const bool negate = p + 1 < pattern.size() &&
                                (pattern[p + 1] == '!' || pattern[p + 1] == '^');
            const std::size_t start = p + (negate ? 2 : 1);
            bool found = false;
            for (std::size_t i = start; i < close; ++i) {
                if (i + 2 < close && pattern[i + 1] == '-') {
                    if (text[t] >= pattern[i] && text[t] <= pattern[i + 2]) found = true;
                    i += 2;
                } else if (pattern[i] == text[t]) {
                    found = true;
                }
            }
            if (found == negate) {
                if (star == std::string::npos) return false;
                p = star + 1;
                t = ++mark;
            } else {
                p = close + 1;
                ++t;
            }
        } else if (p < pattern.size() && pattern[p] == '*') {
            star = p++;
            mark = t;
        } else if (star != std::string::npos) {
            p = star + 1;
            t = ++mark;
        } else {
            return false;
        }
    }
    while (p < pattern.size() && pattern[p] == '*') ++p;
    return p == pattern.size();
}

std::size_t action_default_limit(const std::string& action) {
    if (action == "tests.list") return 1000;
    if (action == "metrics.list") return kMaxResponseRows;
    return 100;
}

double py_round(double value, int digits) {
    const long double factor = std::pow(10.0L, digits);
    const long double scaled = static_cast<long double>(value) * factor;
    return static_cast<double>(std::nearbyint(scaled) / factor);
}

double metric_pct(const MetricAggregate& aggregate) {
    if (aggregate.coverable <= 0) return -1.0;
    return py_round(100.0 * static_cast<double>(aggregate.covered) /
                        static_cast<double>(aggregate.coverable),
                    4);
}

// ---- query / sort / limits ------------------------------------------------
// Python keeps these contracts in xcov/query.py; the C++ backend must apply the
// same selectors instead of only validating them in the request schema.

struct QuerySpec {
    std::vector<std::string> include_patterns;
    std::vector<std::string> exclude_patterns;
    std::string match_field;
    bool case_sensitive = true;
};

std::string json_scalar_text(const nlohmann::json& value) {
    if (value.is_string()) return value.get<std::string>();
    if (value.is_number_integer()) return std::to_string(value.get<long long>());
    if (value.is_number_unsigned()) {
        return std::to_string(value.get<unsigned long long>());
    }
    if (value.is_number_float()) {
        std::ostringstream out;
        out << value.get<double>();
        return out.str();
    }
    if (value.is_boolean()) return value.get<bool>() ? "True" : "False";
    return value.dump();
}

bool row_field_value(const nlohmann::json& row, const std::string& field,
                     std::string* out) {
    if (field == "file") {
        if (row.contains("evidence") && row.at("evidence").is_object()) {
            const nlohmann::json& evidence = row.at("evidence");
            if (evidence.contains("file") && !evidence.at("file").is_null()) {
                *out = json_scalar_text(evidence.at("file"));
                return true;
            }
        }
    }
    auto it = row.find(field);
    if (it == row.end() || it->is_null()) return false;
    *out = json_scalar_text(*it);
    return true;
}

void validate_glob_pattern(const std::string& pattern) {
    // Python rejects regex-looking patterns because only * and ? are part of
    // the public glob contract.
    if (pattern.find_first_of("[]{}^$()|+") != std::string::npos) {
        throw Error("REGEX_NOT_SUPPORTED",
                    "only glob wildcard patterns are supported",
                    {{"pattern", pattern}, {"supported", "*,?"}});
    }
}

QuerySpec parse_query(const nlohmann::json& args,
                      const std::string& default_field) {
    QuerySpec spec;
    spec.match_field = default_field;
    if (!args.contains("query") || !args.at("query").is_object()) return spec;
    const nlohmann::json& query = args.at("query");
    if (query.contains("pattern_mode") &&
        query.at("pattern_mode").is_string() &&
        query.at("pattern_mode").get<std::string>() != "glob") {
        throw Error("REGEX_NOT_SUPPORTED",
                    "only glob wildcard patterns are supported",
                    {{"pattern_mode",
                      query.at("pattern_mode").get<std::string>()}});
    }
    if (query.contains("include_patterns") &&
        query.at("include_patterns").is_array()) {
        for (const auto& item : query.at("include_patterns")) {
            const std::string pattern = item.get<std::string>();
            validate_glob_pattern(pattern);
            spec.include_patterns.push_back(pattern);
        }
    }
    if (query.contains("exclude_patterns") &&
        query.at("exclude_patterns").is_array()) {
        for (const auto& item : query.at("exclude_patterns")) {
            const std::string pattern = item.get<std::string>();
            validate_glob_pattern(pattern);
            spec.exclude_patterns.push_back(pattern);
        }
    }
    if (query.contains("match_field") && query.at("match_field").is_string()) {
        spec.match_field = query.at("match_field").get<std::string>();
    }
    if (query.contains("case_sensitive") && query.at("case_sensitive").is_boolean()) {
        spec.case_sensitive = query.at("case_sensitive").get<bool>();
    }
    return spec;
}

bool query_match_any(const std::vector<std::string>& patterns,
                     const std::string& value, bool case_sensitive) {
    const std::string haystack = case_sensitive ? value : lower_copy(value);
    for (const auto& pattern : patterns) {
        const std::string needle = case_sensitive ? pattern : lower_copy(pattern);
        if (glob_match(needle, haystack)) return true;
    }
    return false;
}

bool query_value_matches(const QuerySpec& spec, const std::string& value) {
    if (!spec.include_patterns.empty() &&
        !query_match_any(spec.include_patterns, value, spec.case_sensitive)) {
        return false;
    }
    if (!spec.exclude_patterns.empty() &&
        query_match_any(spec.exclude_patterns, value, spec.case_sensitive)) {
        return false;
    }
    return true;
}

std::vector<nlohmann::json> filter_rows(const std::vector<nlohmann::json>& rows,
                                        const QuerySpec& spec) {
    std::vector<nlohmann::json> out;
    out.reserve(rows.size());
    for (const auto& row : rows) {
        std::string value;
        if (!row_field_value(row, spec.match_field, &value)) continue;
        if (!spec.include_patterns.empty() &&
            !query_match_any(spec.include_patterns, value, spec.case_sensitive)) {
            continue;
        }
        if (!spec.exclude_patterns.empty() &&
            query_match_any(spec.exclude_patterns, value, spec.case_sensitive)) {
            continue;
        }
        out.push_back(row);
    }
    return out;
}

nlohmann::json filters_summary(const QuerySpec& spec) {
    return {
        {"exclude", spec.exclude_patterns},
        {"include", spec.include_patterns},
        {"match_field", spec.match_field},
    };
}

bool json_less(const nlohmann::json& a, const nlohmann::json& b) {
    if (a.is_number() && b.is_number()) {
        return a.get<double>() < b.get<double>();
    }
    if (a.is_string() && b.is_string()) {
        return a.get<std::string>() < b.get<std::string>();
    }
    if (a.is_boolean() && b.is_boolean()) {
        return !a.get<bool>() && b.get<bool>();
    }
    return a.dump() < b.dump();
}

/// Python's sort contract distinguishes "field absent" (error) from
/// "field present with null" (participates in ordering). Query filtering is
/// stricter and drops null rows, so it keeps using row_field_value().
bool sort_key_value(const nlohmann::json& row, const std::string& field,
                    nlohmann::json* value) {
    auto it = row.find(field);
    if (it != row.end()) {
        *value = *it;
        return true;
    }
    if ((field == "file" || field == "line") && row.contains("evidence") &&
        row.at("evidence").is_object()) {
        const nlohmann::json& evidence = row.at("evidence");
        if (evidence.contains(field)) {
            *value = evidence.at(field);
            return true;
        }
    }
    return false;
}

std::vector<nlohmann::json> sort_rows(const std::string& action,
                                      const nlohmann::json& args,
                                      const std::vector<nlohmann::json>& rows) {
    if (!args.contains("sort") || !args.at("sort").is_object()) return rows;
    const nlohmann::json& sort = args.at("sort");
    const std::string key = sort.value("by", std::string());
    const std::string order = sort.value("order", std::string("asc"));
    if (key.empty()) {
        throw Error("INVALID_SORT_FIELD",
                    "sort.by is not supported for " + action,
                    {{"field", "None"}, {"supported", ""}});
    }
    if (order != "asc" && order != "desc") {
        throw Error("INVALID_SORT_ORDER", "sort.order must be asc or desc");
    }
    std::vector<nlohmann::json> keys(rows.size());
    for (std::size_t index = 0; index < rows.size(); ++index) {
        if (sort_key_value(rows[index], key, &keys[index])) continue;
        throw Error("INVALID_SORT_FIELD",
                    "sort.by is not present in the " + action + " response variant",
                    {{"field", key}, {"row_index", index}});
    }
    std::vector<nlohmann::json> out = rows;
    std::vector<std::size_t> order_index(rows.size());
    for (std::size_t index = 0; index < order_index.size(); ++index) {
        order_index[index] = index;
    }
    auto key_less = [&](std::size_t left, std::size_t right) {
        const nlohmann::json& a = keys[left];
        const nlohmann::json& b = keys[right];
        const bool a_null = a.is_null();
        const bool b_null = b.is_null();
        if (a_null != b_null) return !a_null;  // null last in ascending order
        if (a_null) return false;
        return json_less(a, b);
    };
    if (order == "asc") {
        std::stable_sort(order_index.begin(), order_index.end(), key_less);
    } else {
        std::stable_sort(order_index.begin(), order_index.end(),
                         [&](std::size_t a, std::size_t b) {
                             return key_less(b, a);
                         });
    }
    for (std::size_t index = 0; index < out.size(); ++index) {
        out[index] = rows[order_index[index]];
    }
    return out;
}

struct OutputSlice {
    nlohmann::json summary;
    std::vector<nlohmann::json> rows;
};

OutputSlice apply_output(const std::string& action, const nlohmann::json& args,
                         const std::vector<nlohmann::json>& rows) {
    const nlohmann::json limits =
        args.contains("limits") && args.at("limits").is_object()
            ? args.at("limits")
            : nlohmann::json::object();
    const std::size_t default_limit = action_default_limit(action);
    std::size_t max_items = default_limit;
    if (limits.contains("max_items")) {
        // Python treats an explicit null as MAX_RESPONSE_ROWS while an absent
        // field uses the per-action default.
        max_items = limits.at("max_items").is_null()
                        ? kMaxResponseRows
                        : limits.at("max_items").get<std::size_t>();
    }
    const std::string overflow =
        limits.value("overflow", std::string("truncate"));
    if (overflow != "truncate" && overflow != "error" &&
        overflow != "summary_only") {
        throw Error("INVALID_LIMIT", "unsupported limits.overflow",
                    {{"overflow", overflow}});
    }
    const std::size_t total = rows.size();
    if (overflow == "error" && total > max_items) {
        throw Error("INVALID_LIMIT", "result exceeds limits.max_items",
                    {{"total_count", total}, {"max_items", max_items}});
    }
    OutputSlice slice;
    if (overflow == "summary_only") {
        // summary_only deliberately returns no inline rows.
    } else {
        const std::size_t returned = std::min(total, max_items);
        slice.rows.assign(rows.begin(), rows.begin() +
                                            static_cast<std::ptrdiff_t>(returned));
    }
    const bool truncated = slice.rows.size() < total;
    slice.summary = completeness_summary(
        total, slice.rows.size(), truncated, true, true,
        truncated ? std::vector<std::string>{"data.items"}
                  : std::vector<std::string>());
    return slice;
}

nlohmann::json rows_json(const std::vector<nlohmann::json>& rows) {
    nlohmann::json items = nlohmann::json::array();
    for (const auto& row : rows) items.push_back(row);
    return items;
}

nlohmann::json scope_row(const ScopeInfo& scope, bool summary,
                         const std::set<std::string>& selected_metrics) {
    nlohmann::json row = nlohmann::json::object();
    row["name"] = scope.name;
    row["full_name"] = scope.full_name;
    std::vector<double> percentages;
    std::vector<MetricAggregate> present;
    for (const auto kind : {MetricKind::Line, MetricKind::Toggle, MetricKind::Branch,
                            MetricKind::Condition, MetricKind::Fsm,
                            MetricKind::Assert, MetricKind::Functional}) {
        if (!selected_metrics.empty() &&
            selected_metrics.find(metric_key(kind)) == selected_metrics.end()) {
            if (summary) row[std::string(metric_key(kind)) + "_pct"] = nullptr;
            continue;
        }
        auto it = scope.deep_metrics.find(kind);
        if (it == scope.deep_metrics.end() ||
            scope.deep_present.find(kind) == scope.deep_present.end()) {
            if (summary) row[std::string(metric_key(kind)) + "_pct"] = nullptr;
            continue;
        }
        present.push_back(it->second);
        if (it->second.coverable <= 0) {
            if (summary) row[std::string(metric_key(kind)) + "_pct"] = nullptr;
            continue;
        }
        const double pct = metric_pct(it->second);
        percentages.push_back(pct);
        if (summary) row[std::string(metric_key(kind)) + "_pct"] = pct;
    }
    if (percentages.empty()) {
        row["coverage_pct"] = nullptr;
    } else {
        double total = 0.0;
        for (double value : percentages) total += value;
        row["coverage_pct"] = py_round(total / percentages.size(), 4);
    }
    // The Python contract copies covered/coverable/missing when exactly one
    // requested metric is present, even when it is coverable==0.
    if (summary && present.size() == 1) {
        row["covered"] = present[0].covered;
        row["coverable"] = present[0].coverable;
        row["missing"] = present[0].missing();
    }
    return row;
}

} // namespace

nlohmann::json Dispatcher::action_tests_list(const nlohmann::json& req) {
    Session& sess = session(req);
    const nlohmann::json args = req.value("args", nlohmann::json::object());
    std::vector<nlohmann::json> rows;
    for (const auto& name : sess.backend->test_names()) {
        const std::size_t slash = name.rfind('/');
        rows.push_back(
            {{"name", slash == std::string::npos ? name : name.substr(slash + 1)}});
    }
    const QuerySpec query_spec = parse_query(args, "name");
    rows = filter_rows(rows, query_spec);
    const OutputSlice slice = apply_output("tests.list", args, rows);
    nlohmann::json summary_json = slice.summary;
    summary_json["session_id"] = sess.session_id;
    return ok_response(req, summary_json,
                       {{"filters", filters_summary(query_spec)},
                        {"items", rows_json(slice.rows)}});
}

nlohmann::json Dispatcher::action_scope(const nlohmann::json& req) {
    Session& sess = session(req);
    const std::string action = req.value("action", std::string());
    const nlohmann::json args = req.value("args", nlohmann::json::object());
    const std::string scope = args.value("scope", std::string());
    const bool recursive = args.value("recursive", false);
    const bool summary = action == "scope.summary";
    std::set<std::string> selected_metrics;
    if (args.contains("metrics") && args.at("metrics").is_array()) {
        for (const auto& item : args.at("metrics")) {
            selected_metrics.insert(item.get<std::string>());
        }
    }

    std::vector<const ScopeInfo*> selected;
    if (action == "scope.summary") {
        if (!scope.empty()) {
            const ScopeInfo* found = sess.backend->find_scope(scope);
            if (found == nullptr) {
                throw Error("SCOPE_NOT_FOUND", "coverage scope not found",
                            {{"scope", scope}});
            }
            selected.push_back(found);
        } else {
            for (const auto& name : sess.backend->top_scopes()) {
                const ScopeInfo* found = sess.backend->find_scope(name);
                if (found != nullptr) selected.push_back(found);
            }
        }
    } else if (action == "scope.children") {
        if (!scope.empty()) {
            const ScopeInfo* found = sess.backend->find_scope(scope);
            if (found != nullptr) {
                if (recursive) {
                    for (const auto& row : sess.backend->scopes()) {
                        if (row.full_name.size() > scope.size() &&
                            row.full_name.compare(0, scope.size(), scope) == 0 &&
                            row.full_name[scope.size()] == '.') {
                            selected.push_back(&row);
                        }
                    }
                } else {
                    for (const auto* child : sess.backend->children(scope)) {
                        selected.push_back(child);
                    }
                }
            }
        } else {
            for (const auto& name : sess.backend->top_scopes()) {
                const ScopeInfo* found = sess.backend->find_scope(name);
                if (found != nullptr) selected.push_back(found);
            }
        }
    } else {
        for (const auto& row : sess.backend->scopes()) {
            if (scope.empty()) {
                selected.push_back(&row);
            } else if (row.full_name == scope ||
                       (row.full_name.size() > scope.size() &&
                        row.full_name.compare(0, scope.size(), scope) == 0 &&
                        row.full_name[scope.size()] == '.')) {
                selected.push_back(&row);
            }
        }
    }

    const QuerySpec query_spec = parse_query(args, "full_name");
    std::vector<nlohmann::json> rows;
    for (const ScopeInfo* row : selected) {
        // Filter before materializing rows so a narrow query stays cheap on
        // large scope trees.
        const std::string field =
            query_spec.match_field == "name" ? row->name : row->full_name;
        if (!query_value_matches(query_spec, field)) continue;
        rows.push_back(scope_row(*row, summary, selected_metrics));
    }
    auto depth_of = [](const nlohmann::json& row) {
        const std::string name = row.value("full_name", std::string());
        std::size_t depth = 0;
        for (char ch : name) {
            if (ch == '.') ++depth;
        }
        return depth;
    };
    std::stable_sort(rows.begin(), rows.end(),
                     [&](const nlohmann::json& a, const nlohmann::json& b) {
                         const std::size_t ad = depth_of(a);
                         const std::size_t bd = depth_of(b);
                         if (ad != bd) return ad < bd;
                         return a.value("full_name", std::string()) <
                                b.value("full_name", std::string());
                     });
    rows = sort_rows(action, args, rows);
    const OutputSlice slice = apply_output(action, args, rows);
    nlohmann::json summary_json = slice.summary;
    summary_json["session_id"] = sess.session_id;
    summary_json["scope"] = scope.empty() ? nlohmann::json(nullptr) : nlohmann::json(scope);
    summary_json["test"] = "merged";
    return ok_response(req, summary_json,
                       {{"filters", filters_summary(query_spec)},
                        {"items", rows_json(slice.rows)}});
}

namespace {

nlohmann::json code_metric_row(MetricKind kind, const MetricAggregate& aggregate) {
    nlohmann::json row = nlohmann::json::object();
    row["metric"] = metric_key(kind);
    row["covered"] = aggregate.covered;
    row["coverable"] = aggregate.coverable;
    row["missing"] = aggregate.missing();
    if (aggregate.coverable > 0) {
        row["coverage_pct"] = metric_pct(aggregate);
    } else {
        row["coverage_pct"] = nullptr;
    }
    return row;
}

bool is_descendant(const std::string& scope, const std::string& root) {
    return scope == root ||
           (scope.size() > root.size() &&
            scope.compare(0, root.size(), root) == 0 &&
            scope[root.size()] == '.');
}

} // namespace

nlohmann::json Dispatcher::action_code_coverage(const nlohmann::json& req) {
    Session& sess = session(req);
    const std::string action = req.value("action", std::string());
    const nlohmann::json args = req.value("args", nlohmann::json::object());
    const std::string group_by = args.value("group_by", std::string("metric"));
    const std::string scope_filter = args.value("scope", std::string());
    if (group_by != "metric" && group_by != "scope") {
        throw Error("SCHEMA_INVALID", "unsupported group_by",
                    {{"path", "$.args.group_by"}});
    }
    std::vector<MetricKind> metrics = {MetricKind::Line, MetricKind::Toggle,
                                       MetricKind::Branch, MetricKind::Condition,
                                       MetricKind::Fsm, MetricKind::Assert};
    if (args.contains("metrics") && args.at("metrics").is_array()) {
        metrics.clear();
        for (const auto& item : args.at("metrics")) {
            metrics.push_back(metric_from_key(item.get<std::string>()));
        }
    }

    std::vector<nlohmann::json> rows;
    if (group_by == "metric") {
        std::map<MetricKind, MetricAggregate> totals;
        std::map<MetricKind, bool> has_metric;
        for (MetricKind kind : metrics) {
            totals[kind] = MetricAggregate();
            has_metric[kind] = false;
        }
        std::vector<const ScopeInfo*> roots;
        if (!scope_filter.empty()) {
            const ScopeInfo* root = sess.backend->find_scope(scope_filter);
            // The Python reference simply sees no scope_metrics entries for an
            // unknown name and returns an empty list; it does not raise.
            if (root != nullptr) roots.push_back(root);
        } else {
            for (const auto& root_name : sess.backend->top_scopes()) {
                const ScopeInfo* root = sess.backend->find_scope(root_name);
                if (root != nullptr) roots.push_back(root);
            }
        }
        for (const ScopeInfo* root : roots) {
            for (MetricKind kind : metrics) {
                if (root->deep_present.find(kind) ==
                    root->deep_present.end()) {
                    continue;
                }
                auto it = root->deep_metrics.find(kind);
                if (it == root->deep_metrics.end()) continue;
                has_metric[kind] = true;
                totals[kind].covered += it->second.covered;
                totals[kind].coverable += it->second.coverable;
            }
        }
        for (MetricKind kind : metrics) {
            if (!has_metric[kind]) continue;
            rows.push_back(code_metric_row(kind, totals[kind]));
        }
    } else {
        for (const auto& scope : sess.backend->scopes()) {
            if (!scope_filter.empty() && !is_descendant(scope.full_name, scope_filter)) {
                continue;
            }
            nlohmann::json row = nlohmann::json::object();
            row["scope"] = scope.full_name;
            row["metric"] = "summary";
            std::vector<double> percentages;
            std::vector<MetricAggregate> selected;
            for (MetricKind kind : metrics) {
                if (scope.deep_present.find(kind) ==
                    scope.deep_present.end()) {
                    continue;
                }
                auto it = scope.deep_metrics.find(kind);
                if (it == scope.deep_metrics.end()) continue;
                selected.push_back(it->second);
                if (it->second.coverable > 0) {
                    percentages.push_back(metric_pct(it->second));
                }
            }
            if (percentages.empty()) {
                row["coverage_pct"] = nullptr;
            } else {
                double total = 0.0;
                for (double value : percentages) total += value;
                row["coverage_pct"] = py_round(total / percentages.size(), 4);
            }
            if (selected.size() == 1) {
                row["covered"] = selected[0].covered;
                row["coverable"] = selected[0].coverable;
                row["missing"] = selected[0].missing();
            }
            rows.push_back(row);
        }
        // Python iterates sorted(scope_metrics); keep the same default order.
        std::stable_sort(rows.begin(), rows.end(),
                         [](const nlohmann::json& a, const nlohmann::json& b) {
                             return a.value("scope", std::string()) <
                                    b.value("scope", std::string());
                         });
    }

    const QuerySpec query_spec = parse_query(args, group_by);
    rows = filter_rows(rows, query_spec);
    rows = sort_rows(action, args, rows);
    const OutputSlice slice = apply_output(action, args, rows);
    nlohmann::json summary_json = slice.summary;
    summary_json["session_id"] = sess.session_id;
    summary_json["scope"] = scope_filter.empty() ? nlohmann::json(nullptr)
                                                 : nlohmann::json(scope_filter);
    summary_json["test"] = "merged";
    summary_json["metrics"] = nlohmann::json::array();
    for (MetricKind kind : metrics) summary_json["metrics"].push_back(metric_key(kind));
    return ok_response(req, summary_json,
                       {{"filters", filters_summary(query_spec)},
                        {"items", rows_json(slice.rows)}});
}

nlohmann::json Dispatcher::action_functional(const nlohmann::json& req) {
    Session& sess = session(req);
    const std::string action = req.value("action", std::string());
    const nlohmann::json args = req.value("args", nlohmann::json::object());
    const std::string group_by = args.value("group_by", std::string("covergroup"));
    const std::string scope_filter = args.value("scope", std::string());
    if (group_by != "covergroup") {
        throw Error("ACTION_NOT_IMPLEMENTED",
                    "only group_by=covergroup is implemented by the C++ backend yet",
                    {{"action", action}});
    }
    const auto& groups = sess.backend->functional_groups();
    std::vector<const UcapiBackend::FunctionalGroup*> matched;
    matched.reserve(groups.size());
    for (const auto& group : groups) {
        if (!scope_filter.empty()) {
            const std::size_t marker = group.full_name.find("::");
            const std::string scope_name =
                marker == std::string::npos ? group.full_name
                                            : group.full_name.substr(0, marker);
            if (!is_descendant(scope_name, scope_filter)) continue;
        }
        matched.push_back(&group);
    }
    std::stable_sort(
        matched.begin(), matched.end(),
        [](const UcapiBackend::FunctionalGroup* a,
           const UcapiBackend::FunctionalGroup* b) {
            return a->full_name < b->full_name;
        });
    std::vector<nlohmann::json> rows;
    rows.reserve(matched.size());
    for (const auto* group : matched) {
        nlohmann::json row = nlohmann::json::object();
        row["covergroup"] = group->full_name;
        // Query filtering happens before the Python projection; name and
        // full_name exist there even though the response omits them.
        row["name"] = group->full_name;
        row["full_name"] = group->full_name;
        row["covered"] = group->covered;
        row["coverable"] = group->coverable;
        row["missing"] = group->coverable > group->covered
                             ? group->coverable - group->covered
                             : 0;
        if (group->score_item_count > 0) {
            row["coverage_pct"] = py_round(group->score_pct, 4);
        } else {
            row["coverage_pct"] = nullptr;
        }
        rows.push_back(row);
    }
    const QuerySpec query_spec = parse_query(args, group_by);
    rows = filter_rows(rows, query_spec);
    rows = sort_rows(action, args, rows);
    for (auto& row : rows) {
        row.erase("name");
        row.erase("full_name");
    }
    const OutputSlice slice = apply_output(action, args, rows);
    nlohmann::json summary_json = slice.summary;
    summary_json["session_id"] = sess.session_id;
    summary_json["test"] = "merged";
    return ok_response(req, summary_json,
                       {{"filters", filters_summary(query_spec)},
                        {"items", rows_json(slice.rows)}});
}

nlohmann::json Dispatcher::action_assert(const nlohmann::json& req) {
    Session& sess = session(req);
    const std::string action = req.value("action", std::string());
    const nlohmann::json args = req.value("args", nlohmann::json::object());
    const std::string scope_filter = args.value("scope", std::string());
    const auto& assertion_rows = sess.backend->assertions();
    std::vector<const UcapiBackend::AssertionRow*> matched;
    matched.reserve(assertion_rows.size());
    for (const auto& item : assertion_rows) {
        const std::size_t dot = item.full_name.rfind('.');
        const std::string scope_name =
            dot == std::string::npos ? std::string() : item.full_name.substr(0, dot);
        if (!scope_filter.empty() && !is_descendant(scope_name, scope_filter)) {
            continue;
        }
        matched.push_back(&item);
    }
    std::stable_sort(
        matched.begin(), matched.end(),
        [](const UcapiBackend::AssertionRow* a,
           const UcapiBackend::AssertionRow* b) {
            if (a->name != b->name) return a->name < b->name;
            return a->full_name < b->full_name;
        });
    std::vector<nlohmann::json> rows;
    rows.reserve(matched.size());
    for (const auto* item : matched) {
        const long success = item->type == 1 ? item->all_successes : item->real_successes;
        const long covered = success > 0 ? 1 : 0;
        const long coverable = item->excluded ? 0 : 1;
        nlohmann::json row = nlohmann::json::object();
        row["name"] = item->name;
        row["full_name"] = item->full_name;
        row["covered"] = covered;
        row["coverable"] = coverable;
        row["missing"] = coverable > covered ? coverable - covered : 0;
        if (item->excluded) {
            row["coverage_pct"] = nullptr;
            row["status"] = nlohmann::json::array({"excluded"});
            row["without_attempts"] = 0;
        } else {
            row["coverage_pct"] = covered > 0 ? 100.0 : 0.0;
            row["status"] = nlohmann::json::array(
                {covered > 0 ? "covered" : "not_covered"});
            row["without_attempts"] = item->attempts == 0 ? 1 : 0;
        }
        row["attempts"] = item->attempts;
        row["real_successes"] = success;
        rows.push_back(row);
    }
    const QuerySpec query_spec = parse_query(args, "full_name");
    rows = filter_rows(rows, query_spec);
    rows = sort_rows(action, args, rows);
    const OutputSlice slice = apply_output(action, args, rows);
    nlohmann::json summary_json = slice.summary;
    summary_json["session_id"] = sess.session_id;
    summary_json["scope"] = scope_filter.empty() ? nlohmann::json(nullptr)
                                                 : nlohmann::json(scope_filter);
    summary_json["test"] = "merged";
    return ok_response(req, summary_json,
                       {{"filters", filters_summary(query_spec)},
                        {"items", rows_json(slice.rows)}});
}

nlohmann::json Dispatcher::action_export(const nlohmann::json& req) {
    Session& sess = session(req);
    const std::string action = req.value("action", std::string());
    const nlohmann::json args = req.value("args", nlohmann::json::object());
    const nlohmann::json output = args.value("output", nlohmann::json::object());
    const std::string raw_path = output.value("path", std::string());
    if (raw_path.empty()) {
        throw Error("SCHEMA_INVALID", "output.path is required",
                    {{"path", "$.args.output.path"}});
    }
    const bool allow_absolute = output.value("allow_absolute_path", false);
    if (raw_path[0] == '/' && !allow_absolute) {
        throw Error("OUTPUT_PATH_UNSAFE",
                    "absolute output path requires allow_absolute_path=true",
                    {{"path", raw_path}});
    }
    ensure_directory(raw_path);

    if (action == "export.assert") {
        nlohmann::json gaps = nlohmann::json::array();
        const std::string assert_scope_filter =
            args.value("scope", std::string());
        int index = 0;
        for (const auto& item : sess.backend->assertions()) {
            if (item.excluded) continue;
            if (!assert_scope_filter.empty()) {
                const std::size_t dot = item.full_name.rfind('.');
                const std::string item_scope =
                    dot == std::string::npos ? std::string()
                                             : item.full_name.substr(0, dot);
                if (!is_descendant(item_scope, assert_scope_filter)) continue;
            }
            const long success =
                item.type == 1 ? item.all_successes : item.real_successes;
            if (success > 0) continue;
            ++index;
            const std::size_t dot = item.full_name.rfind('.');
            nlohmann::json gap = nlohmann::json::object();
            gap["gap_id"] = "A" + std::string(4 - std::min<std::size_t>(4, std::to_string(index).size()), '0') + std::to_string(index);
            const std::string assert_scope =
                dot == std::string::npos ? std::string()
                                         : item.full_name.substr(0, dot);
            gap["scope"] = assert_scope;
            gap["kind"] = item.type == 1 ? "npiCovCoverProperty" : "npiCovAssert";
            gap["name"] = item.name;
            gap["full_name"] = item.full_name;
            gap["covergroup"] = nullptr;
            gap["coverpoint"] = nullptr;
            gap["cross"] = nullptr;
            gap["bin"] = nullptr;
            gap["covered"] = 0;
            gap["coverable"] = 1;
            gap["count"] = 0;
            gap["evidence"] = nlohmann::json::object();
            nlohmann::json ref_row = {
                {"metric", "assert"},
                {"scope", assert_scope},
                {"name", item.name},
                {"full_name", item.full_name},
                {"type", "assert"},
            };
            const std::string ref_value = coverage_ref(ref_row);
            gap["coverage_ref"] = ref_value;
            sess.backend->register_ref(ref_value, assert_scope, "assert",
                                       item.full_name);
            gaps.push_back(gap);
        }
        const std::string json_path = raw_path + "/assert.json";
        const std::string xout_path = raw_path + "/assert.xout";
        nlohmann::json payload = {
            {"artifact_format", "xcov_assert_gaps.v1"},
            {"metric", "assert"},
            {"exclusion_locator",
             {{"vdb", sess.vdb}, {"version", "xcov.ucapi_semantic.v1"}}},
            {"source_files", nlohmann::json::array()},
            {"gap_count", gaps.size()},
            {"gaps", gaps},
        };
        write_file(json_path, payload.dump() + "\n");
        write_file(xout_path, "@xcov.export.assert.v1\n\ngaps: " +
                                  std::to_string(gaps.size()) + "\n");
        nlohmann::json summary_json = completeness_summary(0, 0);
        summary_json["session_id"] = sess.session_id;
        summary_json["scope"] = args.value("scope", nlohmann::json(nullptr));
        summary_json["output_dir"] = raw_path;
        summary_json["output_mode"] = "file";
        return ok_response(
            req, summary_json,
            {{"structured",
              {{"metric", "assert"},
               {"json", json_path},
               {"xout", xout_path},
               {"gap_count", gaps.size()}}}});
    }
    if (action == "export.code_coverage") {
        const nlohmann::json scopes =
            args.value("scopes", nlohmann::json::array());
        if (!scopes.is_array() || scopes.empty()) {
            throw Error("SCHEMA_INVALID", "scopes is required",
                        {{"path", "$.args.scopes"}});
        }
        nlohmann::json items = nlohmann::json::array();
        std::size_t index = 0;
        for (const auto& scope_value : scopes) {
            const std::string scope_name = scope_value.get<std::string>();
            const ScopeInfo* scope = sess.backend->find_scope(scope_name);
            if (scope == nullptr) {
                throw Error("SCOPE_NOT_FOUND", "scope was not found",
                            {{"scope_name", scope_name}});
            }
            ++index;
            char dirname[64];
            std::snprintf(dirname, sizeof dirname, "instance-%04zu", index);
            const std::string dir = raw_path + "/" + dirname;
            ensure_directory(dir);
            std::set<std::string> requested_metrics;
            if (args.contains("metrics") && args.at("metrics").is_array()) {
                for (const auto& item : args.at("metrics")) {
                    requested_metrics.insert(item.get<std::string>());
                }
            }
            if (requested_metrics.empty()) {
                requested_metrics = {"line", "toggle", "branch", "condition",
                                     "fsm"};
            }
            const auto scan = sess.backend->scan_code(*scope, requested_metrics);
            const auto& gaps = scan.gaps;
            nlohmann::json metrics_meta = nlohmann::json::array();
            for (const char* metric : {"line", "toggle", "branch", "condition", "fsm"}) {
                if (requested_metrics.find(metric) == requested_metrics.end()) {
                    continue;
                }
                nlohmann::json rows = nlohmann::json::array();
                for (const auto& gap : gaps) {
                    if (gap.metric != metric) continue;
                    nlohmann::json row = nlohmann::json::object();
                    row["gap_id"] = "";
                    row["object"] = gap.name;
                    row["name"] = gap.name;
                    row["metric"] = gap.metric;
                    row["scope"] = scope_name;
                    row["type"] = coverage_type_for_metric(gap.metric);
                    row["full_name"] = gap.full_name;
                    row["coverable"] = gap.coverable;
                    row["covered"] = 0;
                    const std::string ref_value = coverage_ref(row);
                    row["coverage_ref"] = ref_value;
                    sess.backend->register_ref(ref_value, scope_name,
                                               gap.metric, gap.full_name);
                    rows.push_back(row);
                }
                nlohmann::json line_groups = nlohmann::json::array();
                if (std::string(metric) == "line") {
                    std::map<std::pair<std::string, int>, nlohmann::json> groups;
                    int gap_index = 0;
                    for (const auto& leaf : scan.line_leaves) {
                        if (leaf.coverable <= 0 || leaf.covered >= leaf.coverable) {
                            continue;
                        }
                        const std::pair<std::string, int> key{leaf.file,
                                                              leaf.line_no};
                        auto& group = groups[key];
                        if (!group.contains("context")) {
                            group["context"] = nlohmann::json::object();
                            group["context"]["kind"] = lower_copy(leaf.parent_kind);
                            group["context"]["at"] = leaf.file + ":" +
                                                     std::to_string(leaf.line_no);
                            group["context"]["covered"] = 0;
                            group["context"]["coverable"] = 0;
                            group["context"]["missing"] = 0;
                            group["context"]["pct"] = nullptr;
                            group["uncovered"] = nlohmann::json::array();
                        }
                        group["context"]["covered"] =
                            group["context"]["covered"].get<long>() + leaf.covered;
                        group["context"]["coverable"] =
                            group["context"]["coverable"].get<long>() +
                            leaf.coverable;
                        group["context"]["missing"] =
                            group["context"]["coverable"].get<long>() -
                            group["context"]["covered"].get<long>();
                        const long coverable =
                            group["context"]["coverable"].get<long>();
                        const long covered =
                            group["context"]["covered"].get<long>();
                        if (coverable > 0) {
                            group["context"]["pct"] =
                                py_round(100.0 * static_cast<double>(covered) /
                                             static_cast<double>(coverable), 2);
                        }
                        ++gap_index;
                        char gap_id[16];
                        std::snprintf(gap_id, sizeof gap_id, "L%04d", gap_index);
                        std::string statement =
                            read_source_line(leaf.file, leaf.line_no);
                        if (statement.empty()) statement = leaf.name;
                        group["uncovered"].push_back(
                            {{"gap_id", gap_id},
                             {"at", leaf.file + ":" +
                                        std::to_string(leaf.line_no)},
                             {"statement", statement}});
                    }
                    int group_index = 0;
                    for (auto& entry : groups) {
                        ++group_index;
                        char group_id[16];
                        std::snprintf(group_id, sizeof group_id, "LG%04d",
                                      group_index);
                        entry.second["group_id"] = group_id;
                        line_groups.push_back(entry.second);
                    }
                }
                const std::string name = std::string(metric) + ".json";
                const MetricKind kind_for_metric =
                    metric_from_key(std::string(metric));
                long covered = 0;
                long coverable = 0;
                auto deep = scope->metrics.find(kind_for_metric);
                if (deep != scope->metrics.end()) {
                    covered = deep->second.covered;
                    coverable = deep->second.coverable;
                }
                nlohmann::json coverage = nlohmann::json::object();
                coverage["covered"] = covered;
                coverage["coverable"] = coverable;
                coverage["missing"] =
                    coverable > covered ? coverable - covered : 0;
                if (coverable > 0) {
                    coverage["pct"] = py_round(
                        100.0 * static_cast<double>(covered) /
                            static_cast<double>(coverable), 2);
                } else {
                    coverage["pct"] = nullptr;
                }
                nlohmann::json payload = {
                    {"schema", "xcov.code_coverage.gap.v1"},
                    {"metric", metric},
                    {"scope", scope_name},
                    {"coverage_basis", "self"},
                    {"analysis_complete", true},
                    {"coverage", coverage},
                    {"gap_count", rows.size()},
                    {"gaps", rows},
                };
                if (std::string(metric) == "line") {
                    payload["line_group_count"] = line_groups.size();
                    payload["line_groups"] = line_groups;
                }
                if (std::string(metric) == "condition" ||
                    std::string(metric) == "branch") {
                    nlohmann::json groups = nlohmann::json::array();
                    int covered_object_gaps = 0;
                    int group_index = 0;
                    for (const auto& group :
                         sess.backend->decision_groups(
                             *scope, std::string(metric) == "condition"
                                         ? "Condition"
                                         : "Branch")) {
                        nlohmann::json entry = nlohmann::json::object();
                        char group_id[16];
                        std::snprintf(group_id, sizeof group_id, "DG%04d",
                                      ++group_index);
                        entry["group_id"] = group_id;
                        const std::string at =
                            group.file + ":" + std::to_string(group.line_no);
                        if (std::string(metric) == "condition") {
                            entry["condition"] = {{"at", at},
                                                  {"expression", group.expression}};
                        } else {
                            entry["decision_path"] = nlohmann::json::array();
                            entry["decision_path"].push_back(
                                {{"marker", group.expression},
                                 {"kind", "branch"},
                                 {"at", at},
                                 {"expression", group.expression}});
                        }
                        nlohmann::json terms = nlohmann::json::array();
                        nlohmann::json uncovered = nlohmann::json::array();
                        for (const auto& arm : group.arms) {
                            terms.push_back({{"marker", arm.pattern},
                                             {"expression", arm.expression}});
                        }
                        // Emit the arms that are genuinely uncovered first;
                        // anything left is a leaf deeper in the subtree that
                        // has no matching cross arm.
                        long arm_gaps = 0;
                        for (const auto& arm : group.arms) {
                            const long missing_arms =
                                arm.coverable > arm.covered
                                    ? arm.coverable - arm.covered
                                    : 0;
                            for (long k = 0; k < missing_arms; ++k) {
                                ++covered_object_gaps;
                                ++arm_gaps;
                                char gap_id[16];
                                std::snprintf(gap_id, sizeof gap_id, "B%04d",
                                              covered_object_gaps);
                                uncovered.push_back(
                                    {{"gap_id", gap_id},
                                     {"values", arm.pattern},
                                     {"status", "not_covered"}});
                            }
                        }
                        for (long k = arm_gaps; k < group.missing_gaps; ++k) {
                            ++covered_object_gaps;
                            char gap_id[16];
                            std::snprintf(gap_id, sizeof gap_id, "B%04d",
                                          covered_object_gaps);
                            uncovered.push_back(
                                {{"gap_id", gap_id},
                                 {"values", std::string()},
                                 {"status", "unattributed"}});
                        }
                        entry["terms"] = terms;
                        entry["uncovered"] = uncovered;
                        groups.push_back(entry);
                    }
                    const long missing_total =
                        coverage["missing"].get<long>();
                    if (std::string(metric) == "condition") {
                        payload["condition_group_count"] = groups.size();
                        payload["coverage_object_gap_count"] = missing_total;
                        payload["unattributed_gap_count"] =
                            missing_total - covered_object_gaps;
                        payload["condition_groups"] = groups;
                    } else {
                        payload["decision_group_count"] = groups.size();
                        payload["coverage_object_gap_count"] = missing_total;
                        payload["unattributed_gap_count"] =
                            missing_total - covered_object_gaps;
                        payload["decision_groups"] = groups;
                    }
                }
                write_file(dir + "/" + name, payload.dump() + "\n");
                write_file(dir + "/" + std::string(metric) + ".xout",
                           "@xcov.code_coverage." + std::string(metric) +
                               ".v1\n\ngaps: " + std::to_string(rows.size()) + "\n");
                metrics_meta.push_back({{"metric", metric},
                                        {"json", name},
                                        {"xout", std::string(metric) + ".xout"},
                                        {"raw", "../raw/modinfo.urg.txt"}});
            }
            write_file(dir + "/navigation.json",
                       nlohmann::json({{"scope", scope_name}}).dump() + "\n");
            write_file(dir + "/navigation.xout",
                       "@xcov.code_coverage.navigation.v1\n");
            items.push_back(
                {{"scope", scope_name},
                 {"directory", dir},
                 {"metrics", metrics_meta},
                 {"navigation", {{"json", "navigation.json"},
                                 {"xout", "navigation.xout"}}}});
        }
        nlohmann::json summary_json =
            completeness_summary(items.size(), items.size());
        summary_json["session_id"] = sess.session_id;
        summary_json["output_dir"] = raw_path;
        summary_json["output_mode"] = "file";
        return ok_response(req, summary_json, {{"items", items}});
    }
    if (action == "export.functional_coverage") {
        std::vector<UcapiBackend::FunctionalGap> gaps;
        const std::string export_scope =
            args.value("scope", std::string());
        for (const auto& item : sess.backend->functional_gaps()) {
            if (!export_scope.empty() &&
                !is_descendant(item.scope, export_scope)) {
                continue;
            }
            gaps.push_back(item);
        }
        nlohmann::json rows = nlohmann::json::array();
        int index = 0;
        for (const auto& gap : gaps) {
            ++index;
            char id[16];
            std::snprintf(id, sizeof id, "FC%04d", index);
            nlohmann::json row = nlohmann::json::object();
            row["gap_id"] = id;
            row["scope"] = gap.scope;
            row["kind"] = "npiCovCoverBin";
            row["name"] = gap.bin;
            row["full_name"] = gap.full_name;
            row["covergroup"] = gap.covergroup;
            row["coverpoint"] = gap.coverpoint;
            row["cross"] = nullptr;
            row["bin"] = gap.bin;
            row["covered"] = 0;
            row["coverable"] = 1;
            row["count"] = 0;
            row["evidence"] = nlohmann::json::object();
            rows.push_back(row);
        }
        const std::string json_path = raw_path + "/functional.json";
        const std::string xout_path = raw_path + "/functional.xout";
        nlohmann::json payload = {
            {"artifact_format", "xcov_functional_gaps.v1"},
            {"metric", "functional"},
            {"exclusion_locator",
             {{"vdb", sess.vdb}, {"version", "xcov.ucapi_semantic.v1"}}},
            {"source_files", nlohmann::json::array()},
            {"gap_count", rows.size()},
            {"gaps", rows},
        };
        write_file(json_path, payload.dump() + "\n");
        write_file(xout_path, "@xcov.export.functional_coverage.v1\n\ngaps: " +
                                  std::to_string(rows.size()) + "\n");
        nlohmann::json summary_json = completeness_summary(0, 0);
        summary_json["session_id"] = sess.session_id;
        summary_json["scope"] = args.value("scope", nlohmann::json(nullptr));
        summary_json["output_dir"] = raw_path;
        summary_json["output_mode"] = "file";
        return ok_response(
            req, summary_json,
            {{"structured",
              {{"metric", "functional"},
               {"json", json_path},
               {"xout", xout_path},
               {"gap_count", rows.size()}}}});
    }
    throw Error("ACTION_NOT_IMPLEMENTED",
                "this export action is not implemented by the C++ backend yet",
                {{"action", action}});
}

namespace {

bool same_record(const ExclusionRecord& a, const ExclusionRecord& b) {
    return a.kind == b.kind && a.coverage_ref == b.coverage_ref &&
           a.reason == b.reason && a.scope == b.scope &&
           a.metric == b.metric && a.name == b.name &&
           a.full_name == b.full_name && a.target_kind == b.target_kind &&
           a.covergroup == b.covergroup && a.item == b.item &&
           a.bin == b.bin && a.line == b.line &&
           a.source_file == b.source_file && a.recursive == b.recursive;
}

/// Insert/update one reason record under the canonical key. Returns true when
/// the session metadata actually changed.
bool put_exclusion_record(Session& sess, const ExclusionRecord& record) {
    const std::string key = exclusion_record_key(record);
    auto it = sess.exclusion_records.find(key);
    if (it != sess.exclusion_records.end() && same_record(it->second, record)) {
        return false;
    }
    sess.exclusion_records[key] = record;
    return true;
}

bool erase_exclusion_record_by_ref(Session& sess, const std::string& ref) {
    for (auto it = sess.exclusion_records.begin();
         it != sess.exclusion_records.end();) {
        if (it->second.coverage_ref == ref) {
            it = sess.exclusion_records.erase(it);
            return true;
        }
        ++it;
    }
    return false;
}

/// Locators store the fully-qualified leaf name (see export actions). Derive
/// the short object name and a non-duplicated full_name for CSV output.
void assign_locator_record(const std::string& scope, const std::string& metric,
                           const std::string& locator_name,
                           ExclusionRecord* record) {
    record->scope = scope;
    record->metric = metric;
    const std::string prefix = scope + ".";
    if (locator_name.compare(0, prefix.size(), prefix) == 0) {
        record->full_name = locator_name;
        // Keep the fully qualified name in the CSV object column: the apply
        // path resolves refs by accumulated path and cannot disambiguate a
        // bare leaf name such as a toggle transition.
        record->name = locator_name;
    } else {
        record->full_name = scope.empty() ? locator_name
                                          : scope + "." + locator_name;
        record->name = record->full_name;
    }
}

} // namespace

nlohmann::json Dispatcher::action_exclude(const nlohmann::json& req) {
    Session& sess = session(req);
    const std::string action = req.value("action", std::string());
    const nlohmann::json args = req.value("args", nlohmann::json::object());
    nlohmann::json items = nlohmann::json::array();

    if (action == "exclude.load") {
        const nlohmann::json paths = args.value("paths", nlohmann::json::array());
        for (const auto& path_value : paths) {
            const std::string path = path_value.get<std::string>();
            // Parse first: UCAPI applies the file immediately, so a parse
            // failure after load would leave the session modified.
            const ElDocument document = parse_el(path);
            sess.backend->load_exclusions(path);
            for (const auto& entry : document.entries) {
                sess.loaded_el_entries.push_back(entry);
            }
            items.push_back({{"path", path}, {"status", "loaded"}});
        }
        return ok_response(req, completeness_summary(items.size(), items.size()),
                           {{"items", items}});
    }
    if (action == "exclude.unload_all") {
        if (!args.value("confirm", false)) {
            throw Error("CONFIRMATION_REQUIRED",
                        "exclude.unload_all requires confirm=true");
        }
        const std::size_t before = sess.exclusion_records.size();
        sess.backend->unload_exclusions();
        sess.exclusion_records.clear();
        sess.loaded_el_entries.clear();
        // Removing every exclusion also clears the dirty reason set; this
        // mirrors Python clear_exclusions().
        sess.mark_reasons_persisted();
        items.push_back({{"status", "changed"},
                         {"before_count", before},
                         {"after_count", 0}});
        return ok_response(req, completeness_summary(items.size(), items.size()),
                           {{"items", items}});
    }
    const bool adding = action == "exclude.add";
    const nlohmann::json refs =
        args.value("coverage_refs", nlohmann::json::array());
    bool records_changed = false;
    for (const auto& entry : refs) {
        const std::string ref =
            entry.is_string() ? entry.get<std::string>()
                              : entry.value("coverage_ref", std::string());
        nlohmann::json item = nlohmann::json::object();
        item["coverage_ref"] = ref;
        try {
            const std::string reason =
                entry.is_string() ? std::string()
                                  : entry.value("reason", std::string());
            bool already = false;
            const bool known = sess.backend->exclusion_state(ref, &already);
            if (known && already == adding) {
                item["status"] = "already_in_state";
                item["error"] = nullptr;
                if (adding && !reason.empty()) {
                    ExclusionRecord record;
                    record.coverage_ref = ref;
                    record.reason = reason;
                    std::string locator_scope;
                    std::string locator_metric;
                    std::string locator_name;
                    sess.backend->locator_for_ref(ref, &locator_scope,
                                                  &locator_metric, &locator_name);
                    assign_locator_record(locator_scope, locator_metric,
                                          locator_name, &record);
                    record.kind =
                        record.metric == "assert" ? "assertion" : "code";
                    records_changed |= put_exclusion_record(sess, record);
                    sess.backend->set_exclusion(ref, true, reason);
                }
                items.push_back(item);
                continue;
            }
            const bool applied =
                sess.backend->set_exclusion(ref, adding, reason);
            item["status"] = applied ? "changed" : (known ? "failed" : "invalid");
            item["error"] = nullptr;
            if (applied && adding) {
                item["reason"] = reason;
                ExclusionRecord record;
                record.coverage_ref = ref;
                record.reason = reason;
                std::string locator_scope;
                std::string locator_metric;
                std::string locator_name;
                sess.backend->locator_for_ref(ref, &locator_scope,
                                              &locator_metric, &locator_name);
                assign_locator_record(locator_scope, locator_metric,
                                      locator_name, &record);
                record.kind = record.metric == "assert" ? "assertion" : "code";
                records_changed |= put_exclusion_record(sess, record);
            } else if (applied) {
                records_changed |= erase_exclusion_record_by_ref(sess, ref);
            }
        } catch (const Error& exc) {
            item["status"] = "failed";
            item["error"] = exc.message();
        }
        items.push_back(item);
    }
    if (records_changed) sess.mark_reason_mutation();
    return ok_response(req, completeness_summary(items.size(), items.size()),
                       {{"items", items}});
}

nlohmann::json Dispatcher::action_export_exclude(const nlohmann::json& req) {
    Session& sess = session(req);
    const nlohmann::json args = req.value("args", nlohmann::json::object());
    const nlohmann::json output = args.value("output", nlohmann::json::object());
    const std::string path = output.value("path", std::string());
    if (path.empty()) {
        throw Error("SCHEMA_INVALID", "output.path is required",
                    {{"path", "$.args.output.path"}});
    }
    const bool allow_absolute = output.value("allow_absolute_path", false);
    if (path[0] == '/' && !allow_absolute) {
        throw Error("OUTPUT_PATH_UNSAFE",
                    "absolute output path requires allow_absolute_path=true",
                    {{"path", path}});
    }
    const std::size_t slash = path.find_last_of('/');
    if (slash != std::string::npos && slash > 0) {
        ensure_directory(path.substr(0, slash));
    }
    sess.backend->save_exclusions(path);
    nlohmann::json summary_json = completeness_summary(0, 0);
    summary_json["session_id"] = sess.session_id;
    summary_json["output_mode"] = "file";
    return ok_response(req, summary_json, nlohmann::json::object());
}

namespace {

std::string make_temp_baseline(const char* prefix) {
    const char* configured = std::getenv("TMPDIR");
    std::string tmpl = configured != nullptr && *configured != '\0'
                           ? std::string(configured)
                           : std::string(P_tmpdir);
    if (tmpl.empty() || tmpl.back() != '/') tmpl.push_back('/');
    tmpl += prefix;
    tmpl += "XXXXXX";
    std::vector<char> buffer(tmpl.begin(), tmpl.end());
    buffer.push_back('\0');
    char* directory = ::mkdtemp(buffer.data());
    if (directory == nullptr) {
        throw Error("EXCLUSION_BASELINE_FAILED",
                    "cannot create a temporary exclusion baseline directory");
    }
    return std::string(directory) + "/baseline.el";
}

void remove_temp_baseline(const std::string& path) {
    if (path.empty()) return;
    ::unlink(path.c_str());
    const std::size_t slash = path.find_last_of('/');
    if (slash != std::string::npos && slash > 0) {
        ::rmdir(path.substr(0, slash).c_str());
    }
}

struct TempBaselineGuard {
    std::string path;
    explicit TempBaselineGuard(const char* prefix)
        : path(make_temp_baseline(prefix)) {}
    ~TempBaselineGuard() { remove_temp_baseline(path); }
    TempBaselineGuard(const TempBaselineGuard&) = delete;
    TempBaselineGuard& operator=(const TempBaselineGuard&) = delete;
};

bool parse_canonical_line(const std::string& text, int* out) {
    if (text.empty()) return false;
    std::size_t consumed = 0;
    long parsed = 0;
    try {
        parsed = std::stol(text, &consumed);
    } catch (const std::exception&) {
        return false;
    }
    if (consumed != text.size() || parsed <= 0 ||
        std::to_string(parsed) != text) {
        return false;
    }
    *out = static_cast<int>(parsed);
    return true;
}

std::string csv_escape(const std::string& value) {
    if (value.find_first_of(",\"\n") == std::string::npos) return value;
    std::string out = "\"";
    for (char ch : value) {
        if (ch == '"') out.push_back('"');
        out.push_back(ch);
    }
    out.push_back('"');
    return out;
}

} // namespace

nlohmann::json Dispatcher::action_csv_export(const nlohmann::json& req) {
    Session& sess = session(req);
    const nlohmann::json args = req.value("args", nlohmann::json::object());
    const std::string directory = args.value("directory", std::string());
    if (directory.empty()) {
        throw Error("SCHEMA_INVALID", "directory is required",
                    {{"path", "$.args.directory"}});
    }
    const bool allow_absolute = args.value("allow_absolute_path", false);
    if (directory[0] == '/' && !allow_absolute) {
        throw Error("OUTPUT_PATH_UNSAFE",
                    "absolute directory requires allow_absolute_path=true",
                    {{"path", directory}});
    }
    ensure_directory(directory);
    struct CsvKindSpec {
        const char* kind;
        const char* file;
        std::vector<std::string> header;
        std::vector<std::string> identity_fields;
    };
    const std::vector<CsvKindSpec> specs = {
        {"code",
         "code_exclusions.csv",
         {"scope", "metric", "line", "object", "bin", "reason"},
         {"scope", "metric", "line", "object", "bin"}},
        {"functional",
         "functional_exclusions.csv",
         {"scope", "line", "covergroup", "coverpoint", "cross", "bin",
          "reason"},
         {"scope", "line", "covergroup", "coverpoint", "cross", "bin"}},
        {"assertion",
         "assertion_exclusions.csv",
         {"scope", "line", "assertion", "assertion_kind", "reason"},
         {"scope", "line", "assertion", "assertion_kind"}},
        {"container",
         "container_exclusions.csv",
         {"target_kind", "scope", "covergroup", "item", "expansion_root",
          "reason"},
         {"target_kind", "scope", "covergroup", "item", "expansion_root"}},
    };
    auto join_identity = [](const std::vector<std::string>& fields) {
        std::string identity;
        for (const auto& field : fields) {
            identity += field;
            identity.push_back('\x1f');
        }
        return identity;
    };
    auto field_index = [&](const CsvKindSpec& spec, const std::string& name) {
        for (std::size_t index = 0; index < spec.header.size(); ++index) {
            if (spec.header[index] == name) return index;
        }
        return spec.header.size();
    };
    struct OutRow {
        std::string source_file;
        std::vector<std::string> fields;
    };
    std::map<std::string, std::vector<OutRow>> new_rows;
    auto push_row = [&](const std::string& kind, const std::string& source_file,
                        std::vector<std::string> fields) {
        new_rows[kind].push_back(OutRow{source_file, std::move(fields)});
    };
    for (const auto& item : sess.exclusion_records) {
        const ExclusionRecord& record = item.second;
        if (record.kind == "functional") {
            const std::string coverpoint =
                record.target_kind == "coverpoint" ? record.item : std::string();
            const std::string cross =
                record.target_kind == "cross" ? record.item : std::string();
            push_row("functional", record.source_file,
                     {record.scope, record.line, record.covergroup, coverpoint,
                      cross, record.bin, record.reason});
        } else if (record.kind == "assertion") {
            push_row("assertion", record.source_file,
                     {record.scope, record.line,
                      record.full_name.empty() ? record.name : record.full_name,
                      record.target_kind, record.reason});
        } else if (record.kind == "container") {
            if (record.target_kind == "instance" && record.recursive) {
                // Mirror Python's expand_xml_instances: a recursive instance
                // exclusion becomes one CSV row per real instance so a replay
                // covers the same subtree instead of only the root's leaves.
                bool expanded = false;
                for (const auto& scope : sess.backend->scopes()) {
                    if (scope.handle == nullptr ||
                        !is_descendant(scope.full_name, record.scope)) {
                        continue;
                    }
                    expanded = true;
                    push_row("container", record.source_file,
                             {record.target_kind, scope.full_name, "", "",
                              record.scope, record.reason});
                }
                if (!expanded) {
                    push_row("container", record.source_file,
                             {record.target_kind, record.scope, "", "",
                              record.scope, record.reason});
                }
            } else {
                push_row("container", record.source_file,
                         {record.target_kind, record.scope, record.covergroup,
                          record.item,
                          record.target_kind == "instance" ? record.scope
                                                           : std::string(),
                          record.reason});
            }
        } else {
            push_row("code", record.source_file,
                     {record.scope, record.metric, record.line, record.name,
                      record.bin, record.reason});
        }
    }
    if (sess.exclusion_records.empty()) {
        for (const auto& entry : sess.loaded_el_entries) {
            if (entry.annotation.empty()) continue;
            std::string metric;
            if (entry.object_kind == "Block") metric = "line";
            else if (entry.object_kind == "Toggle") metric = "toggle";
            else if (entry.object_kind == "Branch") metric = "branch";
            else if (entry.object_kind == "Condition") metric = "condition";
            else if (entry.object_kind == "Fsm" || entry.object_kind == "Transition")
                metric = "fsm";
            else if (entry.object_kind == "Assert") metric = "assert";
            else continue;
            push_row("code", "",
                     {entry.section_name, metric, entry.object_line, "", "",
                      entry.annotation});
        }
    }

    std::size_t added_rows = 0;
    std::size_t unexportable = 0;
    for (const auto& item : sess.exclusion_records) {
        const ExclusionRecord& record = item.second;
        const bool empty_target =
            (record.kind == "code" && record.name.empty() && record.line.empty()) ||
            (record.kind == "container" && record.target_kind.empty()) ||
            (record.kind == "functional" && record.covergroup.empty() &&
             record.item.empty()) ||
            (record.kind == "assertion" && record.full_name.empty());
        if (empty_target) ++unexportable;
    }

    // Build every output in memory first so a reason conflict leaves all four
    // files untouched (Python contract).
    auto render_fields = [](const std::vector<std::string>& fields) {
        std::string line;
        for (std::size_t index = 0; index < fields.size(); ++index) {
            if (index > 0) line.push_back(',');
            line += csv_escape(fields[index]);
        }
        line.push_back('\n');
        return line;
    };
    std::vector<std::pair<std::string, std::string>> outputs;
    std::vector<nlohmann::json> items;
    for (const auto& spec : specs) {
        const std::string target = directory + "/" + spec.file;
        std::map<std::string, std::string> identity_reason;
        std::vector<OutRow> existing_rows;
        if (file_exists(target)) {
            try {
                const CsvDocument existing = parse_csv(target);
                if (existing.header != spec.header) {
                    throw Error("EXCLUSION_CSV_INVALID",
                                "existing exclusion CSV header does not match "
                                "the current contract",
                                {{"path", target}});
                }
                for (const auto& row : existing.rows) {
                    if (row.fields.size() != spec.header.size()) {
                        throw Error("EXCLUSION_CSV_INVALID",
                                    "existing exclusion CSV row has the wrong "
                                    "field count",
                                    {{"path", target},
                                     {"line", row.line_number}});
                    }
                    std::vector<std::string> identity_values;
                    identity_values.push_back(row.source_file);
                    for (const auto& column : spec.identity_fields) {
                        identity_values.push_back(row.value(column));
                    }
                    const std::string identity = join_identity(identity_values);
                    const std::string reason =
                        row.value("reason");
                    auto seen = identity_reason.find(identity);
                    if (seen != identity_reason.end()) {
                        if (seen->second != reason) {
                            throw Error(
                                "EXCLUSION_REASON_CONFLICT",
                                "CSV already holds a different reason for the "
                                "same exclusion identity",
                                {{"existing_reason", seen->second},
                                 {"requested_reason", reason}});
                        }
                        continue;
                    }
                    identity_reason.emplace(identity, reason);
                    existing_rows.push_back(
                        OutRow{row.source_file, row.fields});
                }
            } catch (const Error& exc) {
                if (exc.code() != "CSV_INVALID") throw;
            }
        }
        std::vector<OutRow> added;
        for (const auto& row : new_rows[spec.kind]) {
            std::vector<std::string> identity_values;
            identity_values.push_back(row.source_file);
            for (const auto& column : spec.identity_fields) {
                identity_values.push_back(
                    row.fields[field_index(spec, column)]);
            }
            const std::string identity = join_identity(identity_values);
            const std::string reason =
                row.fields[field_index(spec, "reason")];
            auto seen = identity_reason.find(identity);
            if (seen != identity_reason.end()) {
                if (seen->second != reason) {
                    throw Error(
                        "EXCLUSION_REASON_CONFLICT",
                        "export would write two different reasons for the same "
                        "exclusion identity",
                        {{"existing_reason", seen->second},
                         {"requested_reason", reason}});
                }
                continue;
            }
            identity_reason.emplace(identity, reason);
            added.push_back(row);
        }

        std::string content;
        content += "# schema_version=xcov-" + std::string(spec.kind) +
                   "-exclusions.v1\n";
        content += "# coverage_kind=" + std::string(spec.kind) + "\n";
        for (std::size_t index = 0; index < spec.header.size(); ++index) {
            if (index > 0) content.push_back(',');
            content += spec.header[index];
        }
        content.push_back('\n');

        std::map<std::string, std::vector<const OutRow*>> groups;
        for (const auto& row : existing_rows) {
            groups[row.source_file].push_back(&row);
        }
        for (const auto& row : added) {
            groups[row.source_file].push_back(&row);
        }
        auto group_rows = groups.find(std::string());
        if (group_rows != groups.end()) {
            for (const OutRow* row : group_rows->second) {
                content += render_fields(row->fields);
            }
        }
        std::size_t group_count = groups.empty() ? 0 : groups.size();
        for (const auto& group : groups) {
            if (group.first.empty()) continue;
            content.push_back('\n');
            content += "# source_file=" + group.first + "\n";
            for (const OutRow* row : group.second) {
                content += render_fields(row->fields);
            }
        }
        outputs.emplace_back(target, std::move(content));
        added_rows += added.size();
        items.push_back({{"coverage_kind", spec.kind},
                         {"path", target},
                         {"status", "published"},
                         {"group_count", group_count},
                         {"record_count", existing_rows.size() +
                                              added.size()}});
    }
    for (const auto& output : outputs) write_file(output.first, output.second);
    sess.mark_reasons_persisted();
    nlohmann::json summary_json =
        completeness_summary(items.size(), items.size());
    summary_json["exported_session_record_count"] = sess.exclusion_records.size();
    summary_json["added_record_count"] = added_rows;
    summary_json["unexportable_session_record_count"] = unexportable;
    summary_json["el_reason_unknown"] = !sess.loaded_el_entries.empty();
    return ok_response(req, summary_json, {{"items", items}});
}

namespace {

struct CsvInputSpec {
    const char* kind;
    const char* file;
    std::vector<std::string> header;
};

const std::vector<CsvInputSpec>& csv_input_specs() {
    static const std::vector<CsvInputSpec> specs = {
        {"code",
         "code_exclusions.csv",
         {"scope", "metric", "line", "object", "bin", "reason"}},
        {"functional",
         "functional_exclusions.csv",
         {"scope", "line", "covergroup", "coverpoint", "cross", "bin",
          "reason"}},
        {"assertion",
         "assertion_exclusions.csv",
         {"scope", "line", "assertion", "assertion_kind", "reason"}},
        {"container",
         "container_exclusions.csv",
         {"target_kind", "scope", "covergroup", "item", "expansion_root",
          "reason"}},
    };
    return specs;
}

bool is_directory_path(const std::string& path) {
    struct stat info;
    return ::stat(path.c_str(), &info) == 0 && S_ISDIR(info.st_mode);
}

/// Parse and validate the four exclusion CSVs before any state mutation.
/// Missing code/functional/assertion files fail closed (container optional,
/// matching the Python reference); headers, schema versions and field counts
/// must match the closed contract.
std::map<std::string, CsvDocument> load_validated_csv_directory(
    const std::string& directory, bool require_all = true) {
    if (!is_directory_path(directory)) {
        throw Error("EXCLUSION_CSV_NOT_FOUND",
                    "exclusion CSV directory does not exist",
                    {{"path", directory}});
    }
    std::map<std::string, CsvDocument> documents;
    for (const auto& spec : csv_input_specs()) {
        const std::string path = directory + "/" + spec.file;
        if (!file_exists(path)) {
            if (!require_all || std::string(spec.kind) == "container") continue;
            throw Error("EXCLUSION_CSV_NOT_FOUND",
                        "required exclusion CSV does not exist",
                        {{"path", path}, {"coverage_kind", spec.kind}});
        }
        CsvDocument document = parse_csv(path);
        if (document.header != spec.header) {
            throw Error("EXCLUSION_CSV_INVALID",
                        "exclusion CSV header does not match the contract",
                        {{"path", path}, {"coverage_kind", spec.kind}});
        }
        const std::string expected_schema =
            "xcov-" + std::string(spec.kind) + "-exclusions.v1";
        if (document.schema_version != expected_schema ||
            document.coverage_kind != spec.kind) {
            throw Error("EXCLUSION_CSV_INVALID",
                        "exclusion CSV metadata does not match its file kind",
                        {{"path", path}, {"coverage_kind", spec.kind}});
        }
        for (const auto& row : document.rows) {
            if (row.fields.size() != spec.header.size()) {
                throw Error("EXCLUSION_CSV_INVALID",
                            "exclusion CSV row has the wrong field count",
                            {{"path", path}, {"line", row.line_number}});
            }
        }
        documents.emplace(spec.kind, std::move(document));
    }
    return documents;
}

} // namespace

nlohmann::json Dispatcher::action_csv_compile(const nlohmann::json& req) {
    Session& sess = session(req);
    const nlohmann::json args = req.value("args", nlohmann::json::object());
    const std::string directory = args.value("directory", std::string());
    std::string output_directory = args.value("output_directory", std::string());
    if (directory.empty()) {
        throw Error("SCHEMA_INVALID", "directory is required",
                    {{"path", "$.args.directory"}});
    }
    if (output_directory.empty()) output_directory = directory;
    // Validate every input before creating a baseline or touching any EL.
    const std::map<std::string, CsvDocument> validated_documents =
        load_validated_csv_directory(directory);
    ensure_directory(output_directory);
    // Snapshot the current exclusion state so a failed compile can roll back
    // instead of wiping pre-existing exclusions.
    TempBaselineGuard baseline_guard("xcov-compile-");
    const std::string& baseline_el = baseline_guard.path;
    try {
        sess.backend->save_exclusions(baseline_el);
        if (!file_exists(baseline_el)) {
            throw Error("EXCLUSION_BASELINE_FAILED",
                        "compiled exclusion baseline was not created");
        }
    } catch (const Error& exc) {
        throw Error("EXCLUSION_BASELINE_FAILED",
                    "cannot snapshot the current exclusion state before compile",
                    {{"cause_message", exc.message()}});
    }
    nlohmann::json items = nlohmann::json::array();
    struct KindFile {
        const char* kind;
        const char* file;
    };
    const KindFile kinds[] = {
        {"code", "code_exclusions.csv"},
        {"functional", "functional_exclusions.csv"},
        {"assertion", "assertion_exclusions.csv"},
        {"container", "container_exclusions.csv"},
    };
    const std::map<std::string, ExclusionRecord> baseline_records =
        sess.exclusion_records;
    bool records_changed = false;
    std::size_t applied_total = 0;
    std::size_t total_failed = 0;
    for (const auto& kind : kinds) {
        const std::string path = directory + "/" + kind.file;
        auto document_it = validated_documents.find(kind.kind);
        if (document_it == validated_documents.end()) continue;
        const CsvDocument& document = document_it->second;
        std::size_t applied = 0;
        std::size_t failed = 0;
        for (const auto& row : document.rows) {
            const std::string reason = row.value("reason");
            const std::string kind_name(kind.kind);
            const std::string scope = row.value("scope");
            const std::string line_text = row.value("line");
            if (kind_name == "container" || kind_name == "functional") {
                std::string target_kind = row.value("target_kind");
                std::string item;
                if (kind_name == "container") {
                    // Container CSV owns the explicit target_kind/item columns.
                    item = row.value("item");
                    if (target_kind.empty()) target_kind = "covergroup";
                } else if (target_kind.empty()) {
                    if (!row.value("cross").empty()) {
                        target_kind = "cross";
                        item = row.value("cross");
                    } else if (!row.value("coverpoint").empty()) {
                        target_kind = "coverpoint";
                        item = row.value("coverpoint");
                    } else {
                        target_kind = "covergroup";
                    }
                } else if (target_kind == "coverpoint") {
                    item = row.value("coverpoint");
                } else if (target_kind == "cross") {
                    item = row.value("cross");
                }
                const std::string covergroup = row.value("covergroup");
                ExclusionRecord record;
                record.kind = kind_name;
                record.reason = reason;
                record.scope = scope;
                record.target_kind = target_kind;
                record.covergroup = covergroup;
                record.item = item;
                record.bin = row.value("bin");
                record.line = line_text;
                record.source_file = row.source_file;
                if (target_kind == "instance") {
                    record.name = scope;
                    record.full_name = scope;
                } else {
                    record.name = !record.bin.empty()
                                      ? record.bin
                                      : (item.empty() ? covergroup : item);
                    record.full_name = scope + "." + record.name;
                }
                std::size_t changed = 0;
                if (target_kind == "instance") {
                    changed = sess.backend->exclude_scope(scope, false, reason);
                } else {
                    changed = sess.backend->exclude_functional(
                        scope, covergroup, target_kind, item, reason);
                }
                if (changed > 0) {
                    ++applied;
                    records_changed |= put_exclusion_record(sess, record);
                } else {
                    ++failed;
                }
                continue;
            }
            if (kind_name == "assertion") {
                std::string full_name = row.value("assertion");
                if (full_name.find('.') == std::string::npos && !scope.empty()) {
                    full_name = scope + "." + full_name;
                }
                if (sess.backend->exclude_assertion(full_name, true, reason)) {
                    ++applied;
                    ExclusionRecord record;
                    record.kind = "assertion";
                    record.reason = reason;
                    record.scope = scope;
                    record.line = line_text;
                    record.source_file = row.source_file;
                    record.target_kind = row.value("assertion_kind");
                    record.name = row.value("assertion");
                    record.full_name = full_name;
                    records_changed |= put_exclusion_record(sess, record);
                } else {
                    ++failed;
                }
                continue;
            }
            const std::string metric = row.value("metric");
            const std::string name = row.has("object")
                                         ? row.value("object")
                                         : row.value("bin");
            bool ok = false;
            if (metric == "line" && name.empty() && !line_text.empty()) {
                // CSV line selector: exclude the line-metric leaves on the
                // requested source line inside this scope.
                int line_no = 0;
                ok = parse_canonical_line(line_text, &line_no) &&
                     sess.backend->exclude_line(scope, line_no, reason,
                                                row.source_file) > 0;
            } else {
                ok = sess.backend->exclude_leaf(scope, metric, name, reason);
            }
            if (ok) {
                ++applied;
                ExclusionRecord record;
                record.kind = kind_name;
                record.reason = reason;
                record.scope = scope;
                record.metric = metric;
                record.line = line_text;
                record.source_file = row.source_file;
                record.name = name;
                record.bin = row.value("bin");
                record.full_name = scope + "." + name;
                records_changed |= put_exclusion_record(sess, record);
            } else {
                ++failed;
            }
        }
        applied_total += applied;
        total_failed += failed;
        items.push_back({{"status", failed == 0 ? "compiled" : "partial"},
                         {"path", path},
                         {"record_count", applied}});
    }
    if (total_failed > 0) {
        // Contract: a partial compile must not publish artifacts; restore the
        // pre-compile snapshot instead of clearing everything.
        sess.backend->unload_exclusions();
        try {
            sess.backend->load_exclusions(baseline_el);
        } catch (const Error& exc) {
            sess.exclusion_records = baseline_records;
            throw Error("EXCLUSION_ROLLBACK_FAILED",
                        "compile failed and the pre-compile baseline could not "
                        "be restored",
                        {{"cause_message", exc.message()}});
        }
        sess.exclusion_records = baseline_records;
        throw Error("EXCLUSION_RESOLVE_FAILED",
                    "every CSV record must resolve exactly once before compile; "
                    "no artifacts were published",
                    {{"failed_count", total_failed}});
    }
    if (records_changed) sess.mark_reason_mutation();
    sess.mark_reasons_persisted();
    const std::string code_el = output_directory + "/code.el";
    sess.backend->save_exclusions(code_el);
    for (const char* extra : {"functional.el", "assertion.el", "container.el"}) {
        write_file(output_directory + "/" + extra, std::string());
        items.push_back({{"status", "published"},
                         {"path", output_directory + "/" + extra},
                         {"record_count", 0}});
    }
    items.push_back({{"status", "published"},
                     {"path", code_el},
                     {"record_count", applied_total}});
    return ok_response(req, completeness_summary(items.size(), items.size()),
                       {{"items", items}});
}

nlohmann::json Dispatcher::action_exclude_container(const nlohmann::json& req) {
    Session& sess = session(req);
    const std::string action = req.value("action", std::string());
    const nlohmann::json args = req.value("args", nlohmann::json::object());
    const bool adding = action.size() > 4 &&
                        action.compare(action.size() - 4, 4, ".add") == 0;
    const bool instance_action = action.find(".instance.") != std::string::npos;
    if (!args.contains("items") || !args.at("items").is_array()) {
        throw Error("SCHEMA_INVALID", "items is required",
                    {{"path", "$.args.items"}});
    }
    nlohmann::json items = nlohmann::json::array();
    bool records_changed = false;
    for (const auto& item : args.at("items")) {
        const std::string scope = item.value("scope", std::string());
        const std::string reason = item.value("reason", std::string());
        nlohmann::json row = nlohmann::json::object();
        row["coverage_ref"] = "container:" + scope;
        ExclusionRecord record;
        record.kind = "container";
        record.scope = scope;
        record.reason = reason;
        if (instance_action) {
            record.target_kind = "instance";
            record.name = scope;
            record.full_name = scope;
            const bool recursive = item.value("recursive", false);
            record.recursive = recursive;
            const std::size_t changed =
                adding ? sess.backend->exclude_scope(scope, recursive, reason)
                       : sess.backend->restore_scope(scope, recursive);
            row["status"] = changed > 0 ? "changed" : "already_in_state";
            row["target_count"] = changed;
        } else {
            record.target_kind = item.value("target_kind", std::string());
            record.covergroup = item.value("covergroup", std::string());
            record.item = item.value("item", std::string());
            record.name = record.item.empty() ? record.covergroup : record.item;
            record.full_name = scope + "." + record.name;
            const std::size_t changed = sess.backend->exclude_functional(
                scope, record.covergroup, record.target_kind, record.item,
                reason, adding);
            row["status"] = changed > 0 ? "changed" : "already_in_state";
            row["target_count"] = changed;
        }
        if (row["status"] == "changed") {
            if (adding) {
                records_changed |= put_exclusion_record(sess, record);
            } else {
                const std::string key = exclusion_record_key(record);
                if (sess.exclusion_records.erase(key) > 0) records_changed = true;
            }
        }
        items.push_back(row);
    }
    if (records_changed) sess.mark_reason_mutation();
    return ok_response(req, completeness_summary(items.size(), items.size()),
                       {{"items", items}});
}

namespace {

struct CsvKindFile {
    const char* kind;
    const char* file;
};

const CsvKindFile kCsvKindFiles[] = {
    {"code", "code_exclusions.csv"},
    {"functional", "functional_exclusions.csv"},
    {"assertion", "assertion_exclusions.csv"},
    {"container", "container_exclusions.csv"},
};

} // namespace

nlohmann::json Dispatcher::action_csv_validate(const nlohmann::json& req) {
    Session& sess = session(req);
    (void)sess;
    const nlohmann::json args = req.value("args", nlohmann::json::object());
    const std::string directory = args.value("directory", std::string());
    if (directory.empty()) {
        throw Error("SCHEMA_INVALID", "directory is required",
                    {{"path", "$.args.directory"}});
    }
    nlohmann::json items = nlohmann::json::array();
    std::size_t total_rows = 0;
    std::size_t total_errors = 0;
    for (const auto& kind : kCsvKindFiles) {
        const std::string path = directory + "/" + kind.file;
        if (!file_exists(path)) continue;
        const CsvDocument document = parse_csv(path);
        total_rows += document.rows.size();
        const std::string kind_name(kind.kind);
        const std::vector<std::string> required_columns =
            kind_name == "code"
                ? std::vector<std::string>{"scope", "metric", "object"}
                : kind_name == "functional"
                      ? std::vector<std::string>{"scope", "covergroup"}
                      : kind_name == "assertion"
                            ? std::vector<std::string>{"scope", "assertion"}
                            : std::vector<std::string>{"target_kind", "scope"};
        for (const auto& column : required_columns) {
            bool present = false;
            for (const auto& header : document.header) {
                if (header == column) present = true;
            }
            if (!present) {
                ++total_errors;
                items.push_back(
                    {{"status", "error"},
                     {"message", "missing required column '" + column +
                                     "' in " + std::string(kind.file)}});
            }
        }
        for (const auto& row : document.rows) {
            bool row_ok = true;
            for (const auto& column : required_columns) {
                if (!row.value(column).empty()) continue;
                // object may be empty when the selector uses a source line;
                // the line value is validated below.
                if (column == "object" && !row.value("line").empty()) continue;
                row_ok = false;
            }
            if (row_ok && kind_name == "code") {
                const std::string metric = row.value("metric");
                static const std::set<std::string> kCodeMetrics = {
                    "line", "toggle", "branch", "condition", "fsm"};
                if (kCodeMetrics.find(metric) == kCodeMetrics.end()) {
                    row_ok = false;
                } else if (metric == "line" && row.value("object").empty()) {
                    int parsed_line = 0;
                    if (!parse_canonical_line(row.value("line"), &parsed_line)) {
                        row_ok = false;
                    }
                }
            }
            if (row_ok && (kind_name == "container" ||
                           kind_name == "functional")) {
                const std::string target_kind = row.value("target_kind");
                if (!target_kind.empty()) {
                    static const std::set<std::string> kContainerKinds = {
                        "instance", "covergroup", "coverpoint", "cross"};
                    if (kContainerKinds.find(target_kind) ==
                        kContainerKinds.end()) {
                        row_ok = false;
                    }
                }
            }
            if (!row_ok) {
                ++total_errors;
                items.push_back(
                    {{"status", "error"},
                     {"message", std::string("required column is empty or invalid at line ") +
                                     std::to_string(row.line_number)}});
            }
        }
    }
    nlohmann::json summary_json =
        completeness_summary(items.size(), items.size());
    return ok_response(req, summary_json, {{"items", items}});
}

nlohmann::json Dispatcher::action_csv_apply(const nlohmann::json& req) {
    Session& sess = session(req);
    const nlohmann::json args = req.value("args", nlohmann::json::object());
    const std::string directory = args.value("directory", std::string());
    if (directory.empty()) {
        throw Error("SCHEMA_INVALID", "directory is required",
                    {{"path", "$.args.directory"}});
    }
    const std::map<std::string, CsvDocument> validated_documents =
        load_validated_csv_directory(directory);
    TempBaselineGuard baseline_guard("xcov-apply-");
    const std::string& baseline_el = baseline_guard.path;
    try {
        sess.backend->save_exclusions(baseline_el);
        if (!file_exists(baseline_el)) {
            throw Error("EXCLUSION_BASELINE_FAILED",
                        "apply exclusion baseline was not created");
        }
    } catch (const Error& exc) {
        throw Error("EXCLUSION_BASELINE_FAILED",
                    "cannot snapshot the current exclusion state before apply",
                    {{"cause_message", exc.message()}});
    }
    const std::map<std::string, ExclusionRecord> baseline_records =
        sess.exclusion_records;
    nlohmann::json items = nlohmann::json::array();
    bool records_changed = false;
    std::size_t total_failed = 0;
    for (const auto& kind : kCsvKindFiles) {
        auto document_it = validated_documents.find(kind.kind);
        if (document_it == validated_documents.end()) continue;
        const CsvDocument& document = document_it->second;
        for (const auto& row : document.rows) {
            const std::string reason = row.value("reason");
            const std::string scope = row.value("scope");
            const std::string kind_name(kind.kind);
            const std::string line_text = row.value("line");
            bool row_ok = false;
            ExclusionRecord record;
            record.kind = kind_name;
            record.reason = reason;
            record.scope = scope;
            record.line = line_text;
            record.source_file = row.source_file;
            if (kind_name == "container" || kind_name == "functional") {
                std::string target_kind = row.value("target_kind");
                std::string item;
                if (kind_name == "container") {
                    item = row.value("item");
                    if (target_kind.empty()) target_kind = "covergroup";
                } else if (target_kind.empty()) {
                    if (!row.value("cross").empty()) {
                        target_kind = "cross";
                        item = row.value("cross");
                    } else if (!row.value("coverpoint").empty()) {
                        target_kind = "coverpoint";
                        item = row.value("coverpoint");
                    } else {
                        target_kind = "covergroup";
                    }
                } else if (target_kind == "coverpoint") {
                    item = row.value("coverpoint");
                } else if (target_kind == "cross") {
                    item = row.value("cross");
                }
                const std::string covergroup = row.value("covergroup");
                record.target_kind = target_kind;
                record.covergroup = covergroup;
                record.item = item;
                record.bin = row.value("bin");
                if (target_kind == "instance") {
                    record.name = scope;
                    record.full_name = scope;
                } else {
                    record.name = !record.bin.empty()
                                      ? record.bin
                                      : (item.empty() ? covergroup : item);
                    record.full_name = scope + "." + record.name;
                }
                if (target_kind == "instance") {
                    row_ok = sess.backend->exclude_scope(scope, false, reason) > 0;
                } else {
                    row_ok = sess.backend->exclude_functional(
                                 scope, covergroup, target_kind, item, reason) > 0;
                }
            } else if (kind_name == "assertion") {
                std::string full_name = row.value("assertion");
                if (full_name.find('.') == std::string::npos && !scope.empty()) {
                    full_name = scope + "." + full_name;
                }
                record.target_kind = row.value("assertion_kind");
                record.name = row.value("assertion");
                record.full_name = full_name;
                row_ok = sess.backend->exclude_assertion(full_name, true, reason);
            } else {
                const std::string metric = row.value("metric");
                const std::string name = row.has("object")
                                             ? row.value("object")
                                             : row.value("bin");
                record.metric = metric;
                record.name = name;
                record.bin = row.value("bin");
                record.full_name = scope + "." + name;
                if (metric == "line" && name.empty() && !line_text.empty()) {
                    int line_no = 0;
                    row_ok = parse_canonical_line(line_text, &line_no) &&
                             sess.backend->exclude_line(scope, line_no, reason,
                                                        row.source_file) > 0;
                } else {
                    row_ok = sess.backend->exclude_leaf(scope, metric, name, reason);
                }
            }
            if (row_ok) {
                records_changed |= put_exclusion_record(sess, record);
            } else {
                ++total_failed;
            }
            items.push_back({{"coverage_ref", nullptr},
                             {"status", row_ok ? "changed" : "invalid"}});
        }
    }
    if (total_failed > 0) {
        sess.backend->unload_exclusions();
        try {
            sess.backend->load_exclusions(baseline_el);
        } catch (const Error& exc) {
            sess.exclusion_records = baseline_records;
            throw Error("EXCLUSION_ROLLBACK_FAILED",
                        "apply failed and the pre-apply baseline could not be "
                        "restored",
                        {{"cause_message", exc.message()}});
        }
        sess.exclusion_records = baseline_records;
        throw Error("EXCLUSION_RESOLVE_FAILED",
                    "every CSV record must resolve exactly once before apply; "
                    "the request was rolled back",
                    {{"failed_count", total_failed}});
    }
    if (records_changed) sess.mark_reason_mutation();
    return ok_response(req, completeness_summary(items.size(), items.size()),
                       {{"items", items}});
}

nlohmann::json Dispatcher::action_csv_format(const nlohmann::json& req) {
    const nlohmann::json args = req.value("args", nlohmann::json::object());
    const std::string directory = args.value("directory", std::string());
    const bool write = args.value("write", false);
    nlohmann::json items = nlohmann::json::array();
    if (!directory.empty()) {
        const std::map<std::string, CsvDocument> validated =
            load_validated_csv_directory(directory, false);
        for (const auto& kind : kCsvKindFiles) {
            auto document_it = validated.find(kind.kind);
            if (document_it == validated.end()) continue;
            const std::string path = directory + "/" + kind.file;
            const CsvDocument& document = document_it->second;
            std::ostringstream out;
            out << "# schema_version=" << document.schema_version << "\n";
            out << "# coverage_kind=" << document.coverage_kind << "\n";
            for (std::size_t index = 0; index < document.header.size(); ++index) {
                if (index > 0) out << ",";
                out << document.header[index];
            }
            out << "\n";
            auto emit_row = [&](const CsvRow& row) {
                for (std::size_t index = 0; index < row.fields.size(); ++index) {
                    if (index > 0) out << ",";
                    out << csv_escape_field(row.fields[index]);
                }
                out << "\n";
            };
            std::string kind_name(kind.kind);
            std::map<std::string, std::vector<const CsvRow*>> groups;
            for (const auto& row : document.rows) {
                groups[kind_name == "container" ? std::string()
                                                : row.source_file]
                    .push_back(&row);
            }
            auto ungrouped = groups.find(std::string());
            if (ungrouped != groups.end()) {
                for (const CsvRow* row : ungrouped->second) emit_row(*row);
            }
            for (const auto& group : groups) {
                if (group.first.empty()) continue;
                out << "\n# source_file=" << group.first << "\n";
                for (const CsvRow* row : group.second) emit_row(*row);
            }
            if (write) write_file(path, out.str());
            items.push_back({{"status", "formatted"},
                             {"path", path},
                             {"record_count", document.rows.size()}});
        }
    }
    return ok_response(req, completeness_summary(items.size(), items.size()),
                       {{"items", items}});
}

nlohmann::json Dispatcher::action_metrics_list(const nlohmann::json& req) {
    Session& sess = session(req);
    const nlohmann::json args = req.value("args", nlohmann::json::object());
    const std::string scope_filter = args.value("scope", std::string());
    // Python aggregates only the roots of its per-scope metric map. In this
    // backend the equivalent source is the deep (subtree) aggregate of a real
    // scope: synthetic generate levels have no metrics of their own, and an
    // unknown name simply contributes nothing.
    std::vector<const ScopeInfo*> roots;
    if (!scope_filter.empty()) {
        const ScopeInfo* scope = sess.backend->find_scope(scope_filter);
        if (scope != nullptr && scope->handle != nullptr) roots.push_back(scope);
    } else {
        for (const auto& root_name : sess.backend->top_scopes()) {
            const ScopeInfo* root = sess.backend->find_scope(root_name);
            if (root != nullptr) roots.push_back(root);
        }
    }
    std::map<std::string, MetricAggregate> totals;
    for (const ScopeInfo* root : roots) {
        for (const auto& item : root->deep_metrics) {
            if (root->deep_present.find(item.first) ==
                root->deep_present.end()) {
                continue;
            }
            MetricAggregate& entry = totals[metric_key(item.first)];
            entry.covered += item.second.covered;
            entry.coverable += item.second.coverable;
        }
    }
    std::vector<nlohmann::json> rows;
    rows.reserve(totals.size());
    for (const auto& item : totals) {
        const long covered = item.second.covered;
        const long coverable = item.second.coverable;
        rows.push_back({
            {"metric", item.first},
            {"covered", covered},
            {"coverable", coverable},
            {"missing", coverable > covered ? coverable - covered : 0},
            {"coverage_pct", coverable > 0
                                 ? nlohmann::json(py_round(
                                       100.0 * static_cast<double>(covered) /
                                           static_cast<double>(coverable), 4))
                                 : nlohmann::json(nullptr)},
        });
    }
    const OutputSlice slice = apply_output("metrics.list", args, rows);
    nlohmann::json summary_json = slice.summary;
    summary_json["session_id"] = sess.session_id;
    summary_json["scope"] = scope_filter.empty() ? nlohmann::json(nullptr)
                                                 : nlohmann::json(scope_filter);
    summary_json["test"] = "merged";
    return ok_response(req, summary_json, {{"items", rows_json(slice.rows)}});
}

} // namespace xcov
