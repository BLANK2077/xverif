#include "stream_expr.h"

#include "core/value/logic_value.h"

#include <algorithm>
#include <cctype>
#include <cstring>
#include <cstdlib>
#include <sstream>

namespace xdebug_waveform {

namespace {

std::string lower_bits(std::string text) {
    std::string out;
    for (char c : text) {
        if (c == '_' || std::isspace(static_cast<unsigned char>(c))) continue;
        if (c == '0' || c == '1' || c == 'x' || c == 'X' || c == 'z' || c == 'Z') {
            out.push_back(static_cast<char>(std::tolower(static_cast<unsigned char>(c))));
        }
    }
    return out;
}

bool has_xz_bits(const std::string& bits) {
    return bits.find_first_of("xzXZ") != std::string::npos;
}

std::string hex_to_bits(const std::string& text) {
    std::string out;
    for (char c : text) {
        if (c == '_' || std::isspace(static_cast<unsigned char>(c))) continue;
        if (c == 'x' || c == 'X' || c == 'z' || c == 'Z') {
            out.append(4, static_cast<char>(std::tolower(static_cast<unsigned char>(c))));
            continue;
        }
        int v = -1;
        if (c >= '0' && c <= '9') v = c - '0';
        else if (c >= 'a' && c <= 'f') v = 10 + c - 'a';
        else if (c >= 'A' && c <= 'F') v = 10 + c - 'A';
        if (v < 0) return "";
        for (int bit = 3; bit >= 0; --bit) out.push_back((v & (1 << bit)) ? '1' : '0');
    }
    return out.empty() ? "0" : out;
}

std::string dec_to_bits(const std::string& text) {
    std::string clean;
    for (char c : text) if (c != '_') clean.push_back(c);
    char* end = nullptr;
    unsigned long long v = std::strtoull(clean.c_str(), &end, 10);
    if (!end || *end != '\0') return "";
    if (v == 0) return "0";
    std::string out;
    while (v) {
        out.push_back((v & 1ULL) ? '1' : '0');
        v >>= 1ULL;
    }
    std::reverse(out.begin(), out.end());
    return out;
}

StreamValue literal_value(const std::string& literal) {
    std::string s = literal;
    int width = 0;
    size_t tick = s.find('\'');
    std::string bits;
    if (tick != std::string::npos && tick + 1 < s.size()) {
        if (tick > 0) width = std::atoi(s.substr(0, tick).c_str());
        char base = static_cast<char>(std::tolower(static_cast<unsigned char>(s[tick + 1])));
        std::string body = s.substr(tick + 2);
        if (base == 'b') bits = lower_bits(body);
        else if (base == 'h') bits = hex_to_bits(body);
        else if (base == 'd') bits = dec_to_bits(body);
    } else if (s.size() > 2 && s[0] == '0' && (s[1] == 'x' || s[1] == 'X')) {
        bits = hex_to_bits(s.substr(2));
    } else if (s.size() > 2 && s[0] == '0' && (s[1] == 'b' || s[1] == 'B')) {
        bits = lower_bits(s.substr(2));
    } else {
        bits = dec_to_bits(s);
    }
    if (bits.empty()) bits = "x";
    if (width > 0) {
        if (static_cast<int>(bits.size()) < width) bits.insert(bits.begin(), width - bits.size(), '0');
        if (static_cast<int>(bits.size()) > width) bits = bits.substr(bits.size() - width);
    }
    return StreamValue{bits, !has_xz_bits(bits), width > 0};
}

StreamValue align_left(StreamValue value, size_t width) {
    if (value.bits.size() < width) value.bits.insert(value.bits.begin(), width - value.bits.size(), '0');
    return value;
}

bool unsigned_value(const StreamValue& value, unsigned long long& out) {
    if (!value.known || value.bits.size() > 63) return false;
    out = 0;
    for (char c : value.bits) {
        out <<= 1ULL;
        if (c == '1') out |= 1ULL;
        else if (c != '0') return false;
    }
    return true;
}

StreamValue one_bit(bool value) {
    return StreamValue{value ? "1" : "0", true};
}

StreamValue eval_node(const StreamExpression::Node& node,
                      const std::map<std::string, StreamValue>& values,
                      std::string& error) {
    if (node.kind == NodeKind::Literal) return literal_value(node.text);
    if (node.kind == NodeKind::Signal) {
        auto it = values.find(node.text);
        if (it == values.end()) {
            error = "signal value not available: " + node.text;
            return StreamValue{"x", false};
        }
        return it->second;
    }
    if (node.kind == NodeKind::Select) {
        StreamValue base = eval_node(*node.a, values, error);
        if (!error.empty()) return StreamValue{"x", false};
        int hi = std::max(node.left, node.right);
        int lo = std::min(node.left, node.right);
        if (lo < 0 || hi < 0 || hi >= static_cast<int>(base.bits.size())) {
            error = "select out of range in expression";
            return StreamValue{"x", false};
        }
        size_t start = base.bits.size() - 1 - static_cast<size_t>(hi);
        size_t end = base.bits.size() - 1 - static_cast<size_t>(lo);
        std::string bits = base.bits.substr(start, end - start + 1);
        return StreamValue{bits, !has_xz_bits(bits), true};
    }
    if (node.kind == NodeKind::Concat) {
        std::string bits;
        bool known = true;
        bool width_reliable = true;
        for (const auto& item : node.items) {
            StreamValue v = eval_node(*item, values, error);
            if (!error.empty()) return StreamValue{"x", false};
            bits += v.bits;
            known = known && v.known;
            width_reliable = width_reliable && v.width_reliable;
        }
        if (bits.empty()) bits = "0";
        return StreamValue{bits, known && !has_xz_bits(bits), width_reliable};
    }
    if (node.kind == NodeKind::Unary) {
        StreamValue v = eval_node(*node.a, values, error);
        if (!error.empty()) return StreamValue{"x", false};
        if (node.op == "!") {
            if (!v.known) return StreamValue{"x", false};
            return one_bit(!stream_value_truthy(v, false));
        }
        if (node.op == "~") {
            std::string bits = v.bits;
            for (char& c : bits) {
                if (c == '0') c = '1';
                else if (c == '1') c = '0';
                else c = 'x';
            }
            return StreamValue{bits, !has_xz_bits(bits), v.width_reliable};
        }
    }

    StreamValue lhs = eval_node(*node.a, values, error);
    if (!error.empty()) return StreamValue{"x", false};
    StreamValue rhs = eval_node(*node.b, values, error);
    if (!error.empty()) return StreamValue{"x", false};
    const std::string& op = node.op;
    if (op == "&&" || op == "||") {
        if (!lhs.known || !rhs.known) return StreamValue{"x", false};
        bool l = stream_value_truthy(lhs, false);
        bool r = stream_value_truthy(rhs, false);
        return one_bit(op == "&&" ? (l && r) : (l || r));
    }
    if (op == "&" || op == "|" || op == "^") {
        size_t width = std::max(lhs.bits.size(), rhs.bits.size());
        lhs = align_left(lhs, width);
        rhs = align_left(rhs, width);
        std::string bits(width, 'x');
        for (size_t i = 0; i < width; ++i) {
            char l = lhs.bits[i], r = rhs.bits[i];
            if (l != '0' && l != '1') continue;
            if (r != '0' && r != '1') continue;
            bool lv = l == '1', rv = r == '1';
            bool out = op == "&" ? (lv && rv) : op == "|" ? (lv || rv) : (lv != rv);
            bits[i] = out ? '1' : '0';
        }
        return StreamValue{bits, !has_xz_bits(bits),
                           lhs.width_reliable && rhs.width_reliable};
    }
    if (op == "==" || op == "!=" || op == ">" || op == ">=" || op == "<" || op == "<=") {
        unsigned long long l = 0, r = 0;
        if (!unsigned_value(lhs, l) || !unsigned_value(rhs, r)) return StreamValue{"x", false};
        bool out = false;
        if (op == "==") out = l == r;
        else if (op == "!=") out = l != r;
        else if (op == ">") out = l > r;
        else if (op == ">=") out = l >= r;
        else if (op == "<") out = l < r;
        else if (op == "<=") out = l <= r;
        return one_bit(out);
    }
    error = "unsupported operator: " + op;
    return StreamValue{"x", false};
}

class Parser {
public:
    explicit Parser(const std::string& text) : text_(text) {}

