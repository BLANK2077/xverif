#pragma once

#include "waveform/common/versioned_json_store.h"

#include <cstdint>
#include <string>
#include <vector>

namespace xdebug_waveform {

struct Cursor {
    std::string name;
    uint64_t time = 0;
    std::string note;
    std::string origin;
    std::string clock;
    long created_at = 0;
    long updated_at = 0;
};

class CursorManager {
public:
    StoreResult set_cursor(
        const std::string& session_id,
        const Cursor& cursor,
        bool make_active = true);
    StoreResult get_cursor(
        const std::string& session_id,
        const std::string& name,
        Cursor& cursor) const;
    StoreResult delete_cursor(
        const std::string& session_id,
        const std::string& name);
    StoreResult use_cursor(
        const std::string& session_id,
        const std::string& name);
    StoreResult get_active_cursor(
        const std::string& session_id,
        std::string& name) const;
    StoreResult list_cursors(
        const std::string& session_id,
        std::vector<Cursor>& cursors) const;
};

} // namespace xdebug_waveform
