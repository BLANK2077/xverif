#pragma once

#include "signal_list.h"
#include "waveform/common/versioned_json_store.h"

#include <cstddef>
#include <string>
#include <vector>

namespace xdebug_waveform {

class ListManager {
public:
    StoreResult load_lists(
        const std::string& session_id,
        const std::vector<SignalList>& incoming,
        const std::string& mode);
    StoreResult create_list(
        const std::string& session_id,
        const std::string& name,
        const std::vector<std::string>& signals);
    StoreResult delete_list(
        const std::string& session_id,
        const std::string& name);
    StoreResult add_signal(
        const std::string& session_id,
        const std::string& list_name,
        const std::string& signal);
    StoreResult delete_signal_by_path(
        const std::string& session_id,
        const std::string& list_name,
        const std::string& signal_path);
    StoreResult delete_signal_by_one_based_index(
        const std::string& session_id,
        const std::string& list_name,
        size_t one_based_index,
        std::string& removed_signal);
    StoreResult get_list(
        const std::string& session_id,
        const std::string& name,
        SignalList& list);
    StoreResult get_latest_list(
        const std::string& session_id,
        std::string& name);
    StoreResult list_all(
        const std::string& session_id,
        std::vector<SignalList>& lists);

private:
    StoreResult load_session(
        const std::string& session_id,
        std::vector<SignalList>& lists);
};

} // namespace xdebug_waveform
