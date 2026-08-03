#pragma once

#include "transport_timeout.h"

#include <arpa/inet.h>
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

inline std::string generate_auth_token() {
    unsigned char bytes[24] = {};
    int fd = open("/dev/urandom", O_RDONLY);
    if (fd >= 0) {
        ssize_t n = read(fd, bytes, sizeof(bytes));
        close(fd);
        if (n != static_cast<ssize_t>(sizeof(bytes))) memset(bytes, 0, sizeof(bytes));
    }
    if (bytes[0] == 0 && bytes[1] == 0) {
        unsigned long long seed = static_cast<unsigned long long>(time(nullptr)) ^
                                  (static_cast<unsigned long long>(getpid()) << 32);
        for (size_t i = 0; i < sizeof(bytes); ++i) {
            seed = seed * 6364136223846793005ULL + 1;
            bytes[i] = static_cast<unsigned char>(seed >> 24);
        }
    }
    static const char hex[] = "0123456789abcdef";
    std::string out;
    out.reserve(sizeof(bytes) * 2);
    for (unsigned char b : bytes) {
        out.push_back(hex[b >> 4]);
        out.push_back(hex[b & 0xf]);
    }
    return out;
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
