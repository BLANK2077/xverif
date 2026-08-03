#pragma once

#include "api/json_types.h"
#include "core/npi/resource_guard.h"
#include "core/npi/time_contract.h"
#include "core/value/logic_value.h"

#include "npi.h"
#include "npi_fsdb.h"
#include "npi_hdl.h"
#include "npi_L1.h"

#include <algorithm>
#include <cmath>
#include <cstdio>
#include <fcntl.h>
#include <sstream>
#include <string>
#include <unistd.h>
#include <vector>

namespace xdebug {

// ═══════════════════════════════════════════════════════════════════
// NPI helpers
// ═══════════════════════════════════════════════════════════════════

inline std::string npi_string(int prop, npiHandle h) {
    const char* s = h ? npi_get_str(prop, h) : nullptr;
    return s ? s : "";
}

inline std::string handle_info(npiHandle h) {
    const char* s = h ? npi_ut_get_hdl_info(h, true, false) : nullptr;
    return s ? s : "";
}

inline std::string statement_kind(int type) {
    switch (type) {
    case npiContAssign:   return "assignment";
    case npiAssignment:   return "assignment";
    case npiForce:        return "force";
    case npiPort:         return "port_boundary";
    case npiIf:           return "if";
    case npiIfElse:       return "if_else";
    case npiCase:         return "case";
    case npiCaseItem:     return "case_item";
    case npiEventControl: return "event_control";
    case npiRelease:      return "release";
#ifdef npiMpPort
    case npiMpPort:       return "modport_port";
#endif
#ifdef npiRefObj
    case npiRefObj:       return "ref_obj";
#endif
    default:
        if (type == 697) return "modport_port";
        if (type == 608) return "ref_obj";
        return "other";
    }
}

inline std::string fsdb_value_at(npiFsdbFileHandle fsdb,
                                  const std::string& sig, npiFsdbTime time) {
    if (!fsdb) return "";
    npiFsdbSigHandle sh = npi_fsdb_sig_by_name(fsdb, sig.c_str(), nullptr);
    if (!sh) return "";
    std::string raw;
    int rc = npi_fsdb_sig_hdl_value_at(sh, time, raw, npiFsdbBinStrVal);
    return rc ? raw : "";
}

inline std::string format_value(const std::string& raw) {
    if (raw.empty()) return "?";
    return xdebug_core::logic_value_compact_string(
        xdebug_core::logic_value_from_fsdb_raw(raw, 'b'));
}

inline std::string driver_text(npiHandle h, const std::string& kind) {
    if (!h) return "(primary input)";
    std::string raw = handle_info(h);
    size_t comma = raw.find(", ");
    if (comma != std::string::npos) raw = raw.substr(comma + 2);
    size_t brace = raw.rfind(" {");
    if (brace != std::string::npos) raw = raw.substr(0, brace);
    return raw.empty() ? "(" + kind + ")" : raw;
}

struct ActiveTraceResolveResult {
    actTrcRes_t active;
    int count = 0;
    bool precise_time_found = false;
    bool ambiguous = false;
    std::string active_time;
    std::string evidence_source = "fsdb_precise_time_static_trace";
    int static_candidate_count = 0;
    int active_check_count = 0;
    std::vector<std::string> limitations;
};

inline bool previous_fsdb_change_time(npiFsdbFileHandle fsdb,
                                      const std::string& signal_name,
                                      const std::string& requested_time,
                                      std::string& precise_time,
                                      npiFsdbTime& precise_fsdb_time) {
    if (!fsdb) return false;
    npiFsdbTime requested_fsdb_time = 0;
    std::string error;
    xdebug_core::TimeParseOptions options;
    options.default_unit = "ns";
    if (!xdebug_core::parse_time(fsdb, requested_time, options, requested_fsdb_time, error)) {
        return false;
    }

    npiFsdbSigHandle signal = npi_fsdb_sig_by_name(fsdb, signal_name.c_str(), nullptr);
    if (!signal) return false;

    npiFsdbVctHandle vct = npi_fsdb_create_vct(signal);
    if (!vct) return false;

    bool ok = false;
    if (npi_fsdb_goto_time(vct, requested_fsdb_time) &&
        npi_fsdb_vct_time(vct, &precise_fsdb_time)) {
        precise_time = xdebug_core::format_time(fsdb, precise_fsdb_time);
        ok = !precise_time.empty();
    }
    npi_fsdb_release_vct(vct);
    return ok;
}

inline bool is_assignment_like_statement(const drvLoadStmt_s& stmt) {
    int type = stmt.useHdl ? npi_get(npiType, stmt.useHdl) : 0;
    std::string kind = statement_kind(type);
    return kind == "assignment" || kind == "force";
}

inline ActiveTraceResolveResult resolve_active_driver_precise(
    npiFsdbFileHandle fsdb,
    npiHandle signal_hdl,
    const std::string& signal_name,
    const std::string& requested_time,
    const trcOption_t& options) {
    ActiveTraceResolveResult result;

    npiFsdbTime precise_fsdb_time = 0;
    if (!previous_fsdb_change_time(
            fsdb, signal_name, requested_time, result.active_time, precise_fsdb_time)) {
        result.limitations.push_back(
            "could not locate precise FSDB value-change time for " + signal_name);
        return result;
    }
    result.precise_time_found = true;
    result.active.activeTime = result.active_time;
    result.active.isForce = false;

    drvLoadStmtVec_t candidates;
    int static_rc = signal_hdl
        ? npi_trace_driver_by_hdl2(signal_hdl, candidates, true, nullptr, options)
        : 0;
    result.static_candidate_count = static_rc > 0
        ? static_cast<int>(candidates.size()) : 0;
    if (static_rc <= 0 || candidates.empty()) {
        result.limitations.push_back(
            "static driver trace returned no candidates for " + signal_name);
        return result;
    }

    int active_assignment_count = 0;
    for (const auto& candidate : candidates) {
        if (!candidate.useHdl) continue;
        int active_rc = npi_check_active_handle(candidate.useHdl, result.active_time.c_str());
        if (active_rc != 1) continue;
        result.active.drvLoadStmtVec.push_back(candidate);
        result.active_check_count++;
        if (is_assignment_like_statement(candidate)) active_assignment_count++;
    }

    result.count = static_cast<int>(result.active.drvLoadStmtVec.size());
    if (result.count == 0) {
        result.limitations.push_back(
            "no static driver candidate is active at precise FSDB time " + result.active_time +
            " for " + signal_name);
    }
    if (active_assignment_count > 1) {
        result.ambiguous = true;
        result.limitations.push_back(
            "multiple active assignment candidates at precise FSDB time " + result.active_time +
            " for " + signal_name);
    }
    return result;
}

struct PortConnectionInfo {
    bool found_port = false;
    bool is_input_like = false;
    std::string instance_path;
    std::string port_name;
    std::string target_signal;
};

inline bool is_input_like_direction(int dir) {
    return dir == npiInput || dir == npiInout;
}

inline std::vector<std::string> split_hier_name(const std::string& path) {
    std::vector<std::string> parts;
    std::string current;
    for (char ch : path) {
        if (ch == '.') {
            if (!current.empty()) {
                parts.push_back(current);
                current.clear();
            }
        } else {
            current += ch;
        }
    }
    if (!current.empty()) parts.push_back(current);
    return parts;
}

inline std::string join_hier_name(const std::vector<std::string>& parts,
                                  size_t begin,
                                  size_t end) {
    std::string out;
    for (size_t i = begin; i < end && i < parts.size(); ++i) {
        if (!out.empty()) out += ".";
        out += parts[i];
    }
    return out;
}

inline PortConnectionInfo resolve_input_port_connection(const std::string& signal_name) {
    PortConnectionInfo info;
    auto parts = split_hier_name(signal_name);
    if (parts.size() < 2) return info;

    for (size_t inst_end = parts.size() - 1; inst_end >= 1; --inst_end) {
        std::string inst_path = join_hier_name(parts, 0, inst_end);
        std::string port_name = parts[inst_end];

        npiHandle inst = npi_handle_by_name(inst_path.c_str(), nullptr);
        if (!inst) {
            if (inst_end == 1) break;
            continue;
        }

        int inst_type = npi_get(npiType, inst);
        if (inst_type != npiModule && inst_type != npiInterface &&
            inst_type != npiInterfaceArray) {
            npi_release_handle(inst);
            if (inst_end == 1) break;
            continue;
        }

        npiHandle port_iter = npi_iterate(npiPort, inst);
        if (!port_iter) {
            npi_release_handle(inst);
            if (inst_end == 1) break;
            continue;
        }

        npiHandle port;
        while ((port = npi_scan(port_iter)) != nullptr) {
            std::string pname = npi_string(npiName, port);
            if (pname != port_name) {
                npi_release_handle(port);
                continue;
            }

            info.found_port = true;
            info.instance_path = inst_path;
            info.port_name = port_name;
            info.is_input_like = is_input_like_direction(npi_get(npiDirection, port));

            if (info.is_input_like) {
                npiHandle high = npi_handle(npiHighConn, port);
                if (high) {
                    std::string high_name = npi_string(npiFullName, high);
                    if (!high_name.empty()) {
                        std::string resolved = high_name;
                        for (size_t i = inst_end + 1; i < parts.size(); ++i) {
                            resolved += "." + parts[i];
                        }
                        if (resolved != signal_name) info.target_signal = resolved;
                    }
                    npi_release_handle(high);
                }
            }

            npi_release_handle(port);
            break;
        }

        npi_release_handle(port_iter);
        npi_release_handle(inst);
        if (info.found_port) break;
        if (inst_end == 1) break;
    }
    return info;
}

} // namespace xdebug