    std::unique_ptr<StreamExpression::Node> parse(std::string& error) {
        auto out = parse_or(error);
        skip();
        if (error.empty() && pos_ != text_.size()) error = "unexpected token near: " + text_.substr(pos_);
        return out;
    }

    const std::set<std::string>& signals() const { return signals_; }

private:
    std::unique_ptr<StreamExpression::Node> parse_or(std::string& error) {
        auto lhs = parse_and(error);
        while (error.empty()) {
            if (eat("||")) lhs = binary("||", std::move(lhs), parse_and(error));
            else break;
        }
        return lhs;
    }

    std::unique_ptr<StreamExpression::Node> parse_and(std::string& error) {
        auto lhs = parse_bitor(error);
        while (error.empty()) {
            if (eat("&&")) lhs = binary("&&", std::move(lhs), parse_bitor(error));
            else break;
        }
        return lhs;
    }

    std::unique_ptr<StreamExpression::Node> parse_bitor(std::string& error) {
        auto lhs = parse_bitxor(error);
        while (error.empty()) {
            skip();
            if (peek("||")) break;
            if (eat("|")) lhs = binary("|", std::move(lhs), parse_bitxor(error));
            else break;
        }
        return lhs;
    }

    std::unique_ptr<StreamExpression::Node> parse_bitxor(std::string& error) {
        auto lhs = parse_bitand(error);
        while (error.empty()) {
            if (eat("^")) lhs = binary("^", std::move(lhs), parse_bitand(error));
            else break;
        }
        return lhs;
    }

