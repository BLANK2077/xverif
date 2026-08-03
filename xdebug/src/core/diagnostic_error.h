#pragma once

#include "json.hpp"

#include <cctype>
#include <string>
#include <vector>

namespace xdebug_core {

using DiagnosticJson = nlohmann::ordered_json;

inline bool sensitive_diagnostic_path(const std::string& path) {
    std::string segment;
    for (size_t i = 0; i <= path.size(); ++i) {
        const char c = i < path.size() ? path[i] : '\0';
        if (std::isalnum(static_cast<unsigned char>(c)) || c == '_') {
            segment.push_back(c);
            continue;
        }
        if (segment == "ownership_token" ||
            segment == "ownership_token_hash") {
            return true;
        }
        segment.clear();
    }
    return false;
}

inline bool sensitive_diagnostic_key(const std::string& key) {
    return key == "ownership_token" ||
           key == "ownership_token_hash";
}

inline DiagnosticJson redact_sensitive_diagnostic_value(
    const DiagnosticJson& value,
    bool& redacted) {
    if (value.is_array()) {
        DiagnosticJson out = DiagnosticJson::array();
        for (const auto& item : value) {
            out.push_back(
                redact_sensitive_diagnostic_value(item, redacted));
        }
        return out;
    }
    if (!value.is_object()) return value;

    const bool sensitive_invalid_arg =
        value.contains("invalid_arg") &&
        value["invalid_arg"].is_string() &&
        sensitive_diagnostic_path(
            value["invalid_arg"].get<std::string>());
    const bool sensitive_issue_path =
        value.contains("path") &&
        value["path"].is_string() &&
        sensitive_diagnostic_path(
            value["path"].get<std::string>());

    DiagnosticJson out = DiagnosticJson::object();
    for (auto it = value.begin(); it != value.end(); ++it) {
        if (sensitive_diagnostic_key(it.key())) {
            redacted = true;
            continue;
        }
        if (sensitive_invalid_arg && it.key() == "received") {
            redacted = true;
            continue;
        }
        if ((sensitive_invalid_arg || sensitive_issue_path) &&
            it.key() == "message") {
            redacted = true;
            out[it.key()] =
                "sensitive request field failed validation";
            continue;
        }
        out[it.key()] =
            redact_sensitive_diagnostic_value(it.value(), redacted);
    }
    if (sensitive_invalid_arg) {
        redacted = true;
        out["received_redacted"] = true;
    }
    return out;
}

inline DiagnosticJson redact_sensitive_diagnostic(
    const DiagnosticJson& value) {
    bool redacted = false;
    return redact_sensitive_diagnostic_value(value, redacted);
}

class DiagnosticErrorBuilder {
public:
    DiagnosticErrorBuilder(std::string code, std::string message, std::string layer)
        : error_(DiagnosticJson::object()) {
        error_["code"] = code;
        error_["message"] = message;
        error_["recoverable"] = true;
        error_["error_layer"] = layer;
    }

    static DiagnosticErrorBuilder schema(std::string code, std::string message) {
        return DiagnosticErrorBuilder(code, message, "schema");
    }

    static DiagnosticErrorBuilder handler(std::string code, std::string message) {
        return DiagnosticErrorBuilder(code, message, "handler");
    }

    static DiagnosticErrorBuilder wrapper(std::string code, std::string message) {
        return DiagnosticErrorBuilder(code, message, "wrapper");
    }

    static DiagnosticErrorBuilder session_manager(std::string code, std::string message) {
        return DiagnosticErrorBuilder(code, message, "session_manager");
    }

    static DiagnosticErrorBuilder transport(std::string code, std::string message) {
        return DiagnosticErrorBuilder(code, message, "transport");
    }

    static DiagnosticErrorBuilder internal(std::string code, std::string message) {
        DiagnosticErrorBuilder builder(code, message, "internal");
        builder.recoverable(false);
        return builder;
    }

    DiagnosticErrorBuilder& recoverable(bool value) {
        error_["recoverable"] = value;
        return *this;
    }

    DiagnosticErrorBuilder& invalid_arg(const std::string& value) {
        error_["invalid_arg"] = value;
        return *this;
    }

    DiagnosticErrorBuilder& expected(const std::string& value) {
        error_["expected"] = value;
        return *this;
    }

    DiagnosticErrorBuilder& received(const DiagnosticJson& value) {
        error_["received"] = value;
        return *this;
    }

    DiagnosticErrorBuilder& received_type(const std::string& value) {
        error_["received_type"] = value;
        return *this;
    }

    DiagnosticErrorBuilder& schema_path(const std::string& value) {
        if (!value.empty()) error_["schema_path"] = value;
        return *this;
    }

    DiagnosticErrorBuilder& required_any_of(const DiagnosticJson& value) {
        if (!value.is_null()) error_["required_any_of"] = value;
        return *this;
    }

    DiagnosticErrorBuilder& missing_name(const std::string& value) {
        error_["missing_name"] = value;
        return *this;
    }

    DiagnosticErrorBuilder& missing_resource(const std::string& value) {
        error_["missing_resource"] = value;
        return *this;
    }

    DiagnosticErrorBuilder& available_values(const DiagnosticJson& value) {
        error_["available_values"] = value;
        return *this;
    }

    DiagnosticErrorBuilder& next_actions(const DiagnosticJson& value) {
        error_["next_actions"] = value;
        return *this;
    }

    DiagnosticErrorBuilder& example_note(const std::string& value) {
        if (!value.empty()) error_["example_note"] = value;
        return *this;
    }

    DiagnosticErrorBuilder& correct_example(const DiagnosticJson& value) {
        if (!value.is_null()) error_["correct_example"] = value;
        return *this;
    }

    DiagnosticErrorBuilder& cause_code(const std::string& value) {
        if (!value.empty()) error_["cause_code"] = value;
        return *this;
    }

    DiagnosticJson to_json() const {
        return redact_sensitive_diagnostic(error_);
    }

private:
    DiagnosticJson error_;
};

inline DiagnosticJson normalize_diagnostic_error(DiagnosticJson error,
                                                 const std::string& default_layer) {
    if (!error.is_object()) error = DiagnosticJson::object();
    if (!error.contains("code")) error["code"] = "ACTION_FAILED";
    if (!error.contains("message")) error["message"] = "action failed";
    if (!error.contains("error_layer")) error["error_layer"] = default_layer;
    if (!error.contains("recoverable")) error["recoverable"] = true;
    return redact_sensitive_diagnostic(error);
}

inline DiagnosticJson request_consumption_violation(
    const std::vector<std::string>& unconsumed_paths) {
    DiagnosticJson received = DiagnosticJson::array();
    for (const std::string& path : unconsumed_paths) {
        received.push_back(path);
    }
    return DiagnosticErrorBuilder::internal(
               "INTERNAL_REQUEST_CONSUMPTION_VIOLATION",
               "action left provided request fields unconsumed")
        .invalid_arg("request")
        .expected("every provided request field must be consumed exactly once")
        .received(received)
        .to_json();
}

} // namespace xdebug_core
