#pragma once

#include <string>
#include <vector>

namespace xcov {

/// One object entry parsed from a VCS exclusion file (Format Version 2).
struct ElEntry {
    std::string section_kind;   // "INSTANCE" or "MODULE"
    std::string section_name;   // instance path or module name
    std::string object_line;    // raw object line, e.g. `Block 18 "cs" "src"`
    std::string object_kind;    // Block / Toggle / Branch / Condition / Fsm / Transition / Assert / covergroup ...
    std::string annotation;     // ANNOTATION text attached to this object
    int line_number = 0;
};

struct ElDocument {
    std::vector<ElEntry> entries;
    std::string checksum;       // last CHECKSUM line
};

/// Parse an exclusion file; throws Error("EL_PARSE_FAILED") with line context.
ElDocument parse_el(const std::string& path);

/// Render one raw annotation value with the EL escaping rules.
std::string escape_el_text(const std::string& value);

} // namespace xcov
