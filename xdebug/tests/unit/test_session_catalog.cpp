#include "session/session_catalog.h"
#include "test_temp_path.h"

#include <cassert>
#include <cstdlib>
#include <fstream>
#include <stdexcept>
#include <string>
#include <sys/stat.h>
#include <unistd.h>

namespace {

xdebug::Json record(
    const std::string& id,
    const std::string& daidir,
    const std::string& fsdb,
    const std::string& transport = "uds") {
    return {
        {"session_id", id},
        {"generation", std::string(64, '1')},
        {"lifecycle_state", "active"},
        {"transport", transport},
        {"socket_path", transport == "uds" ? "fixtures/" + id + ".sock" : ""},
        {"file_dir", transport == "file" ? "fixtures/" + id + ".exchange" : ""},
        {"host", transport == "tcp" ? "launcher" : ""},
        {"bind_host", transport == "tcp" ? "127.0.0.1" : ""},
        {"port", transport == "tcp" ? 43123 : 0},
        {"server_host", "worker"},
        {"auth_token", transport == "tcp" ? "test-token" : ""},
        {"ownership_token_hash", ""},
        {"dbdir_path", daidir},
        {"fsdb_file", fsdb},
        {"server_pid", 123},
        {"created_at", 1000},
        {"last_active", 1200},
        {"dbdir_mtime_ns", daidir.empty() ? 0 : 100},
        {"dbdir_size", daidir.empty() ? 0 : 200},
        {"dbdir_dev", daidir.empty() ? 0 : 3},
        {"dbdir_inode", daidir.empty() ? 0 : 4},
        {"fsdb_mtime_ns", fsdb.empty() ? 0 : 300},
        {"fsdb_size", fsdb.empty() ? 0 : 400},
        {"fsdb_dev", fsdb.empty() ? 0 : 5},
        {"fsdb_inode", fsdb.empty() ? 0 : 6}
    };
}

void write_registry(
    const std::string& path,
    const xdebug::Json& root) {
    std::ofstream output(path.c_str());
    assert(output.good());
    output << root.dump(2) << "\n";
}

} // namespace

