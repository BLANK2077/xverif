#include "json_line_reader.h"

#include <string>

namespace xdebug_engine {

JsonLineReadStatus read_bounded_json_line_status(
    int fd, nlohmann::json& response, std::size_t max_bytes,
    const xdebug_core::TransportDeadline& deadline) {
    std::string line;
    const xdebug_core::TransportIoStatus io_status =
        xdebug_core::read_bounded_line_deadline(
            fd, line, max_bytes, deadline);
    switch (io_status) {
    case xdebug_core::TransportIoStatus::EndOfFile:
        return JsonLineReadStatus::EndOfFile;
    case xdebug_core::TransportIoStatus::Timeout:
        return JsonLineReadStatus::Timeout;
    case xdebug_core::TransportIoStatus::TooLarge:
        return JsonLineReadStatus::TooLarge;
    case xdebug_core::TransportIoStatus::IoError:
        return JsonLineReadStatus::IoError;
    case xdebug_core::TransportIoStatus::Ok:
        break;
    }
    try {
        response = nlohmann::json::parse(line);
        return JsonLineReadStatus::Ok;
    } catch (...) {
        return JsonLineReadStatus::InvalidJson;
    }
}

bool read_bounded_json_line(int fd,
                            nlohmann::json& response,
                            std::size_t max_bytes) {
    return read_bounded_json_line_status(fd, response, max_bytes) ==
           JsonLineReadStatus::Ok;
}

}  // namespace xdebug_engine