    std::unique_ptr<StreamExpression::Node> parse_bitand(std::string& error) {
        auto lhs = parse_compare(error);
        while (error.empty()) {
            skip();
            if (peek("&&")) break;
            if (eat("&")) lhs = binary("&", std::move(lhs), parse_compare(error));
            else break;
        }
        return lhs;
    }

    std::unique_ptr<StreamExpression::Node> parse_compare(std::string& error) {
        auto lhs = parse_unary(error);
        while (error.empty()) {
            if (eat("==")) lhs = binary("==", std::move(lhs), parse_unary(error));
            else if (eat("!=")) lhs = binary("!=", std::move(lhs), parse_unary(error));
            else if (eat(">=")) lhs = binary(">=", std::move(lhs), parse_unary(error));
            else if (eat("<=")) lhs = binary("<=", std::move(lhs), parse_unary(error));
            else if (eat(">")) lhs = binary(">", std::move(lhs), parse_unary(error));
            else if (eat("<")) lhs = binary("<", std::move(lhs), parse_unary(error));
            else break;
        }
        return lhs;
    }

    std::unique_ptr<StreamExpression::Node> parse_unary(std::string& error) {
        if (eat("!")) {
            auto n = std::unique_ptr<StreamExpression::Node>(new StreamExpression::Node());
            n->kind = NodeKind::Unary; n->op = "!"; n->a = parse_unary(error);
            return n;
        }
        if (eat("~")) {
            auto n = std::unique_ptr<StreamExpression::Node>(new StreamExpression::Node());
            n->kind = NodeKind::Unary; n->op = "~"; n->a = parse_unary(error);
            return n;
        }
        return parse_primary(error);
    }

    std::unique_ptr<StreamExpression::Node> parse_primary(std::string& error) {
        skip();
        if (eat("(")) {
            auto n = parse_or(error);
            if (error.empty() && !eat(")")) error = "missing ')'";
            return n;
        }
        if (eat("{")) {
            auto n = std::unique_ptr<StreamExpression::Node>(new StreamExpression::Node());
            n->kind = NodeKind::Concat;
            while (error.empty()) {
                n->items.push_back(parse_or(error));
                if (eat("}")) break;
                if (!eat(",")) {
                    error = "missing ',' or '}' in concat";
                    break;
                }
            }
            return n;
        }
        if (pos_ < text_.size() && (std::isdigit(static_cast<unsigned char>(text_[pos_])) || text_[pos_] == '\'')) {
            return literal();
        }
        return signal_or_select(error);
    }

    std::unique_ptr<StreamExpression::Node> literal() {
        size_t start = pos_;
        while (pos_ < text_.size()) {
            char c = text_[pos_];
            if (std::isalnum(static_cast<unsigned char>(c)) || c == '_' || c == '\'' || c == 'x' || c == 'X' || c == 'z' || c == 'Z') pos_++;
            else break;
        }
        auto n = std::unique_ptr<StreamExpression::Node>(new StreamExpression::Node());
        n->kind = NodeKind::Literal;
        n->text = text_.substr(start, pos_ - start);
        return n;
    }

