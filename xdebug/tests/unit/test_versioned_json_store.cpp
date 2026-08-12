#include "waveform/common/versioned_json_store.h"

#include <cassert>
#include <cstdlib>
#include <fstream>
#include <string>
#include <unistd.h>
#include <vector>

using xdebug_waveform::StoreJson;
using xdebug_waveform::StoreStatus;
using xdebug_waveform::VersionedJsonStore;

namespace {

std::string make_temp_dir() {
    std::string pattern = "xdebug-versioned-store-XXXXXX";
    std::vector<char> buffer(pattern.begin(), pattern.end());
    buffer.push_back('\0');
    char* path = mkdtemp(buffer.data());
    assert(path != nullptr);
    return path;
}

void write_text(const std::string& path, const std::string& text) {
    std::ofstream output(path.c_str(), std::ios::trunc);
    assert(output.good());
    output << text;
    output.close();
    assert(output.good());
}

} // namespace

int main() {
    const std::string directory = make_temp_dir();
    const std::string path = directory + "/configs.json";
    VersionedJsonStore store(path, "configs");

    StoreJson items;
    auto loaded = store.load(items);
    assert(loaded.ok());
    assert(items == StoreJson::array());

    write_text(path, "{\"version\":1,\"configs\":[");
    loaded = store.load(items);
    assert(loaded.status == StoreStatus::Invalid);
    assert(loaded.code == "CONFIG_STORE_INVALID");
    auto refused = store.update([](StoreJson& values) {
        values.push_back({{"name", "must-not-write"}});
        return xdebug_waveform::StoreResult{};
    });
    assert(refused.status == StoreStatus::Invalid);
    std::ifstream still_corrupt(path.c_str());
    std::string corrupt_text(
        (std::istreambuf_iterator<char>(still_corrupt)),
        std::istreambuf_iterator<char>());
    assert(corrupt_text == "{\"version\":1,\"configs\":[");

    write_text(path, "{\"version\":1,\"configs\":[],\"extra\":true}\n");
    loaded = store.load(items);
    assert(loaded.status == StoreStatus::Invalid);

    write_text(path, "{\"version\":1,\"configs\":[]}\n");
    constexpr int kWriters = 12;
    for (int index = 0; index < kWriters; ++index) {
        auto result = store.update([index](StoreJson& values) {
            values.push_back({{"writer", index}});
            return xdebug_waveform::StoreResult{};
        });
        assert(result.ok());
    }

    loaded = store.load(items);
    assert(loaded.ok());
    assert(items.size() == kWriters);
    for (int index = 0; index < kWriters; ++index) {
        assert(items[index]["writer"] == index);
    }

    assert(unlink(path.c_str()) == 0);
    assert(rmdir(directory.c_str()) == 0);
    return 0;
}
