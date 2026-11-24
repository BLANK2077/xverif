#include "actions/dispatch.h"
#include "api/protocol.h"
#include "core/errors.h"
#include "core/limits.h"

#include <chrono>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <fstream>
#include <iostream>
#include <sstream>
#include <string>
#include <unistd.h>

namespace {

std::string read_stream(std::istream& in) {
    std::ostringstream out;
    out << in.rdbuf();
    return out.str();
}

std::string trim_line(const std::string& text) {
    std::size_t start = 0;
    std::size_t end = text.size();
    while (start < end && (text[start] == '\n' || text[start] == '\r')) ++start;
    while (end > start && (text[end - 1] == '\n' || text[end - 1] == '\r')) --end;
    return text.substr(start, end - start);
}

int run_once(xcov::Dispatcher& dispatcher, const std::string& text, bool json_output) {
    std::string request_id = "req-unknown";
    std::string action;
    nlohmann::json rsp;
    try {
        nlohmann::json req = xcov::parse_request(text);
        request_id = req.value("request_id", std::string("req-unknown"));
        action = req.value("action", std::string());
        rsp = dispatcher.dispatch(req);
    } catch (const xcov::Error& exc) {
        rsp = xcov::error_response(action, request_id, exc);
    } catch (const std::exception& exc) {
        rsp = xcov::error_response(action, request_id,
                                   xcov::Error("INTERNAL_ERROR", exc.what()));
    }
    if (json_output) {
        std::cout << xcov::json_dumps(rsp) << "\n";
    } else {
        std::cout << xcov::render_xout(rsp);
    }
    std::cout.flush();
    return rsp.value("ok", false) ? 0 : 1;
}

int stdio_loop(xcov::Dispatcher& dispatcher) {
    nlohmann::json ready = {
        {"type", "ready"},
        {"protocol", "xcov-stdio-loop"},
        {"version", 1},
        {"pid", static_cast<long long>(::getpid())},
    };
    if (const char* fingerprint = std::getenv("XVERIF_LSF_ENV_VERIFIED_FINGERPRINT")) {
        ready["environment_fingerprint"] = fingerprint;
    }
    std::cout << xcov::json_dumps(ready) << "\n";
    std::cout.flush();

    std::string line;
    while (std::getline(std::cin, line)) {
        const std::string text = trim_line(line);
        if (text.empty()) continue;
        if (text.size() > xcov::kMaxRequestBytes) {
            nlohmann::json rsp = xcov::error_response(
                "", "req-unknown",
                xcov::Error("REQUEST_BUDGET_EXCEEDED",
                            "request exceeds the xcov transport byte budget",
                            {{"max_request_bytes", xcov::kMaxRequestBytes}}));
            nlohmann::json envelope = {
                {"request_id", "req-unknown"},
                {"ok", false},
                {"api_version", rsp.value("api_version", "xcov.v1")},
                {"action", ""},
                {"payload_format", "xout"},
                {"json", rsp},
                {"xout", xcov::render_transport_xout(rsp)},
            };
            std::cout << xcov::json_dumps(envelope) << "\n";
            std::cout.flush();
            continue;
        }
        std::string request_id = "req-unknown";
        std::string action;
        nlohmann::json rsp;
        try {
            nlohmann::json req = xcov::parse_request(text);
            request_id = req.value("request_id", std::string("req-unknown"));
            action = req.value("action", std::string());
            if (action == "stdio.quit") {
                nlohmann::json envelope = {
                    {"request_id", request_id},
                    {"ok", true},
                    {"api_version", "xcov.v1"},
                    {"action", "stdio.quit"},
                    {"payload_format", "json"},
                    {"json",
                     {{"ok", true},
                      {"api_version", "xcov.v1"},
                      {"request_id", request_id},
                      {"action", "stdio.quit"}}},
                };
                std::cout << xcov::json_dumps(envelope) << "\n";
                std::cout.flush();
                return 0;
            }
            rsp = dispatcher.dispatch(req);
        } catch (const xcov::Error& exc) {
            rsp = xcov::error_response(action, request_id, exc);
        } catch (const std::exception& exc) {
            rsp = xcov::error_response(action, request_id,
                                       xcov::Error("INTERNAL_ERROR", exc.what()));
        }
        std::string xout;
        try {
            xout = xcov::render_transport_xout(rsp);
        } catch (const std::exception& exc) {
            xout = std::string("@xcov.v1 error action=") + action +
                   " request_id=" + request_id + "\n";
        }
        nlohmann::json envelope = {
            {"request_id", request_id},
            {"ok", rsp.value("ok", false)},
            {"api_version", rsp.value("api_version", std::string("xcov.v1"))},
            {"action", rsp.value("action", action)},
            {"payload_format", "xout"},
            {"json", rsp},
            {"xout", xout},
        };
        std::cout << xcov::json_dumps(envelope) << "\n";
        std::cout.flush();
    }
    return 0;
}

void print_usage() {
    std::fprintf(stderr,
                 "usage: xcov [--stdio-loop] [--once] [--json] [--request FILE] "
                 "[FILE|-]\n");
}

} // namespace

int main(int argc, char** argv) {
    bool loop = false;
    bool once = false;
    bool json_output = false;
    std::string input_arg;
    for (int index = 1; index < argc; ++index) {
        const std::string arg = argv[index];
        if (arg == "--stdio-loop") {
            loop = true;
        } else if (arg == "--once") {
            once = true;
        } else if (arg == "--json") {
            json_output = true;
        } else if (arg == "--request") {
            if (index + 1 >= argc) {
                print_usage();
                return 2;
            }
            input_arg = argv[++index];
        } else if (arg == "-h" || arg == "--help") {
            print_usage();
            return 0;
        } else if (input_arg.empty()) {
            input_arg = arg;
        } else {
            print_usage();
            return 2;
        }
    }
    try {
        xcov::Dispatcher dispatcher;
        if (loop) return stdio_loop(dispatcher);
        std::string text;
        if (input_arg.empty() || input_arg == "-") {
            text = read_stream(std::cin);
        } else {
            std::ifstream in(input_arg);
            if (!in) {
                std::fprintf(stderr, "ERROR: cannot open %s\n", input_arg.c_str());
                return 2;
            }
            text = read_stream(in);
        }
        if (text.empty()) {
            print_usage();
            return 2;
        }
        return run_once(dispatcher, trim_line(text), json_output);
    } catch (const xcov::Error& exc) {
        std::fprintf(stderr, "ERROR: %s: %s\n", exc.code().c_str(), exc.what());
        return 1;
    }
}
