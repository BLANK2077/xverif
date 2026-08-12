#include "waveform/common/versioned_json_store.h"

#include <cerrno>
#include <cstdlib>
#include <cstring>
#include <exception>
#include <fcntl.h>
#include <fstream>
#include <sys/stat.h>
#include <unistd.h>
#include <utility>
#include <vector>

namespace xdebug_waveform {
namespace {

StoreResult result(
    StoreStatus status,
    const std::string& code,
    const std::string& message) {
    return {status, code, message};
}

bool test_hook_enabled(const char* name) {
    const char* value = std::getenv(name);
    return value != nullptr && std::strcmp(value, "1") == 0;
}

bool write_atomic_file(const std::string& path, const std::string& data) {
    std::string pattern = path + ".tmp.XXXXXX";
    std::vector<char> writable(pattern.begin(), pattern.end());
    writable.push_back('\0');
    int fd = mkstemp(writable.data());
    if (fd < 0) return false;
    bool ok = fchmod(fd, 0600) == 0;
    if (test_hook_enabled("XDEBUG_TEST_CONFIG_STORE_WRITE_FAIL")) {
        ok = false;
    }
    size_t offset = 0;
    while (ok && offset < data.size()) {
        ssize_t count = write(fd, data.data() + offset, data.size() - offset);
        if (count < 0 && errno == EINTR) continue;
        if (count <= 0) {
            ok = false;
            break;
        }
        offset += static_cast<size_t>(count);
    }
    if (ok) ok = fsync(fd) == 0;
    if (close(fd) != 0) ok = false;
    if (ok &&
        test_hook_enabled("XDEBUG_TEST_CONFIG_STORE_RENAME_FAIL")) {
        ok = false;
    }
    if (ok) ok = rename(writable.data(), path.c_str()) == 0;
    if (!ok) unlink(writable.data());
    if (!ok) return false;

    const size_t slash = path.rfind('/');
    const std::string directory =
        slash == std::string::npos ? "." : path.substr(0, slash);
    int dir_fd = open(directory.c_str(), O_RDONLY | O_DIRECTORY);
    if (dir_fd < 0) return false;
    const bool synced = fsync(dir_fd) == 0;
    close(dir_fd);
    return synced;
}

} // namespace

VersionedJsonStore::VersionedJsonStore(
    std::string path,
    std::string collection)
    : path_(std::move(path)),
      collection_(std::move(collection)) {}

StoreResult VersionedJsonStore::load_unlocked(StoreJson& items) const {
    items = StoreJson::array();
    std::ifstream input(path_.c_str());
    if (!input) {
        if (access(path_.c_str(), F_OK) != 0 && errno == ENOENT) return {};
        return result(
            StoreStatus::IoError,
            "CONFIG_STORE_IO_ERROR",
            "cannot read config store: " + path_);
    }
    try {
        StoreJson root;
        input >> root;
        if (!root.is_object() || root.size() != 2 ||
            !root.contains("version") || !root["version"].is_number_integer() ||
            root["version"].get<int>() != 1 ||
            !root.contains(collection_) || !root[collection_].is_array()) {
            return store_invalid(
                "config store does not match version 1 contract: " + path_);
        }
        items = root[collection_];
        return {};
    } catch (const std::exception& exc) {
        return store_invalid(
            "cannot parse config store " + path_ + ": " + exc.what());
    }
}

StoreResult VersionedJsonStore::save_unlocked(const StoreJson& items) const {
    if (!items.is_array())
        return store_invalid("config store collection must be an array");
    StoreJson root = {
        {"version", 1},
        {collection_, items}
    };
    if (!write_atomic_file(path_, root.dump(2) + "\n")) {
        return result(
            StoreStatus::IoError,
            "CONFIG_STORE_IO_ERROR",
            "cannot atomically write config store: " + path_);
    }
    return {};
}

StoreResult VersionedJsonStore::load(StoreJson& items) const {
    return load_unlocked(items);
}

StoreResult VersionedJsonStore::update(
    const std::function<StoreResult(StoreJson&)>& mutation) const {
    StoreJson items;
    StoreResult outcome = load_unlocked(items);
    if (outcome.ok()) outcome = mutation(items);
    if (outcome.ok()) outcome = save_unlocked(items);
    return outcome;
}

StoreResult store_not_found(const std::string& message) {
    return result(StoreStatus::NotFound, "CONFIG_NOT_FOUND", message);
}

StoreResult store_conflict(const std::string& message) {
    return result(StoreStatus::Conflict, "CONFIG_ALREADY_EXISTS", message);
}

StoreResult store_invalid(const std::string& message) {
    return result(StoreStatus::Invalid, "CONFIG_STORE_INVALID", message);
}

std::string store_error_text(const StoreResult& value) {
    const std::string code =
        value.code.empty() ? "CONFIG_STORE_IO_ERROR" : value.code;
    const std::string message =
        value.message.empty()
            ? "configuration store operation failed"
            : value.message;
    return code + ": " + message;
}

} // namespace xdebug_waveform
