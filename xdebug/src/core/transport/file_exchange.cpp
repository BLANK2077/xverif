#include "transport/file_exchange.h"

#include "common/env_config.h"
#include "session/transport_common.h"

#include <algorithm>
#include <atomic>
#include <cerrno>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <ctime>
#include <dirent.h>
#include <fcntl.h>
#include <sstream>
#include <strings.h>
#include <sys/stat.h>
#include <sys/time.h>
#include <unistd.h>
#include <vector>

namespace xdebug_core {

namespace {

std::string join_path(const std::string& a, const std::string& b) {
    if (a.empty()) return b;
    if (a[a.size() - 1] == '/') return a + b;
    return a + "/" + b;
}

std::string dirname_of(const std::string& path) {
    size_t slash = path.rfind('/');
    if (slash == std::string::npos) return ".";
    if (slash == 0) return "/";
    return path.substr(0, slash);
}

std::string basename_of(const std::string& path) {
    size_t slash = path.rfind('/');
    return slash == std::string::npos ? path : path.substr(slash + 1);
}

bool mkdir_p(const std::string& path) {
    if (path.empty()) return false;
    std::string cur;
    for (size_t i = 0; i < path.size(); ++i) {
        cur.push_back(path[i]);
        if (path[i] != '/' && i + 1 != path.size()) continue;
        if (cur.empty() || cur == "/") continue;
        if (mkdir(cur.c_str(), 0700) != 0 && errno != EEXIST) return false;
    }
    return true;
}

bool file_exists(const std::string& path) {
    struct stat st;
    return stat(path.c_str(), &st) == 0;
}

bool write_all(int fd, const char* data, size_t size) {
    size_t off = 0;
    while (off < size) {
        ssize_t n = write(fd, data + off, size - off);
        if (n < 0) {
            if (errno == EINTR) continue;
            return false;
        }
        if (n == 0) {
            errno = EIO;
            return false;
        }
        off += static_cast<size_t>(n);
    }
    return true;
}

bool fsync_dir(const std::string& dir) {
    int fd = open(dir.c_str(), O_RDONLY | O_DIRECTORY);
    if (fd < 0) return false;
    bool ok = fsync(fd) == 0;
    int saved = errno;
    close(fd);
    errno = saved;
    return ok;
}

std::vector<std::string> list_json_files(const std::string& dir) {
    std::vector<std::string> out;
    DIR* dp = opendir(dir.c_str());
    if (!dp) return out;
    while (dirent* ent = readdir(dp)) {
        std::string name = ent->d_name;
        if (name.size() >= 5 && name.substr(name.size() - 5) == ".json") {
            out.push_back(name);
        }
    }
    closedir(dp);
    std::sort(out.begin(), out.end());
    return out;
}

Json client_info() {
    char host[256] = {};
    if (gethostname(host, sizeof(host) - 1) != 0 || !host[0]) {
        std::strncpy(host, "localhost", sizeof(host) - 1);
    }
    return {{"host", std::string(host)}, {"pid", static_cast<int>(getpid())}};
}

Json error_obj(const std::string& code, const std::string& message, const Json& detail = Json::object()) {
    Json err = {{"code", code}, {"message", message}};
    if (!detail.empty()) err["detail"] = detail;
    return err;
}

std::string status_suffix(const std::string& status) {
    return status.empty() ? "failed" : status;
}

std::string claim_id_from_name(const std::string& name) {
    size_t dot = name.find('.');
    return dot == std::string::npos ? name : name.substr(0, dot);
}

enum class JsonFileReadStatus {
    Ok,
    OpenFailed,
    ReadFailed,
    TooLarge,
    InvalidJson,
};

JsonFileReadStatus read_json_limited(const std::string& path, Json& out,
                                     std::string& message,
                                     std::size_t max_bytes) {
    int fd = open(path.c_str(), O_RDONLY);
    if (fd < 0) {
        message = std::string("open failed: ") + std::strerror(errno);
        return JsonFileReadStatus::OpenFailed;
    }
    std::string text;
    char buf[8192];
    while (true) {
        ssize_t n = read(fd, buf, sizeof(buf));
        if (n < 0) {
            if (errno == EINTR) continue;
            message = std::string("read failed: ") + std::strerror(errno);
            close(fd);
            return JsonFileReadStatus::ReadFailed;
        }
        if (n == 0) break;
        if (text.size() + static_cast<size_t>(n) > max_bytes) {
            message = "JSON file exceeds the transport size limit";
            close(fd);
            return JsonFileReadStatus::TooLarge;
        }
        text.append(buf, static_cast<size_t>(n));
    }
    close(fd);
    try {
        out = Json::parse(text);
        if (!out.is_object()) {
            message = "JSON root is not an object";
            return JsonFileReadStatus::InvalidJson;
        }
        return JsonFileReadStatus::Ok;
    } catch (const std::exception& e) {
        message = std::string("JSON parse failed: ") + e.what();
        return JsonFileReadStatus::InvalidJson;
    }
}

bool move_file(const std::string& src, const std::string& dst) {
    size_t slash = dst.rfind('/');
    if (slash != std::string::npos && !mkdir_p(dst.substr(0, slash))) return false;
    if (rename(src.c_str(), dst.c_str()) == 0) {
        fsync_dir(dirname_of(dst));
        fsync_dir(dirname_of(src));
        return true;
    }
    return false;
}

Json make_response_wrapper(const std::string& id,
                           bool ok,
                           const std::string& status,
                           const std::string& message,
                           long long created_at_us,
                           const Json& worker,
                           const Json& response,
                           const Json& error) {
    Json wrapper = {
        {"version", kFileRpcVersion},
        {"id", id},
        {"ok", ok},
        {"status", status.empty() ? (ok ? "ok" : "server_error") : status},
        {"message", message},
        {"created_at_us", created_at_us},
        {"finished_at_us", file_exchange_now_us()},
        {"worker", worker},
        {"response", response.is_null() ? Json::object() : response}
    };
    if (!error.empty()) wrapper["error"] = error;
    return wrapper;
}

bool write_response(const std::string& dir,
                    const std::string& id,
                    const Json& wrapper) {
    std::string path = join_path(join_path(dir, "responses"), id + ".json");
    AtomicWriteResult wr = atomic_write_json_file_ex(path, wrapper, AtomicWriteMode::CreateNew,
                                                     join_path(dir, "tmp"));
    if (!wr.ok && wr.err == EEXIST) {
        return true;
    }
    return wr.ok;
}

bool validate_request_wrapper(const std::string& expected_id,
                              const Json& wrapper,
                              std::string& message) {
    if (wrapper.value("version", std::string()) != kFileRpcVersion) {
        message = "unsupported or missing file RPC version";
        return false;
    }
    if (wrapper.value("id", std::string()) != expected_id) {
        message = "request id does not match filename";
        return false;
    }
    if (!wrapper.contains("created_at_us") || !wrapper["created_at_us"].is_number_integer()) {
        message = "created_at_us must be an integer";
        return false;
    }
    if (!wrapper.contains("deadline_us") || !wrapper["deadline_us"].is_number_integer()) {
        message = "deadline_us must be an integer";
        return false;
    }
    if (!wrapper.contains("request") || !wrapper["request"].is_object()) {
        message = "request must be an object";
        return false;
    }
    return true;
}

bool fail_claim(const std::string& dir,
                const std::string& id,
                const std::string& claim_path,
                const std::string& status,
                const std::string& message,
                const Json& worker,
                const Json& error_detail = Json::object()) {
    const std::string error_code =
        status == "request_too_large" ? "REQUEST_TOO_LARGE" : status;
    Json response = make_response_wrapper(
        id, false, status, message, file_exchange_now_us(), worker,
        Json::object(), error_obj(error_code, message, error_detail));
    write_response(dir, id, response);
    std::string dst = join_path(join_path(dir, "failed"), id + "." + status_suffix(status) + ".json");
    return move_file(claim_path, dst);
}

void cleanup_ttl_dir(const std::string& dir, long long ttl_sec) {
    if (ttl_sec <= 0) return;
    DIR* dp = opendir(dir.c_str());
    if (!dp) return;
    time_t now = time(nullptr);
    while (dirent* ent = readdir(dp)) {
        std::string name = ent->d_name;
        if (name == "." || name == "..") continue;
        std::string path = join_path(dir, name);
        struct stat st;
        if (stat(path.c_str(), &st) == 0 && S_ISREG(st.st_mode) && now - st.st_mtime > ttl_sec) {
            unlink(path.c_str());
        }
    }
    closedir(dp);
}

} // namespace

long long file_exchange_now_us() {
    struct timeval tv;
    gettimeofday(&tv, nullptr);
    return static_cast<long long>(tv.tv_sec) * 1000000LL + tv.tv_usec;
}

int file_exchange_poll_interval_ms() {
    return xdebug_file_poll_interval_ms();
}

int file_exchange_max_json_bytes() {
    return xdebug_file_max_json_bytes();
}

int file_exchange_claim_timeout_ms(int request_timeout_ms) {
    return xdebug_file_claim_timeout_ms(request_timeout_ms);
}

bool file_exchange_keep_history() {
    return xdebug_file_keep_history();
}

std::string file_transport_dir(const std::string& session_dir) {
    return join_path(session_dir, "transport");
}

bool ensure_file_transport_layout(const std::string& dir) {
    if (!mkdir_p(dir)) return false;
    for (const char* sub : {"requests", "claims", "responses", "done", "failed", "tmp", "heartbeat"}) {
        if (!mkdir_p(join_path(dir, sub))) return false;
    }
    return true;
}

AtomicWriteResult atomic_write_json_file_ex(const std::string& path,
                                            const Json& payload,
                                            AtomicWriteMode mode,
                                            const std::string& tmp_dir) {
    AtomicWriteResult result;
    result.path = path;
    std::string parent = dirname_of(path);
    std::string actual_tmp_dir = tmp_dir.empty() ? parent : tmp_dir;
    if (!mkdir_p(parent) || !mkdir_p(actual_tmp_dir)) {
        result.err = errno;
        result.message = "failed to create parent or tmp directory";
        return result;
    }
    std::ostringstream tmp;
    tmp << join_path(actual_tmp_dir, "." + basename_of(path)) << ".tmp."
        << getpid() << "." << file_exchange_now_us();
    result.tmp_path = tmp.str();

    int flags = O_CREAT | O_EXCL | O_WRONLY;
    int fd = open(result.tmp_path.c_str(), flags, 0600);
    if (fd < 0) {
        result.err = errno;
        result.message = std::string("open tmp failed: ") + std::strerror(errno);
        return result;
    }

    std::string data = payload.dump(2) + "\n";
    bool ok = write_all(fd, data.c_str(), data.size());
    if (ok) ok = fsync(fd) == 0;
    int saved = errno;
    if (close(fd) != 0 && ok) {
        ok = false;
        saved = errno;
    }
    if (!ok) {
        unlink(result.tmp_path.c_str());
        result.err = saved;
        result.message = std::string("write/fsync/close failed: ") + std::strerror(saved);
        return result;
    }

    if (mode == AtomicWriteMode::CreateNew) {
        if (link(result.tmp_path.c_str(), path.c_str()) != 0) {
            saved = errno;
            unlink(result.tmp_path.c_str());
            result.err = saved;
            result.message = std::string("create target failed: ") + std::strerror(saved);
            return result;
        }
        unlink(result.tmp_path.c_str());
        fsync_dir(actual_tmp_dir);
    } else if (rename(result.tmp_path.c_str(), path.c_str()) != 0) {
        saved = errno;
        unlink(result.tmp_path.c_str());
        result.err = saved;
        result.message = std::string("rename failed: ") + std::strerror(saved);
        return result;
    }
    if (!fsync_dir(parent)) {
        result.err = errno;
        result.message = std::string("parent directory fsync failed: ") + std::strerror(errno);
        return result;
    }
    result.ok = true;
    return result;
}

bool atomic_write_json_file(const std::string& path, const Json& payload) {
    return atomic_write_json_file_ex(path, payload, AtomicWriteMode::Replace).ok;
}

std::string make_file_request_id() {
    static std::atomic<unsigned long long> counter{0};
    std::ostringstream ss;
    ss << "req-" << file_exchange_now_us() << "-" << getpid() << "-" << counter.fetch_add(1);
    return ss.str();
}

FileExchangeResult file_exchange_send_request(const std::string& dir,
                                               const Json& request,
                                               int timeout_ms) {
    FileExchangeResult result;
    if (request.dump().size() > kMaxSessionJsonBytes) {
        result.status = "request_too_large";
        result.message = "JSON request exceeds the session transport limit";
        return result;
    }
    FileTransportEnvConfig env_config;
    std::string env_error;
    if (!xdebug_file_transport_env_config(
            env_config, env_error, timeout_ms)) {
        result.status = "invalid_config";
        result.message = env_error;
        return result;
    }
    if (!ensure_file_transport_layout(dir)) {
        result.status = "layout_failed";
        result.message = "failed to create file transport directory";
        return result;
    }
    file_exchange_gc(dir);
    result.request_id = make_file_request_id();
    std::string req_path = join_path(join_path(dir, "requests"), result.request_id + ".json");
    std::string rsp_path = join_path(join_path(dir, "responses"), result.request_id + ".json");
    long long start = file_exchange_now_us();
    long long deadline = start + static_cast<long long>(timeout_ms) * 1000LL;
    Json wrapper = {
        {"version", kFileRpcVersion},
        {"id", result.request_id},
        {"created_at_us", start},
        {"deadline_us", deadline},
        {"client", client_info()},
        {"request", request}
    };
    AtomicWriteResult wr = atomic_write_json_file_ex(req_path, wrapper, AtomicWriteMode::CreateNew,
                                                     join_path(dir, "tmp"));
    if (!wr.ok) {
        result.status = "write_failed";
        result.message = wr.message;
        return result;
    }

    const int poll_ms = env_config.poll_interval_ms;
    while (file_exchange_now_us() < deadline) {
        if (file_exists(rsp_path)) {
            Json response_wrapper;
            std::string read_error;
            const JsonFileReadStatus read_status = read_json_limited(
                rsp_path, response_wrapper, read_error,
                static_cast<std::size_t>(file_exchange_max_json_bytes()));
            if (read_status != JsonFileReadStatus::Ok) {
                result.status = read_status == JsonFileReadStatus::TooLarge
                                    ? "response_too_large"
                                    : "invalid_response";
                result.message = read_error;
                return result;
            }
            result.elapsed_ms = static_cast<long>((file_exchange_now_us() - start) / 1000);
            result.ok = response_wrapper.value("ok", false);
            result.status = response_wrapper.value("status", std::string(result.ok ? "ok" : "server_error"));
            result.message = response_wrapper.value("message", std::string());
            result.response_wrapper = response_wrapper;
            result.response = response_wrapper.value("response", Json::object());

            if (env_config.keep_history) {
                move_file(rsp_path, join_path(join_path(dir, "done"), result.request_id + ".response.json"));
            } else {
                unlink(rsp_path.c_str());
                fsync_dir(dirname_of(rsp_path));
            }
            return result;
        }
        usleep(static_cast<useconds_t>(poll_ms) * 1000);
    }

    result.elapsed_ms = static_cast<long>((file_exchange_now_us() - start) / 1000);
    result.status = "timeout";
    result.message = "file transport request timed out";
    move_file(req_path, join_path(join_path(dir, "failed"), result.request_id + ".client_timeout.json"));
    return result;
}

FileClaimResult file_exchange_claim_one(const std::string& dir,
                                        const std::string& agent_id) {
    FileClaimResult result;
    if (!ensure_file_transport_layout(dir)) {
        result.status = "layout_failed";
        result.message = "failed to create file transport directory";
        return result;
    }
    std::string req_dir = join_path(dir, "requests");
    std::string claim_dir = join_path(dir, "claims");
    Json worker = client_info();
    worker["agent_id"] = agent_id;

    for (const std::string& name : list_json_files(req_dir)) {
        std::string id = name.substr(0, name.size() - 5);
        std::string src = join_path(req_dir, name);
        std::string claim_path = join_path(claim_dir, id + "." + agent_id + ".json");
        if (rename(src.c_str(), claim_path.c_str()) != 0) continue;
        fsync_dir(req_dir);
        fsync_dir(claim_dir);
        result.claimed = true;
        result.request_id = id;
        result.claim_path = claim_path;

        Json wrapper;
        std::string read_error;
        constexpr std::size_t kFileRpcEnvelopeOverheadBytes = 64U * 1024U;
        const JsonFileReadStatus read_status = read_json_limited(
            claim_path, wrapper, read_error,
            kMaxSessionJsonBytes + kFileRpcEnvelopeOverheadBytes);
        if (read_status != JsonFileReadStatus::Ok) {
            result.status = read_status == JsonFileReadStatus::TooLarge
                                ? "request_too_large"
                                : "invalid_request";
            result.message = read_error;
            fail_claim(dir, id, claim_path, result.status, read_error, worker);
            return result;
        }
        std::string validation_error;
        if (!validate_request_wrapper(id, wrapper, validation_error)) {
            result.status = "invalid_request";
            result.message = validation_error;
            fail_claim(dir, id, claim_path, "invalid_request", validation_error, worker);
            return result;
        }
        if (wrapper["request"].dump().size() > kMaxSessionJsonBytes) {
            result.status = "request_too_large";
            result.message =
                "JSON request exceeds the session transport limit";
            fail_claim(dir, id, claim_path, result.status, result.message,
                       worker);
            return result;
        }
        long long now = file_exchange_now_us();
        long long deadline = wrapper["deadline_us"].get<long long>();
        if (now > deadline) {
            result.status = "expired";
            result.message = "request deadline expired before execution";
            fail_claim(dir, id, claim_path, "expired", result.message, worker);
            return result;
        }
        wrapper["claimed_at_us"] = now;
        wrapper["worker"] = worker;
        atomic_write_json_file_ex(claim_path, wrapper, AtomicWriteMode::Replace, join_path(dir, "tmp"));
        result.ready = true;
        result.status = "claimed";
        result.wrapper = wrapper;
        result.request = wrapper["request"];
        return result;
    }
    return result;
}

bool file_exchange_complete_claim(const std::string& dir,
                                  const FileClaimResult& claim,
                                  const Json& response,
                                  bool ok,
                                  const std::string& status,
                                  const std::string& message,
                                  const Json& worker,
                                  const Json& error) {
    if (!claim.claimed || claim.request_id.empty() || claim.claim_path.empty()) return false;
    long long created_at = claim.wrapper.value("created_at_us", file_exchange_now_us());
    Json wrapper = make_response_wrapper(claim.request_id, ok, status, message, created_at,
                                         worker, response, error);
    bool wrote = write_response(dir, claim.request_id, wrapper);
    std::string done = join_path(join_path(dir, "done"), claim.request_id + ".claim.json");
    bool moved = move_file(claim.claim_path, done);
    return wrote && moved;
}

int file_exchange_scan_stale_claims(const std::string& dir,
                                    const std::string& agent_id,
                                    long long claim_timeout_ms) {
    if (!ensure_file_transport_layout(dir)) return 0;
    std::string claim_dir = join_path(dir, "claims");
    int count = 0;
    Json worker = client_info();
    worker["agent_id"] = agent_id;
    long long now = file_exchange_now_us();
    for (const std::string& name : list_json_files(claim_dir)) {
        std::string path = join_path(claim_dir, name);
        Json wrapper;
        std::string read_error;
        std::string id = claim_id_from_name(name.substr(0, name.size() - 5));
        long long created = 0;
        if (read_json_limited(
                path, wrapper, read_error,
                kMaxSessionJsonBytes + 64U * 1024U) ==
                JsonFileReadStatus::Ok &&
            wrapper.contains("created_at_us") &&
            wrapper["created_at_us"].is_number_integer()) {
            id = wrapper.value("id", id);
            if (wrapper.contains("claimed_at_us") && wrapper["claimed_at_us"].is_number_integer()) {
                created = wrapper["claimed_at_us"].get<long long>();
            } else {
                created = wrapper["created_at_us"].get<long long>();
            }
        } else {
            struct stat st;
            if (stat(path.c_str(), &st) == 0) created = static_cast<long long>(st.st_ctime) * 1000000LL;
        }
        if (created > 0 && now - created > claim_timeout_ms * 1000LL) {
            std::string message = "claimed request exceeded XDEBUG_FILE_CLAIM_TIMEOUT_MS";
            Json response = make_response_wrapper(id, false, "stale_claim", message, created,
                                                  worker, Json::object(), error_obj("stale_claim", message));
            write_response(dir, id, response);
            move_file(path, join_path(join_path(dir, "failed"), id + ".stale_claim.json"));
            count++;
        }
    }
    return count;
}

int file_exchange_gc(const std::string& dir) {
    if (!ensure_file_transport_layout(dir)) return 0;
    long long done_ttl = xdebug_file_done_ttl_sec();
    long long failed_ttl = xdebug_file_failed_ttl_sec();
    cleanup_ttl_dir(join_path(dir, "done"), done_ttl);
    cleanup_ttl_dir(join_path(dir, "failed"), failed_ttl);
    return 0;
}

} // namespace xdebug_core
