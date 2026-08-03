#pragma once

#include "apb_config.h"
#include "waveform/common/versioned_json_store.h"

#include <string>
#include <vector>

namespace xdebug_waveform {

class ApbManager {
public:
    StoreResult create_apb(
        const std::string& session_id,
        const ApbConfig& config);
    StoreResult delete_apb(
        const std::string& session_id,
        const std::string& name);
    StoreResult get_apb(
        const std::string& session_id,
        const std::string& name,
        ApbConfig& config);
    StoreResult get_latest_apb(
        const std::string& session_id,
        std::string& name);
    StoreResult list_all(
        const std::string& session_id,
        std::vector<ApbConfig>& configs);

private:
    StoreResult load_session(
        const std::string& session_id,
        std::vector<ApbConfig>& configs);
};

} // namespace xdebug_waveform
