#pragma once

#include "transport_timeout.h"

#include <arpa/inet.h>
#include <cerrno>
#include <cstring>
#include <fcntl.h>
#include <netdb.h>
#include <string>
#include <sys/socket.h>
#include <sys/time.h>
#include <sys/types.h>
#include <sys/un.h>
#include <unistd.h>

namespace xdebug_core {

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

inline int connect_uds(const std::string& path) {
    int fd = socket(AF_UNIX, SOCK_STREAM, 0);
    if (fd < 0) return -1;
    struct sockaddr_un addr;
    memset(&addr, 0, sizeof(addr));
    addr.sun_family = AF_UNIX;
    strncpy(addr.sun_path, path.c_str(), sizeof(addr.sun_path) - 1);
    if (connect(fd, reinterpret_cast<struct sockaddr*>(&addr), sizeof(addr)) < 0) {
        close(fd);
        return -1;
    }
    return fd;
}

inline int connect_tcp(const std::string& host, int port) {
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
        if (connect(fd, p->ai_addr, p->ai_addrlen) == 0) break;
        close(fd);
        fd = -1;
    }
    freeaddrinfo(res);
    return fd;
}

inline bool read_line_timeout(int fd, std::string& line, int timeout_sec = 2) {
    line.clear();
    struct timeval tv;
    tv.tv_sec = timeout_sec;
    tv.tv_usec = 0;
    setsockopt(fd, SOL_SOCKET, SO_RCVTIMEO, &tv, sizeof(tv));
    char c = 0;
    while (true) {
        ssize_t n = read(fd, &c, 1);
        if (n <= 0) return false;
        if (c == '\n') return true;
        line.push_back(c);
        if (line.size() > 4096) return false;
    }
}

} // namespace xdebug_core
