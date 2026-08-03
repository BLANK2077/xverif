#include "waveform/apb/apb_manager.h"
#include "waveform/common/xdebug_waveform_paths.h"
#include "test_temp_path.h"

#include <cassert>
#include <cstdlib>
#include <fstream>
#include <string>
#include <unistd.h>
#include <vector>

using namespace xdebug_waveform;

namespace {

ApbConfig apb2_config() {
    ApbConfig config;
    config.name = "apb2";
    config.clock_sample.clock = "top.pclk";
    config.clock_sample.edge = ClockEdgeKind::Negedge;
    config.reset.signal = "top.presetn";
    config.reset.polarity = ResetPolarity::ActiveLow;
    config.paddr = "top.paddr";
    config.psel = "top.psel";
    config.penable = "top.penable";
    config.pwrite = "top.pwrite";
    config.pwdata = "top.pwdata";
    config.prdata = "top.prdata";
    return config;
}

StoreJson read_json(const std::string& path) {
    std::ifstream input(path.c_str());
    assert(input.good());
    StoreJson value;
    input >> value;
    return value;
}

} // namespace

int main() {
    std::vector<char> root_storage =
        test_temp_template("xdebug-apb-manager.XXXXXX");
    char* root = root_storage.data();
    assert(mkdtemp(root) != nullptr);
    setenv("HOME", root, 1);

    const std::string session = "ApbOptionalSignals";
    ApbManager manager;
    const ApbConfig input = apb2_config();
    assert(input.pready.empty());
    assert(input.pslverr.empty());
    assert(manager.create_apb(session, input).ok());

    ApbConfig loaded;
    assert(manager.get_apb(session, input.name, loaded).ok());
    assert(loaded.pready.empty());
    assert(loaded.pslverr.empty());

    const StoreJson persisted =
        read_json(xdebug_waveform_apb_path(session));
    assert(persisted["version"] == 1);
    assert(persisted["configs"].size() == 1);
    const StoreJson& stored = persisted["configs"][0];
    assert(!stored.contains("pready"));
    assert(!stored.contains("pslverr"));
    assert(stored["penable"] == input.penable);

    xdebug_waveform_remove_session_dir(session);
    return 0;
}
