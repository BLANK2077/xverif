#include "action_support.h"

#include <cctype>
#include <cstring>
#include <set>
#include <utility>

namespace xdebug_design {

namespace {

int find_top_level_op(const std::string& s, const std::string& op) {
    int depth = 0;
    for (int i = static_cast<int>(s.size()) - static_cast<int>(op.size()); i >= 0; --i) {
        char c = s[i];
        if (c == ')') depth++;
        else if (c == '(') depth--;
        if (depth == 0 && s.compare(i, op.size(), op) == 0) return i;
    }
    return -1;
}

json parse_atom(const std::string& text) {
    std::string s = trim(text);
    if (s.empty()) return {{"type", "unknown"}, {"text", ""}};
    if (s.size() >= 2 && s.front() == '(' && s.back() == ')') {
        return parse_expr_ast(s.substr(1, s.size() - 2));
    }
    if (s[0] == '!') {
        return {{"op", "not"}, {"args", json::array({parse_expr_ast(s.substr(1))})}};
    }
    bool numeric_or_const = false;
    for (char c : s) {
        if (std::isdigit(static_cast<unsigned char>(c)) || c == '\'' || c == 'h' || c == 'b' || c == 'd' ||
            c == 'x' || c == 'z' || c == '_' || c == '-') {
            numeric_or_const = true;
        } else {
            numeric_or_const = false;
            break;
        }
    }
    if (numeric_or_const || s == "RUN" || s == "IDLE" || s == "BUSY") {
        return {{"type", "const"}, {"value", s}};
    }
    return {{"type", "signal"}, {"name", s}};
}

void collect_ast_signals(const json& node, std::set<std::string>& signals) {
    if (!node.is_object()) return;
    std::string kind = node.value("kind", node.value("type", ""));
    if (kind == "signal") {
        std::string name = node.value("name", "");
        if (!name.empty()) signals.insert(name);
    }
    if (node.contains("base_signal") && node["base_signal"].is_string()) {
        std::string name = node["base_signal"].get<std::string>();
        if (!name.empty()) signals.insert(name);
    }
    for (const auto& item : node.items()) {
        if (item.value().is_object()) collect_ast_signals(item.value(), signals);
        if (item.value().is_array()) {
            for (const auto& elem : item.value()) collect_ast_signals(elem, signals);
        }
    }
}

std::string rhs_from_source(const std::string& source) {
    std::string s = trim(source);
    size_t eq = std::string::npos;
    size_t le = s.find("<=");
    if (le != std::string::npos) eq = le + 1;
    else eq = s.find('=');
    if (eq == std::string::npos) return "";
    std::string rhs = s.substr(eq + 1);
    size_t semi = rhs.rfind(';');
    if (semi != std::string::npos) rhs = rhs.substr(0, semi);
    return trim(rhs);
}

std::string assignment_kind_from_source(const std::string& source) {
    std::string s = trim(source);
    if (starts_with(s, "assign ")) return "continuous_assign";
    if (s.find("<=") != std::string::npos) return "clocked_update";
    if (s.find("=") != std::string::npos) return "procedural_assignment";
    return "statement_only";
}

std::string confidence_for_trace(const json& trace) {
    if (!trace.value("ok", true)) return "unknown";
    if (trace.value("has_statement_only", false)) return "low";
    int count = trace.value("result_count", 0);
    if (count <= 0 && trace.value("control_dependency_count", 0) <= 0) return "unknown";
    for (const auto& r : trace.value("results", json::array())) {
        if (!r.value("source", "").empty()) return "high";
    }
    return "medium";
}

} // namespace

ExprSyntaxValidation validate_expr_syntax(const std::string& expr) {
    ExprSyntaxValidation result;
    std::string s = trim(expr);
    if (s.empty()) {
        result.ok = false;
        result.message = "expression is empty";
        return result;
    }
    int depth = 0;
    int question_depth = 0;
    for (size_t i = 0; i < s.size(); ++i) {
        const char c = s[i];
        if (c == '(') ++depth;
        else if (c == ')') {
            if (depth == 0) {
                result.ok = false;
                result.message = "unmatched closing parenthesis";
                result.offset = i;
                return result;
            }
            --depth;
        } else if (c == '?') {
            ++question_depth;
        } else if (c == ':' && question_depth > 0) {
            --question_depth;
        }
    }
    if (depth != 0) {
        result.ok = false;
        result.message = "unmatched opening parenthesis";
        result.offset = s.size() - 1;
        return result;
    }
    if (question_depth != 0) {
        result.ok = false;
        result.message = "ternary expression is missing ':' branch";
        result.offset = s.size() - 1;
        return result;
    }
    static const char* const dangling_ops[] = {
        "||", "&&", "!=", "==", ">=", "<=", ">", "<", "+", "-", "*", "?", ":"
    };
    for (const char* op : dangling_ops) {
        const size_t n = std::strlen(op);
        if (s.size() >= n && s.compare(s.size() - n, n, op) == 0) {
            result.ok = false;
            result.message = "expression ends with operator '" + std::string(op) + "'";
            result.offset = s.size() - n;
            return result;
        }
    }
    return result;
}

json parse_expr_ast(const std::string& expr) {
    std::string s = trim(expr);
    if (s.empty()) return {{"type", "unknown"}, {"text", ""}};
    int qpos = find_top_level_op(s, "?");
    if (qpos >= 0) {
        int depth = 0;
        for (size_t i = qpos + 1; i < s.size(); ++i) {
            if (s[i] == '(') depth++;
            else if (s[i] == ')') depth--;
            else if (s[i] == ':' && depth == 0) {
                return {{"op", "ternary"},
                        {"args", json::array({parse_expr_ast(s.substr(0, qpos)),
                                               parse_expr_ast(s.substr(qpos + 1, i - qpos - 1)),
                                               parse_expr_ast(s.substr(i + 1))})}};
            }
        }
    }
    const std::vector<std::pair<std::string, std::string>> ops = {
        {"||", "or"}, {"&&", "and"}, {"!=", "neq"}, {"==", "eq"},
        {">=", "ge"}, {"<=", "le"}, {">", "gt"}, {"<", "lt"},
        {"+", "add"}, {"-", "sub"}, {"*", "mul"}
    };
    for (const auto& item : ops) {
        int pos = find_top_level_op(s, item.first);
        if (pos > 0) {
            return {{"op", item.second},
                    {"args", json::array({parse_expr_ast(s.substr(0, pos)),
                                           parse_expr_ast(s.substr(pos + item.first.size()))})}};
        }
    }
    return parse_atom(s);
}

std::string expr_op(const json& expr) {
    return expr.is_object() ? expr.value("op", "") : "";
}

bool expr_mentions_signal(const json& expr, const std::string& signal) {
    std::set<std::string> signals;
    collect_ast_signals(expr, signals);
    std::string target_leaf = leaf_name(signal);
    for (const auto& name : signals) {
        if (name == signal || leaf_name(name) == target_leaf) return true;
    }
    return false;
}

json signal_array_from_ast(const json& expr) {
    std::set<std::string> signals;
    collect_ast_signals(expr, signals);
    json out = json::array();
    for (const auto& name : signals) out.push_back(name);
    return out;
}

json enrich_trace_payload(const json& request, const json& trace) {
    json out = trace;
    std::string query = trace.value("query", request.value("args", json::object()).value("signal", ""));
    std::string mode = trace.value("mode", "driver");
    json rhs_signals = json::array();
    json edges = json::array();
    json records = trace.value("results", json::array());
    for (const auto& r : records) {
        std::string signal = r.value("signal", "");
        std::string role = r.value("role", "");
        std::string resolution = r.value("resolution", "");
        if (!signal.empty() && resolution != "statement_only") rhs_signals.push_back(signal);
        std::string edge_type = resolution == "statement_only" ? "statement_only" : "data_dependency";
        if (role == "lhs_target") edge_type = "load_dependency";
        edges.push_back({
            {"from", mode == "driver" ? signal : query}, {"to", mode == "driver" ? query : signal},
            {"type", edge_type}, {"role", role}, {"file", r.value("file", "")},
            {"line", r.value("line", 0)}, {"source", r.value("source", "")},
            {"resolution", resolution}, {"confidence", edge_type == "statement_only" ? "low" : "high"}
        });
    }
    for (const auto& r : trace.value("control_dependencies", json::array())) {
        const bool evidence_complete = r.at("evidence_complete").get<bool>();
        edges.push_back({
            {"from", r.value("signal", "")}, {"to", query}, {"type", "control_dependency"},
            {"relation", "controls_assignment"}, {"file", r.value("file", "")},
            {"line", r.value("line", 0)}, {"source", r.value("source", "")},
            {"resolution", r.value("resolution", "")},
            {"evidence_kind", r.at("evidence_kind").get<std::string>()},
            {"evidence_complete", evidence_complete},
            {"confidence", evidence_complete ? "medium" : "low"}
        });
    }
    std::string confidence = confidence_for_trace(trace);
    out["rhs_signals"] = rhs_signals;
    out["dependency_edges"] = edges;
    out["confidence"] = confidence;
    out["confidence_reason"] =
        confidence == "high" ? "exact signal references with source locations were resolved" :
        confidence == "medium" ? "trace records were resolved but structured expression is incomplete" :
        confidence == "low" ? "trace contains unresolved statement_only records" :
        "no reliable trace result was resolved";
    if (!records.empty()) {
        std::string source = records[0].value("source", "");
        std::string rhs = rhs_from_source(source);
        if (!rhs.empty()) {
            out["assignment"] = {{"kind", assignment_kind_from_source(source)},
                {"lhs", {{"type", "signal"}, {"name", query}}},
                {"rhs", parse_expr_ast(rhs)}, {"source", source},
                {"ast_confidence", "heuristic"}};
        }
    }
    return out;
}

json make_trace_summary(const json& trace) {
    return {{"query", trace.value("query", "")}, {"mode", trace.value("mode", "")},
        {"result_count", trace.value("result_count", 0)},
        {"control_dependency_count", trace.value("control_dependency_count", 0)},
        {"analysis_complete", trace.value("analysis_complete", false)},
        {"confidence", trace.value("confidence", "unknown")}};
}

} // namespace xdebug_design
