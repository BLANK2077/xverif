#include "session/session_catalog.h"
#include "common/path_utils.h"
#include "test_temp_path.h"

#include <cassert>
#include <cstdlib>
#include <fstream>
#include <string>
#include <sys/stat.h>
#include <unistd.h>
#include <vector>

namespace {

xdebug::Json record(const std::string& id,
                    const std::string& daidir,
                    const std::string& fsdb,
                    const std::string& transport = "uds") {
    return {
        {"session_id", id}, {"generation", std::string(64, '1')},
        {"lifecycle_state", "active"}, {"transport", transport},
        {"socket_path", transport == "uds" ? "fixtures/" + id + ".sock" : ""},
        {"file_dir", transport == "file" ? "fixtures/" + id + ".exchange" : ""},
        {"host", transport == "tcp" ? "launcher" : ""},
        {"bind_host", transport == "tcp" ? "127.0.0.1" : ""},
        {"port", transport == "tcp" ? 43123 : 0},
        {"server_host", "worker"},
        {"auth_token", transport == "tcp" ? "test-token" : ""},
        {"ownership_token_hash", ""}, {"dbdir_path", daidir},
        {"fsdb_file", fsdb}, {"server_pid", 123}, {"created_at", 1000},
        {"last_active", 1200}, {"dbdir_mtime_ns", daidir.empty() ? 0 : 100},
        {"dbdir_size", daidir.empty() ? 0 : 200},
        {"dbdir_dev", daidir.empty() ? 0 : 3},
        {"dbdir_inode", daidir.empty() ? 0 : 4},
        {"fsdb_mtime_ns", fsdb.empty() ? 0 : 300},
        {"fsdb_size", fsdb.empty() ? 0 : 400},
        {"fsdb_dev", fsdb.empty() ? 0 : 5},
        {"fsdb_inode", fsdb.empty() ? 0 : 6},
    };
}

void write_state(const std::string& sessions,
                 const std::string& id,
                 const xdebug::Json& value) {
    const std::string dir = sessions + "/" + xdebug_core::session_dir_name(id);
    assert(mkdir(dir.c_str(), 0700) == 0);
    std::ofstream output((dir + "/state.json").c_str());
    assert(output.good());
    output << value.dump(2) << "\n";
}

}  // namespace

int main() {
    std::vector<char> temp = test_temp_template("xdebug-session-catalog.XXXXXX");
    char* home = mkdtemp(temp.data());
    assert(home != nullptr);
    assert(setenv("HOME", home, 1) == 0);
    const std::string xdebug_home = std::string(home) + "/.xdebug";
    const std::string engine_home = xdebug_home + "/engine";
    const std::string sessions = engine_home + "/sessions";
    assert(mkdir(xdebug_home.c_str(), 0700) == 0);
    assert(mkdir(engine_home.c_str(), 0700) == 0);
    assert(mkdir(sessions.c_str(), 0700) == 0);

    xdebug::Json wave = record("wave", "", "fixtures/waves.fsdb");
    wave["ownership_token_hash"] = std::string(64, 'a');
    write_state(sessions, "wave", wave);
    write_state(sessions, "design", record("design", "fixtures/simv.daidir", ""));
    write_state(sessions, "combined", record("combined", "fixtures/simv.daidir", "fixtures/waves.fsdb"));
    write_state(sessions, "file_transport", record("file_transport", "", "fixtures/file.fsdb", "file"));
    write_state(sessions, "tcp_transport", record("tcp_transport", "fixtures/tcp.daidir", "", "tcp"));
    xdebug::Json opening = record("opening_tcp", "fixtures/opening.daidir", "", "tcp");
    opening["lifecycle_state"] = "opening";
    opening["port"] = 0;
    opening["server_pid"] = 0;
    write_state(sessions, "opening_tcp", opening);
    xdebug::Json failed = record("cleanup_failed", "", "fixtures/cleanup.fsdb");
    failed["lifecycle_state"] = "cleanup_failed";
    failed["server_pid"] = 0;
    write_state(sessions, "cleanup_failed", failed);
    xdebug::Json terminated = record("terminated", "", "fixtures/terminated.fsdb");
    terminated["lifecycle_state"] = "terminated_on_timeout";
    terminated["server_pid"] = 0;
    write_state(sessions, "terminated", terminated);

    xdebug::SessionCatalog catalog;
    std::vector<xdebug::SessionRecord> records;
    xdebug::SessionCatalogResult result = catalog.list(records);
    assert(result.ok());
    assert(records.size() == 8);

    xdebug::SessionRecord current;
    result = catalog.get("wave", current);
    assert(result.ok());
    assert(current.mode == "waveform");
    assert(current.fsdb == "fixtures/waves.fsdb");
    assert(current.ownership_token_hash == std::string(64, 'a'));
    xdebug::Json public_record = xdebug::session_record_json(current);
    assert(public_record["session_id"] == "wave");
    assert(!public_record.contains("ownership_token_hash"));

    xdebug::Json compact = xdebug::session_list_record_json(
        current, false, true, "session.gc");
    assert(compact["expired"] == true);
    assert(!compact.contains("fsdb"));
    xdebug::Json verbose = xdebug::session_list_record_json(
        current, true, false, "session.doctor");
    assert(verbose["fsdb"] == "fixtures/waves.fsdb");

    assert(catalog.get("design", current).ok() && current.mode == "design");
    assert(catalog.get("combined", current).ok() && current.mode == "combined");
    assert(catalog.get("opening_tcp", current).ok() && current.lifecycle_state == "opening");
    assert(catalog.get("cleanup_failed", current).ok() && current.lifecycle_state == "cleanup_failed");
    assert(catalog.get("terminated", current).ok() && current.lifecycle_state == "terminated_on_timeout");
    assert(catalog.get("missing", current).status == xdebug::SessionCatalogStatus::NotFound);

    // A corrupt state is isolated during enumeration but a targeted lookup
    // reports the exact session as invalid.
    const std::string corrupt_id = "corrupt";
    const std::string corrupt_dir = sessions + "/" + xdebug_core::session_dir_name(corrupt_id);
    assert(mkdir(corrupt_dir.c_str(), 0700) == 0);
    {
        std::ofstream output((corrupt_dir + "/state.json").c_str());
        output << "{not-json\n";
    }
    records.clear();
    assert(catalog.list(records).ok());
    assert(records.size() == 8);
    assert(catalog.get(corrupt_id, current).status == xdebug::SessionCatalogStatus::Invalid);

    // The directory identity is authoritative for targeted lookup.
    const std::string alias_id = "alias";
    write_state(sessions, alias_id, record("different", "", "fixtures/a.fsdb"));
    assert(catalog.get(alias_id, current).status == xdebug::SessionCatalogStatus::Invalid);
    return 0;
}
