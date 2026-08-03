#include "cursor_manager.h"

#include "../common/xdebug_waveform_paths.h"

#include <cctype>
#include <ctime>
#include <exception>
#include <set>
#include <utility>

namespace xdebug_waveform {

namespace {

struct StoredCursor {
    Cursor cursor;
    bool active = false;
};

bool valid_cursor_name(const std::string& name) {
    if (name.empty()) return false;
    for (char character : name) {
        if (!std::isalnum(static_cast<unsigned char>(character)) &&
            character != '_' && character != '-' && character != '.') {
            return false;
        }
    }
    return true;
}

bool nonnegative_integer(const StoreJson& value) {
    if (value.is_number_unsigned()) return true;
    return value.is_number_integer() &&
           value.get<long long>() >= 0;
}

StoreJson cursor_to_json(const StoredCursor& stored) {
    const Cursor& cursor = stored.cursor;
    return {
        {"name", cursor.name},
        {"time", cursor.time},
        {"note", cursor.note},
        {"origin", cursor.origin},
        {"clock", cursor.clock},
        {"created_at", cursor.created_at},
        {"updated_at", cursor.updated_at},
        {"active", stored.active},
    };
}

StoreResult json_to_cursor(
    const StoreJson& value,
    StoredCursor& stored) {
    static const std::set<std::string> fields = {
        "name",
        "time",
        "note",
        "origin",
        "clock",
        "created_at",
        "updated_at",
        "active",
    };
    if (!value.is_object() || value.size() != fields.size()) {
        return store_invalid(
            "cursor record must contain exactly name, time, note, origin, "
            "clock, created_at, updated_at, and active");
    }
    for (auto it = value.begin(); it != value.end(); ++it) {
        if (fields.count(it.key()) == 0) {
            return store_invalid(
                "cursor record contains unknown field: " + it.key());
        }
    }
    if (!value["name"].is_string() ||
        !valid_cursor_name(value["name"].get<std::string>()) ||
        !nonnegative_integer(value["time"]) ||
        !value["note"].is_string() ||
        !value["origin"].is_string() ||
        value["origin"].get<std::string>().empty() ||
        !value["clock"].is_string() ||
        !nonnegative_integer(value["created_at"]) ||
        !nonnegative_integer(value["updated_at"]) ||
        !value["active"].is_boolean()) {
        return store_invalid(
            "cursor record has invalid field types or values");
    }
    try {
        stored.cursor.name = value["name"].get<std::string>();
        stored.cursor.time = value["time"].get<uint64_t>();
        stored.cursor.note = value["note"].get<std::string>();
        stored.cursor.origin = value["origin"].get<std::string>();
        stored.cursor.clock = value["clock"].get<std::string>();
        stored.cursor.created_at = value["created_at"].get<long>();
        stored.cursor.updated_at = value["updated_at"].get<long>();
        stored.active = value["active"].get<bool>();
    } catch (const std::exception& error) {
        return store_invalid(
            std::string("cursor record value is out of range: ") +
            error.what());
    }
    return {};
}

StoreResult parse_cursors(
    const StoreJson& items,
    std::vector<StoredCursor>& cursors) {
    cursors.clear();
    std::set<std::string> names;
    size_t active_count = 0;
    for (size_t index = 0; index < items.size(); ++index) {
        StoredCursor stored;
        StoreResult parsed = json_to_cursor(items[index], stored);
        if (!parsed.ok()) {
            parsed.message =
                "cursors[" + std::to_string(index) +
                "]: " + parsed.message;
            return parsed;
        }
        if (!names.insert(stored.cursor.name).second) {
            return store_invalid(
                "duplicate cursor name: " + stored.cursor.name);
        }
        if (stored.active) ++active_count;
        cursors.push_back(std::move(stored));
    }
    if (active_count > 1) {
        return store_invalid(
            "cursor store must contain at most one active cursor");
    }
    return {};
}

StoreJson serialize_cursors(
    const std::vector<StoredCursor>& cursors) {
    StoreJson items = StoreJson::array();
    for (const auto& stored : cursors) {
        items.push_back(cursor_to_json(stored));
    }
    return items;
}

VersionedJsonStore store_for(const std::string& session_id) {
    return VersionedJsonStore(
        xdebug_waveform_cursors_path(session_id),
        "cursors");
}

StoreResult cursor_not_found(const std::string& message) {
    return {
        StoreStatus::NotFound,
        "CURSOR_NOT_FOUND",
        message,
    };
}

StoreResult cursor_invalid(const std::string& message) {
    return {
        StoreStatus::Invalid,
        "INVALID_ARGUMENT",
        message,
    };
}

StoreResult cursor_session_dir_error() {
    return {
        StoreStatus::IoError,
        "CONFIG_STORE_IO_ERROR",
        "cannot create cursor session directory",
    };
}

StoreResult load_cursors(
    const std::string& session_id,
    std::vector<StoredCursor>& cursors) {
    StoreJson items;
    StoreResult loaded = store_for(session_id).load(items);
    if (!loaded.ok()) return loaded;
    return parse_cursors(items, cursors);
}

} // namespace

StoreResult CursorManager::set_cursor(
    const std::string& session_id,
    const Cursor& cursor,
    bool make_active) {
    if (!valid_cursor_name(cursor.name)) {
        return cursor_invalid(
            "cursor name contains unsupported characters");
    }
    if (!xdebug_waveform_ensure_session_dir(session_id)) {
        return cursor_session_dir_error();
    }

    return store_for(session_id).update([&](StoreJson& items) {
        std::vector<StoredCursor> cursors;
        StoreResult parsed = parse_cursors(items, cursors);
        if (!parsed.ok()) return parsed;

        const long now = static_cast<long>(time(nullptr));
        StoredCursor replacement;
        replacement.cursor = cursor;
        replacement.cursor.updated_at = now;
        if (replacement.cursor.origin.empty()) {
            replacement.cursor.origin = "manual";
        }

        bool replaced = false;
        for (auto& stored : cursors) {
            if (stored.cursor.name != cursor.name) continue;
            if (replacement.cursor.created_at == 0) {
                replacement.cursor.created_at =
                    stored.cursor.created_at;
            }
            replacement.active = stored.active;
            stored = replacement;
            replaced = true;
            break;
        }
        if (!replaced) {
            if (replacement.cursor.created_at == 0) {
                replacement.cursor.created_at = now;
            }
            cursors.push_back(replacement);
        }
        if (make_active) {
            for (auto& stored : cursors) {
                stored.active =
                    stored.cursor.name == cursor.name;
            }
        }
        items = serialize_cursors(cursors);
        return StoreResult{};
    });
}

StoreResult CursorManager::get_cursor(
    const std::string& session_id,
    const std::string& name,
    Cursor& cursor) const {
    if (!valid_cursor_name(name)) {
        return cursor_invalid(
            "cursor name contains unsupported characters");
    }
    std::vector<StoredCursor> cursors;
    StoreResult loaded = load_cursors(session_id, cursors);
    if (!loaded.ok()) return loaded;
    for (const auto& stored : cursors) {
        if (stored.cursor.name != name) continue;
        cursor = stored.cursor;
        return {};
    }
    return cursor_not_found("cursor not found: " + name);
}

StoreResult CursorManager::delete_cursor(
    const std::string& session_id,
    const std::string& name) {
    if (!valid_cursor_name(name)) {
        return cursor_invalid(
            "cursor name contains unsupported characters");
    }
    return store_for(session_id).update([&](StoreJson& items) {
        std::vector<StoredCursor> cursors;
        StoreResult parsed = parse_cursors(items, cursors);
        if (!parsed.ok()) return parsed;
        std::vector<StoredCursor> kept;
        bool found = false;
        for (const auto& stored : cursors) {
            if (stored.cursor.name == name) {
                found = true;
            } else {
                kept.push_back(stored);
            }
        }
        if (!found) {
            return cursor_not_found("cursor not found: " + name);
        }
        items = serialize_cursors(kept);
        return StoreResult{};
    });
}

StoreResult CursorManager::use_cursor(
    const std::string& session_id,
    const std::string& name) {
    if (!valid_cursor_name(name)) {
        return cursor_invalid(
            "cursor name contains unsupported characters");
    }
    return store_for(session_id).update([&](StoreJson& items) {
        std::vector<StoredCursor> cursors;
        StoreResult parsed = parse_cursors(items, cursors);
        if (!parsed.ok()) return parsed;
        bool found = false;
        for (auto& stored : cursors) {
            stored.active = stored.cursor.name == name;
            found = found || stored.active;
        }
        if (!found) {
            return cursor_not_found("cursor not found: " + name);
        }
        items = serialize_cursors(cursors);
        return StoreResult{};
    });
}

StoreResult CursorManager::get_active_cursor(
    const std::string& session_id,
    std::string& name) const {
    name.clear();
    std::vector<StoredCursor> cursors;
    StoreResult loaded = load_cursors(session_id, cursors);
    if (!loaded.ok()) return loaded;
    for (const auto& stored : cursors) {
        if (!stored.active) continue;
        name = stored.cursor.name;
        return {};
    }
    return cursor_not_found("active cursor is not set");
}

StoreResult CursorManager::list_cursors(
    const std::string& session_id,
    std::vector<Cursor>& cursors) const {
    cursors.clear();
    std::vector<StoredCursor> stored;
    StoreResult loaded = load_cursors(session_id, stored);
    if (!loaded.ok()) return loaded;
    for (const auto& item : stored) {
        cursors.push_back(item.cursor);
    }
    return {};
}

} // namespace xdebug_waveform