int main() {
    std::vector<char> temp = test_temp_template("xdebug-session-catalog.XXXXXX");
    char* home = mkdtemp(temp.data());
    assert(home != nullptr);
    assert(setenv("HOME", home, 1) == 0);

    const std::string xdebug_home = std::string(home) + "/.xdebug";
    const std::string engine_home = xdebug_home + "/engine";
    const std::string registry_path = engine_home + "/registry.json";
    assert(mkdir(xdebug_home.c_str(), 0700) == 0);
    assert(mkdir(engine_home.c_str(), 0700) == 0);

    xdebug::Json bound_wave =
        record("wave", "", "fixtures/waves.fsdb");
    bound_wave["ownership_token_hash"] =
        std::string(64, 'a');
    xdebug::Json opening_tcp =
        record("opening_tcp", "fixtures/opening.daidir", "", "tcp");
    opening_tcp["lifecycle_state"] = "opening";
    opening_tcp["port"] = 0;
    opening_tcp["server_pid"] = 0;
    xdebug::Json cleanup_failed =
        record("cleanup_failed", "", "fixtures/cleanup.fsdb");
    cleanup_failed["lifecycle_state"] = "cleanup_failed";
    cleanup_failed["server_pid"] = 0;
    xdebug::Json terminated =
        record("terminated", "", "fixtures/terminated.fsdb");
    terminated["lifecycle_state"] = "terminated_on_timeout";
    terminated["server_pid"] = 0;
    write_registry(registry_path, {
        {"version", 3},
        {"sessions", xdebug::Json::array({
            bound_wave,
            record("design", "fixtures/simv.daidir", ""),
            record("combined", "fixtures/simv.daidir", "fixtures/waves.fsdb"),
            record("file_transport", "", "fixtures/file.fsdb", "file"),
            record("tcp_transport", "fixtures/tcp.daidir", "", "tcp"),
            opening_tcp,
            cleanup_failed,
            terminated,
        })}
    });

    // An unrelated old frontend registry must never be consulted.
    std::ofstream old_frontend((xdebug_home + "/registry.json").c_str());
    old_frontend << R"JSON([{"id":"stale"}])JSON";
    old_frontend.close();

    xdebug::SessionCatalog catalog;
    std::vector<xdebug::SessionRecord> records;
    xdebug::SessionCatalogResult result = catalog.list(records);
    assert(result.ok());
    assert(records.size() == 8);

    xdebug::SessionRecord current;
    result = catalog.get("wave", current);
    assert(result.ok());
    assert(current.mode == "waveform");
    assert(current.lifecycle_state == "active");
    assert(current.fsdb == "fixtures/waves.fsdb");
    assert(current.socket_path == "fixtures/wave.sock");
    assert(current.server_pid == 123);
    assert(current.ownership_token_hash == std::string(64, 'a'));
    xdebug::Json public_record = xdebug::session_record_json(current);
    assert(public_record["session_id"] == "wave");
    assert(public_record["server_host"] == "worker");
    assert(!public_record.contains("id"));
    assert(!public_record.contains("dbdir_path"));
    assert(!public_record.contains("fsdb_file"));
    assert(!public_record.contains("ownership_token_hash"));

    xdebug::Json compact_list_record =
        xdebug::session_list_record_json(
            current, false, true, "session.gc");
    assert(compact_list_record == xdebug::Json({
        {"session_id", "wave"},
        {"mode", "waveform"},
        {"transport", "uds"},
        {"lifecycle_state", "active"},
        {"expired", true},
        {"recommended_action", "session.gc"},
        {"last_active", 1200},
    }));
    assert(!compact_list_record.contains("fsdb"));
    assert(!compact_list_record.contains("server_pid"));
    assert(!compact_list_record.contains("socket_path"));

    xdebug::Json verbose_list_record =
        xdebug::session_list_record_json(
            current, true, false, "session.doctor");
    assert(verbose_list_record["fsdb"] == "fixtures/waves.fsdb");
    assert(verbose_list_record["server_pid"] == 123);
    assert(verbose_list_record["socket_path"] == "fixtures/wave.sock");
    assert(verbose_list_record["lifecycle_state"] == "active");
    assert(verbose_list_record["expired"] == false);
    assert(verbose_list_record["recommended_action"] == "session.doctor");

    result = catalog.get("design", current);
    assert(result.ok() && current.mode == "design");
    result = catalog.get("combined", current);
    assert(result.ok() && current.mode == "combined");
    result = catalog.get("opening_tcp", current);
    assert(result.ok());
    assert(current.lifecycle_state == "opening");
    assert(current.port == 0);
    assert(current.server_pid == 0);
    xdebug::Json opening_list_record =
        xdebug::session_list_record_json(
            current, false, false, "session.doctor");
    assert(opening_list_record["lifecycle_state"] == "opening");

    result = catalog.get("cleanup_failed", current);
    assert(result.ok());
    assert(current.lifecycle_state == "cleanup_failed");
    xdebug::Json failed_list_record =
        xdebug::session_list_record_json(
            current, false, false, "session.gc");
    assert(failed_list_record["recommended_action"] == "session.gc");
    result = catalog.get("terminated", current);
    assert(result.ok());
    assert(current.lifecycle_state == "terminated_on_timeout");
    xdebug::Json terminated_list_record =
        xdebug::session_list_record_json(
            current, false, false, "session.gc");
    assert(terminated_list_record["expired"] == false);
    assert(terminated_list_record["recommended_action"] == "session.gc");
    result = catalog.get("missing", current);
    assert(result.status == xdebug::SessionCatalogStatus::NotFound);
    assert(result.code == "SESSION_NOT_FOUND");

    std::ofstream corrupt(registry_path.c_str());
    corrupt << R"JSON({"version":3,"sessions":[)JSON";
    corrupt.close();
    records.clear();
    result = catalog.list(records);
    assert(result.status == xdebug::SessionCatalogStatus::Invalid);
    assert(result.code == "REGISTRY_INVALID");
    assert(records.empty());

    // Frontend parsing is whole-document strict.  A valid registry followed
    // by any non-whitespace payload is invalid, not partially accepted.
    {
        xdebug::Json valid = {
            {"version", 3},
            {"sessions", xdebug::Json::array({
                record("trailing", "", "fixtures/trailing.fsdb"),
            })}
        };
        std::ofstream output(registry_path.c_str());
        assert(output.good());
        output << valid.dump() << "\ntrailing-data\n";
    }
    records.clear();
    result = catalog.list(records);
    assert(result.status == xdebug::SessionCatalogStatus::Invalid);
    assert(result.code == "REGISTRY_INVALID");
    assert(records.empty());

    // Version 1 is intentionally not dual-read or auto-migrated.  The
    // lifecycle caller receives an actionable canonical-registry diagnosis.
    write_registry(registry_path, {
        {"version", 1},
        {"sessions", xdebug::Json::array({
            record("legacy_v1", "", "fixtures/legacy.fsdb"),
        })}
    });
    records.clear();
    result = catalog.list(records);
    assert(result.status == xdebug::SessionCatalogStatus::Invalid);
    assert(result.code == "REGISTRY_INVALID");
    assert(result.message.find("schema version 2 or 3") != std::string::npos);
    assert(records.empty());

    // A single malformed, aliased, unknown, or duplicate record invalidates
    // the whole versioned registry; no partial session facts are published.
    xdebug::Json aliased = record("aliased", "fixtures/a.daidir", "");
    aliased["design_file"] = aliased["dbdir_path"];
    write_registry(registry_path, {
        {"version", 3},
        {"sessions", xdebug::Json::array({
            record("valid_before_error", "", "fixtures/ok.fsdb"),
            aliased,
        })}
    });
    records.clear();
    result = catalog.list(records);
    assert(result.status == xdebug::SessionCatalogStatus::Invalid);
    assert(records.empty());

    // Transport is mandatory canonical registry state.  Missing or invalid
    // values must invalidate the document rather than being interpreted as
    // an implicit UDS session.
    xdebug::Json missing_transport =
        record("missing_transport", "", "fixtures/missing.fsdb");
    missing_transport.erase("transport");
    write_registry(registry_path, {
        {"version", 3},
        {"sessions", xdebug::Json::array({missing_transport})}
    });
    records.clear();
    result = catalog.list(records);
    assert(result.status == xdebug::SessionCatalogStatus::Invalid);
    assert(records.empty());

    write_registry(registry_path, {
        {"version", 3},
        {"sessions", xdebug::Json::array({
            record("invalid_transport", "", "fixtures/invalid.fsdb", "invalid"),
        })}
    });
    records.clear();
    result = catalog.list(records);
    assert(result.status == xdebug::SessionCatalogStatus::Invalid);
    assert(records.empty());

    xdebug::Json missing_server_host =
        record("missing_server_host", "", "fixtures/missing-host.fsdb");
    missing_server_host["server_host"] = "";
    write_registry(registry_path, {
        {"version", 3},
        {"sessions", xdebug::Json::array({missing_server_host})}
    });
    records.clear();
    result = catalog.list(records);
    assert(result.status == xdebug::SessionCatalogStatus::Invalid);
    assert(records.empty());

    xdebug::Json uds_with_file_endpoint =
        record("uds_with_file_endpoint", "", "fixtures/uds.fsdb");
    uds_with_file_endpoint["file_dir"] = "fixtures/unexpected.exchange";
    write_registry(registry_path, {
        {"version", 3},
        {"sessions", xdebug::Json::array({uds_with_file_endpoint})}
    });
    records.clear();
    result = catalog.list(records);
    assert(result.status == xdebug::SessionCatalogStatus::Invalid);
    assert(records.empty());

    xdebug::Json tcp_with_socket =
        record("tcp_with_socket", "fixtures/tcp.daidir", "", "tcp");
    tcp_with_socket["socket_path"] = "fixtures/unexpected.sock";
    write_registry(registry_path, {
        {"version", 3},
        {"sessions", xdebug::Json::array({tcp_with_socket})}
    });
    records.clear();
    result = catalog.list(records);
    assert(result.status == xdebug::SessionCatalogStatus::Invalid);
    assert(records.empty());

    xdebug::Json file_with_host =
        record("file_with_host", "", "fixtures/file.fsdb", "file");
    file_with_host["host"] = "unexpected-host";
    write_registry(registry_path, {
        {"version", 3},
        {"sessions", xdebug::Json::array({file_with_host})}
    });
    records.clear();
    result = catalog.list(records);
    assert(result.status == xdebug::SessionCatalogStatus::Invalid);
    assert(records.empty());

    xdebug::Json invalid_ownership_hash =
        record("invalid_ownership_hash", "", "fixtures/token.fsdb");
    invalid_ownership_hash["ownership_token_hash"] =
        std::string(64, 'A');
    write_registry(registry_path, {
        {"version", 3},
        {"sessions", xdebug::Json::array({invalid_ownership_hash})}
    });
    records.clear();
    result = catalog.list(records);
    assert(result.status == xdebug::SessionCatalogStatus::Invalid);
    assert(result.code == "REGISTRY_INVALID");
    assert(records.empty());

    xdebug::Json overflow_port =
        record("overflow_port", "fixtures/overflow.daidir", "", "tcp");
    overflow_port["port"] = 4294967296ULL;
    write_registry(registry_path, {
        {"version", 3},
        {"sessions", xdebug::Json::array({overflow_port})}
    });
    records.clear();
    result = catalog.list(records);
    assert(result.status == xdebug::SessionCatalogStatus::Invalid);
    assert(records.empty());

    xdebug::Json overflow_pid =
        record("overflow_pid", "", "fixtures/overflow.fsdb");
    overflow_pid["server_pid"] =
        18446744073709551615ULL;
    write_registry(registry_path, {
        {"version", 3},
        {"sessions", xdebug::Json::array({overflow_pid})}
    });
    records.clear();
    result = catalog.list(records);
    assert(result.status == xdebug::SessionCatalogStatus::Invalid);
    assert(records.empty());

    xdebug::Json invalid_generation =
        record("invalid_generation", "", "fixtures/generation.fsdb");
    invalid_generation["generation"] = std::string(63, 'a');
    write_registry(registry_path, {
        {"version", 3},
        {"sessions", xdebug::Json::array({invalid_generation})}
    });
    records.clear();
    result = catalog.list(records);
    assert(result.status == xdebug::SessionCatalogStatus::Invalid);
    assert(records.empty());

    xdebug::Json invalid_lifecycle =
        record("invalid_lifecycle", "", "fixtures/lifecycle.fsdb");
    invalid_lifecycle["lifecycle_state"] = "closing";
    write_registry(registry_path, {
        {"version", 3},
        {"sessions", xdebug::Json::array({invalid_lifecycle})}
    });
    records.clear();
    result = catalog.list(records);
    assert(result.status == xdebug::SessionCatalogStatus::Invalid);
    assert(records.empty());

    xdebug::Json waveform_with_design_fingerprint =
        record("wave_with_design_fingerprint", "", "fixtures/wave.fsdb");
    waveform_with_design_fingerprint["dbdir_size"] = 1;
    write_registry(registry_path, {
        {"version", 3},
        {"sessions", xdebug::Json::array({
            waveform_with_design_fingerprint
        })}
    });
    records.clear();
    result = catalog.list(records);
    assert(result.status == xdebug::SessionCatalogStatus::Invalid);
    assert(records.empty());

    xdebug::SessionRecord invalid_public_record;
    invalid_public_record.id = "invalid-public";
    invalid_public_record.mode = "waveform";
    invalid_public_record.fsdb = "fixtures/public.fsdb";
    invalid_public_record.transport = "uds";
    invalid_public_record.socket_path = "fixtures/public.sock";
    bool public_record_rejected = false;
    try {
        (void)xdebug::session_record_json(invalid_public_record);
    } catch (const std::invalid_argument&) {
        public_record_rejected = true;
    }
    assert(public_record_rejected);

    write_registry(registry_path, {
        {"version", 3},
        {"sessions", xdebug::Json::array({
            record("duplicate", "", "fixtures/a.fsdb"),
            record("duplicate", "", "fixtures/b.fsdb"),
        })}
    });
    result = catalog.list(records);
    assert(result.status == xdebug::SessionCatalogStatus::Invalid);

    assert(unlink(registry_path.c_str()) == 0);
    records.clear();
    result = catalog.list(records);
    assert(result.ok());
    assert(records.empty());
    return 0;
}
