#include "waveform/common/xdebug_waveform_paths.h"
#include "waveform/stream/stream_manager.h"
#include "test_temp_path.h"

#include <cassert>
#include <cstdlib>
#include <dirent.h>
#include <fstream>
#include <string>
#include <sys/stat.h>
#include <sys/wait.h>
#include <unistd.h>
#include <vector>

using namespace xdebug_waveform;

namespace {

StreamConfig config(const std::string& name, const std::string& signal,
                    const std::string& description) {
    StreamConfig value;
    value.name = name;
    value.signals["clk"] = "top.clk";
    value.signals["vld"] = "top.vld";
    value.signals["data"] = signal;
    value.clock_sample.clock = "clk";
    value.vld = "vld";
    value.data = "data";
    value.description = description;
    return value;
}

std::string read_text(const std::string& path) {
    std::ifstream input(path.c_str());
    return std::string((std::istreambuf_iterator<char>(input)),
                       std::istreambuf_iterator<char>());
}

bool has_temporary(const std::string& directory) {
    DIR* dir = opendir(directory.c_str());
    assert(dir != nullptr);
    bool found = false;
    while (dirent* entry = readdir(dir)) {
        if (std::string(entry->d_name).find("streams.json.tmp.") == 0) {
            found = true;
            break;
        }
    }
    closedir(dir);
    return found;
}

void require_stream_config_documents_stay_closed() {
    const StreamConfig baseline =
        config("strict_stream", "top.data", "strict");
    Json canonical = {
        {"streams", Json::array({stream_config_json(baseline)})}
    };
    std::vector<StreamConfig> parsed;
    std::string error;
    assert(parse_stream_config_list(canonical, parsed, error));
    assert(parsed.size() == 1);

    Json unknown_root = canonical;
    unknown_root["ignored"] = true;
    parsed.clear();
    error.clear();
    assert(!parse_stream_config_list(unknown_root, parsed, error));
    assert(error.find("exactly one root field") != std::string::npos);

    Json unknown_item = canonical;
    unknown_item["streams"][0]["ignored"] = true;
    parsed.clear();
    error.clear();
    assert(!parse_stream_config_list(unknown_item, parsed, error));
    assert(error.find("unknown field") != std::string::npos);

    Json empty_optional = canonical;
    empty_optional["streams"][0]["description"] = "";
    parsed.clear();
    error.clear();
    assert(!parse_stream_config_list(empty_optional, parsed, error));
    assert(error.find("non-empty string") != std::string::npos);

    Json empty_fields = canonical;
    empty_fields["streams"][0]["beat_fields"] = Json::object();
    parsed.clear();
    error.clear();
    assert(!parse_stream_config_list(empty_fields, parsed, error));
    assert(error.find("must be non-empty") != std::string::npos);
}

}  // namespace

int main() {
    require_stream_config_documents_stay_closed();

    std::vector<char> root_storage = test_temp_template("xdebug-stream-manager.XXXXXX");
    char* root = root_storage.data();
    assert(mkdtemp(root) != nullptr);
    setenv("HOME", root, 1);
    const std::string session = "StreamAtomic";
    StreamManager manager;
    std::vector<StreamConfigChange> changes;

    const StreamConfig original = config("stream0", "top.data_a", "old text");
    StoreResult stored =
        manager.load_configs(
            session,
            {original},
            "replace",
            &changes);
    assert(stored.ok());
    assert(changes.size() == 1 && changes[0].old_semantic_fingerprint.empty());
    const std::string path = xdebug_waveform_streams_path(session);
    const std::string directory = xdebug_waveform_session_dir(session);
    const std::string before = read_text(path);
    assert(!before.empty());
    struct stat info {};
    assert(stat(path.c_str(), &info) == 0 && (info.st_mode & 0777) == 0600);
    assert(!has_temporary(directory));

    StreamConfig description_only = original;
    description_only.name = "another_name";
    description_only.description = "new text";
    assert(normalized_stream_config_semantics(original) ==
           normalized_stream_config_semantics(description_only));
    assert(stream_config_semantic_fingerprint(original) ==
           stream_config_semantic_fingerprint(description_only));

    const StreamConfig changed = config("stream0", "top.data_b", "changed");
    setenv("XDEBUG_TEST_CONFIG_STORE_WRITE_FAIL", "1", 1);
    stored =
        manager.load_configs(
            session,
            {changed},
            "replace",
            &changes);
    assert(stored.status == StoreStatus::IoError);
    unsetenv("XDEBUG_TEST_CONFIG_STORE_WRITE_FAIL");
    assert(changes.empty());
    assert(read_text(path) == before);
    assert(!has_temporary(directory));

    setenv("XDEBUG_TEST_CONFIG_STORE_RENAME_FAIL", "1", 1);
    stored =
        manager.load_configs(
            session,
            {changed},
            "replace",
            &changes);
    assert(stored.status == StoreStatus::IoError);
    unsetenv("XDEBUG_TEST_CONFIG_STORE_RENAME_FAIL");
    assert(changes.empty());
    assert(read_text(path) == before);
    assert(!has_temporary(directory));

    stored =
        manager.load_configs(
            session,
            {changed},
            "replace",
            &changes);
    assert(stored.ok());
    assert(changes.size() == 1);
    assert(changes[0].old_semantic_fingerprint ==
           stream_config_semantic_fingerprint(original));
    assert(changes[0].new_semantic_fingerprint ==
           stream_config_semantic_fingerprint(changed));
    assert(changes[0].old_semantic_fingerprint !=
           changes[0].new_semantic_fingerprint);
    assert(read_text(path) != before);
    StreamConfig loaded;
    assert(manager.get_stream(session, "stream0", loaded).ok());
    assert(loaded.signals.at("data") == "top.data_b");
    assert(!has_temporary(directory));

    constexpr int kWriters = 8;
    std::vector<pid_t> children;
    for (int index = 0; index < kWriters; ++index) {
        const pid_t child = fork();
        assert(child >= 0);
        if (child == 0) {
            StreamManager writer;
            const StreamConfig value =
                config(
                    "parallel_" + std::to_string(index),
                    "top.parallel_" + std::to_string(index),
                    "parallel");
            StoreResult appended =
                writer.load_configs(
                    session,
                    {value},
                    "append");
            _exit(appended.ok() ? 0 : 1);
        }
        children.push_back(child);
    }
    for (pid_t child : children) {
        int status = 0;
        assert(waitpid(child, &status, 0) == child);
        assert(WIFEXITED(status));
        assert(WEXITSTATUS(status) == 0);
    }
    std::vector<StreamConfig> all;
    assert(manager.list_streams(session, all).ok());
    assert(all.size() == static_cast<size_t>(kWriters + 1));

    const std::string corrupt =
        "{\"version\":1,\"streams\":[{\"name\":\"broken\"}]}\n";
    {
        std::ofstream output(path.c_str(), std::ios::trunc);
        output << corrupt;
    }
    all.clear();
    StoreResult invalid = manager.list_streams(session, all);
    assert(invalid.status == StoreStatus::Invalid);
    assert(invalid.code == "CONFIG_STORE_INVALID");
    stored =
        manager.load_configs(
            session,
            {original},
            "replace",
            &changes);
    assert(stored.status == StoreStatus::Invalid);
    assert(changes.empty());
    assert(read_text(path) == corrupt);

    xdebug_waveform_remove_session_dir(session);
    return 0;
}
