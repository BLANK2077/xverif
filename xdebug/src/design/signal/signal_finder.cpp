#include "signal_finder.h"

#include "json.hpp"

#include <sstream>

namespace xdebug_design {

using json = nlohmann::json;

SignalResolveResult SignalFinder::resolve(const std::string& query) const {
    SignalResolveResult result;
    result.query = query;

    npiHandle direct = npi_handle_by_name(query.c_str(), NULL);
    if (!direct) {
        result.ok = false;
        result.status = "not_found";
        result.message = "Signal not found: " + query;
        return result;
    }

    result.matches.push_back(make_match(direct));
    npi_release_handle(direct);
    return result;
}

SignalMatch SignalFinder::make_match(npiHandle hdl) const {
    SignalMatch match;
    const char* full_name = npi_get_str(npiFullName, hdl);
    if (full_name) {
        match.signal = full_name;
    }
    match.type = type_name(npi_get(npiType, hdl));
    const char* file = npi_get_str(npiFile, hdl);
    if (!file) {
        file = npi_get_str(npiDefFile, hdl);
    }
    if (file) {
        match.file = file;
    }
    match.line = npi_get(npiLineNo, hdl);
    if (match.line <= 0) {
        match.line = npi_get(npiDefLineNo, hdl);
    }
    return match;
}

std::string SignalFinder::type_name(int type) const {
    switch (type) {
        case npiPort: return "port";
        case npiNet: return "net";
        case npiReg: return "reg";
        case npiBitVar: return "bitvar";
        case npiEnumVar: return "enum_var";
        case npiStructVar: return "struct_var";
        case npiEnumNet: return "enum_net";
        case npiStructNet: return "struct_net";
        case npiRefObj: return "ref_obj";
        default: {
            std::ostringstream out;
            out << "type_" << type;
            return out.str();
        }
    }
}

std::string SignalFinder::render_text(const SignalResolveResult& result) const {
    std::ostringstream out;
    if (!result.ok) {
        out << "Error: " << result.message << " (status=" << result.status << ")\n";
        return out.str();
    }
    out << "Signal resolve for " << result.query << "\n";
    int idx = 1;
    for (const auto& match : result.matches) {
        out << "[" << idx++ << "] " << match.signal << "\n";
        out << "    type: " << match.type << "\n";
        if (!match.file.empty() || match.line > 0) {
            out << "    location: " << match.file << ":" << match.line << "\n";
        }
    }
    return out.str();
}

std::string SignalFinder::render_json(const SignalResolveResult& result) const {
    json payload;
    payload["ok"] = result.ok;
    payload["query"] = result.query;
    payload["status"] = result.status;
    payload["message"] = result.message;
    payload["scan_complete"] = !result.truncated;
    payload["analysis_complete"] = !result.truncated;
    payload["response_truncated"] = false;
    payload["total_count"] = result.matches.size();
    payload["returned_count"] = result.matches.size();
    payload["truncation_scopes"] = result.truncated
        ? json::array({"analysis_matches"})
        : json::array();
    payload["matches"] = json::array();
    for (const auto& match : result.matches) {
        payload["matches"].push_back({
            {"signal", match.signal},
            {"type", match.type},
            {"file", match.file},
            {"line", match.line}
        });
    }
    return payload.dump(2) + "\n";
}

} // namespace xdebug_design
