#pragma once

#include <string>

namespace xcov {

/// Read a whole UTF-8 file; throws Error("IO_ERROR") on failure.
std::string read_file(const std::string& path);

bool file_exists(const std::string& path);

/// Directory holding the canonical schema JSON files.
std::string schema_root();

/// Resolve a path relative to the schema root.
std::string schema_path(const std::string& relative);

std::string executable_dir(const char* argv0);

/// Create a directory tree; throws Error("IO_ERROR") on failure.
void ensure_directory(const std::string& path);

/// Write a UTF-8 file, creating parents; throws Error("IO_ERROR") on failure.
void write_file(const std::string& path, const std::string& text);

} // namespace xcov
