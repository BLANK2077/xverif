#include "expression.h"

#include "../event/event_expr.h"
#include "../stream/stream_expr.h"
#include "core/value/logic_value.h"

#include <cctype>

namespace xdebug_waveform {

namespace {

StreamValue to_stream_value(const ExpressionValue& value) {
    return StreamValue{value.bits, value.known};
}

ExpressionValue from_stream_value(const StreamValue& value) {
    return ExpressionValue{value.bits, value.known};
}

bool is_raw_bit_string(const std::string& text) {
    bool has_bit = false;
    if (text.size() >= 2 && text[0] == '\'' &&
        (text[1] == 'b' || text[1] == 'B' || text[1] == 'h' || text[1] == 'H' ||
         text[1] == 'd' || text[1] == 'D')) {
        return false;
    }
    if (text.find('\'') != std::string::npos) return false;
    for (char c : text) {
        if (c == '_' || std::isspace(static_cast<unsigned char>(c))) continue;
        if (c != '0' && c != '1' && c != 'x' && c != 'X' && c != 'z' && c != 'Z') return false;
        has_bit = true;
    }
    return has_bit;
}

ExpressionValue expression_value_from_raw(const std::string& raw) {
    if (!is_raw_bit_string(raw)) {
        xdebug_core::LogicValue parsed =
            xdebug_core::parse_user_logic_literal(raw);
        if (parsed.valid && !parsed.bits.empty()) return ExpressionValue{parsed.bits, parsed.known};
    }

    std::string out;
    for (char c : raw) {
        if (c == '_' || std::isspace(static_cast<unsigned char>(c))) continue;
        if (c == '0' || c == '1' || c == 'x' || c == 'X' || c == 'z' || c == 'Z') {
            out.push_back(static_cast<char>(std::tolower(static_cast<unsigned char>(c))));
        }
    }
    if (out.empty()) out = "x";
    return ExpressionValue{out, !stream_value_has_xz(StreamValue{out, true})};
}

} // namespace

class Expression::Impl {
public:
    StreamExpression parsed;
};

Expression::Expression() : impl_(new Impl()) {}

Expression::~Expression() {
    delete impl_;
}

Expression::Expression(Expression&& other) noexcept : impl_(other.impl_) {
    other.impl_ = nullptr;
}

Expression& Expression::operator=(Expression&& other) noexcept {
    if (this != &other) {
        delete impl_;
        impl_ = other.impl_;
        other.impl_ = nullptr;
    }
    return *this;
}

bool Expression::parse(const std::string& text, std::string& error) {
    return impl_->parsed.parse(text, error);
}

ExpressionResult Expression::evaluate(const std::map<std::string, ExpressionValue>& values) const {
    std::map<std::string, StreamValue> stream_values;
    for (const auto& item : values) {
        stream_values[item.first] = to_stream_value(item.second);
    }

    StreamValue out;
    std::string error;
    if (!impl_->parsed.evaluate(stream_values, out, error)) {
        ExpressionResult result;
        result.ok = false;
        result.value = ExpressionValue{"x", false};
        result.error_code = expression_error_code_from_message(error);
        result.message = error;
        return result;
    }

    ExpressionResult result;
    result.ok = true;
    result.value = from_stream_value(out);
    if (stream_value_has_xz(out)) {
        result.error_code = "UNKNOWN_VALUE";
        result.message = "expression result contains X/Z";
    }
    return result;
}

const std::string& Expression::text() const {
    return impl_->parsed.text();
}

const std::set<std::string>& Expression::aliases() const {
    return impl_->parsed.signals();
}

std::string expression_error_code_from_message(const std::string& message) {
    if (message.find("signal value not available:") == 0) return "MISSING_SIGNAL_VALUE";
    if (message.find("select out of range") != std::string::npos) return "SELECT_OUT_OF_RANGE";
    if (message.find("unsupported operator:") == 0) return "UNSUPPORTED_OPERATOR";
    if (message.find("expression not parsed") != std::string::npos) return "EXPRESSION_NOT_PARSED";
    return "EXPRESSION_PARSE_ERROR";
}

bool expression_alias_name_is_simple(const std::string& alias) {
    if (alias.empty()) return false;
    unsigned char first = static_cast<unsigned char>(alias[0]);
    if (!(std::isalpha(first) || alias[0] == '_')) return false;
    for (char c : alias) {
        unsigned char ch = static_cast<unsigned char>(c);
        if (!(std::isalnum(ch) || c == '_')) return false;
    }
    return true;
}

std::vector<std::string>
expression_aliases_that_look_like_paths(const std::set<std::string>& aliases) {
    std::vector<std::string> out;
    for (const auto& alias : aliases) {
        if (!expression_alias_name_is_simple(alias)) out.push_back(alias);
    }
    return out;
}

std::map<std::string, ExpressionValue>
expression_stream_values_from_raw(const std::map<std::string, std::string>& values) {
    std::map<std::string, ExpressionValue> out;
    for (const auto& item : values) {
        out[item.first] = expression_value_from_raw(item.second);
    }
    return out;
}

ExprTri expression_tri_from_value(const ExpressionValue& value) {
    StreamValue stream_value = to_stream_value(value);
    if (stream_value_has_xz(stream_value)) return ExprTri::Unknown;
    return stream_value_truthy(stream_value, false) ? ExprTri::True : ExprTri::False;
}

bool expression_evaluate_tri(const std::string& expr,
                             const std::map<std::string, std::string>& values,
                             ExprTri& result,
                             std::string& error) {
    Expression parsed;
    if (!parsed.parse(expr, error)) {
        result = ExprTri::Unknown;
        return false;
    }
    ExpressionResult evaluated = parsed.evaluate(expression_stream_values_from_raw(values));
    if (!evaluated.ok) {
        error = evaluated.message;
        result = ExprTri::Unknown;
        return false;
    }
    error.clear();
    result = expression_tri_from_value(evaluated.value);
    return true;
}

Json expression_value_json(const ExpressionValue& value) {
    return stream_value_json(to_stream_value(value));
}

bool expression_value_truthy(const ExpressionValue& value, bool unknown_default) {
    return stream_value_truthy(to_stream_value(value), unknown_default);
}

std::string expression_value_hex(const ExpressionValue& value) {
    return stream_value_hex(to_stream_value(value));
}

bool expression_value_has_xz(const ExpressionValue& value) {
    return stream_value_has_xz(to_stream_value(value));
}

} // namespace xdebug_waveform
