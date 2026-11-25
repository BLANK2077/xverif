#include "exclusion/el_parser.h"

#include "core/errors.h"
#include "core/fs.h"

#include <cctype>
#include <sstream>

namespace xcov {

namespace {

std::string trim(const std::string& text) {
    std::size_t start = 0;
    std::size_t end = text.size();
    while (start < end && std::isspace(static_cast<unsigned char>(text[start]))) ++start;
    while (end > start && std::isspace(static_cast<unsigned char>(text[end - 1]))) --end;
    return text.substr(start, end - start);
}

// Decode one double-quoted EL token starting at `pos`.
bool parse_quoted(const std::string& text, std::size_t pos, std::string* out,
                  std::size_t* next) {
    if (pos >= text.size() || text[pos] != '"') return false;
    std::string value;
    std::size_t index = pos + 1;
    while (index < text.size()) {
        const char ch = text[index];
        if (ch == '\\' && index + 1 < text.size()) {
            value.push_back(text[index + 1]);
            index += 2;
            continue;
        }
        if (ch == '"') {
            *out = value;
            *next = index + 1;
            return true;
        }
        value.push_back(ch);
        ++index;
    }
    return false;
}

std::string first_token(const std::string& text) {
    std::size_t end = 0;
    while (end < text.size() && std::isspace(static_cast<unsigned char>(text[end]))) {
        ++end;
    }
    const std::size_t start = end;
    while (end < text.size() && !std::isspace(static_cast<unsigned char>(text[end]))) {
        ++end;
    }
    return text.substr(start, end - start);
}

} // namespace

std::string escape_el_text(const std::string& value) {
    std::string out;
    out.reserve(value.size() + 8);
    for (char ch : value) {
        if (ch == '"' || ch == '\\') out.push_back('\\');
        out.push_back(ch);
    }
    return out;
}

ElDocument parse_el(const std::string& path) {
    const std::string text = read_file(path);
    ElDocument document;
    std::string pending_annotation;
    std::string section_kind;
    std::string section_name;
    std::string line;
    int line_number = 0;
    std::istringstream stream(text);
    while (std::getline(stream, line)) {
        ++line_number;
        const std::string stripped = trim(line);
        if (stripped.empty()) continue;
        if (stripped.rfind("//", 0) == 0) continue;
        if (stripped.rfind("CHECKSUM:", 0) == 0) {
            const std::size_t quote = stripped.find('"');
            std::string value;
            std::size_t next = 0;
            if (quote != std::string::npos &&
                parse_quoted(stripped, quote, &value, &next)) {
                document.checksum = value;
            }
            section_kind.clear();
            section_name.clear();
            pending_annotation.clear();
            continue;
        }
        if (stripped.rfind("INSTANCE:", 0) == 0) {
            const std::string rest = trim(stripped.substr(9));
            section_kind = "INSTANCE";
            section_name = rest;
            continue;
        }
        if (stripped.rfind("MODULE:", 0) == 0) {
            const std::string rest = trim(stripped.substr(7));
            section_kind = "MODULE";
            section_name = rest;
            continue;
        }
        if (stripped.rfind("ANNOTATION:", 0) == 0) {
            const std::size_t quote = stripped.find('"');
            std::string value;
            std::size_t next = 0;
            if (quote == std::string::npos ||
                !parse_quoted(stripped, quote, &value, &next)) {
                throw Error("EL_PARSE_FAILED", "malformed ANNOTATION line",
                            {{"path", path}, {"line", line_number}});
            }
            if (pending_annotation.empty()) {
                pending_annotation = value;
            } else {
                pending_annotation += value;
            }
            continue;
        }
        // Test-level sections (covergroup/coverpoint/cross/assert without an
        // INSTANCE/MODULE header) are legal in UCAPI-saved exclusion files.
        if (section_name.empty()) {
            section_kind = "TEST";
        }
        ElEntry entry;
        entry.section_kind = section_kind;
        entry.section_name = section_name;
        entry.object_line = stripped;
        entry.object_kind = first_token(stripped);
        entry.annotation = pending_annotation;
        entry.line_number = line_number;
        document.entries.push_back(entry);
        pending_annotation.clear();
    }
    return document;
}

} // namespace xcov
