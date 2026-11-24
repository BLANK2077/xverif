#include "api/protocol.h"

#include "api/schema.h"
#include "core/errors.h"

#include <algorithm>
#include <cmath>
#include <sstream>

namespace xcov {

namespace {

const std::string kActionTokenChars =
    "abcdefghijklmnopqrstuvwxyz"
    "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    "0123456789"
    "._-";

std::string scalar(const nlohmann::json& value) {
    if (value.is_null()) return "null";
    if (value.is_boolean()) return value.get<bool>() ? "true" : "false";
    if (value.is_string()) return value.get<std::string>();
    if (value.is_array()) {
        std::ostringstream out;
        bool first = true;
        for (const auto& item : value) {
            if (!first) out << ",";
            out << scalar(item);
            first = false;
        }
        return out.str();
    }
    if (value.is_object()) return value.dump();
    if (value.is_number_integer()) return std::to_string(value.get<long long>());
    if (value.is_number_unsigned()) return std::to_string(value.get<unsigned long long>());
    if (value.is_number_float()) {
        std::ostringstream out;
        out.precision(17);
        out << value.get<double>();
        std::string text = out.str();
        // Trim a trailing ".0" so 1.0 renders like Python's str(1.0).
        return text;
    }
    return value.dump();
}

nlohmann::json flatten_item(const nlohmann::json& item) {
    nlohmann::json flat = nlohmann::json::object();
    for (auto it = item.begin(); it != item.end(); ++it) {
        const std::string key = it.key();
        const nlohmann::json& value = it.value();
        if (key == "evidence" && value.is_object()) {
            for (const char* field : {"file", "line"}) {
                if (value.contains(field) && !value.at(field).is_null()) {
                    flat[field] = value.at(field);
                }
            }
        } else if ((key == "evidence_source" || key == "branch_mask" ||
                    key == "toggle_0_to_1" || key == "toggle_1_to_0") &&
                   value.is_object()) {
            for (auto nested = value.begin(); nested != value.end(); ++nested) {
                flat[key + "." + nested.key()] = nested.value();
            }
        } else if ((key == "annotations" || key == "bits") && value.is_array()) {
            flat[key + "_count"] = value.size();
        } else {
            flat[key] = value;
        }
    }
    return flat;
}

std::vector<std::string> render_table(const nlohmann::json& items,
                                      const std::string& indent) {
    std::vector<nlohmann::json> rows;
    for (const auto& item : items) {
        if (item.is_object()) rows.push_back(flatten_item(item));
    }
    if (rows.empty()) return {};
    std::vector<std::string> columns;
    for (const auto& row : rows) {
        for (auto it = row.begin(); it != row.end(); ++it) {
            if (std::find(columns.begin(), columns.end(), it.key()) == columns.end()) {
                columns.push_back(it.key());
            }
        }
    }
    std::vector<std::vector<std::string>> values;
    std::map<std::string, std::size_t> widths;
    for (const auto& column : columns) widths[column] = column.size();
    for (const auto& row : rows) {
        std::vector<std::string> cells;
        for (const auto& column : columns) {
            const std::string cell = row.contains(column) ? scalar(row.at(column)) : "";
            widths[column] = std::max(widths[column], cell.size());
            cells.push_back(cell);
        }
        values.push_back(std::move(cells));
    }
    auto line = [&](const std::vector<std::string>* cells) {
        std::ostringstream out;
        out << indent;
        for (std::size_t i = 0; i < columns.size(); ++i) {
            if (i > 0) out << "  ";
            const std::string text = cells == nullptr ? columns[i] : (*cells)[i];
            out << text;
            if (text.size() < widths[columns[i]]) {
                out << std::string(widths[columns[i]] - text.size(), ' ');
            }
        }
        std::string rendered = out.str();
        while (!rendered.empty() && rendered.back() == ' ') rendered.pop_back();
        return rendered;
    };
    std::vector<std::string> out{line(nullptr)};
    for (const auto& cells : values) out.push_back(line(&cells));
    return out;
}

const std::vector<std::string> kScopeColumns = {
    "name", "full_name", "covered", "coverable", "missing", "coverage_pct"};
const std::vector<std::pair<std::string, std::string>> kScopeMetrics = {
    {"line", "line_pct"},
    {"toggle", "toggle_pct"},
    {"branch", "branch_pct"},
    {"condition", "condition_pct"},
    {"fsm", "fsm_pct"},
    {"assert", "assert_pct"},
    {"functional", "functional_pct"},
};

std::string render_human_xout(const nlohmann::json& rsp,
                              const std::string& action,
                              bool include_envelope) {
    std::vector<std::string> lines;
    const bool ok = rsp.value("ok", false);
    const std::string status = ok ? "ok" : "error";
    const std::string rid = rsp.value("request_id", std::string("req-unknown"));
    if (include_envelope) {
        lines.push_back("@xcov.v1 " + status + " action=" + action +
                        " request_id=" + rid);
    } else {
        lines.push_back("@xcov." + action + ".v1");
    }
    lines.push_back("");
    if (!ok) {
        lines.push_back("error:");
        if (rsp.contains("error") && rsp.at("error").is_object()) {
            for (auto it = rsp.at("error").begin(); it != rsp.at("error").end(); ++it) {
                lines.push_back("  " + it.key() + ": " + scalar(it.value()));
            }
        }
    } else {
        lines.push_back("summary:");
        if (rsp.contains("summary") && rsp.at("summary").is_object()) {
            for (auto it = rsp.at("summary").begin(); it != rsp.at("summary").end(); ++it) {
                lines.push_back("  " + it.key() + ": " + scalar(it.value()));
            }
        }
        const nlohmann::json& data =
            rsp.contains("data") ? rsp.at("data") : nlohmann::json::object();
        if (data.is_object() && data.contains("filters") && data.at("filters").is_object()) {
            lines.push_back("");
            lines.push_back("filters:");
            for (auto it = data.at("filters").begin(); it != data.at("filters").end(); ++it) {
                lines.push_back("  " + it.key() + ": " + scalar(it.value()));
            }
        }
        if (data.is_object() && data.contains("sections") && data.at("sections").is_object()) {
            lines.push_back("");
            lines.push_back("sections:");
            for (auto it = data.at("sections").begin(); it != data.at("sections").end(); ++it) {
                lines.push_back("  " + it.key() + ":");
                if (it.value().is_array()) {
                    bool all_objects = true;
                    for (const auto& item : it.value()) {
                        if (!item.is_object()) { all_objects = false; break; }
                    }
                    if (all_objects) {
                        for (const auto& line : render_table(it.value(), "    ")) {
                            lines.push_back(line);
                        }
                    } else {
                        for (const auto& item : it.value()) {
                            lines.push_back("    - " + scalar(item));
                        }
                    }
                } else {
                    lines.push_back("    " + scalar(it.value()));
                }
            }
        }
        if (data.is_object() && data.contains("items") && data.at("items").is_array()) {
            const nlohmann::json& items = data.at("items");
            lines.push_back("");
            lines.push_back("items:");
            bool all_objects = true;
            for (const auto& item : items) {
                if (!item.is_object()) { all_objects = false; break; }
            }
            if (all_objects) {
                if (action == "scope.summary") {
                    nlohmann::json projected = nlohmann::json::array();
                    for (const auto& row : items) {
                        nlohmann::json projected_row = nlohmann::json::object();
                        for (const auto& column : kScopeColumns) {
                            if (row.contains(column)) projected_row[column] = row.at(column);
                        }
                        projected.push_back(projected_row);
                    }
                    for (const auto& line : render_table(projected, "  ")) {
                        lines.push_back(line);
                    }
                    nlohmann::json coverage = nlohmann::json::array();
                    for (const auto& row : items) {
                        for (const auto& metric : kScopeMetrics) {
                            if (row.contains(metric.second) &&
                                !row.at(metric.second).is_null()) {
                                nlohmann::json entry = {
                                    {"metric", metric.first},
                                    {"coverage_pct", row.at(metric.second)},
                                };
                                if (items.size() > 1) {
                                    entry["full_name"] = row.value("full_name", "");
                                }
                                coverage.push_back(entry);
                            }
                        }
                    }
                    if (!coverage.empty()) {
                        lines.push_back("");
                        lines.push_back("coverage:");
                        for (const auto& line : render_table(coverage, "  ")) {
                            lines.push_back(line);
                        }
                    }
                } else {
                    for (const auto& line : render_table(items, "  ")) {
                        lines.push_back(line);
                    }
                }
            } else {
                for (const auto& item : items) {
                    lines.push_back("  - " + scalar(item));
                }
            }
        }
    }
    if (rsp.contains("warnings") && rsp.at("warnings").is_array() &&
        !rsp.at("warnings").empty()) {
        lines.push_back("");
        lines.push_back("warnings:");
        for (const auto& item : rsp.at("warnings")) {
            lines.push_back("  - " + scalar(item));
        }
    }
    while (!lines.empty() && lines.back().empty()) lines.pop_back();
    std::ostringstream out;
    for (std::size_t i = 0; i < lines.size(); ++i) {
        if (i > 0) out << "\n";
        out << lines[i];
    }
    out << "\n";
    return out.str();
}

std::string validated_response_action(const nlohmann::json& rsp) {
    if (!rsp.is_object()) {
        throw Error("RESPONSE_SCHEMA_INVALID", "response must be an object",
                    {{"path", "$"}});
    }
    const std::string action = rsp.value("action", std::string());
    if (action.empty()) {
        throw Error("RESPONSE_SCHEMA_INVALID",
                    "response action must be a non-empty string",
                    {{"path", "$.action"}});
    }
    SchemaCatalog::instance().validate_response(action, rsp);
    return action;
}

} // namespace

nlohmann::json parse_request(const std::string& text) {
    nlohmann::json req;
    try {
        req = nlohmann::json::parse(text);
    } catch (const std::exception& exc) {
        throw Error("INVALID_JSON", exc.what());
    }
    if (!req.is_object()) {
        throw Error("SCHEMA_INVALID", "request must be a JSON object",
                    {{"path", "$"}});
    }
    if (req.value("api_version", std::string()) != kApiVersion) {
        throw Error("API_VERSION_UNSUPPORTED", "api_version must be xcov.v1",
                    {{"path", "$.api_version"}});
    }
    validate_action_token(req.contains("action") ? req.at("action") : nlohmann::json());
    return req;
}

std::string validate_action_token(const nlohmann::json& action) {
    if (!action.is_string()) {
        throw Error("SCHEMA_INVALID",
                    "action must be a non-empty header-safe token using [A-Za-z0-9_.-]",
                    {{"path", "$.action"}});
    }
    const std::string text = action.get<std::string>();
    if (text.empty() ||
        text.find_first_not_of(kActionTokenChars) != std::string::npos) {
        throw Error("SCHEMA_INVALID",
                    "action must be a non-empty header-safe token using [A-Za-z0-9_.-]",
                    {{"path", "$.action"}});
    }
    return text;
}

nlohmann::json normalize_request(const nlohmann::json& req) {
    nlohmann::json normalized = req;
    if (!normalized.contains("request_id")) normalized["request_id"] = "req-unknown";
    if (!normalized.contains("target")) normalized["target"] = nlohmann::json::object();
    if (!normalized.contains("args")) normalized["args"] = nlohmann::json::object();
    return normalized;
}

nlohmann::json completeness_summary(
    std::size_t total_count,
    std::size_t returned_count,
    bool response_truncated,
    bool scan_complete,
    bool analysis_complete,
    const std::vector<std::string>& truncation_scopes) {
    nlohmann::json summary = nlohmann::json::object();
    summary["total_count"] = total_count;
    summary["returned_count"] = returned_count;
    summary["response_truncated"] = response_truncated;
    summary["scan_complete"] = scan_complete;
    summary["analysis_complete"] = analysis_complete;
    summary["truncation_scopes"] = truncation_scopes;
    return summary;
}

nlohmann::json ok_response(const nlohmann::json& req,
                           const nlohmann::json& summary,
                           const nlohmann::json& data,
                           const std::vector<std::string>& warnings) {
    nlohmann::json rsp = nlohmann::json::object();
    rsp["ok"] = true;
    rsp["api_version"] = kApiVersion;
    rsp["request_id"] = req.value("request_id", std::string("req-unknown"));
    rsp["action"] = req.value("action", std::string());
    rsp["summary"] = summary;
    rsp["data"] = data;
    rsp["warnings"] = warnings;
    return rsp;
}

std::string json_dumps(const nlohmann::json& value) {
    return value.dump(-1, ' ', false, nlohmann::json::error_handler_t::strict);
}

std::string render_xout(const nlohmann::json& rsp) {
    const std::string action = validated_response_action(rsp);
    return render_human_xout(rsp, action, true);
}

std::string render_transport_xout(const nlohmann::json& rsp) {
    const std::string action = validated_response_action(rsp);
    return render_human_xout(rsp, action, false);
}

} // namespace xcov
