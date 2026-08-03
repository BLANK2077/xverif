#pragma once

#include "json.hpp"

#include <functional>
#include <string>
#include <utility>

namespace xdebug_waveform {

using StoreJson = nlohmann::ordered_json;

enum class StoreStatus {
    Ok,
    NotFound,
    Invalid,
    IoError,
    Conflict
};

struct StoreResult {
    StoreStatus status = StoreStatus::Ok;
    std::string code;
    std::string message;

    StoreResult() = default;
    StoreResult(
        StoreStatus result_status,
        std::string result_code,
        std::string result_message)
        : status(result_status),
          code(std::move(result_code)),
          message(std::move(result_message)) {}

    bool ok() const { return status == StoreStatus::Ok; }
};

class VersionedJsonStore {
public:
    VersionedJsonStore(std::string path, std::string collection);

    StoreResult load(StoreJson& items) const;
    StoreResult update(
        const std::function<StoreResult(StoreJson&)>& mutation) const;

private:
    std::string path_;
    std::string lock_path_;
    std::string collection_;

    int lock() const;
    static bool unlock(int fd);
    StoreResult load_unlocked(StoreJson& items) const;
    StoreResult save_unlocked(const StoreJson& items) const;
};

StoreResult store_not_found(const std::string& message);
StoreResult store_conflict(const std::string& message);
StoreResult store_invalid(const std::string& message);
std::string store_error_text(const StoreResult& result);

} // namespace xdebug_waveform
