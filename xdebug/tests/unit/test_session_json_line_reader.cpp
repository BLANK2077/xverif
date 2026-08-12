#include "engine/session/json_line_reader.h"
#include "test_temp_path.h"

#include <cstdlib>
#include <iostream>
#include <string>
#include <vector>

#include <fcntl.h>
#include <sys/socket.h>
#include <sys/wait.h>
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
    std::vector<char> path =
        test_temp_template("xdebug-session-json-line.XXXXXX");
    const int fd = mkstemp(path.data());
    require(fd >= 0, "create temporary input");
    require(unlink(path.data()) == 0, "unlink temporary input");

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

xdebug_engine::JsonLineReadStatus read_wire_status(
    const std::string& wire,
    Json& response,
    std::size_t max_bytes =
        xdebug_engine::kMaxSessionJsonResponseBytes) {
    const int fd = input_fd(wire);
    const xdebug_engine::JsonLineReadStatus status =
        xdebug_engine::read_bounded_json_line_status(
            fd, response, max_bytes);
    require(close(fd) == 0, "close temporary input");
    return status;
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
    require(read_wire_status("{\"value\":\"too large\"}\n", response, 8) ==
                xdebug_engine::JsonLineReadStatus::TooLarge,
            "classify response over configured limit");
    require(!read_wire("{not-json}\n", response),
            "reject invalid JSON response");
    require(read_wire_status("{not-json}\n", response) ==
                xdebug_engine::JsonLineReadStatus::InvalidJson,
            "classify invalid JSON response");
    require(!read_wire("{\"ok\":true}", response),
            "reject EOF before newline");
    require(read_wire_status("{\"ok\":true}", response) ==
                xdebug_engine::JsonLineReadStatus::EndOfFile,
            "classify EOF before newline");

    int pipe_fds[2] = {-1, -1};
    require(pipe(pipe_fds) == 0, "create timeout pipe");
    require(xdebug_engine::read_bounded_json_line_status(
                pipe_fds[0], response,
                xdebug_engine::kMaxSessionJsonResponseBytes,
                xdebug_core::TransportDeadline(1)) ==
                xdebug_engine::JsonLineReadStatus::Timeout,
            "classify deadline expiry");
    require(close(pipe_fds[0]) == 0, "close timeout reader");
    require(close(pipe_fds[1]) == 0, "close timeout writer");

    int socket_fds[2] = {-1, -1};
    require(socketpair(AF_UNIX, SOCK_STREAM, 0, socket_fds) == 0,
            "create partial-write socketpair");
    const std::string large_wire(2U * 1024U * 1024U, 'w');
    const pid_t reader = fork();
    require(reader >= 0, "fork partial-write reader");
    if (reader == 0) {
        std::size_t received = 0;
        char buffer[4096];
        while (received < large_wire.size()) {
            const ssize_t n = read(socket_fds[1], buffer, sizeof(buffer));
            if (n <= 0) _exit(2);
            received += static_cast<std::size_t>(n);
        }
        _exit(received == large_wire.size() ? 0 : 3);
    }
    require(close(socket_fds[1]) == 0, "close parent reader socket");
    require(xdebug_core::write_all_deadline(
                socket_fds[0], large_wire.data(), large_wire.size(),
                xdebug_core::TransportDeadline(2000)) ==
                xdebug_core::TransportIoStatus::Ok,
            "write complete payload across partial socket writes");
    require(close(socket_fds[0]) == 0, "close partial-write socket");
    int reader_status = 0;
    require(waitpid(reader, &reader_status, 0) == reader,
            "wait partial-write reader");
    require(WIFEXITED(reader_status) && WEXITSTATUS(reader_status) == 0,
            "partial-write reader received complete payload");

    require(socketpair(AF_UNIX, SOCK_STREAM, 0, socket_fds) == 0,
            "create write-timeout socketpair");
    int send_buffer_bytes = 4096;
    require(setsockopt(socket_fds[0], SOL_SOCKET, SO_SNDBUF,
                       &send_buffer_bytes, sizeof(send_buffer_bytes)) == 0,
            "shrink send buffer");
    require(xdebug_core::write_all_deadline(
                socket_fds[0], large_wire.data(), large_wire.size(),
                xdebug_core::TransportDeadline(1)) ==
                xdebug_core::TransportIoStatus::Timeout,
            "classify write deadline expiry");
    require(close(socket_fds[0]) == 0, "close timeout sender");
    require(close(socket_fds[1]) == 0, "close timeout receiver");

    std::cout << "PASS: session JSON line reader\n";
    return 0;
}
