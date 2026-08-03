#include "engine_action_handler.h"

#include "core/diagnostic_error.h"
#include "waveform/cache/analysis_repository.h"
#include "../../api/text_response_builder.h"

#include <algorithm>
#include <cctype>
#include <set>
#include <vector>

namespace xdebug_design {

Json EngineActionHandler::run(ContractBoundRequest& request,
                              EngineActionContext& ctx) const {
    return run(request.consume_args_request("legacy_typed_action_parser"), ctx);
}

Json EngineActionHandler::run(const Json&, EngineActionContext&) const {
    return make_handler_error(
        "INTERNAL_CONTRACT_ERROR",
        "action handler does not implement a request parser");
}

namespace {

bool should_emit_scalar_key(const std::string& key, const Json& value) {
    if (key == "known" && value.is_boolean() && value.get<bool>()) return false;
    return xdebug::is_xout_scalar_json(value);
}

std::string scalar_text(const Json& object, const char* key) {
    if (!object.is_object() || !object.contains(key)) return std::string();
    const Json& value = object[key];
    if (!xdebug::is_xout_scalar_json(value)) return std::string();
    return xdebug::json_to_xout_value(value);
}

std::string lowercase(std::string text) {
    std::transform(text.begin(), text.end(), text.begin(),
                   [](unsigned char c) { return static_cast<char>(std::tolower(c)); });
    return text;
}

bool contains_text(const std::string& haystack, const char* needle) {
    return haystack.find(needle) != std::string::npos;
}

std::string code_for_handler_message(const std::string& message) {
    std::string lower = lowercase(message);
    if (contains_text(lower, "value_not_available") ||
        contains_text(lower, "value not available")) {
        return "VALUE_NOT_AVAILABLE";
    }
    if (contains_text(lower, "signal not found") ||
        contains_text(lower, "failed to read value for signal")) {
        return "SIGNAL_NOT_FOUND";
    }
    if (contains_text(lower, "clock") && contains_text(lower, "not found")) {
        return "CLOCK_NOT_FOUND";
    }
    if (contains_text(lower, "config not found") ||
        contains_text(lower, "configuration not found")) {
        return "CONFIG_NOT_FOUND";
    }
    if (contains_text(lower, "list not found")) return "LIST_NOT_FOUND";
    if (contains_text(lower, "file not found") ||
        contains_text(lower, "no such file")) {
        return "FILE_NOT_FOUND";
    }
    if (contains_text(lower, "requires") ||
        contains_text(lower, "must ") ||
        contains_text(lower, "invalid") ||
        contains_text(lower, "unsupported") ||
        contains_text(lower, "unknown")) {
        return "INVALID_ARGUMENT";
    }
    return "PRECONDITION_FAILED";
}

} // namespace

Json make_handler_error(const std::string& code, const std::string& message) {
    return make_handler_error(code, message, Json::object());
}

Json make_handler_error(const std::string& code, const std::string& message,
                        const Json& details) {
    Json error = xdebug_core::DiagnosticErrorBuilder::handler(code, message).to_json();
    if (details.is_object()) {
        for (auto it = details.begin(); it != details.end(); ++it) {
            error[it.key()] = it.value();
        }
    }
    return Json{{"error", error}};
}

Json make_handler_error_from_message(const std::string& message) {
    return make_handler_error(code_for_handler_message(message), message);
}

Json make_analysis_cache_error(
    const xdebug_waveform::AnalysisCacheError& error) {
    Json suggestions = Json::array();
    for (const std::string& suggestion : error.suggestions)
        suggestions.push_back(suggestion);
    return make_handler_error(
        error.code.empty() ? "ANALYSIS_BUILD_FAILED" : error.code,
        error.message.empty() ? "analysis build failed" : error.message,
        {{"recoverable", error.recoverable},
         {"current_estimated_bytes", error.current_estimated_bytes},
         {"hard_max_bytes", error.hard_max_bytes},
         {"protocol", error.protocol},
         {"key_summary", error.key_summary},
         {"suggestions", suggestions}});
}

std::string append_common_blocks_xout(std::string text, const Json& response) {
    const Json data = response.value("data", Json::object());
    if (!data.is_object() || !data.contains("common_blocks") ||
        !data["common_blocks"].is_array() || data["common_blocks"].empty()) {
        return text;
    }
    xdebug::TextResponseBuilder out("xdebug");
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
    std::string addition = out.str();
    if (addition == "\n") return text;
    if (!text.empty() && text.back() != '\n') text.push_back('\n');
    if (!text.empty()) text.push_back('\n');
    text += addition;
    return text;
}

// Helper: recursively render a JSON value.
static void render_data_value(xdebug::TextResponseBuilder& out,
                              const std::string& key, const Json& val) {
    if (should_emit_scalar_key(key, val)) {
        out.emit_kv(key, val);
    } else if (val.is_array() && val.empty()) {
        out.emit_kv(key, "[empty]");
    } else if (val.is_array() && val.size() > 0 &&
               xdebug::is_xout_scalar_json(val[0])) {
        out.emit_section(key);
        int n = std::min(20, (int)val.size());
        for (int i = 0; i < n; ++i)
            out.emit_row({xdebug::json_to_xout_value(val[i])});
        if ((int)val.size() > n)
            out.emit_kv("(+ " + std::to_string(val.size() - n) + " more)", "");
    } else if (val.is_array() && val.size() > 0 && val[0].is_object()) {
        int count = (int)val.size();
        out.emit_section(key);
        int n = std::min(20, count);
        out.emit_json_table(val, n);
        if (count > n)
            out.emit_kv("(+ " + std::to_string(count - n) + " more)", "");
    } else if (val.is_object()) {
        out.emit_section(key);
        for (auto it = val.begin(); it != val.end(); ++it)
            render_data_value(out, it.key(), it.value());
    }
}

std::string EngineActionHandler::render_xout(const Json& response) const {
    xdebug::TextResponseBuilder out("xdebug");
    out.emit_header(action_name());

    // ── summary ──
    if (response.contains("summary") && response["summary"].is_object()) {
        out.emit_section("summary");
        for (auto it = response["summary"].begin();
             it != response["summary"].end(); ++it) {
            if (should_emit_scalar_key(it.key(), it.value())) {
                out.emit_kv(it.key(), it.value());
            }
        }
    }

    // ── data ── recursive tree
    const Json& data = response.value("data", Json::object());
    if (data.is_object() && !data.empty()) {
        out.emit_section("data");
        for (auto it = data.begin(); it != data.end(); ++it) {
            if (it.key() == "summary") continue;  // already rendered above
            if (it.key() == "common_blocks") continue;
            render_data_value(out, it.key(), it.value());
        }
    }

    // ── findings ──
    if (response.contains("findings") && response["findings"].is_array() &&
        !response["findings"].empty()) {
        render_data_value(out, "findings", response["findings"]);
    }

    return append_common_blocks_xout(out.str(), response);
}

} // namespace xdebug_design
