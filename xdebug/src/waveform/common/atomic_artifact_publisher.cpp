#include "atomic_artifact_publisher.h"

#include <cerrno>
#include <cstring>
#include <exception>
#include <fcntl.h>
#include <fstream>
#include <set>
#include <sys/stat.h>
#include <unistd.h>

namespace xdebug_waveform {
namespace {

std::string parent_directory(const std::string& path) {
    const std::size_t slash = path.find_last_of('/');
    if (slash == std::string::npos) return ".";
    if (slash == 0) return "/";
    return path.substr(0, slash);
}

bool ensure_directory(const std::string& directory, std::string& error) {
    if (directory == "." || directory.empty()) return true;
    std::string current = directory[0] == '/' ? "/" : std::string();
    std::size_t position = directory[0] == '/' ? 1 : 0;
    while (position <= directory.size()) {
        const std::size_t next = directory.find('/', position);
        const std::string part = directory.substr(
            position, next == std::string::npos ? std::string::npos
                                                : next - position);
        if (!part.empty()) {
            if (!current.empty() && current.back() != '/') current += '/';
            current += part;
            if (mkdir(current.c_str(), 0700) != 0 && errno != EEXIST) {
                error = "failed to create artifact directory " + current +
                        ": " + std::strerror(errno);
                return false;
            }
            struct stat info {};
            if (stat(current.c_str(), &info) != 0 || !S_ISDIR(info.st_mode)) {
                error = "artifact parent is not a directory: " + current;
                return false;
            }
        }
        if (next == std::string::npos) break;
        position = next + 1;
    }
    return true;
}

bool target_available(const std::string& path, std::string& error) {
    struct stat info {};
    if (lstat(path.c_str(), &info) == 0) {
        error = "artifact target already exists: " + path;
        return false;
    }
    if (errno == ENOENT) return true;
    error = "failed to inspect artifact target " + path + ": " +
            std::strerror(errno);
    return false;
}

bool make_temp_path(const std::string& target, std::string& temporary,
                    std::string& error) {
    std::string pattern = target + ".tmp.XXXXXX";
    std::vector<char> writable(pattern.begin(), pattern.end());
    writable.push_back('\0');
    const int fd = mkstemp(writable.data());
    if (fd < 0) {
        error = "failed to create artifact temporary file for " + target +
                ": " + std::strerror(errno);
        return false;
    }
    if (close(fd) != 0) {
        error = "failed to close artifact temporary file for " + target +
                ": " + std::strerror(errno);
        unlink(writable.data());
        return false;
    }
    temporary = writable.data();
    return true;
}

bool sync_and_measure(const std::string& path, std::uint64_t& bytes,
                      std::string& error) {
    const int fd = open(path.c_str(), O_RDONLY | O_CLOEXEC);
    if (fd < 0) {
        error = "failed to open staged artifact for fsync: " + path + ": " +
                std::strerror(errno);
        return false;
    }
    struct stat info {};
    const bool stat_ok = fstat(fd, &info) == 0 && S_ISREG(info.st_mode);
    const int stat_errno = errno;
    const bool sync_ok = stat_ok && fsync(fd) == 0;
    const int sync_errno = errno;
    const bool close_ok = close(fd) == 0;
    const int close_errno = errno;
    if (!stat_ok) {
        error = "failed to stat staged artifact " + path + ": " +
                std::strerror(stat_errno);
        return false;
    }
    if (!sync_ok) {
        error = "failed to fsync staged artifact " + path + ": " +
                std::strerror(sync_errno);
        return false;
    }
    if (!close_ok) {
        error = "failed to close staged artifact " + path + ": " +
                std::strerror(close_errno);
        return false;
    }
    bytes = static_cast<std::uint64_t>(info.st_size);
    return true;
}

bool sync_directory(const std::string& directory, std::string& error) {
    const int fd = open(directory.c_str(), O_RDONLY | O_DIRECTORY | O_CLOEXEC);
    if (fd < 0) {
        error = "failed to open artifact directory for fsync " + directory +
                ": " + std::strerror(errno);
        return false;
    }
    const bool sync_ok = fsync(fd) == 0;
    const int sync_errno = errno;
    const bool close_ok = close(fd) == 0;
    const int close_errno = errno;
    if (!sync_ok) {
        error = "failed to fsync artifact directory " + directory + ": " +
                std::strerror(sync_errno);
        return false;
    }
    if (!close_ok) {
        error = "failed to close artifact directory " + directory + ": " +
                std::strerror(close_errno);
        return false;
    }
    return true;
}

}  // namespace

bool publish_atomic_artifact_set(std::vector<AtomicArtifact>& artifacts,
                                 std::string& error) {
    if (artifacts.empty()) {
        error = "artifact set must not be empty";
        return false;
    }
    const std::string directory = parent_directory(artifacts.front().target_path);
    std::set<std::string> targets;
    for (const AtomicArtifact& artifact : artifacts) {
        if (artifact.target_path.empty() || !artifact.writer) {
            error = "artifact target and writer are required";
            return false;
        }
        if (parent_directory(artifact.target_path) != directory) {
            error = "all artifacts must share one parent directory";
            return false;
        }
        if (!targets.insert(artifact.target_path).second) {
            error = "duplicate artifact target: " + artifact.target_path;
            return false;
        }
    }
    if (!ensure_directory(directory, error)) return false;
    for (const AtomicArtifact& artifact : artifacts) {
        if (!target_available(artifact.target_path, error)) return false;
    }

    std::vector<std::string> temporary(artifacts.size());
    std::vector<std::string> published;
    struct Rollback {
        Rollback(std::vector<std::string>& temporary_paths,
                 std::vector<std::string>& published_paths)
            : temporary(temporary_paths), published(published_paths) {}
        std::vector<std::string>& temporary;
        std::vector<std::string>& published;
        bool committed = false;
        ~Rollback() {
            for (const std::string& path : temporary) {
                if (!path.empty()) unlink(path.c_str());
            }
            if (!committed) {
                for (const std::string& path : published) unlink(path.c_str());
            }
        }
    } rollback(temporary, published);

    for (std::size_t index = 0; index < artifacts.size(); ++index) {
        AtomicArtifact& artifact = artifacts[index];
        if (!make_temp_path(artifact.target_path, temporary[index], error))
            return false;
        std::ofstream output(
            temporary[index].c_str(), std::ios::binary | std::ios::trunc);
        if (!output) {
            error = "failed to open staged artifact: " + artifact.target_path;
            return false;
        }
        try {
            if (!artifact.writer(output, error)) {
                if (error.empty())
                    error = "artifact writer failed: " + artifact.target_path;
                return false;
            }
        } catch (const std::exception& exc) {
            error = "artifact writer raised for " + artifact.target_path +
                    ": " + exc.what();
            return false;
        } catch (...) {
            error = "artifact writer raised for " + artifact.target_path;
            return false;
        }
        output.flush();
        output.close();
        if (!output) {
            error = "failed to write staged artifact: " + artifact.target_path;
            return false;
        }
        if (!sync_and_measure(temporary[index], artifact.bytes, error))
            return false;
    }

    for (std::size_t index = 0; index < artifacts.size(); ++index) {
        if (link(temporary[index].c_str(),
                 artifacts[index].target_path.c_str()) != 0) {
            error = "failed to publish artifact " +
                    artifacts[index].target_path + ": " +
                    std::strerror(errno);
            return false;
        }
        published.push_back(artifacts[index].target_path);
    }
    for (std::string& path : temporary) {
        if (unlink(path.c_str()) != 0) {
            error = "failed to remove staged artifact " + path + ": " +
                    std::strerror(errno);
            return false;
        }
        path.clear();
    }
    if (!sync_directory(directory, error)) return false;
    rollback.committed = true;
    return true;
}

}  // namespace xdebug_waveform
