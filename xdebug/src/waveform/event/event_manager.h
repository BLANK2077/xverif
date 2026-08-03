#pragma once

#include "event_config.h"
#include "waveform/common/versioned_json_store.h"

#include <string>
#include <vector>

namespace xdebug_waveform {

class EventManager {
public:
    StoreResult create_event(
        const std::string& session_id,
        const std::string& fsdb_file,
        const EventConfig& config);
    StoreResult delete_event(
        const std::string& session_id,
        const std::string& fsdb_file,
        const std::string& name);
    StoreResult get_event(
        const std::string& session_id,
        const std::string& fsdb_file,
        const std::string& name,
        EventConfig& config);
    StoreResult get_latest_event(
        const std::string& session_id,
        const std::string& fsdb_file,
        std::string& name);
    StoreResult list_events(
        const std::string& session_id,
        const std::string& fsdb_file,
        std::vector<std::string>& names);

private:
    StoreResult load_session(
        const std::string& session_id,
        std::vector<EventConfig>& configs,
        std::vector<std::string>& fsdb_files);
};

} // namespace xdebug_waveform
