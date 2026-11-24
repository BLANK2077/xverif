#pragma once

#include <cstddef>
#include <string>

namespace xcov {

// Closed resource budgets mirrored from xcov/limits.py.
constexpr std::size_t kMaxRequestBytes = 1u * 1024u * 1024u;
constexpr std::size_t kMaxSchemaStringChars = 64u * 1024u;
constexpr std::size_t kMaxSchemaArrayItems = 100000u;
constexpr std::size_t kMaxQueryPatterns = 64u;
constexpr std::size_t kMaxExportScopes = 256u;
constexpr std::size_t kMaxResponseRows = 10000u;
constexpr std::size_t kMaxResponseBytes = 16u * 1024u * 1024u;
constexpr std::size_t kMaxIrScopes = 100000u;
constexpr std::size_t kMaxTypedRows = 500000u;
constexpr std::size_t kMaxGapRows = 100000u;
constexpr std::size_t kMaxCsvBytes = 64u * 1024u * 1024u;
constexpr std::size_t kMaxCsvRecords = 100000u;
constexpr std::size_t kMaxCsvFieldChars = 16u * 1024u;

} // namespace xcov
