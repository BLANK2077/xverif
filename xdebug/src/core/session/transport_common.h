#pragma once

#include "transport_timeout.h"

#include <arpa/inet.h>
#include <cerrno>
#include <cstring>
#include <fcntl.h>
#include <netdb.h>
#include <poll.h>
#include <chrono>
#include <cstddef>
#include <string>
#include <sys/socket.h>
#include <sys/types.h>
#include <sys/un.h>
#include <unistd.h>

namespace xdebug_core {

constexpr std::size_t kMaxSessionJsonBytes = 64U * 1024U * 1024U;

enum class TransportIoStatus {
    Ok,
    EndOfFile,
    Timeout,
    TooLarge,
    IoError,
};

class TransportDeadline {
public:
    TransportDeadline() : present_(false) {}
    explicit TransportDeadline(int timeout_ms)
        : present_(timeout_ms > 0),
          end_(std::chrono::steady_clock::now() +
               std::chrono::milliseconds(timeout_ms > 0 ? timeout_ms : 0)) {}

    bool present() const { return present_; }

    int remaining_ms() const {
        if (!present_) return -1;
        const auto now = std::chrono::steady_clock::now();
        if (now >= end_) return 0;
        const auto remaining =
            std::chrono::duration_cast<std::chrono::milliseconds>(end_ - now);
        return static_cast<int>(remaining.count()) + 1;
    }

private:
    bool present_;
    std::chrono::steady_clock::time_point end_;
};

inline bool wait_for_socket(int fd, short events,
                            const TransportDeadline& deadline) {
    while (true) {
        struct pollfd pfd = {fd, events, 0};
        const int timeout_ms = deadline.remaining_ms();
        if (deadline.present() && timeout_ms == 0) {
            errno = ETIMEDOUT;
            return false;
        }
        const int rc = poll(&pfd, 1, timeout_ms);
        if (rc > 0) {
            if ((pfd.revents & events) != 0) return true;
            errno = EIO;
            return false;
        }
        if (rc == 0) {
            errno = ETIMEDOUT;
            return false;
        }
        if (errno != EINTR) return false;
    }
}

inline bool set_nonblocking(int fd, bool enabled, int& original_flags) {
    original_flags = fcntl(fd, F_GETFL, 0);
    if (original_flags < 0) return false;
    const int flags = enabled ? (original_flags | O_NONBLOCK)
                              : (original_flags & ~O_NONBLOCK);
    return fcntl(fd, F_SETFL, flags) == 0;
}

inline TransportIoStatus write_all_deadline(
    int fd, const char* data, std::size_t size,
    const TransportDeadline& deadline = TransportDeadline()) {
    int original_flags = 0;
    if (!set_nonblocking(fd, true, original_flags))
        return TransportIoStatus::IoError;
    std::size_t offset = 0;
    TransportIoStatus status = TransportIoStatus::Ok;
    while (offset < size) {
        if (!wait_for_socket(fd, POLLOUT, deadline)) {
            status = errno == ETIMEDOUT ? TransportIoStatus::Timeout
                                        : TransportIoStatus::IoError;
            break;
        }
        const ssize_t n = write(fd, data + offset, size - offset);
        if (n > 0) {
            offset += static_cast<std::size_t>(n);
            continue;
        }
        if (n < 0 && (errno == EINTR || errno == EAGAIN ||
                      errno == EWOULDBLOCK))
            continue;
        status = TransportIoStatus::IoError;
        break;
    }
    const int saved_errno = errno;
    if (fcntl(fd, F_SETFL, original_flags) != 0 &&
        status == TransportIoStatus::Ok)
        status = TransportIoStatus::IoError;
    if (status != TransportIoStatus::Ok) errno = saved_errno;
    return status;
}

inline TransportIoStatus read_bounded_line_deadline(
    int fd, std::string& line, std::size_t max_bytes,
    const TransportDeadline& deadline = TransportDeadline()) {
    constexpr std::size_t kReadBlockBytes = 64U * 1024U;
    char buffer[kReadBlockBytes];
    line.clear();
    int original_flags = 0;
    if (!set_nonblocking(fd, true, original_flags))
        return TransportIoStatus::IoError;
    TransportIoStatus status = TransportIoStatus::IoError;
    while (true) {
        if (!wait_for_socket(fd, POLLIN, deadline)) {
            status = errno == ETIMEDOUT ? TransportIoStatus::Timeout
                                        : TransportIoStatus::IoError;
            break;
        }
        const ssize_t n = read(fd, buffer, sizeof(buffer));
        if (n == 0) {
            status = TransportIoStatus::EndOfFile;
            break;
        }
        if (n < 0) {
            if (errno == EINTR || errno == EAGAIN || errno == EWOULDBLOCK)
                continue;
            status = TransportIoStatus::IoError;
            break;
        }
        const std::size_t bytes_read = static_cast<std::size_t>(n);
        const void* newline = std::memchr(buffer, '\n', bytes_read);
        const std::size_t payload_bytes =
            newline == nullptr
                ? bytes_read
                : static_cast<const char*>(newline) - buffer;
        if (line.size() > max_bytes ||
            payload_bytes > max_bytes - line.size()) {
            status = TransportIoStatus::TooLarge;
            break;
        }
        line.append(buffer, payload_bytes);
        if (newline != nullptr) {
            status = TransportIoStatus::Ok;
            break;
        }
    }
    const int saved_errno = errno;
    if (fcntl(fd, F_SETFL, original_flags) != 0 &&
        status == TransportIoStatus::Ok)
        status = TransportIoStatus::IoError;
    if (status != TransportIoStatus::Ok) errno = saved_errno;
    return status;
}

// --- Host identity ---

inline std::string current_host_name() {
    char buf[256] = {};
    if (gethostname(buf, sizeof(buf) - 1) == 0 && buf[0]) return std::string(buf);
    return "localhost";
}

// --- Auth token generation ---

using SecureRandomReadFn = ssize_t (*)(int, void*, size_t);

inline bool fill_secure_random_bytes(int fd,
                                     unsigned char* bytes,
                                     size_t size,
                                     std::string& error,
                                     SecureRandomReadFn read_fn = ::read) {
    size_t offset = 0;
    while (offset < size) {
        const ssize_t count =
            read_fn(fd, bytes + offset, size - offset);
        if (count > 0) {
            offset += static_cast<size_t>(count);
            continue;
        }
        if (count < 0 && errno == EINTR) continue;
        error = count == 0
            ? "secure random source ended before the authentication token was complete"
            : std::string("failed to read secure random source: ") +
                  std::strerror(errno);
        return false;
    }
    return true;
}

inline bool generate_auth_token(std::string& token, std::string& error) {
    token.clear();
    error.clear();
    int flags = O_RDONLY;
#ifdef O_CLOEXEC
    flags |= O_CLOEXEC;
#endif
    int fd = -1;
    do {
        fd = open("/dev/urandom", flags);
    } while (fd < 0 && errno == EINTR);
    if (fd < 0) {
        error = std::string("failed to open secure random source: ") +
                std::strerror(errno);
        return false;
    }

    unsigned char bytes[24] = {};
    const bool filled =
        fill_secure_random_bytes(fd, bytes, sizeof(bytes), error);
    close(fd);
    if (!filled) return false;

    static const char hex[] = "0123456789abcdef";
    token.reserve(sizeof(bytes) * 2);
    for (unsigned char b : bytes) {
        token.push_back(hex[b >> 4]);
        token.push_back(hex[b & 0xf]);
    }
    return true;
}

// --- Transport type checks ---

inline bool is_tcp_transport(const std::string& transport) {
    return transport == "tcp";
}

inline bool is_file_transport(const std::string& transport) {
    return transport == "file";
}

inline bool is_local_session_host(const std::string& server_host) {
    return server_host == current_host_name() ||
           server_host == "localhost" || server_host == "127.0.0.1";
}

// --- Socket connection helpers ---

inline int connect_uds(const std::string& path,
                       const TransportDeadline& deadline = TransportDeadline()) {
    int fd = socket(AF_UNIX, SOCK_STREAM, 0);
    if (fd < 0) return -1;
    struct sockaddr_un addr;
    memset(&addr, 0, sizeof(addr));
    addr.sun_family = AF_UNIX;
    strncpy(addr.sun_path, path.c_str(), sizeof(addr.sun_path) - 1);
    int original_flags = 0;
    if (!set_nonblocking(fd, true, original_flags)) {
        close(fd);
        return -1;
    }
    int rc = connect(fd, reinterpret_cast<struct sockaddr*>(&addr), sizeof(addr));
    if (rc < 0 && errno == EINPROGRESS && wait_for_socket(fd, POLLOUT, deadline)) {
        int socket_error = 0;
        socklen_t error_size = sizeof(socket_error);
        if (getsockopt(fd, SOL_SOCKET, SO_ERROR, &socket_error, &error_size) == 0 &&
            socket_error == 0)
            rc = 0;
        else
            errno = socket_error ? socket_error : errno;
    }
    const int saved_errno = errno;
    if (fcntl(fd, F_SETFL, original_flags) != 0) rc = -1;
    errno = saved_errno;
    if (rc < 0) {
        close(fd);
        return -1;
    }
    return fd;
}

inline int connect_tcp(const std::string& host, int port,
                       const TransportDeadline& deadline = TransportDeadline()) {
    if (host.empty() || port <= 0) return -1;
    struct addrinfo hints;
    memset(&hints, 0, sizeof(hints));
    hints.ai_family = AF_UNSPEC;
    hints.ai_socktype = SOCK_STREAM;
    std::string port_s = std::to_string(port);
    struct addrinfo* res = nullptr;
    if (getaddrinfo(host.c_str(), port_s.c_str(), &hints, &res) != 0) return -1;
    int fd = -1;
    for (struct addrinfo* p = res; p; p = p->ai_next) {
        fd = socket(p->ai_family, p->ai_socktype, p->ai_protocol);
        if (fd < 0) continue;
        int original_flags = 0;
        if (!set_nonblocking(fd, true, original_flags)) {
            close(fd);
            fd = -1;
            continue;
        }
        int rc = connect(fd, p->ai_addr, p->ai_addrlen);
        if (rc < 0 && errno == EINPROGRESS &&
            wait_for_socket(fd, POLLOUT, deadline)) {
            int socket_error = 0;
            socklen_t error_size = sizeof(socket_error);
            if (getsockopt(fd, SOL_SOCKET, SO_ERROR, &socket_error,
                           &error_size) == 0 && socket_error == 0)
                rc = 0;
            else
                errno = socket_error ? socket_error : errno;
        }
        const int saved_errno = errno;
        if (fcntl(fd, F_SETFL, original_flags) != 0) rc = -1;
        errno = saved_errno;
        if (rc == 0) break;
        close(fd);
        fd = -1;
        if (deadline.present() && deadline.remaining_ms() == 0) break;
    }
    freeaddrinfo(res);
    return fd;
}

} // namespace xdebug_core
