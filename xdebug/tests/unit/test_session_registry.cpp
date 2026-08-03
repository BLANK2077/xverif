#include "design/common/xdebug_design_paths.h"
#include "engine/session/session_lifecycle_lease.h"
#include "engine/session/session_registry.h"
#include "test_temp_path.h"

#include <atomic>
#include <cassert>
#include <cstdlib>
#include <fstream>
#include <string>
#include <sys/stat.h>
#include <thread>
#include <unistd.h>
#include <vector>

namespace {

xdebug_engine::SessionInfo opening_session(
    const std::string& id,
    const std::string& generation) {
    xdebug_engine::SessionInfo session;
    session.session_id = id;
    session.generation = generation;
    session.lifecycle_state = "opening";
    session.transport = "uds";
    session.socket_path =
        xdebug_design::xdebug_design_socket_path(id);
    session.server_host = "localhost";
    session.fsdb_file = "fixtures/waves.fsdb";
    session.created_at = 100;
    session.last_active = 100;
    return session;
}

void wait_until(const std::atomic<bool>& ready) {
    for (int i = 0; i < 1000 && !ready.load(); ++i) {
        usleep(1000);
    }
    assert(ready.load());
}

} // namespace

int main() {
    std::vector<char> temp =
        test_temp_template("xdebug-session-registry.XXXXXX");
    char* home = mkdtemp(temp.data());
    assert(home != nullptr);
    assert(setenv("HOME", home, 1) == 0);

    const std::string alias = "same_alias";
    const std::string generation_one(64, '1');
    const std::string generation_two(64, '2');
    const xdebug_engine::SessionInfo first =
        opening_session(alias, generation_one);
    const xdebug_engine::SessionInfo second =
        opening_session(alias, generation_two);
    xdebug_engine::SessionRegistry registry;

    std::atomic<bool> first_locked(false);
    std::atomic<bool> second_started(false);
    std::atomic<bool> second_acquired(false);
    std::atomic<bool> release_first(false);
    xdebug_engine::SessionRegistryResult first_reserve;
    xdebug_engine::SessionRegistryResult second_reserve;

    std::thread owner_one([&]() {
        xdebug_engine::SessionLifecycleLease lease(alias);
        assert(lease.locked());
        first_locked.store(true);
        while (!release_first.load()) usleep(1000);
        first_reserve = registry.reserve_opening(first);
    });
    wait_until(first_locked);
    std::thread owner_two([&]() {
        second_started.store(true);
        xdebug_engine::SessionLifecycleLease lease(alias);
        assert(lease.locked());
        second_acquired.store(true);
        second_reserve = registry.reserve_opening(second);
    });
    wait_until(second_started);
    usleep(50000);
    assert(!second_acquired.load());
    release_first.store(true);
    owner_one.join();
    owner_two.join();
    assert(first_reserve.ok());
    assert(
        second_reserve.status ==
        xdebug_engine::SessionRegistryStatus::Conflict);

    assert(
        xdebug_design::xdebug_design_write_generation_marker(
            alias, generation_one));
    const std::string transport_dir =
        xdebug_design::xdebug_design_session_dir(alias) +
        "/transport";
    const std::string request_dir =
        transport_dir + "/requests";
    assert(mkdir(transport_dir.c_str(), 0700) == 0);
    assert(mkdir(request_dir.c_str(), 0700) == 0);
    const std::string request_path =
        request_dir + "/old.json";
    {
        std::ofstream output(request_path.c_str());
        assert(output.good());
        output << "{}\n";
    }
    xdebug_engine::SessionInfo retained = first;
    retained.lifecycle_state = "cleanup_failed";
    assert(
        registry
            .mark_cleanup_failed(
                retained, generation_one)
            .ok());

    // A mismatched marker makes artifact cleanup fail closed while the
    // cleanup_failed generation remains managed in the canonical registry.
    assert(
        xdebug_design::xdebug_design_write_generation_marker(
            alias, generation_two));
    assert(
        !xdebug_design::xdebug_design_remove_session_generation(
            alias, generation_one));
    assert(access(request_path.c_str(), F_OK) == 0);
    xdebug_engine::SessionInfo current;
    assert(registry.get(alias, current).ok());
    assert(current.generation == generation_one);
    assert(current.lifecycle_state == "cleanup_failed");

    assert(
        xdebug_design::xdebug_design_write_generation_marker(
            alias, generation_one));
    assert(
        xdebug_design::xdebug_design_remove_session_generation(
            alias, generation_one));
    assert(access(transport_dir.c_str(), F_OK) != 0);
    assert(
        registry
            .remove_if_generation(
                alias, generation_one)
            .ok());

    // Reusing the alias creates a new generation.  A delayed cleanup from
    // generation one cannot delete generation two's sidecar or registry row.
    assert(registry.reserve_opening(second).ok());
    assert(
        xdebug_design::xdebug_design_write_generation_marker(
            alias, generation_two));
    assert(
        !xdebug_design::xdebug_design_remove_session_generation(
            alias, generation_one));
    assert(
        xdebug_design::xdebug_design_generation_matches(
            alias, generation_two));
    assert(registry.get(alias, current).ok());
    assert(current.generation == generation_two);

    // A touch only rewrites the durable registry when time advances.  The
    // same-second helper/server pair and an older concurrent observation are
    // successful no-ops, while generation checks still fail closed.
    assert(
        registry
            .touch_if_generation(alias, generation_two, 200)
            .ok());
    assert(registry.get(alias, current).ok());
    assert(current.last_active == 200);
    struct stat registry_before_noop;
    assert(
        stat(
            xdebug_design::xdebug_design_registry_path().c_str(),
            &registry_before_noop) == 0);
    assert(
        registry
            .touch_if_generation(alias, generation_two, 200)
            .ok());
    assert(
        registry
            .touch_if_generation(alias, generation_two, 150)
            .ok());
    const xdebug_engine::SessionRegistryResult stale_touch =
        registry.touch_if_generation(alias, generation_one, 300);
    assert(
        stale_touch.status ==
        xdebug_engine::SessionRegistryStatus::GenerationMismatch);
    struct stat registry_after_noop;
    assert(
        stat(
            xdebug_design::xdebug_design_registry_path().c_str(),
            &registry_after_noop) == 0);
    assert(registry_before_noop.st_ino == registry_after_noop.st_ino);
    assert(registry.get(alias, current).ok());
    assert(current.last_active == 200);
    assert(
        registry
            .touch_if_generation(alias, generation_two, 201)
            .ok());
    assert(registry.get(alias, current).ok());
    assert(current.last_active == 201);

    retained = second;
    retained.lifecycle_state = "cleanup_failed";
    assert(
        registry
            .mark_cleanup_failed(
                retained, generation_two)
            .ok());
    assert(
        xdebug_design::xdebug_design_remove_session_generation(
            alias, generation_two));
    assert(
        registry
            .remove_if_generation(
                alias, generation_two)
            .ok());
    assert(
        registry.get(alias, current).status ==
        xdebug_engine::SessionRegistryStatus::NotFound);

    {
        std::ofstream output(
            xdebug_design::xdebug_design_registry_path().c_str(),
            std::ios::trunc);
        assert(output.good());
        output << "{\"version\":1,\"sessions\":[]}\n";
    }
    std::vector<xdebug_engine::SessionInfo> sessions;
    assert(
        registry.load_all(sessions).status ==
        xdebug_engine::SessionRegistryStatus::Invalid);
    assert(sessions.empty());

    {
        std::ofstream output(
            xdebug_design::xdebug_design_registry_path().c_str(),
            std::ios::trunc);
        assert(output.good());
        output
            << "{\"version\":2,\"sessions\":[]}\n"
            << "trailing-data\n";
    }
    assert(
        registry.load_all(sessions).status ==
        xdebug_engine::SessionRegistryStatus::Invalid);
    assert(sessions.empty());
    return 0;
}
