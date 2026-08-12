#include "common/env_config.h"

#include <cerrno>
#include <algorithm>
#include <climits>
#include <cstdlib>
#include <cstring>
#include <strings.h>
#include <stdexcept>

namespace xdebug_core {

namespace {

bool empty_env(const char* raw) {
    return raw == nullptr || raw[0] == '\0';
}

std::string range_error(const char* name, const std::string& type, long long min_value, long long max_value) {
    return std::string(name) + " must be a " + type + " in range [" +
           std::to_string(min_value) + ", " + std::to_string(max_value) + "]";
}

bool parse_ll_value(const char* raw, long long& value) {
    errno = 0;
    char* end = nullptr;
    long long parsed = std::strtoll(raw, &end, 10);
    if (errno != 0 || end == raw || (end && *end != '\0')) return false;
    value = parsed;
    return true;
}

bool strict_env_ll(const char* name,
                   long long default_value,
                   long long min_value,
                   long long max_value,
                   long long& value,
                   std::string& error) {
    const char* raw = std::getenv(name);
    if (raw == nullptr) {
        value = default_value;
        return true;
    }
    if (raw[0] == '\0') {
        error = range_error(name, "integer", min_value, max_value);
        return false;
    }
    return env_ll(
        name, default_value, min_value, max_value, value, error);
}

bool strict_env_bool(const char* name,
                     bool default_value,
                     bool& value,
                     std::string& error) {
    const char* raw = std::getenv(name);
    if (raw == nullptr) {
        value = default_value;
        return true;
    }
    if (raw[0] == '\0') {
        error = std::string(name) + " must be a boolean value";
        return false;
    }
    return env_bool(name, default_value, value, error);
}

} // namespace

std::string env_raw_string(const char* name) {
    const char* value = std::getenv(name);
    return value ? std::string(value) : std::string();
}

std::string env_string(const char* name, const std::string& default_value) {
    std::string value = env_raw_string(name);
    return value.empty() ? default_value : value;
}

bool env_bool(const char* name, bool default_value, bool& value, std::string& error) {
    const char* raw = std::getenv(name);
    if (empty_env(raw)) {
        value = default_value;
        return true;
    }
    if (std::strcmp(raw, "1") == 0 || strcasecmp(raw, "true") == 0 ||
        strcasecmp(raw, "yes") == 0 || strcasecmp(raw, "on") == 0) {
        value = true;
        return true;
    }
    if (std::strcmp(raw, "0") == 0 || strcasecmp(raw, "false") == 0 ||
        strcasecmp(raw, "no") == 0 || strcasecmp(raw, "off") == 0) {
        value = false;
        return true;
    }
    error = std::string(name) + " must be a boolean value";
    return false;
}

bool env_int(const char* name, int default_value, int min_value, int max_value,
             int& value, std::string& error) {
    long long parsed = default_value;
    std::string local_error;
    if (!env_ll(name, default_value, min_value, max_value, parsed, local_error)) {
        error = local_error;
        return false;
    }
    value = static_cast<int>(parsed);
    return true;
}

bool env_ll(const char* name, long long default_value, long long min_value, long long max_value,
            long long& value, std::string& error) {
    const char* raw = std::getenv(name);
    if (empty_env(raw)) {
        value = default_value;
        return true;
    }
    long long parsed = 0;
    if (!parse_ll_value(raw, parsed) || parsed < min_value || parsed > max_value) {
        error = range_error(name, "integer", min_value, max_value);
        return false;
    }
    value = parsed;
    return true;
}

bool env_bool_or_default(const char* name, bool default_value) {
    bool value = default_value;
    std::string error;
    return env_bool(name, default_value, value, error) ? value : default_value;
}

int env_int_or_default(const char* name, int default_value, int min_value, int max_value) {
    int value = default_value;
    std::string error;
    return env_int(name, default_value, min_value, max_value, value, error) ? value : default_value;
}

long long env_ll_or_default(const char* name,
                            long long default_value,
                            long long min_value,
                            long long max_value) {
    long long value = default_value;
    std::string error;
    return env_ll(name, default_value, min_value, max_value, value, error) ? value : default_value;
}

bool xdebug_file_transport_env_config(
    FileTransportEnvConfig& config,
    std::string& error,
    int request_timeout_ms) {
    config = FileTransportEnvConfig();
    error.clear();
    long long value = 0;
    if (!strict_env_ll(
            "XDEBUG_FILE_TRANSPORT_TIMEOUT_MS", 300000, 1, INT_MAX,
            value, error)) return false;
    config.request_timeout_ms = static_cast<int>(value);
    if (!strict_env_ll(
            "XDEBUG_FILE_TRANSPORT_PING_TIMEOUT_MS", 2000, 1, INT_MAX,
            value, error)) return false;
    config.ping_timeout_ms = static_cast<int>(value);
    if (!strict_env_ll(
            "XDEBUG_FILE_POLL_INTERVAL_MS", 20, 1, 10000,
            value, error)) return false;
    config.poll_interval_ms = static_cast<int>(value);
    if (!strict_env_ll(
            "XDEBUG_FILE_MAX_JSON_BYTES", 67108864, 1,
            1024LL * 1024LL * 1024LL, value, error)) return false;
    config.max_json_bytes = static_cast<int>(value);

    const long long effective_request_timeout =
        request_timeout_ms > 0
            ? request_timeout_ms
            : config.request_timeout_ms;
    const long long claim_default =
        effective_request_timeout > 300000
            ? std::min(
                  2LL * effective_request_timeout,
                  24LL * 60LL * 60LL * 1000LL)
            : 600000LL;
    if (!strict_env_ll(
            "XDEBUG_FILE_CLAIM_TIMEOUT_MS", claim_default, 1,
            24LL * 60LL * 60LL * 1000LL, value, error)) return false;
    config.claim_timeout_ms = static_cast<int>(value);
    if (!strict_env_bool(
            "XDEBUG_FILE_KEEP_HISTORY", true,
            config.keep_history, error)) return false;
    if (!strict_env_ll(
            "XDEBUG_FILE_DONE_TTL_SEC", 7LL * 24LL * 60LL * 60LL,
            0, LLONG_MAX, config.done_ttl_sec, error)) return false;
    if (!strict_env_ll(
            "XDEBUG_FILE_FAILED_TTL_SEC", 30LL * 24LL * 60LL * 60LL,
            0, LLONG_MAX, config.failed_ttl_sec, error)) return false;
    return true;
}

bool xdebug_log_env_config(LogEnvConfig& config, std::string& error) {
    config = LogEnvConfig();
    error.clear();
    if (!strict_env_ll(
            "XDEBUG_LOG_MAX_BYTES", 0, 0, LLONG_MAX,
            config.max_bytes, error)) return false;
    if (!strict_env_ll(
            "XDEBUG_LOG_MAX_FILES", 3, 1, LLONG_MAX,
            config.max_files, error)) return false;
    config.path_mode = env_raw_string("XDEBUG_LOG_PATH_MODE");
    if (std::getenv("XDEBUG_LOG_PATH_MODE") != nullptr &&
        config.path_mode != "full" && config.path_mode != "basename" &&
        config.path_mode != "hash") {
        error =
            "XDEBUG_LOG_PATH_MODE must be full, basename, or hash";
        return false;
    }
    if (!strict_env_bool(
            "XDEBUG_LOG_REDACT", false, config.redact, error)) return false;
    return true;
}

bool xdebug_file_and_log_env_config_valid(std::string& error) {
    FileTransportEnvConfig file_config;
    if (!xdebug_file_transport_env_config(file_config, error)) return false;
    LogEnvConfig log_config;
    return xdebug_log_env_config(log_config, error);
}

std::string xdebug_transport() {
    return env_string("XDEBUG_TRANSPORT", "uds");
}

bool xdebug_debug_enabled() {
    return env_bool_or_default("XDEBUG_DEBUG", false);
}

int xdebug_session_start_timeout_sec(std::string& error) {
    int value = 300;
    if (!env_int("XDEBUG_SESSION_START_TIMEOUT_SEC", 300, 1, INT_MAX, value, error)) return -1;
    return value;
}

int xdebug_session_idle_timeout_sec(std::string& error) {
    int value = 86400;
    if (!env_int("XDEBUG_SESSION_IDLE_TIMEOUT_SEC", 86400, 1, INT_MAX, value, error)) return -1;
    return value;
}

int xdebug_file_transport_timeout_ms() {
    FileTransportEnvConfig config;
    std::string error;
    if (!xdebug_file_transport_env_config(config, error))
        throw std::invalid_argument(error);
    return config.request_timeout_ms;
}

int xdebug_file_transport_ping_timeout_ms() {
    FileTransportEnvConfig config;
    std::string error;
    if (!xdebug_file_transport_env_config(config, error))
        throw std::invalid_argument(error);
    return config.ping_timeout_ms;
}

int xdebug_file_poll_interval_ms() {
    FileTransportEnvConfig config;
    std::string error;
    if (!xdebug_file_transport_env_config(config, error))
        throw std::invalid_argument(error);
    return config.poll_interval_ms;
}

int xdebug_file_max_json_bytes() {
    FileTransportEnvConfig config;
    std::string error;
    if (!xdebug_file_transport_env_config(config, error))
        throw std::invalid_argument(error);
    return config.max_json_bytes;
}

int xdebug_file_claim_timeout_ms(int request_timeout_ms) {
    FileTransportEnvConfig config;
    std::string error;
    if (!xdebug_file_transport_env_config(
            config, error, request_timeout_ms))
        throw std::invalid_argument(error);
    return config.claim_timeout_ms;
}

bool xdebug_file_keep_history() {
    FileTransportEnvConfig config;
    std::string error;
    if (!xdebug_file_transport_env_config(config, error))
        throw std::invalid_argument(error);
    return config.keep_history;
}

long long xdebug_file_done_ttl_sec() {
    FileTransportEnvConfig config;
    std::string error;
    if (!xdebug_file_transport_env_config(config, error))
        throw std::invalid_argument(error);
    return config.done_ttl_sec;
}

long long xdebug_file_failed_ttl_sec() {
    FileTransportEnvConfig config;
    std::string error;
    if (!xdebug_file_transport_env_config(config, error))
        throw std::invalid_argument(error);
    return config.failed_ttl_sec;
}

std::string xdebug_common_blocks_path() {
    return env_string("XDEBUG_COMMON_BLOCKS");
}

long long xdebug_log_max_bytes() {
    LogEnvConfig config;
    std::string error;
    if (!xdebug_log_env_config(config, error))
        throw std::invalid_argument(error);
    return config.max_bytes;
}

long long xdebug_log_max_files() {
    LogEnvConfig config;
    std::string error;
    if (!xdebug_log_env_config(config, error))
        throw std::invalid_argument(error);
    return config.max_files;
}

std::string xdebug_log_path_mode() {
    LogEnvConfig config;
    std::string error;
    if (!xdebug_log_env_config(config, error))
        throw std::invalid_argument(error);
    return config.path_mode;
}

bool xdebug_log_redact_enabled() {
    LogEnvConfig config;
    std::string error;
    if (!xdebug_log_env_config(config, error))
        throw std::invalid_argument(error);
    return config.redact;
}

bool xdebug_engine_test_crash_marker_enabled() {
    return env_bool_or_default("XDEBUG_ENGINE_TEST_CRASH_MARKER", false);
}

std::string xdebug_engine_test_crash_action() {
    return env_string("XDEBUG_ENGINE_TEST_CRASH_ACTION");
}

std::string xdebug_engine_test_crash_request_id() {
    return env_string("XDEBUG_ENGINE_TEST_CRASH_REQUEST_ID");
}

bool xdebug_engine_test_npi_init_fail_enabled() {
    return env_bool_or_default("XDEBUG_ENGINE_TEST_NPI_INIT_FAIL", false);
}

bool xdebug_engine_test_npi_load_design_fail_enabled() {
    return env_bool_or_default("XDEBUG_ENGINE_TEST_NPI_LOAD_DESIGN_FAIL", false);
}

bool xdebug_engine_test_npi_fsdb_open_fail_enabled() {
    return env_bool_or_default("XDEBUG_ENGINE_TEST_NPI_FSDB_OPEN_FAIL", false);
}

int xdebug_trace_source_context_lines() {
    return env_int_or_default("XDEBUG_TRACE_SOURCE_CONTEXT_LINES", 3, 0, 1000);
}

int xdebug_trace_source_merge_threshold_lines() {
    return env_int_or_default("XDEBUG_TRACE_SOURCE_MERGE_THRESHOLD_LINES", 10, 1, 1000000);
}

} // namespace xdebug_core
