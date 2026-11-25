#pragma once

#include <string>

namespace xcov {

/// Lowercase hex SHA-256 of the given bytes.
std::string sha256_hex(const std::string& data);

/// Raw 32-byte SHA-256 digest of the given bytes.
std::string sha256_raw(const std::string& data);

/// Raw 32-byte SHA-256 digest of one regular file (streamed, not buffered).
std::string sha256_file_raw(const std::string& path);

} // namespace xcov
