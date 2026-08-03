#include "json_line_reader.h"

#include <cerrno>
#include <cstring>
#include <string>

#include <unistd.h>

namespace xdebug_engine {

bool read_bounded_json_line(int fd,
                            nlohmann::json& response,
                            std::size_t max_bytes) {
    constexpr std::size_t kReadBlockBytes = 64U * 1024U;
    char buffer[kReadBlockBytes];
    std::string line;

    while (true) {
        const ssize_t n = read(fd, buffer, sizeof(buffer));
        if (n < 0 && errno == EINTR) continue;
        if (n <= 0) return false;

        const std::size_t bytes_read = static_cast<std::size_t>(n);
        const void* newline = std::memchr(buffer, '\n', bytes_read);
        const std::size_t payload_bytes =
            newline == nullptr
                ? bytes_read
                : static_cast<const char*>(newline) - buffer;
        if (line.size() > max_bytes ||
            payload_bytes > max_bytes - line.size()) {
            return false;
        }
        line.append(buffer, payload_bytes);

        if (newline != nullptr) {
            try {
                response = nlohmann::json::parse(line);
                return true;
            } catch (...) {
                return false;
            }
        }
    }
}

}  // namespace xdebug_engine
