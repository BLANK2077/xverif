#include "engine/session/json_line_reader.h"

#include <cstdlib>
#include <iostream>
#include <string>

#include <fcntl.h>
#include <unistd.h>

using Json = nlohmann::json;

namespace {

void require(bool condition, const char* message) {
    if (!condition) {
        std::cerr << "FAIL: " << message << "\n";
        std::exit(1);
    }
}

int input_fd(const std::string& wire) {
    char path[] = "/tmp/xdebug-session-json-line.XXXXXX";
    const int fd = mkstemp(path);
    require(fd >= 0, "create temporary input");
    require(unlink(path) == 0, "unlink temporary input");

    std::size_t offset = 0;
    while (offset < wire.size()) {
        const ssize_t n = write(fd, wire.data() + offset, wire.size() - offset);
        require(n > 0, "write temporary input");
        offset += static_cast<std::size_t>(n);
    }
    require(lseek(fd, 0, SEEK_SET) == 0, "rewind temporary input");
    return fd;
}

bool read_wire(const std::string& wire,
               Json& response,
               std::size_t max_bytes =
                   xdebug_engine::kMaxSessionJsonResponseBytes) {
    const int fd = input_fd(wire);
    const bool ok =
        xdebug_engine::read_bounded_json_line(fd, response, max_bytes);
    require(close(fd) == 0, "close temporary input");
    return ok;
}

}  // namespace

int main() {
    static_assert(xdebug_engine::kMaxSessionJsonResponseBytes ==
                  64U * 1024U * 1024U);

    Json response;
    require(read_wire("{\"ok\":true,\"data\":{\"count\":2}}\n", response),
            "read normal response");
    require(response["data"]["count"] == 2,
            "parse normal response payload");

    const std::string large_value(1024U * 1024U + 4096U, 'x');
    require(read_wire("{\"value\":\"" + large_value + "\"}\n", response),
            "read response larger than one MiB");
    require(response["value"].get<std::string>().size() == large_value.size(),
            "preserve response larger than one MiB");

    require(!read_wire("{\"value\":\"too large\"}\n", response, 8),
            "reject response over configured limit");
    require(!read_wire("{not-json}\n", response),
            "reject invalid JSON response");
    require(!read_wire("{\"ok\":true}", response),
            "reject EOF before newline");

    std::cout << "PASS: session JSON line reader\n";
    return 0;
}
