#include "actions/dispatch.h"

#include "api/protocol.h"
#include "api/schema.h"
#include "core/errors.h"
#include "coverage/coverage_ref.h"
#include "exclusion/csv_parser.h"
#include "exclusion/el_parser.h"
#include "core/fs.h"
#include <cstdio>
#include <cstdlib>
#include <cctype>
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
        contract.handler == "_tests_list" || contract.handler == "_functional" ||
        contract.handler == "_assert_report" || contract.handler == "_exclude" ||
        contract.handler == "_exclude_container" ||
        contract.handler == "_exclude_csv_apply" ||
        contract.handler == "_exclude_csv_compile" ||
        contract.handler == "_exclude_csv_export" ||
        contract.handler == "_export_exclude" ||
        contract.handler == "_exclude_load" ||
        contract.handler == "_exclude_unload_all") {
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
        {"run_manifest", nullptr},
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
    return ok_response(req, completeness_summary(1, 1),
                       {{"session", session_json}});
}

nlohmann::json Dispatcher::action_tests_list(const nlohmann::json& req) {
    Session& sess = session(req);
    nlohmann::json items = nlohmann::json::array();
    for (const auto& name : sess.backend->test_names()) {
        const std::size_t slash = name.rfind('/');
        items.push_back({{"name", slash == std::string::npos ? name : name.substr(slash + 1)}});
    }
    nlohmann::json filters = {
        {"exclude", nlohmann::json::array()},
        {"include", nlohmann::json::array()},
        {"match_field", "name"},
    };
    return ok_response(req, completeness_summary(items.size(), items.size()),
                       {{"filters", filters}, {"items", items}});
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

std::size_t limit_max_items(const std::string& action, const nlohmann::json& args) {
    if (!args.contains("limits") || !args.at("limits").is_object()) {
        return action_default_limit(action);
    }
    const nlohmann::json& limits = args.at("limits");
    if (!limits.contains("max_items") || limits.at("max_items").is_null()) {
        return action_default_limit(action);
    }
    return limits.at("max_items").get<std::size_t>();
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

nlohmann::json scope_row(const ScopeInfo& scope, bool summary) {
    nlohmann::json row = nlohmann::json::object();
    row["name"] = scope.name;
    row["full_name"] = scope.full_name;
    std::vector<double> percentages;
    for (const auto kind : {MetricKind::Line, MetricKind::Toggle, MetricKind::Branch,
                            MetricKind::Condition, MetricKind::Fsm,
                            MetricKind::Assert, MetricKind::Functional}) {
        auto it = scope.deep_metrics.find(kind);
        if (it == scope.deep_metrics.end() || it->second.coverable <= 0) {
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
    return row;
}

} // namespace

nlohmann::json Dispatcher::action_scope(const nlohmann::json& req) {
    Session& sess = session(req);
    const std::string action = req.value("action", std::string());
    const nlohmann::json args = req.value("args", nlohmann::json::object());
    const std::string scope = args.value("scope", std::string());
    const bool recursive = args.value("recursive", false);
    const bool summary = action == "scope.summary";

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

    const nlohmann::json query = args.value("query", nlohmann::json::object());
    std::vector<std::string> include_patterns;
    std::vector<std::string> exclude_patterns;
    const std::string match_field = query.value("match_field", std::string("full_name"));
    if (query.contains("include_patterns")) {
        for (const auto& item : query.at("include_patterns")) {
            include_patterns.push_back(item.get<std::string>());
        }
    }
    if (query.contains("exclude_patterns")) {
        for (const auto& item : query.at("exclude_patterns")) {
            exclude_patterns.push_back(item.get<std::string>());
        }
    }

    std::vector<nlohmann::json> rows;
    for (const ScopeInfo* row : selected) {
        const std::string field =
            match_field == "name" ? row->name : row->full_name;
        if (!include_patterns.empty()) {
            bool matched = false;
            for (const auto& pattern : include_patterns) {
                if (glob_match(pattern, field)) { matched = true; break; }
            }
            if (!matched) continue;
        }
        bool excluded = false;
        for (const auto& pattern : exclude_patterns) {
            if (glob_match(pattern, field)) { excluded = true; break; }
        }
        if (excluded) continue;
        rows.push_back(scope_row(*row, summary));
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
    const std::size_t total = rows.size();
    const std::size_t max_items = limit_max_items(action, args);
    bool truncated = false;
    if (max_items > 0 && rows.size() > max_items) {
        rows.resize(max_items);
        truncated = true;
    }
    nlohmann::json items = nlohmann::json::array();
    for (const auto& row : rows) items.push_back(row);
    nlohmann::json filters = {
        {"exclude", exclude_patterns},
        {"include", include_patterns},
        {"match_field", match_field},
    };
    nlohmann::json summary_json = completeness_summary(
        total, items.size(), truncated, true, true,
        truncated ? std::vector<std::string>{"data.items"} : std::vector<std::string>());
    summary_json["session_id"] = sess.session_id;
    summary_json["scope"] = scope.empty() ? nlohmann::json(nullptr) : nlohmann::json(scope);
    summary_json["test"] = "merged";
    return ok_response(req, summary_json, {{"filters", filters}, {"items", items}});
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
        for (MetricKind kind : metrics) totals[kind] = MetricAggregate();
        for (const auto& root_name : sess.backend->top_scopes()) {
            const ScopeInfo* root = sess.backend->find_scope(root_name);
            if (root == nullptr) continue;
            for (MetricKind kind : metrics) {
                auto it = root->deep_metrics.find(kind);
                if (it == root->deep_metrics.end()) continue;
                totals[kind].covered += it->second.covered;
                totals[kind].coverable += it->second.coverable;
            }
        }
        for (MetricKind kind : metrics) rows.push_back(code_metric_row(kind, totals[kind]));
    } else {
        for (const auto& scope : sess.backend->scopes()) {
            if (!scope_filter.empty() && !is_descendant(scope.full_name, scope_filter)) {
                continue;
            }
            nlohmann::json row = nlohmann::json::object();
            row["scope"] = scope.full_name;
            row["metric"] = "summary";
            std::vector<double> percentages;
            MetricAggregate only;
            bool single = metrics.size() == 1;
            for (MetricKind kind : metrics) {
                auto it = scope.deep_metrics.find(kind);
                if (it == scope.deep_metrics.end() || it->second.coverable <= 0) continue;
                percentages.push_back(metric_pct(it->second));
                if (single) only = it->second;
            }
            if (percentages.empty()) {
                row["coverage_pct"] = nullptr;
            } else {
                double total = 0.0;
                for (double value : percentages) total += value;
                row["coverage_pct"] = py_round(total / percentages.size(), 4);
            }
            if (single) {
                row["covered"] = only.covered;
                row["coverable"] = only.coverable;
                row["missing"] = only.missing();
            }
            rows.push_back(row);
        }
    }

    std::stable_sort(rows.begin(), rows.end(),
                     [](const nlohmann::json& a, const nlohmann::json& b) {
                         return a.value("covergroup", std::string()) <
                                b.value("covergroup", std::string());
                     });
    const std::size_t total = rows.size();
    const std::size_t max_items = limit_max_items(action, args);
    bool truncated = false;
    if (max_items > 0 && rows.size() > max_items) {
        rows.resize(max_items);
        truncated = true;
    }
    nlohmann::json items = nlohmann::json::array();
    for (const auto& row : rows) items.push_back(row);
    nlohmann::json filters = {
        {"exclude", nlohmann::json::array()},
        {"include", nlohmann::json::array()},
        {"match_field", group_by},
    };
    nlohmann::json summary_json = completeness_summary(
        total, items.size(), truncated, true, true,
        truncated ? std::vector<std::string>{"data.items"} : std::vector<std::string>());
    summary_json["session_id"] = sess.session_id;
    summary_json["scope"] = scope_filter.empty() ? nlohmann::json(nullptr)
                                                 : nlohmann::json(scope_filter);
    summary_json["test"] = "merged";
    summary_json["metrics"] = nlohmann::json::array();
    for (MetricKind kind : metrics) summary_json["metrics"].push_back(metric_key(kind));
    return ok_response(req, summary_json, {{"filters", filters}, {"items", items}});
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
    const std::size_t total = matched.size();
    const std::size_t max_items = limit_max_items(action, args);
    bool truncated = false;
    if (max_items > 0 && matched.size() > max_items) {
        matched.resize(max_items);
        truncated = true;
    }
    nlohmann::json items = nlohmann::json::array();
    for (const auto* group : matched) {
        nlohmann::json row = nlohmann::json::object();
        row["covergroup"] = group->full_name;
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
        items.push_back(row);
    }
    nlohmann::json filters = {
        {"exclude", nlohmann::json::array()},
        {"include", nlohmann::json::array()},
        {"match_field", group_by},
    };
    nlohmann::json summary_json = completeness_summary(
        total, items.size(), truncated, true, true,
        truncated ? std::vector<std::string>{"data.items"} : std::vector<std::string>());
    summary_json["session_id"] = sess.session_id;
    summary_json["test"] = "merged";
    return ok_response(req, summary_json, {{"filters", filters}, {"items", items}});
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
    const std::size_t total = matched.size();
    const std::size_t max_items = limit_max_items(action, args);
    bool truncated = false;
    if (max_items > 0 && matched.size() > max_items) {
        matched.resize(max_items);
        truncated = true;
    }
    nlohmann::json items = nlohmann::json::array();
    for (const auto* item : matched) {
        const long success = item->type == 1 ? item->all_successes : item->real_successes;
        const long covered = success > 0 ? 1 : 0;
        nlohmann::json row = nlohmann::json::object();
        row["name"] = item->name;
        row["full_name"] = item->full_name;
        row["covered"] = covered;
        row["coverable"] = 1;
        row["missing"] = 1 - covered;
        row["coverage_pct"] = covered > 0 ? 100.0 : 0.0;
        row["status"] = nlohmann::json::array({covered > 0 ? "covered" : "not_covered"});
        row["attempts"] = item->attempts;
        row["real_successes"] = success;
        row["without_attempts"] = item->attempts == 0 ? 1 : 0;
        items.push_back(row);
    }
    nlohmann::json filters = {
        {"exclude", nlohmann::json::array()},
        {"include", nlohmann::json::array()},
        {"match_field", "full_name"},
    };
    nlohmann::json summary_json = completeness_summary(
        total, items.size(), truncated, true, true,
        truncated ? std::vector<std::string>{"data.items"} : std::vector<std::string>());
    summary_json["session_id"] = sess.session_id;
    summary_json["scope"] = scope_filter.empty() ? nlohmann::json(nullptr)
                                                 : nlohmann::json(scope_filter);
    summary_json["test"] = "merged";
    return ok_response(req, summary_json, {{"filters", filters}, {"items", items}});
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
        int index = 0;
        for (const auto& item : sess.backend->assertions()) {
            const long success =
                item.type == 1 ? item.all_successes : item.real_successes;
            if (success > 0) continue;
            ++index;
            const std::size_t dot = item.full_name.rfind('.');
            nlohmann::json gap = nlohmann::json::object();
            gap["gap_id"] = "A" + std::string(4 - std::min<std::size_t>(4, std::to_string(index).size()), '0') + std::to_string(index);
            gap["scope"] = dot == std::string::npos
                               ? std::string()
                               : item.full_name.substr(0, dot);
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
        write_file(json_path, payload.dump(2) + "\n");
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
            if (scope == nullptr) continue;
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
                                               gap.metric, gap.name);
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
                if (deep != scope->deep_metrics.end()) {
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
                        for (long k = 0; k < group.missing_gaps; ++k) {
                            ++covered_object_gaps;
                            char gap_id[16];
                            std::snprintf(gap_id, sizeof gap_id, "B%04d",
                                          covered_object_gaps);
                            const std::string pattern =
                                group.arms.empty()
                                    ? std::string()
                                    : group.arms[static_cast<std::size_t>(k) %
                                                 group.arms.size()]
                                          .pattern;
                            uncovered.push_back(
                                {{"gap_id", gap_id},
                                 {"values", pattern},
                                 {"status", "not_covered"}});
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
                write_file(dir + "/" + name, payload.dump(2) + "\n");
                write_file(dir + "/" + std::string(metric) + ".xout",
                           "@xcov.code_coverage." + std::string(metric) +
                               ".v1\n\ngaps: " + std::to_string(rows.size()) + "\n");
                metrics_meta.push_back({{"metric", metric},
                                        {"json", name},
                                        {"xout", std::string(metric) + ".xout"},
                                        {"raw", "../raw/modinfo.urg.txt"}});
            }
            write_file(dir + "/navigation.json",
                       nlohmann::json({{"scope", scope_name}}).dump(2) + "\n");
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
        for (const auto& item : sess.backend->functional_gaps()) {
            const std::string scope_filter = args.value("scope", std::string());
            if (!scope_filter.empty() && !is_descendant(item.scope, scope_filter)) {
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
        write_file(json_path, payload.dump(2) + "\n");
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

nlohmann::json Dispatcher::action_exclude(const nlohmann::json& req) {
    Session& sess = session(req);
    const std::string action = req.value("action", std::string());
    const nlohmann::json args = req.value("args", nlohmann::json::object());
    nlohmann::json items = nlohmann::json::array();

    if (action == "exclude.load") {
        const nlohmann::json paths = args.value("paths", nlohmann::json::array());
        for (const auto& path_value : paths) {
            const std::string path = path_value.get<std::string>();
            sess.backend->load_exclusions(path);
            const ElDocument document = parse_el(path);
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
        sess.backend->unload_exclusions();
        items.push_back({{"status", "changed"},
                         {"before_count", 0},
                         {"after_count", 0}});
        return ok_response(req, completeness_summary(items.size(), items.size()),
                           {{"items", items}});
    }
    const bool adding = action == "exclude.add";
    const nlohmann::json refs =
        args.value("coverage_refs", nlohmann::json::array());
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
            const bool applied =
                sess.backend->set_exclusion(ref, adding, reason);
            item["status"] = applied ? "changed" : "invalid";
            item["error"] = nullptr;
            if (applied && adding) {
                item["reason"] = reason;
                ExclusionRecord record;
                record.coverage_ref = ref;
                record.reason = reason;
                sess.backend->locator_for_ref(ref, &record.scope, &record.metric,
                                              &record.name);
                record.full_name = record.scope + "." + record.name;
                sess.exclusion_records[ref] = record;
            } else if (applied) {
                sess.exclusion_records.erase(ref);
            }
        } catch (const Error& exc) {
            item["status"] = "failed";
            item["error"] = exc.message();
        }
        items.push_back(item);
    }
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
    sess.backend->save_exclusions(path);
    nlohmann::json summary_json = completeness_summary(0, 0);
    summary_json["session_id"] = sess.session_id;
    summary_json["output_mode"] = "file";
    return ok_response(req, summary_json, nlohmann::json::object());
}

namespace {

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
    std::ostringstream code;
    code << "# schema_version=xcov-code-exclusions.v1\n";
    code << "# coverage_kind=code\n";
    code << "scope,metric,line,object,bin,reason\n";
    for (const auto& item : sess.exclusion_records) {
        const ExclusionRecord& record = item.second;
        code << csv_escape(record.scope) << "," << record.metric << ",,"
             << csv_escape(record.name) << ",,"
             << csv_escape(record.reason) << "\n";
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
            code << csv_escape(entry.section_name) << "," << metric << ",,"
                 << csv_escape(entry.object_line) << ",,"
                 << csv_escape(entry.annotation) << "\n";
        }
    }
    write_file(directory + "/code_exclusions.csv", code.str());
    const std::pair<const char*, const char*> empty_files[] = {
        {"functional_exclusions.csv",
         "# schema_version=xcov-functional-exclusions.v1\n"
         "# coverage_kind=functional\n"
         "scope,line,covergroup,coverpoint,cross,bin,reason\n"},
        {"assertion_exclusions.csv",
         "# schema_version=xcov-assertion-exclusions.v1\n"
         "# coverage_kind=assertion\n"
         "scope,line,assertion,assertion_kind,reason\n"},
        {"container_exclusions.csv",
         "# schema_version=xcov-container-exclusions.v1\n"
         "# coverage_kind=container\n"
         "target_kind,scope,covergroup,item,expansion_root,reason\n"},
    };
    for (const auto& entry : empty_files) {
        write_file(directory + "/" + entry.first, entry.second);
    }
    nlohmann::json items = nlohmann::json::array();
    items.push_back({{"status", "exported"},
                     {"path", directory},
                     {"record_count", sess.exclusion_records.size()}});
    return ok_response(req, completeness_summary(items.size(), items.size()),
                       {{"items", items}});
}

nlohmann::json Dispatcher::action_csv_compile(const nlohmann::json& req) {
    Session& sess = session(req);
    const nlohmann::json args = req.value("args", nlohmann::json::object());
    const std::string directory = args.value("directory", std::string());
    const std::string output_directory =
        args.value("output_directory", std::string());
    if (directory.empty()) {
        throw Error("SCHEMA_INVALID", "directory is required",
                    {{"path", "$.args.directory"}});
    }
    ensure_directory(output_directory);
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
    std::size_t applied_total = 0;
    for (const auto& kind : kinds) {
        const std::string path = directory + "/" + kind.file;
        if (!file_exists(path)) continue;
        const CsvDocument document = parse_csv(path);
        std::size_t applied = 0;
        std::size_t failed = 0;
        for (const auto& row : document.rows) {
            const std::string reason = row.value("reason");
            if (std::string(kind.kind) == "container") {
                const std::string target_kind = row.value("target_kind");
                const std::string scope = row.value("scope");
                if (target_kind == "instance") {
                    const std::size_t changed = sess.backend->exclude_scope(
                        scope, false, reason);
                    if (changed > 0) {
                        ++applied;
                    } else {
                        ++failed;
                    }
                } else {
                    const std::size_t changed = sess.backend->exclude_functional(
                        scope, row.value("covergroup"), target_kind,
                        row.value("item"), reason);
                    if (changed > 0) {
                        ++applied;
                    } else {
                        ++failed;
                    }
                }
                continue;
            }
            const std::string scope = row.value("scope");
            const std::string metric = row.value("metric");
            const std::string name = row.has("object") ? row.value("object")
                                                       : row.value("assertion");
            if (sess.backend->exclude_leaf(scope, metric, name, reason)) {
                ++applied;
                ExclusionRecord record;
                record.reason = reason;
                record.scope = scope;
                record.metric = metric;
                record.name = name;
                record.full_name = scope + "." + name;
                sess.exclusion_records[record.full_name] = record;
            } else {
                ++failed;
            }
        }
        applied_total += applied;
        items.push_back({{"status", failed == 0 ? "compiled" : "partial"},
                         {"path", path},
                         {"record_count", applied}});
    }
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
    for (const auto& item : args.at("items")) {
        const std::string scope = item.value("scope", std::string());
        const std::string reason = item.value("reason", std::string());
        nlohmann::json row = nlohmann::json::object();
        row["coverage_ref"] = "container:" + scope;
        if (instance_action) {
            const bool recursive = item.value("recursive", false);
            const std::size_t changed =
                adding ? sess.backend->exclude_scope(scope, recursive, reason)
                       : sess.backend->restore_scope(scope, recursive);
            row["status"] = changed > 0 ? "changed" : "already_in_state";
            row["target_count"] = changed;
        } else {
            const std::string target_kind =
                item.value("target_kind", std::string());
            const std::size_t changed = adding
                ? sess.backend->exclude_functional(
                      scope, item.value("covergroup", std::string()),
                      target_kind, item.value("item", std::string()), reason)
                : 0;
            row["status"] = changed > 0 ? "changed" : "already_in_state";
            row["target_count"] = changed;
        }
        items.push_back(row);
    }
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
                      ? std::vector<std::string>{"scope", "covergroup", "bin"}
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
                // object/metric may be empty when the selector uses line/bin
                if (column == "object" && !row.value("line").empty()) continue;
                if (column == "metric" && !row.value("bin").empty()) continue;
                row_ok = false;
            }
            if (!row_ok) {
                ++total_errors;
                items.push_back(
                    {{"status", "error"},
                     {"message", std::string("required column is empty at line ") +
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
    nlohmann::json items = nlohmann::json::array();
    for (const auto& kind : kCsvKindFiles) {
        const std::string path = directory + "/" + kind.file;
        if (!file_exists(path)) continue;
        const CsvDocument document = parse_csv(path);
        std::size_t applied = 0;
        std::size_t failed = 0;
        for (const auto& row : document.rows) {
            const std::string reason = row.value("reason");
            const std::string scope = row.value("scope");
            if (std::string(kind.kind) == "container") {
                if (row.value("target_kind") == "instance") {
                    if (sess.backend->exclude_scope(scope, false, reason) > 0) {
                        ++applied;
                    } else {
                        ++failed;
                    }
                } else {
                    ++failed;
                }
                continue;
            }
            const std::string metric = row.value("metric");
            const std::string name =
                row.has("object") ? row.value("object") : row.value("assertion");
            if (sess.backend->exclude_leaf(scope, metric, name, reason)) {
                ++applied;
            } else {
                ++failed;
            }
        }
        items.push_back({{"status", failed == 0 ? "compiled" : "partial"},
                         {"path", path},
                         {"record_count", applied}});
    }
    return ok_response(req, completeness_summary(items.size(), items.size()),
                       {{"items", items}});
}

nlohmann::json Dispatcher::action_csv_format(const nlohmann::json& req) {
    const nlohmann::json args = req.value("args", nlohmann::json::object());
    const std::string directory = args.value("directory", std::string());
    const bool write = args.value("write", false);
    nlohmann::json items = nlohmann::json::array();
    if (!directory.empty()) {
        for (const auto& kind : kCsvKindFiles) {
            const std::string path = directory + "/" + kind.file;
            if (!file_exists(path)) continue;
            const CsvDocument document = parse_csv(path);
            std::ostringstream out;
            out << "# schema_version=" << document.schema_version << "\n";
            out << "# coverage_kind=" << document.coverage_kind << "\n";
            for (std::size_t index = 0; index < document.header.size(); ++index) {
                if (index > 0) out << ",";
                out << document.header[index];
            }
            out << "\n";
            for (const auto& row : document.rows) {
                for (std::size_t index = 0; index < row.fields.size(); ++index) {
                    if (index > 0) out << ",";
                    out << csv_escape_field(row.fields[index]);
                }
                out << "\n";
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
    std::map<std::string, std::pair<long, long>> totals;
    for (const auto& scope : sess.backend->scopes()) {
        for (const auto& item : scope.metrics) {
            auto& entry = totals[metric_key(item.first)];
            entry.first += item.second.covered;
            entry.second += item.second.coverable;
        }
    }
    const MetricAggregate assert_totals = sess.backend->assert_totals();
    const MetricAggregate functional_totals = sess.backend->functional_totals();
    totals["assert"] = {assert_totals.covered, assert_totals.coverable};
    totals["functional"] = {functional_totals.covered, functional_totals.coverable};
    nlohmann::json items = nlohmann::json::array();
    for (const auto& item : totals) {
        const long covered = item.second.first;
        const long coverable = item.second.second;
        items.push_back({
            {"metric", item.first},
            {"covered", covered},
            {"coverable", coverable},
            {"missing", coverable > covered ? coverable - covered : 0},
            {"coverage_pct", coverable > 0 ? 100.0 * covered / coverable : 0.0},
        });
    }
    return ok_response(req, completeness_summary(items.size(), items.size()),
                       {{"items", items}});
}

} // namespace xcov
