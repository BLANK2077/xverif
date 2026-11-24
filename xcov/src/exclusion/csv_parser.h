#pragma once

#include <string>
#include <vector>

namespace xcov {

struct CsvRow {
    std::vector<std::string> fields;
    int line_number = 0;
    std::vector<std::string> header;
    std::string value(const std::string& name) const;
    bool has(const std::string& name) const;
};

struct CsvDocument {
    std::string schema_version;
    std::string coverage_kind;
    std::vector<std::string> header;
    std::vector<CsvRow> rows;
};

/// Parse one xcov exclusion CSV file; throws Error("CSV_INVALID") on failure.
CsvDocument parse_csv(const std::string& path);

std::string csv_escape_field(const std::string& value);

} // namespace xcov
