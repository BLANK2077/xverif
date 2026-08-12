#include "transport/file_exchange.h"
#include "session/transport_common.h"
#include "test_temp_path.h"

#include <cassert>
#include <cstdlib>
#include <fstream>
#include <sstream>
#include <string>
#include <sys/wait.h>
#include <unistd.h>

using xdebug_core::Json;

static std::string join_path(const std::string& a, const std::string& b) {
    if (a.empty()) return b;
    if (a[a.size() - 1] == '/') return a + b;
    return a + "/" + b;
}

static bool exists(const std::string& path) {
    return access(path.c_str(), F_OK) == 0;
}

static Json read_json_file(const std::string& path) {
    std::ifstream in(path.c_str());
    std::ostringstream ss;
    ss << in.rdbuf();
    return Json::parse(ss.str());
}

static Json request_wrapper(const std::string& id, long long deadline_us) {
    long long now = xdebug_core::file_exchange_now_us();
    return {
        {"version", xdebug_core::kFileRpcVersion},
        {"id", id},
        {"created_at_us", now},
        {"deadline_us", deadline_us},
        {"client", {{"host", "unit"}, {"pid", 1}}},
        {"request", {{"command", "PING"}}}
    };
}

int main() {
    std::vector<char> dir_storage = test_temp_template("xdebug_file_exchange_test_XXXXXX");
    char* dir_path = mkdtemp(dir_storage.data());
    assert(dir_path != nullptr);
    std::string dir = dir_path;
    assert(xdebug_core::ensure_file_transport_layout(dir));
    for (const char* sub : {"requests", "claims", "responses", "done", "failed", "tmp", "heartbeat"}) {
        assert(exists(join_path(dir, sub)));
    }

    std::string create_once = join_path(join_path(dir, "tmp"), "create_once.json");
    assert(xdebug_core::atomic_write_json_file_ex(create_once, {{"a", 1}}, xdebug_core::AtomicWriteMode::CreateNew).ok);
    assert(!xdebug_core::atomic_write_json_file_ex(create_once, {{"a", 2}}, xdebug_core::AtomicWriteMode::CreateNew).ok);
    assert(xdebug_core::atomic_write_json_file_ex(create_once, {{"a", 3}}, xdebug_core::AtomicWriteMode::Replace).ok);
    assert(read_json_file(create_once)["a"] == 3);

    std::string manual_id = "manual";
    std::string manual_path = join_path(join_path(dir, "requests"), manual_id + ".json");
    assert(xdebug_core::atomic_write_json_file_ex(
        manual_path,
        request_wrapper(manual_id, xdebug_core::file_exchange_now_us() + 1000000),
        xdebug_core::AtomicWriteMode::CreateNew,
        join_path(dir, "tmp")).ok);
    xdebug_core::FileClaimResult claim = xdebug_core::file_exchange_claim_one(dir, "agent_a");
    assert(claim.claimed);
    assert(claim.ready);
    assert(claim.request_id == manual_id);
    assert(claim.request["command"] == "PING");
    assert(claim.wrapper.contains("claimed_at_us"));
    Json worker = {{"agent_id", "agent_a"}, {"host", "unit"}, {"pid", 2}};
    assert(xdebug_core::file_exchange_complete_claim(
        dir, claim, {{"payload", "PONG"}, {"server_error", false}},
        true, "ok", "", worker));
    assert(exists(join_path(join_path(dir, "done"), manual_id + ".claim.json")));
    assert(exists(join_path(join_path(dir, "responses"), manual_id + ".json")));

    std::string expired_id = "expired";
    assert(xdebug_core::atomic_write_json_file_ex(
        join_path(join_path(dir, "requests"), expired_id + ".json"),
        request_wrapper(expired_id, xdebug_core::file_exchange_now_us() - 1),
        xdebug_core::AtomicWriteMode::CreateNew,
        join_path(dir, "tmp")).ok);
    xdebug_core::FileClaimResult expired = xdebug_core::file_exchange_claim_one(dir, "agent_a");
    assert(expired.claimed);
    assert(!expired.ready);
    assert(expired.status == "expired");
    assert(exists(join_path(join_path(dir, "failed"), expired_id + ".expired.json")));
    assert(read_json_file(join_path(join_path(dir, "responses"), expired_id + ".json"))["status"] == "expired");

    std::string invalid_id = "invalid";
    assert(xdebug_core::atomic_write_json_file_ex(
        join_path(join_path(dir, "requests"), invalid_id + ".json"),
        {{"id", invalid_id}, {"request", Json::object()}},
        xdebug_core::AtomicWriteMode::CreateNew,
        join_path(dir, "tmp")).ok);
    xdebug_core::FileClaimResult invalid = xdebug_core::file_exchange_claim_one(dir, "agent_a");
    assert(invalid.claimed);
    assert(!invalid.ready);
    assert(invalid.status == "invalid_request");
    assert(exists(join_path(join_path(dir, "failed"), invalid_id + ".invalid_request.json")));

    std::string stale_id = "stale";
    assert(xdebug_core::atomic_write_json_file_ex(
        join_path(join_path(dir, "claims"), stale_id + ".dead_agent.json"),
        request_wrapper(stale_id, xdebug_core::file_exchange_now_us() + 10000000),
        xdebug_core::AtomicWriteMode::CreateNew,
        join_path(dir, "tmp")).ok);
    assert(xdebug_core::file_exchange_scan_stale_claims(dir, "agent_a", 0) >= 1);
    assert(exists(join_path(join_path(dir, "failed"), stale_id + ".stale_claim.json")));
    assert(read_json_file(join_path(join_path(dir, "responses"), stale_id + ".json"))["status"] == "stale_claim");

    pid_t child = fork();
    assert(child >= 0);
    if (child == 0) {
        for (int i = 0; i < 100; ++i) {
            xdebug_core::FileClaimResult c = xdebug_core::file_exchange_claim_one(dir, "agent_child");
            if (c.claimed && c.ready) {
                Json w = {{"agent_id", "agent_child"}, {"host", "unit"}, {"pid", static_cast<int>(getpid())}};
                bool ok = xdebug_core::file_exchange_complete_claim(
                    dir, c, {{"payload", std::string("PONG ") + c.request.value("command", std::string())},
                             {"server_error", false}},
                    true, "ok", "", w);
                _exit(ok ? 0 : 2);
            }
            usleep(10000);
        }
        _exit(1);
    }

    xdebug_core::FileExchangeResult result =
        xdebug_core::file_exchange_send_request(dir, {{"command", "PING"}}, 1500);
    assert(result.ok);
    assert(result.status == "ok");
    assert(result.response["payload"] == "PONG PING");
    assert(exists(join_path(join_path(dir, "done"), result.request_id + ".response.json")));

    int status = 0;
    assert(waitpid(child, &status, 0) == child);
    assert(WIFEXITED(status) && WEXITSTATUS(status) == 0);

    std::string timeout_dir = dir + "_timeout";
    xdebug_core::FileExchangeResult timeout =
        xdebug_core::file_exchange_send_request(timeout_dir, {{"command", "PING"}}, 50);
    assert(!timeout.ok);
    assert(timeout.status == "timeout");
    assert(exists(join_path(join_path(timeout_dir, "failed"), timeout.request_id + ".client_timeout.json")));

    setenv("XDEBUG_FILE_KEEP_HISTORY", "0", 1);
    pid_t child2 = fork();
    assert(child2 >= 0);
    if (child2 == 0) {
        for (int i = 0; i < 100; ++i) {
            xdebug_core::FileClaimResult c = xdebug_core::file_exchange_claim_one(dir, "agent_child2");
            if (c.claimed && c.ready) {
                Json w = {{"agent_id", "agent_child2"}, {"host", "unit"}, {"pid", static_cast<int>(getpid())}};
                bool ok = xdebug_core::file_exchange_complete_claim(dir, c, {{"payload", "PONG"}, {"server_error", false}},
                                                                    true, "ok", "", w);
                _exit(ok ? 0 : 2);
            }
            usleep(10000);
        }
        _exit(1);
    }
    xdebug_core::FileExchangeResult no_history =
        xdebug_core::file_exchange_send_request(dir, {{"command", "PING"}}, 1500);
    assert(no_history.ok);
    assert(!exists(join_path(join_path(dir, "done"), no_history.request_id + ".response.json")));
    assert(waitpid(child2, &status, 0) == child2);
    assert(WIFEXITED(status) && WEXITSTATUS(status) == 0);

    Json oversized_request = {
        {"payload", std::string(xdebug_core::kMaxSessionJsonBytes, 'x')},
    };
    xdebug_core::FileExchangeResult too_big =
        xdebug_core::file_exchange_send_request(
            dir, oversized_request, 1500);
    assert(!too_big.ok);
    assert(too_big.status == "request_too_large");
    assert(too_big.message.find("transport limit") != std::string::npos);

    return 0;
}
