#include "waveform/common/xdebug_waveform_paths.h"
#include "waveform/cursor/cursor_manager.h"
#include "test_temp_path.h"

#include <cassert>
#include <cstdlib>
#include <fstream>
#include <string>
#include <sys/stat.h>
#include <unistd.h>
#include <vector>

using namespace xdebug_waveform;

namespace {

Cursor cursor(const std::string& name, uint64_t time) {
    Cursor value;
    value.name = name;
    value.time = time;
    value.note = "note-" + name;
    value.origin = "manual";
    value.clock = "top.clk";
    return value;
}

StoreJson read_json(const std::string& path) {
    std::ifstream input(path.c_str());
    assert(input.good());
    StoreJson value;
    input >> value;
    return value;
}

std::string read_text(const std::string& path) {
    std::ifstream input(path.c_str());
    return std::string(
        (std::istreambuf_iterator<char>(input)),
        std::istreambuf_iterator<char>());
}

} // namespace

int main() {
    std::vector<char> root_storage =
        test_temp_template("xdebug-cursor-manager.XXXXXX");
    char* root = root_storage.data();
    assert(mkdtemp(root) != nullptr);
    setenv("HOME", root, 1);

    const std::string session = "CursorAtomic";
    const std::string path =
        xdebug_waveform_cursors_path(session);
    CursorManager manager;

    assert(manager.set_cursor(
        session,
        cursor("first", 10),
        true).ok());
    assert(manager.set_cursor(
        session,
        cursor("second", 20),
        false).ok());

    StoreJson persisted = read_json(path);
    assert(persisted.is_object());
    assert(persisted.size() == 2);
    assert(persisted["version"] == 1);
    assert(persisted["cursors"].is_array());
    assert(!persisted.contains("active_cursor"));
    size_t active_count = 0;
    for (const auto& item : persisted["cursors"]) {
        assert(item.size() == 8);
        assert(item["active"].is_boolean());
        if (item["active"].get<bool>()) ++active_count;
    }
    assert(active_count == 1);
    struct stat info {};
    assert(stat(path.c_str(), &info) == 0);
    assert((info.st_mode & 0777) == 0600);

    std::string active;
    assert(manager.get_active_cursor(session, active).ok());
    assert(active == "first");
    assert(manager.use_cursor(session, "second").ok());
    assert(manager.get_active_cursor(session, active).ok());
    assert(active == "second");

    Cursor loaded;
    assert(manager.get_cursor(session, "second", loaded).ok());
    assert(loaded.time == 20);
    assert(loaded.created_at > 0);
    assert(loaded.updated_at >= loaded.created_at);

    setenv("XDEBUG_TEST_CONFIG_STORE_WRITE_FAIL", "1", 1);
    StoreResult failed =
        manager.set_cursor(
            session,
            cursor("must_not_commit", 30),
            false);
    unsetenv("XDEBUG_TEST_CONFIG_STORE_WRITE_FAIL");
    assert(failed.status == StoreStatus::IoError);
    assert(manager.get_cursor(
        session,
        "must_not_commit",
        loaded).status == StoreStatus::NotFound);

    constexpr int kWriters = 8;
    for (int index = 0; index < kWriters; ++index) {
        CursorManager writer;
        StoreResult stored =
            writer.set_cursor(
                session,
                cursor(
                    "sequential_" + std::to_string(index),
                    static_cast<uint64_t>(100 + index)),
                false);
        assert(stored.ok());
    }
    std::vector<Cursor> cursors;
    assert(manager.list_cursors(session, cursors).ok());
    assert(cursors.size() == static_cast<size_t>(kWriters + 2));

    persisted = read_json(path);
    persisted["cursors"][0]["active"] = true;
    persisted["cursors"][1]["active"] = true;
    const std::string corrupt = persisted.dump(2) + "\n";
    {
        std::ofstream output(path.c_str(), std::ios::trunc);
        output << corrupt;
    }
    cursors.clear();
    StoreResult invalid =
        manager.list_cursors(session, cursors);
    assert(invalid.status == StoreStatus::Invalid);
    assert(invalid.code == "CONFIG_STORE_INVALID");
    assert(manager.set_cursor(
        session,
        cursor("refused", 40),
        true).status == StoreStatus::Invalid);
    assert(read_text(path) == corrupt);

    xdebug_waveform_remove_session_dir(session);
    return 0;
}
