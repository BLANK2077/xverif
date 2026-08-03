#pragma once
#include "signal_list.h"
#include <vector>
#include <string>

namespace xdebug_waveform {

class ListManager {
public:
    ListManager();
    ~ListManager();

    // Atomically validate and persist all named lists in one update.  append
    // rejects name conflicts; replace updates only incoming names and keeps
    // unrelated lists.
    bool load_lists(const std::string& session_id,
                    const std::vector<SignalList>& incoming,
                    const std::string& mode,
                    std::string& error);

    bool create_list(const std::string& session_id, const std::string& name);
    bool create_list(int session_id, const std::string& name) { return create_list(std::to_string(session_id), name); }
    bool delete_list(const std::string& session_id, const std::string& name);
    bool add_signal(const std::string& session_id, const std::string& list_name, const std::string& signal);
    bool add_signal(int session_id, const std::string& list_name, const std::string& signal) { return add_signal(std::to_string(session_id), list_name, signal); }
    bool del_signal(const std::string& session_id, const std::string& list_name, const std::string& path_or_index);
    bool del_signal(int session_id, const std::string& list_name, const std::string& path_or_index) { return del_signal(std::to_string(session_id), list_name, path_or_index); }
    bool get_list(const std::string& session_id, const std::string& name, SignalList& list);
    bool get_list(int session_id, const std::string& name, SignalList& list) { return get_list(std::to_string(session_id), name, list); }
    bool get_latest_list(const std::string& session_id, std::string& name);
    bool get_latest_list(int session_id, std::string& name) { return get_latest_list(std::to_string(session_id), name); }
    std::vector<SignalList> list_all(const std::string& session_id);

private:
    bool load_session(const std::string& session_id, std::vector<SignalList>& lists);
    bool save_session(const std::string& session_id, const std::vector<SignalList>& lists);
    bool migrate_legacy(const std::string& session_id, std::vector<SignalList>& lists);
    bool parse_legacy_line(const char* line, SignalList& list, int& session_id);
};

} // namespace xdebug_waveform
