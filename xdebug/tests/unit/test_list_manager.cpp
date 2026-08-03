#include "waveform/common/xdebug_waveform_paths.h"
#include "waveform/list/list_manager.h"
#include "test_temp_path.h"

#include <cassert>
#include <cstdlib>
#include <limits>
#include <string>
#include <vector>

using namespace xdebug_waveform;

namespace {

void assert_signals(
    ListManager& manager,
    const std::string& session,
    const std::string& name,
    const std::vector<std::string>& expected) {
    SignalList list;
    assert(manager.get_list(session, name, list).ok());
    assert(list.signals == expected);
}

} // namespace

int main() {
    std::vector<char> root_storage =
        test_temp_template("xdebug-list-manager.XXXXXX");
    char* root = root_storage.data();
    assert(mkdtemp(root) != nullptr);
    setenv("HOME", root, 1);

    const std::string session = "ListTypedDelete";
    ListManager manager;

    SignalList loaded_a;
    loaded_a.name = "loaded_a";
    loaded_a.signals = {"top.load_a", "top.load_b"};
    SignalList loaded_b;
    loaded_b.name = "loaded_b";
    loaded_b.signals = {"top.load_c"};
    assert(manager.load_lists(
        session, {loaded_a, loaded_b}, "replace").ok());
    assert_signals(
        manager, session, "loaded_a", {"top.load_a", "top.load_b"});
    assert_signals(
        manager, session, "loaded_b", {"top.load_c"});

    SignalList replaced_a;
    replaced_a.name = "loaded_a";
    replaced_a.signals = {"top.replaced"};
    assert(manager.load_lists(
        session, {replaced_a}, "replace").ok());
    assert_signals(manager, session, "loaded_a", {"top.replaced"});
    assert_signals(manager, session, "loaded_b", {"top.load_c"});

    StoreResult append_conflict =
        manager.load_lists(session, {replaced_a}, "append");
    assert(append_conflict.status == StoreStatus::Conflict);
    assert_signals(manager, session, "loaded_a", {"top.replaced"});

    SignalList duplicate_signal;
    duplicate_signal.name = "duplicate_signal";
    duplicate_signal.signals = {"top.same", "top.same"};
    StoreResult duplicate_result =
        manager.load_lists(
            session, {duplicate_signal}, "replace");
    assert(duplicate_result.status == StoreStatus::Invalid);
    assert_signals(manager, session, "loaded_b", {"top.load_c"});

    StoreResult invalid_mode =
        manager.load_lists(session, {loaded_a}, "merge");
    assert(invalid_mode.status == StoreStatus::Invalid);

    assert(manager.create_list(
        session,
        "numeric_paths",
        {"2", "top.a", "0007"}).ok());
    StoreResult missing_path =
        manager.delete_signal_by_path(
            session, "numeric_paths", "3");
    assert(missing_path.status == StoreStatus::NotFound);
    assert(missing_path.code == "CONFIG_NOT_FOUND");
    assert_signals(
        manager,
        session,
        "numeric_paths",
        {"2", "top.a", "0007"});

    assert(manager.delete_signal_by_path(
        session, "numeric_paths", "2").ok());
    assert_signals(
        manager,
        session,
        "numeric_paths",
        {"top.a", "0007"});
    assert(manager.delete_signal_by_path(
        session, "numeric_paths", "0007").ok());
    assert_signals(
        manager,
        session,
        "numeric_paths",
        {"top.a"});

    assert(manager.create_list(
        session,
        "indexed",
        {"123", "top.b", "0009"}).ok());
    std::string removed = "must-be-cleared";
    StoreResult zero_index =
        manager.delete_signal_by_one_based_index(
            session, "indexed", 0, removed);
    assert(zero_index.status == StoreStatus::Invalid);
    assert(zero_index.code == "PRECONDITION_FAILED");
    assert(removed.empty());
    assert_signals(
        manager,
        session,
        "indexed",
        {"123", "top.b", "0009"});

    StoreResult huge_index =
        manager.delete_signal_by_one_based_index(
            session,
            "indexed",
            std::numeric_limits<size_t>::max(),
            removed);
    assert(huge_index.status == StoreStatus::Invalid);
    assert(huge_index.code == "PRECONDITION_FAILED");
    assert(removed.empty());
    assert_signals(
        manager,
        session,
        "indexed",
        {"123", "top.b", "0009"});

    assert(manager.delete_signal_by_one_based_index(
        session, "indexed", 2, removed).ok());
    assert(removed == "top.b");
    assert_signals(
        manager,
        session,
        "indexed",
        {"123", "0009"});

    setenv("XDEBUG_TEST_CONFIG_STORE_WRITE_FAIL", "1", 1);
    StoreResult write_failure =
        manager.delete_signal_by_one_based_index(
            session, "indexed", 1, removed);
    unsetenv("XDEBUG_TEST_CONFIG_STORE_WRITE_FAIL");
    assert(write_failure.status == StoreStatus::IoError);
    assert(write_failure.code == "CONFIG_STORE_IO_ERROR");
    assert(removed.empty());
    assert_signals(
        manager,
        session,
        "indexed",
        {"123", "0009"});

    StoreResult missing_list =
        manager.delete_signal_by_one_based_index(
            session, "missing", 1, removed);
    assert(missing_list.status == StoreStatus::NotFound);
    assert(missing_list.code == "CONFIG_NOT_FOUND");
    assert(removed.empty());

    xdebug_waveform_remove_session_dir(session);
    return 0;
}
