#include "api/xout_renderer.h"

#include "api/text_response_builder.h"

#include <algorithm>
#include <set>
#include <string>
#include <vector>

namespace xdebug {

namespace {

bool has_scalar(const Json& object, const std::string& key) {
    return object.is_object() && object.contains(key) &&
           xdebug::is_xout_scalar_json(object[key]);
}

bool should_emit_scalar_key(const std::string& key, const Json& value) {
    if (key == "known" && value.is_boolean() && value.get<bool>()) return false;
    return xdebug::is_xout_scalar_json(value);
}

std::string scalar_text(const Json& object, const std::string& key) {
    if (!has_scalar(object, key)) return std::string();
    return json_to_xout_value(object[key]);
}

void emit_summary(TextResponseBuilder& out, const Json& response) {
    if (!response.contains("summary") || !response["summary"].is_object()) return;
    out.emit_section("summary");
    for (auto it = response["summary"].begin(); it != response["summary"].end(); ++it) {
        if (should_emit_scalar_key(it.key(), it.value())) out.emit_kv(it.key(), it.value());
    }
}

void emit_warnings(TextResponseBuilder& out, const Json& response) {
    if (!response.contains("warnings") || !response["warnings"].is_array()) return;
    std::vector<std::vector<std::string>> rows;
    for (const auto& warning : response["warnings"]) {
        if (warning.is_string()) {
            rows.push_back({"warning", warning.get<std::string>()});
        } else if (warning.is_object()) {
            rows.push_back({
                scalar_text(warning, "code").empty() ? "warning" : scalar_text(warning, "code"),
                scalar_text(warning, "message").empty() ? warning.dump() : scalar_text(warning, "message")
            });
        }
    }
    if (!rows.empty()) {
        out.emit_section("warnings");
        out.emit_table({"code", "message"}, rows);
    }
}

void emit_suggestions(TextResponseBuilder& out, const Json& response) {
    if (!response.contains("suggested_next_actions") ||
        !response["suggested_next_actions"].is_array()) return;
    out.emit_section("next");
    for (const auto& item : response["suggested_next_actions"]) {
        if (item.is_string()) {
            out.emit_row({item.get<std::string>()});
        } else if (item.is_object()) {
            std::string action = scalar_text(item, "action");
            std::string reason = scalar_text(item, "reason");
            if (action.empty()) action = item.dump();
            out.emit_row({action, reason});
        }
    }
}

void emit_common_blocks(TextResponseBuilder& out, const Json& response) {
    const Json data = response.value("data", Json::object());
    if (!data.is_object() || !data.contains("common_blocks") ||
        !data["common_blocks"].is_array() || data["common_blocks"].empty()) {
        return;
    }
    out.emit_section("common_blocks");
    for (const auto& item : data["common_blocks"]) {
        if (!item.is_object()) continue;
        std::string message = scalar_text(item, "message");
        std::string file = scalar_text(item, "file");
        std::string card = scalar_text(item, "card");
        if (!message.empty()) out.emit_row({message});
        if (!file.empty()) out.emit_kv("file", file);
        if (!card.empty()) out.emit_kv("card", card);
    }
}

void render_data_value(TextResponseBuilder& out, const std::string& key,
                       const Json& value) {
    if (should_emit_scalar_key(key, value)) {
        out.emit_kv(key, value);
    } else if (value.is_array() && value.empty()) {
        out.emit_kv(key, "[empty]");
    } else if (value.is_array() && !value.empty() &&
               xdebug::is_xout_scalar_json(value[0])) {
        out.emit_section(key);
        for (const auto& item : value)
            out.emit_row({json_to_xout_value(item)});
    } else if (value.is_array() && !value.empty() && value[0].is_object()) {
        out.emit_section(key);
        out.emit_json_table(value, static_cast<int>(value.size()));
    } else if (value.is_object()) {
        bool has_direct_fields = false;
        for (auto it = value.begin(); it != value.end(); ++it) {
            if (should_emit_scalar_key(it.key(), it.value()) ||
                (it.value().is_array() && it.value().empty())) {
                if (!has_direct_fields) out.emit_section(key);
                if (should_emit_scalar_key(it.key(), it.value()))
                    out.emit_kv(it.key(), it.value());
                else
                    out.emit_kv(it.key(), "[empty]");
                has_direct_fields = true;
            }
        }
        for (auto it = value.begin(); it != value.end(); ++it) {
            if (should_emit_scalar_key(it.key(), it.value()) ||
                (it.value().is_array() && it.value().empty())) continue;
            render_data_value(out, key + "." + it.key(), it.value());
        }
    }
}

void render_generic(TextResponseBuilder& out, const Json& response) {
    emit_summary(out, response);
    const Json data = response.value("data", Json::object());
    if (data.is_object() && !data.empty()) {
        out.emit_section("data");
        for (auto it = data.begin(); it != data.end(); ++it) {
            if (it.key() == "common_blocks") continue;
            render_data_value(out, it.key(), it.value());
        }
    }
    if (response.contains("findings") && response["findings"].is_array() &&
        !response["findings"].empty()) {
        render_data_value(out, "findings", response["findings"]);
    }
}

} // namespace

std::string render_xout_response(const Json& response,
                                 const std::string& handler_xout) {
    if (response.value("ok", false) && !handler_xout.empty()) {
        std::string text = handler_xout;
        while (!text.empty() && text.back() == '\n') text.pop_back();
        text.push_back('\n');
        return text;
    }
    if (response.value("ok", false) && response.contains("text") &&
        response["text"].is_string()) {
        std::string text = response["text"].get<std::string>();
        while (!text.empty() && text.back() == '\n') text.pop_back();
        text.push_back('\n');
        return text;
    }

    const bool ok = response.value("ok", false);
    const std::string action =
        ok ? response.value("action", std::string("unknown")) : std::string("error");
    TextResponseBuilder out("xdebug");
    out.emit_header(action);

    if (!ok) {
        if (response.contains("action")) out.emit_kv("action", response["action"]);
        if (response.contains("error")) out.emit_error(response["error"]);
        if (response.contains("summary") && response["summary"].is_object() &&
            !response["summary"].empty()) {
            Json details = Json::object();
            const Json error = response.value("error", Json::object());
            const Json data = response.value("data", Json::object());
            for (auto it = response["summary"].begin(); it != response["summary"].end(); ++it) {
                if (it.key() == "status" || it.key() == "error_code") continue;
                if (error.is_object() && error.contains(it.key()) && error[it.key()] == it.value()) continue;
                if (data.is_object() && data.contains(it.key()) && data[it.key()] == it.value()) continue;
                details[it.key()] = it.value();
            }
            if (!details.empty()) {
                out.emit_section("failure_summary");
                for (auto it = details.begin(); it != details.end(); ++it) {
                    render_data_value(out, it.key(), it.value());
                }
            }
        }
        if (response.contains("error") && response["error"].is_object()) {
            const Json& error = response["error"];
            if (error.contains("validation_issues") &&
                error["validation_issues"].is_array()) {
                const Json& issues = error["validation_issues"];
                const size_t rendered = std::min<size_t>(20, issues.size());
                out.emit_section("validation_issues");
                out.emit_kv("issue_count", Json(static_cast<unsigned long long>(issues.size())));
                out.emit_kv("issues_truncated", rendered < issues.size());
                std::vector<std::vector<std::string>> rows;
                rows.reserve(rendered);
                for (size_t i = 0; i < rendered; ++i) {
                    rows.push_back({scalar_text(issues[i], "path"),
                                    scalar_text(issues[i], "message")});
                }
                out.emit_table({"path", "message"}, rows);
            }
            if (error.contains("candidates") && error["candidates"].is_array()) {
                out.emit_section("candidates");
                for (const auto& item : error["candidates"])
                    out.emit_row({json_to_xout_value(item)});
            }
            if (error.contains("suggested_actions") && error["suggested_actions"].is_array()) {
                out.emit_section("next");
                for (const auto& item : error["suggested_actions"])
                    out.emit_row({json_to_xout_value(item)});
            }
        }
        return out.str();
    }

    render_generic(out, response);
    emit_warnings(out, response);
    emit_suggestions(out, response);
    emit_common_blocks(out, response);
    return out.str();
}

std::string render_xout_response(const Json& response) {
    return render_xout_response(response, std::string());
}

std::string render_xout_transport_payload(const Json& response,
                                          const std::string& handler_xout) {
    return render_xout_response(response, handler_xout);
}

std::string render_xout_transport_payload(const Json& response) {
    return render_xout_response(response);
}

} // namespace xdebug
