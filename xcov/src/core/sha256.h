#pragma once

#include <string>

namespace xcov {

/// Lowercase hex SHA-256 of the given bytes.
std::string sha256_hex(const std::string& data);

} // namespace xcov
