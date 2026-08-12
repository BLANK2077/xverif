#include "session/session_types.h"

namespace xdebug_core {

Fingerprint::Fingerprint()
    : mtime(0),
      size(0),
      dev(0),
      inode(0) {}

DatabaseRef::DatabaseRef()
    : kind(DatabaseKind::Fsdb) {}

// SessionInfo uses in-class default initializers — no out-of-line ctor needed.

const char* database_kind_name(DatabaseKind kind) {
    switch (kind) {
    case DatabaseKind::Fsdb:
        return "fsdb";
    case DatabaseKind::Daidir:
        return "daidir";
    case DatabaseKind::Combined:
        return "combined";
    }
    return "unknown";
}

bool resource_content_matches(long long expected_mtime_ns,
                              long long expected_size,
                              long long current_mtime_ns,
                              long long current_size) {
    return expected_mtime_ns == current_mtime_ns &&
           expected_size == current_size;
}

bool resource_identity_differs(unsigned long long expected_dev,
                               unsigned long long expected_inode,
                               unsigned long long current_dev,
                               unsigned long long current_inode) {
    return expected_dev != current_dev || expected_inode != current_inode;
}

} // namespace xdebug_core
