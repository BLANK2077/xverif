#include "exclusion/csv_parser.h"

#include "core/errors.h"
#include "core/fs.h"

#include <sstream>

namespace xcov {

namespace {

// Split one CSV record honoring double-quoted fields with "" escapes.
std::vector<std::string> split_record(const std::string& line) {
    std::vector<std::string> fields;
    std::string current;
    bool quoted = false;
    for (std::size_t index = 0; index < line.size(); ++index) {
        const char ch = line[index];
        if (quoted) {
            if (ch == '"') {
                if (index + 1 < line.size() && line[index + 1] == '"') {
                    current.push_back('"');
                    ++index;
                } else {
                    quoted = false;
                }
            } else {
                current.push_back(ch);
            }
            continue;
        }
        if (ch == '"') {
            quoted = true;
        } else if (ch == ',') {
            fields.push_back(current);
            current.clear();
        } else {
            current.push_back(ch);
        }
    }
    fields.push_back(current);
    return fields;
}

std::string trimmed(const std::string& value) {
    std::size_t start = 0;
    std::size_t end = value.size();
    while (start < end &&
           (value[start] == ' ' || value[start] == '\t' || value[start] == '\r')) {
        ++start;
    }
    while (end > start &&
           (value[end - 1] == ' ' || value[end - 1] == '\t' || value[end - 1] == '\r')) {
        --end;
    }
    return value.substr(start, end - start);
}

} // namespace

std::string CsvRow::value(const std::string& name) const {
    for (std::size_t index = 0; index < header.size() && index < fields.size();
         ++index) {
        if (header[index] == name) return fields[index];
    }
    return std::string();
}

bool CsvRow::has(const std::string& name) const {
    for (const auto& item : header) {
        if (item == name) return true;
    }
    return false;
}

CsvDocument parse_csv(const std::string& path) {
    const std::string text = read_file(path);
    CsvDocument document;
    std::istringstream stream(text);
    std::string line;
    int line_number = 0;
    bool header_seen = false;
    std::string current_source_file;
    while (std::getline(stream, line)) {
        ++line_number;
        const std::string stripped = trimmed(line);
        if (stripped.empty()) continue;
        if (stripped.rfind("#", 0) == 0) {
            const std::string body = trimmed(stripped.substr(1));
            if (body.rfind("schema_version=", 0) == 0) {
                document.schema_version = trimmed(body.substr(15));
            } else if (body.rfind("coverage_kind=", 0) == 0) {
                document.coverage_kind = trimmed(body.substr(14));
            } else if (body.rfind("source_file=", 0) == 0) {
                // Python groups data rows under "# source_file=<rel>"; keep the
                // group so line selectors can match the right file.
                current_source_file = trimmed(body.substr(12));
            }
            continue;
        }
        const std::vector<std::string> fields = split_record(stripped);
        if (!header_seen) {
            for (const auto& field : fields) {
                document.header.push_back(trimmed(field));
            }
            header_seen = true;
            continue;
        }
        CsvRow row;
        row.fields = fields;
        row.line_number = line_number;
        row.source_file = current_source_file;
        row.header = document.header;
        document.rows.push_back(row);
    }
    if (!header_seen) {
        throw Error("CSV_INVALID", "exclusion CSV has no header row",
                    {{"path", path}});
    }
    return document;
}

std::string csv_escape_field(const std::string& value) {
    if (value.find_first_of(",\"\n") == std::string::npos) return value;
    std::string out = "\"";
    for (char ch : value) {
        if (ch == '"') out.push_back('"');
        out.push_back(ch);
    }
    out.push_back('"');
    return out;
}

} // namespace xcov
