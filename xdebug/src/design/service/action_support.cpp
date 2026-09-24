#include "action_support.h"

#include <cctype>

namespace xdebug_design {

const char* const API_VERSION = "xdebug.internal.v1";
const char* const TOOL_VERSION = "1.0.0";

std::string trim(const std::string& s) {
    size_t b = 0;
    while (b < s.size() && std::isspace(static_cast<unsigned char>(s[b]))) b++;
    size_t e = s.size();
    while (e > b && std::isspace(static_cast<unsigned char>(s[e - 1]))) e--;
    return s.substr(b, e - b);
}

bool starts_with(const std::string& s, const std::string& prefix) {
    return s.compare(0, prefix.size(), prefix) == 0;
}

std::string leaf_name(const std::string& signal) {
    size_t dot = signal.rfind('.');
    std::string leaf = dot == std::string::npos ? signal : signal.substr(dot + 1);
    size_t bracket = leaf.find('[');
    if (bracket != std::string::npos) leaf = leaf.substr(0, bracket);
    return leaf;
}

std::string lower_copy(const std::string& s) {
    std::string out;
    out.reserve(s.size());
    for (char c : s) out.push_back((char)std::tolower((unsigned char)c));
    return out;
}

bool contains_word_like(const std::string& text, const std::string& token) {
    return lower_copy(text).find(lower_copy(token)) != std::string::npos;
}

std::string next_token_after(const std::string& text, const std::string& key) {
    size_t pos = lower_copy(text).find(lower_copy(key));
    if (pos == std::string::npos) return "";
    pos += key.size();
    while (pos < text.size() && std::isspace((unsigned char)text[pos])) pos++;
    size_t begin = pos;
    while (pos < text.size()) {
        char c = text[pos];
        if (!(std::isalnum((unsigned char)c) || c == '_' || c == '.' || c == '[' || c == ']')) break;
        pos++;
    }
    return begin < pos ? text.substr(begin, pos - begin) : "";
}

} // namespace xdebug_design
