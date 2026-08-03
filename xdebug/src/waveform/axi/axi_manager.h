#pragma once

#include "axi_config.h"
#include "waveform/common/versioned_json_store.h"

#include <string>
#include <vector>

namespace xdebug_waveform {

class AxiManager {
public:
    StoreResult create_axi(
        const std::string& session_id,
        const AxiConfig& config);
    StoreResult delete_axi(
        const std::string& session_id,
        const std::string& name);
    StoreResult get_axi(
        const std::string& session_id,
        const std::string& name,
        AxiConfig& config);
    StoreResult get_latest_axi(
        const std::string& session_id,
        std::string& name);
    StoreResult list_all(
        const std::string& session_id,
        std::vector<AxiConfig>& configs);

private:
    StoreResult load_session(
        const std::string& session_id,
        std::vector<AxiConfig>& configs);
};

} // namespace xdebug_waveform