    std::unique_ptr<StreamExpression::Node> signal_or_select(std::string& error) {
        skip();
        size_t start = pos_;
        if (pos_ >= text_.size() || !(std::isalpha(static_cast<unsigned char>(text_[pos_])) || text_[pos_] == '_' || text_[pos_] == '\\')) {
            error = "expected signal, literal, concat, or parenthesized expression";
            return std::unique_ptr<StreamExpression::Node>(new StreamExpression::Node());
        }
        while (pos_ < text_.size()) {
            char c = text_[pos_];
            if (std::isalnum(static_cast<unsigned char>(c)) || c == '_' || c == '.' || c == '$' || c == '\\') {
                pos_++;
                continue;
            }
            if (c == '[') {
                size_t rb = text_.find(']', pos_);
                if (rb != std::string::npos && rb + 1 < text_.size() && text_[rb + 1] == '.') {
                    pos_ = rb + 1;
                    continue;
                }
            }
            break;
        }
        std::string name = text_.substr(start, pos_ - start);
        signals_.insert(name);
        auto sig = std::unique_ptr<StreamExpression::Node>(new StreamExpression::Node());
        sig->kind = NodeKind::Signal;
        sig->text = name;
        if (eat("[")) {
            int left = parse_int(error);
            int right = left;
            if (eat(":")) right = parse_int(error);
            if (error.empty() && !eat("]")) error = "missing ']'";
            auto sel = std::unique_ptr<StreamExpression::Node>(new StreamExpression::Node());
            sel->kind = NodeKind::Select;
            sel->left = left;
            sel->right = right;
            sel->a = std::move(sig);
            return sel;
        }
        return sig;
    }

    int parse_int(std::string& error) {
        skip();
        size_t start = pos_;
        while (pos_ < text_.size() && std::isdigit(static_cast<unsigned char>(text_[pos_]))) pos_++;
        if (start == pos_) {
            error = "expected integer index";
            return 0;
        }
        return std::atoi(text_.substr(start, pos_ - start).c_str());
    }

    static std::unique_ptr<StreamExpression::Node> binary(const std::string& op,
                                                          std::unique_ptr<StreamExpression::Node> lhs,
                                                          std::unique_ptr<StreamExpression::Node> rhs) {
        auto n = std::unique_ptr<StreamExpression::Node>(new StreamExpression::Node());
        n->kind = NodeKind::Binary;
        n->op = op;
        n->a = std::move(lhs);
        n->b = std::move(rhs);
        return n;
    }

    bool eat(const char* token) {
        skip();
        size_t len = std::strlen(token);
        if (text_.compare(pos_, len, token) != 0) return false;
        pos_ += len;
        return true;
    }

    bool peek(const char* token) {
        size_t len = std::strlen(token);
        return text_.compare(pos_, len, token) == 0;
    }

    void skip() {
        while (pos_ < text_.size() && std::isspace(static_cast<unsigned char>(text_[pos_]))) pos_++;
    }

    std::string text_;
    size_t pos_ = 0;
    std::set<std::string> signals_;
};

} // namespace

Json stream_value_json(const StreamValue& value) {
    xdebug_core::LogicValue logic =
        xdebug_core::logic_value_from_fsdb_raw(
        value.bits, 'b', value.width_reliable ? value.width() : 0);
    return xdebug_core::logic_value_json(
        logic, xdebug_core::current_value_render_format());
}

bool stream_value_truthy(const StreamValue& value, bool unknown_default) {
    if (!value.known) return unknown_default;
    for (char c : value.bits) if (c == '1') return true;
    return false;
}

std::string stream_value_hex(const StreamValue& value) {
    xdebug_core::LogicValue logic =
        xdebug_core::logic_value_from_fsdb_raw(
        value.bits, 'b', value.width_reliable ? value.width() : 0);
    return xdebug_core::render_logic_value(
        logic, xdebug_core::ValueRenderFormat::Hex);
}

bool stream_value_has_xz(const StreamValue& value) {
    return !value.known || has_xz_bits(value.bits);
}

StreamExpression::StreamExpression() = default;
StreamExpression::~StreamExpression() = default;
StreamExpression::StreamExpression(StreamExpression&&) noexcept = default;
StreamExpression& StreamExpression::operator=(StreamExpression&&) noexcept = default;

bool StreamExpression::parse(const std::string& text, std::string& error) {
    text_ = text;
    Parser parser(text);
    root_ = parser.parse(error);
    signals_ = parser.signals();
    plain_signal_ = !root_.get() ? false :
        (signals_.size() == 1 && text_.find_first_of("!~&|^=<>({") == std::string::npos &&
         text_.find('[') == std::string::npos);
    return error.empty();
}

bool StreamExpression::evaluate(const std::map<std::string, StreamValue>& values,
                                StreamValue& out, std::string& error) const {
    if (!root_) {
        error = "expression not parsed";
        return false;
    }
    out = eval_node(*root_, values, error);
    return error.empty();
}

} // namespace xdebug_waveform
