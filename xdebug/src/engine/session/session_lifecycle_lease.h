#pragma once

#include "../../design/common/xdebug_design_paths.h"

#include <fcntl.h>
#include <sys/file.h>
#include <unistd.h>

#include <string>

namespace xdebug_engine {

// Stable cross-process lease for one logical session name.  The lock file
// lives outside the removable session directory, so an old generation cannot
// lose exclusion when its artifacts are cleaned.
class SessionLifecycleLease {
public:
    explicit SessionLifecycleLease(const std::string& session_id)
        : fd_(-1), locked_(false) {
        if (!xdebug_design::xdebug_design_ensure_home()) return;
        const std::string path =
            xdebug_design::xdebug_design_session_lifecycle_lock_path(
                session_id);
        fd_ = open(path.c_str(), O_RDWR | O_CREAT | O_CLOEXEC, 0600);
        if (fd_ < 0) return;
        if (flock(fd_, LOCK_EX) != 0) {
            close(fd_);
            fd_ = -1;
            return;
        }
        locked_ = true;
    }

    ~SessionLifecycleLease() {
        if (fd_ < 0) return;
        if (locked_) flock(fd_, LOCK_UN);
        close(fd_);
    }

    SessionLifecycleLease(const SessionLifecycleLease&) = delete;
    SessionLifecycleLease& operator=(const SessionLifecycleLease&) = delete;

    bool locked() const { return locked_; }

private:
    int fd_;
    bool locked_;
};

}  // namespace xdebug_engine
