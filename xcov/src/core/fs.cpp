#include "core/fs.h"

#include "core/errors.h"

#include <cstdlib>
#include <sys/stat.h>
#include <fstream>
#include <sstream>
#include <unistd.h>

namespace xcov {

std::string read_file(const std::string& path) {
    std::ifstream in(path, std::ios::in | std::ios::binary);
    if (!in) {
        throw Error("IO_ERROR", "cannot open file", {{"path", path}});
    }
    std::ostringstream buf;
    buf << in.rdbuf();
    if (in.bad()) {
        throw Error("IO_ERROR", "cannot read file", {{"path", path}});
    }
    return buf.str();
}

bool file_exists(const std::string& path) {
    std::ifstream in(path);
    return in.good();
}

std::string executable_dir(const char* argv0) {
    char buffer[4096];
    const ssize_t n = ::readlink("/proc/self/exe", buffer, sizeof(buffer) - 1);
    if (n > 0) {
        buffer[n] = '\0';
        std::string exe(buffer);
        const std::size_t slash = exe.rfind('/');
        return slash == std::string::npos ? std::string(".") : exe.substr(0, slash);
    }
    std::string arg = argv0 ? argv0 : "";
    const std::size_t slash = arg.rfind('/');
    return slash == std::string::npos ? std::string(".") : arg.substr(0, slash);
}

std::string schema_root() {
    if (const char* override_dir = std::getenv("XVERIF_XCOV_SCHEMA_DIR")) {
        if (override_dir[0] != '\0') {
            return std::string(override_dir);
        }
    }
    if (const char* home = std::getenv("XVERIF_HOME")) {
        if (home[0] != '\0') {
            return std::string(home) + "/xcov/xcov/schemas_data/v1";
        }
    }
    return "xcov/xcov/schemas_data/v1";
}

std::string schema_path(const std::string& relative) {
    return schema_root() + "/" + relative;
}

void ensure_directory(const std::string& path) {
    std::string current;
    for (std::size_t index = 0; index < path.size(); ++index) {
        current.push_back(path[index]);
        if (path[index] == '/' && current.size() > 1) {
            ::mkdir(current.c_str(), 0755);
        }
    }
    if (!path.empty()) {
        if (::mkdir(path.c_str(), 0755) != 0) {
            struct stat info;
            if (::stat(path.c_str(), &info) != 0 || !S_ISDIR(info.st_mode)) {
                throw Error("IO_ERROR", "cannot create directory",
                            {{"path", path}});
            }
        }
    }
}

void write_file(const std::string& path, const std::string& text) {
    const std::size_t slash = path.rfind('/');
    if (slash != std::string::npos && slash > 0) {
        ensure_directory(path.substr(0, slash));
    }
    std::ofstream out(path, std::ios::out | std::ios::binary | std::ios::trunc);
    if (!out) {
        throw Error("IO_ERROR", "cannot write file", {{"path", path}});
    }
    out << text;
    if (!out) {
        throw Error("IO_ERROR", "failed while writing file", {{"path", path}});
    }
}

} // namespace xcov
