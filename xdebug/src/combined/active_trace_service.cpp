#include "combined/active_trace_service.h"
#include "combined/active_trace_common.h"
#include "api/response.h"
#include "core/ai/common_blocks.h"
#include "core/npi/time_contract.h"
#include "runtime/work_dir.h"

#include "npi.h"
#include "npi_fsdb.h"
#include "npi_hdl.h"
#include "npi_L1.h"

#include <algorithm>
#include <cctype>
#include <cstdio>
#include <cstdlib>
#include <fcntl.h>
#include <set>
#include <string>
#include <unistd.h>
#include <vector>

namespace xdebug {

namespace {

bool is_control_kind(const std::string& kind) {
    return kind == "if" || kind == "if_else" ||
           kind == "case" || kind == "case_item";
}

bool is_alias_kind(const std::string& kind) {
    return kind == "port_boundary" || kind == "modport_port" || kind == "ref_obj";
}

bool is_primary_input(npiHandle signal_hdl) {
    if (!signal_hdl) return false;
    int dir = npi_get(npiDirection, signal_hdl);
    return is_input_like_direction(dir);
}

bool is_ref_obj_type(int type) {
#ifdef npiRefObj
    if (type == npiRefObj) return true;
#endif
    return type == 608;
}

bool is_modport_port_type(int type) {
#ifdef npiMpPort
    if (type == npiMpPort) return true;
#endif
    return type == 697;
}

bool is_signal_like_type(int type) {
    return type == npiNet || type == npiNetBit ||
           type == npiReg || type == npiRegBit ||
           type == npiBitVar ||
           type == npiPartSelect || type == npiBitSelect ||
           type == npiVarSelect || type == npiNetSelect ||
           is_ref_obj_type(type) || is_modport_port_type(type);
}

std::string normalized_signal_name(npiHandle handle) {
    if (!handle) return "";
    int type = npi_get(npiType, handle);
    if (type == npiPartSelect || type == npiBitSelect ||
        type == npiVarSelect || type == npiNetSelect ||
        type == npiNetBit || type == npiRegBit) {
        NpiHandleGuard parent(npi_handle(npiParent, handle));
        std::string parent_name = npi_string(npiFullName, parent.get());
        if (!parent_name.empty()) return parent_name;
    }
    std::string name = npi_string(npiFullName, handle);
    if (name.empty()) name = npi_string(npiName, handle);
    return name;
}

std::string direct_rhs_signal_name(const drvLoadStmt_s& statement) {
    if (!statement.useHdl) return "";

    NpiHandleGuard rhs(npi_handle(npiRhs, statement.useHdl));
    if (rhs) {
        int rhs_type = npi_get(npiType, rhs.get());
        if (rhs_type == npiOperation ||
            rhs_type == npiFunction ||
            rhs_type == npiSysFuncCall ||
            rhs_type == npiSysTaskCall ||
            rhs_type == npiConstant) {
            return "";
        }
        if (is_signal_like_type(rhs_type)) {
            return normalized_signal_name(rhs.get());
        }
    }
    return "";
}

Json value_map(npiFsdbFileHandle fsdb,
               const std::vector<std::string>& signals,
               const std::string& time_spec,
               std::vector<std::string>& limitations) {
    Json values = Json::object();
    npiFsdbTime time = 0;
    std::string error;
    xdebug_core::TimeParseOptions options;
    options.default_unit = "ns";
    if (!xdebug_core::parse_time(fsdb, time_spec, options, time, error)) {
        limitations.push_back("can not convert time " + time_spec + " to FSDB time");
        return values;
    }
    for (const auto& signal : signals) {
        npiFsdbSigHandle handle = npi_fsdb_sig_by_name(fsdb, signal.c_str(), nullptr);
        std::string raw;
        int rc = handle ? npi_fsdb_sig_hdl_value_at(handle, time, raw, npiFsdbBinStrVal) : 0;
        if (!handle || !rc) {
            values[signal] = nullptr;
            continue;
        }
        bool known = raw.find_first_of("xXzZ") == std::string::npos;
        values[signal] = {{"value", raw}, {"known", known}};
    }
    return values;
}

// ─── new data model ─────────────────────────────────────────────────────────

struct ActiveTraceLimits {
    int max_depth = 8;
    int max_nodes = 50;
    int max_time_steps = 128;
    int max_trace_signals = 64;
};

struct ActiveTraceOptions {
    ActiveTraceLimits limits;
    bool include_trace = false;
};

struct AliasCandidate {
    std::string from;
    std::string to;
    std::string alias_kind;
    std::string confidence;
    std::string reason;
};

struct TraceEdge {
    std::string from;
    std::string to;
    std::string relation;
    std::string confidence;
};

struct TraceNode {
    std::string id;
    std::string role;
    std::string kind;
    std::string signal;
    std::vector<std::string> signals;
    std::string file;
    int line = 0;
    std::string text;
    std::string active_time;
    Json value = nullptr;
    std::string next_signal;
    std::string next_relation;
    std::string next_confidence;
    std::string alias_kind;
};

struct TraceBuildResult {
    std::vector<TraceNode> nodes;
    std::vector<TraceEdge> edges;
    std::vector<std::string> selected_path;
    std::vector<TraceNode> controls;
    std::vector<TraceNode> events;
    std::vector<std::string> limitations;
    std::vector<AliasCandidate> alias_candidates;
    Json root_driver = nullptr;
    Json current_driver = nullptr;
    std::string evidence_source;
    int static_candidate_count = 0;
    int active_check_count = 0;
    bool truncated = false;
    std::string termination = "unresolved";
    std::string termination_detail;
    int node_count = 0;
};

Json to_json(const AliasCandidate& candidate) {
    return {
        {"from", candidate.from},
        {"to", candidate.to},
        {"alias_kind", candidate.alias_kind},
        {"confidence", candidate.confidence},
        {"reason", candidate.reason}
    };
}

Json to_json(const TraceEdge& edge) {
    return {
        {"from", edge.from},
        {"to", edge.to},
        {"relation", edge.relation},
        {"confidence", edge.confidence}
    };
}

Json to_json(const TraceNode& node) {
    Json signals = Json::array();
    for (const auto& signal : node.signals) signals.push_back(signal);
    return {
        {"id", node.id},
        {"role", node.role},
        {"kind", node.kind},
        {"signal", node.signal},
        {"signals", signals},
        {"file", node.file},
        {"line", node.line},
        {"text", node.text},
        {"active_time", node.active_time},
        {"value", node.value},
        {"next_signal", node.next_signal},
        {"alias_kind", node.alias_kind}
    };
}

Json nodes_to_json(const std::vector<TraceNode>& nodes) {
    Json out = Json::array();
    for (const auto& node : nodes) out.push_back(to_json(node));
    return out;
}

Json edges_to_json(const std::vector<TraceEdge>& edges) {
    Json out = Json::array();
    for (const auto& edge : edges) out.push_back(to_json(edge));
    return out;
}

Json strings_to_json(const std::vector<std::string>& values) {
    Json out = Json::array();
    for (const auto& value : values) out.push_back(value);
    return out;
}

Json alias_candidates_to_json(const std::vector<AliasCandidate>& candidates) {
    Json out = Json::array();
    for (const auto& candidate : candidates) out.push_back(to_json(candidate));
    return out;
}

ActiveTraceLimits parse_limits(const Json& request, const Json& args) {
    (void)args;
    ActiveTraceLimits limits;
    Json limits_json = request.value("limits", Json::object());
    if (limits_json.contains("max_depth") && limits_json["max_depth"].is_number()) {
        limits.max_depth = std::max(1, limits_json["max_depth"].get<int>());
    }
    if (limits_json.contains("max_nodes") && limits_json["max_nodes"].is_number()) {
        limits.max_nodes = std::max(1, limits_json["max_nodes"].get<int>());
    }
    if (limits_json.contains("max_time_steps") && limits_json["max_time_steps"].is_number()) {
        limits.max_time_steps = std::max(1, limits_json["max_time_steps"].get<int>());
    }
    if (limits_json.contains("max_trace_signals") && limits_json["max_trace_signals"].is_number()) {
        limits.max_trace_signals = std::max(1, limits_json["max_trace_signals"].get<int>());
    }
    return limits;
}

ActiveTraceOptions parse_options(const Json& request,
                                 const Json& args,
                                 bool include_trace) {
    ActiveTraceOptions options;
    options.limits = parse_limits(request, args);
    options.include_trace = include_trace;
    return options;
}

// ─── trace node builder ─────────────────────────────────────────────────────

TraceNode trace_node_from_statement(const drvLoadStmt_s& statement,
                                    const std::string& node_id,
                                    const std::string& role,
                                    const std::string& active_time,
                                    const std::string& current_signal,
                                    const Json& value) {
    int type = statement.useHdl ? npi_get(npiType, statement.useHdl) : 0;
    std::string kind = statement_kind(type);
    std::string file = npi_string(npiFile, statement.useHdl);
    int line = statement.useHdl ? npi_get(npiLineNo, statement.useHdl) : 0;
    std::string text = handle_info(statement.useHdl);

    std::vector<std::string> signals;
    std::string next_signal;
    std::string next_relation = "rhs_dependency";
    std::string next_confidence = "high";
    for (const auto& handle : statement.sigHdlVec) {
        std::string name = normalized_signal_name(handle);
        if (name.empty()) continue;
        signals.push_back(name);
    }

    // A dependency edge is published only when the NPI RHS relation names the
    // exact signal.  sigHdlVec is intentionally not guessed into a dependency.
    if (kind == "assignment") {
        std::string candidate = direct_rhs_signal_name(statement);
        if (!candidate.empty() && candidate != current_signal) {
            NpiHandleGuard verify(npi_handle_by_name(candidate.c_str(), nullptr));
            if (verify) next_signal = candidate;
        }
    }

    TraceNode node;
    node.id = node_id;
    node.role = role;
    node.kind = kind;
    node.signal = current_signal;
    node.signals = signals;
    node.file = file;
    node.line = line;
    node.text = text;
    node.active_time = active_time;
    node.value = value;
    node.next_signal = next_signal;
    node.next_relation = next_relation;
    node.next_confidence = next_confidence;
    node.alias_kind = kind == "modport_port" ? "interface_modport" :
                      kind == "port_boundary" ? "module_port" :
                      kind == "ref_obj" ? "direct_ref" : "none";
    return node;
}

// ─── alias resolver ─────────────────────────────────────────────────────────

// Split a hierarchical name into segments.
static std::vector<std::string> split_hier(const std::string& path) {
    std::vector<std::string> parts;
    std::string current;
    for (size_t i = 0; i < path.size(); ++i) {
        if (path[i] == '.') {
            if (!current.empty()) { parts.push_back(current); current.clear(); }
        } else {
            current += path[i];
        }
    }
    if (!current.empty()) parts.push_back(current);
    return parts;
}

AliasCandidate make_alias_candidate(const std::string& from,
                                    const std::string& to,
                                    const std::string& alias_kind,
                                    const std::string& confidence,
                                    const std::string& reason) {
    AliasCandidate candidate;
    candidate.from = from;
    candidate.to = to;
    candidate.alias_kind = alias_kind;
    candidate.confidence = confidence;
    candidate.reason = reason;
    return candidate;
}

// Try to resolve a signal through interface/modport aliases.
// Returns array of candidate objects.
std::vector<AliasCandidate> resolve_alias_candidates(npiHandle signal_handle,
                                                     const std::string& signal_name) {
    std::vector<AliasCandidate> candidates;
    if (!signal_handle) return candidates;

    int hdl_type = npi_get(npiType, signal_handle);
    std::string full_name = npi_string(npiFullName, signal_handle);

    // Strategy 1: Use the hierarchical signal_name (not the handle's full_name
    // which may be a definition-side path like "data_if.source.data") to trace
    // through instance port connections.
    // e.g., if_root_tb.u_sink.bus.data → find port 'bus' on u_sink → highconn
    auto parts = split_hier(signal_name);
    if (parts.size() >= 3) {
        // Try each prefix as a possible instance path
        for (size_t inst_end = parts.size() - 1; inst_end >= 1; --inst_end) {
            std::string inst_path;
            for (size_t i = 0; i < inst_end; ++i) {
                if (i > 0) inst_path += ".";
                inst_path += parts[i];
            }

            npiHandle inst = npi_handle_by_name(inst_path.c_str(), nullptr);
            if (!inst) continue;

            int inst_type = npi_get(npiType, inst);
            // Accept module instances and interface instances
            if (inst_type != npiModule && inst_type != npiInterface &&
                inst_type != npiInterfaceArray) {
                npi_release_handle(inst);
                continue;
            }

            // The next part is the port name
            std::string port_name = parts[inst_end];

            // Iterate ports on this instance
            npiHandle port_iter = npi_iterate(npiPort, inst);
            if (!port_iter) { npi_release_handle(inst); continue; }

            npiHandle port;
            bool found = false;
            while ((port = npi_scan(port_iter)) != nullptr) {
                std::string pname = npi_string(npiName, port);
                if (pname == port_name) {
                    // Found the port — get highconn
                    npiHandle high = npi_handle(npiHighConn, port);
                    if (high) {
                        std::string high_name = npi_string(npiFullName, high);
                        // Reconstruct: high_name + remaining parts after port
                        std::string resolved = high_name;
                        for (size_t i = inst_end + 1; i < parts.size(); ++i) {
                            resolved += "." + parts[i];
                        }

                        candidates.push_back(make_alias_candidate(
                            signal_name,
                            resolved,
                            "module_port",
                            "high",
                            "traced through instance port " + inst_path + "." + port_name + " → " + high_name));

                        npi_release_handle(high);
                        found = true;
                    }
                    npi_release_handle(port);
                    break;
                }
                npi_release_handle(port);
            }
            npi_release_handle(port_iter);
            npi_release_handle(inst);

            if (found) break;
        }
    }

    // Strategy 2a: For modport_port or ref_obj handles, try npiActual first
    // to find the directly connected signal.
    bool is_mp_port = false;
#ifdef npiMpPort
    is_mp_port = (hdl_type == npiMpPort);
#else
    is_mp_port = (hdl_type == 697);
#endif
    if (is_mp_port || hdl_type == 608 /* npiRefObj */) {
        npiHandle actual = npi_handle(npiActual, signal_handle);
        if (actual) {
            std::string actual_name = npi_string(npiFullName, actual);
            if (!actual_name.empty() && actual_name != full_name) {
                candidates.push_back(make_alias_candidate(
                    signal_name,
                    actual_name,
                    is_mp_port ? "interface_modport" : "direct_ref",
                    "high",
                    "resolved via npiActual to " + actual_name));
            }
            npi_release_handle(actual);
        }
        // Also try npiLowConn for modport ports
        if (candidates.empty() && is_mp_port) {
            npiHandle low = npi_handle(npiLowConn, signal_handle);
            if (low) {
                std::string low_name = npi_string(npiFullName, low);
                if (!low_name.empty() && low_name != full_name) {
                    candidates.push_back(make_alias_candidate(
                        signal_name,
                        low_name,
                        "interface_modport",
                        "high",
                        "resolved via npiLowConn to " + low_name));
                }
                npi_release_handle(low);
            }
        }

    }

    // If the signal is a ref_obj, resolve only through the explicit NPI
    // reference relation.
    if (candidates.empty()) {
#ifdef npiRefObj
        if (hdl_type == npiRefObj) {
#else
        if (hdl_type == 608) {  // npiRefObj value in NPI versions without the symbol
#endif
            // For ref_obj, the NPI full name should give us the underlying object
            // Try to get the actual reference target
            npiHandle ref = npi_handle(npiActual, signal_handle);
            if (ref) {
                std::string ref_name = npi_string(npiFullName, ref);
                if (!ref_name.empty() && ref_name != full_name) {
                    candidates.push_back(make_alias_candidate(
                        signal_name,
                        ref_name,
                        "direct_ref",
                        "high",
                        "resolved ref_obj to actual target"));
                }
                npi_release_handle(ref);
            }
        }
    }

    return candidates;
}

// ─── recursive active trace builder ─────────────────────────────────────────

TraceBuildResult build_active_trace(
    npiFsdbFileHandle fsdb,
    const std::string& root_signal,
    const std::string& requested_time,
    const trcOption_t& options,
    const ActiveTraceLimits& limits) {

    TraceBuildResult result;

    // BFS/DFS queue: (signal, time, depth, parent edge metadata)
    struct QueueItem {
        std::string signal;
        std::string time;
        int depth;
        std::string parent_id;
        std::string parent_relation;
        std::string parent_confidence;
    };

    std::vector<QueueItem> queue;
    queue.push_back({root_signal, requested_time, 0, "", "", ""});

    // Visited set to prevent loops but allow temporal revisits.
    auto vkey = [](const std::string& sig, const std::string& t) { return sig + "\x1f" + t; };
    std::set<std::string> visited;
    visited.insert(vkey(root_signal, requested_time));
    std::set<std::string> visited_times;

    while (!queue.empty()) {
        QueueItem current = queue.front();
        queue.erase(queue.begin());  // BFS-style pop front

        // A temporal step is one distinct active-trace time point.  Count the
        // query time as the first step and stop before processing a new time
        // once the public max_time_steps budget has been exhausted.
        if (visited_times.find(current.time) == visited_times.end()) {
            if (static_cast<int>(visited_times.size()) >= limits.max_time_steps) {
                result.truncated = true;
                result.termination = "limit";
                result.termination_detail = "max_time_steps";
                result.limitations.push_back("trace truncated by limits.max_time_steps");
                break;
            }
            visited_times.insert(current.time);
        }

        // Check depth limit
        if (current.depth > limits.max_depth) {
            result.truncated = true;
            result.termination = "limit";
            result.termination_detail = "max_depth";
            result.limitations.push_back("trace truncated by limits.max_depth at signal " + current.signal);
            break;
        }

        // Check node count limit
        if (result.node_count >= limits.max_nodes) {
            result.truncated = true;
            result.termination = "limit";
            result.termination_detail = "max_nodes";
            result.limitations.push_back("trace truncated by limits.max_nodes");
            break;
        }

        // Get handle for the signal (RAII via NpiHandleGuard).
        NpiHandleGuard signal_hdl(npi_handle_by_name(current.signal.c_str(), nullptr));
        if (!signal_hdl) {
            result.limitations.push_back("SIGNAL_NOT_FOUND: " + current.signal);
            if (result.node_count == 0) {
                result.termination = "unresolved";
                result.termination_detail = current.signal.find('[') != std::string::npos
                    ? "dynamic_index_boundary" : "signal_missing";
                break;
            }
            continue;
        }

        int signal_type = npi_get(npiType, signal_hdl.get());
        PortConnectionInfo input_port = resolve_input_port_connection(current.signal);

        ActiveTraceResolveResult resolved = resolve_active_driver_precise(
            fsdb, signal_hdl.get(), current.signal, current.time, options);
        actTrcRes_t active = resolved.active;
        int active_count = resolved.count;
        for (const auto& limitation : resolved.limitations) {
            result.limitations.push_back(limitation);
        }
        if (current.depth == 0) {
            result.evidence_source = resolved.evidence_source;
            result.static_candidate_count = resolved.static_candidate_count;
            result.active_check_count = resolved.active_check_count;
        }
        if (resolved.ambiguous) {
            result.termination = "ambiguous";
            result.termination_detail = "multiple_active_candidates";
            break;
        }

        if (active_count == 0) {
            std::string active_time = active.activeTime.empty() ? current.time : active.activeTime;
            // No active driver found.  Check if this is an alias-type signal
            // that can be resolved through the design hierarchy.
            std::string alias_kind_str = statement_kind(signal_type);
            if (is_alias_kind(alias_kind_str)) {
                std::vector<AliasCandidate> candidates =
                    resolve_alias_candidates(signal_hdl.get(), current.signal);
                if (candidates.size() == 1 && candidates[0].confidence == "high") {
                    std::string target = candidates[0].to;
                    if (!target.empty() && visited.find(vkey(target, current.time)) == visited.end() &&
                        current.depth < limits.max_depth) {
                        visited.insert(vkey(target, current.time));
                        // Create an alias node
                        std::string nid = "n" + std::to_string(result.node_count);
                        TraceNode alias_node;
                        alias_node.id = nid;
                        alias_node.role = "alias";
                        alias_node.kind = alias_kind_str;
                        alias_node.signal = current.signal;
                        alias_node.active_time = current.time;
                        alias_node.next_signal = target;
                        alias_node.alias_kind = candidates[0].alias_kind.empty() ?
                            "none" : candidates[0].alias_kind;
                        result.nodes.push_back(alias_node);
                        result.selected_path.push_back(nid);
                        result.node_count++;
                        queue.push_back({
                            target,
                            current.time,
                            current.depth + 1,
                            nid,
                            "alias",
                            candidates[0].confidence.empty() ? "medium" : candidates[0].confidence
                        });
                        continue;
                    }
                } else if (candidates.size() > 1) {
                    result.termination = "ambiguous";
                    for (const auto& c : candidates) {
                        result.alias_candidates.push_back(c);
                    }
                                        continue;
                }
            }

            if (input_port.is_input_like && !input_port.target_signal.empty()) {
                std::string target = input_port.target_signal;
                if (visited.find(vkey(target, active_time)) == visited.end() &&
                    current.depth < limits.max_depth) {
                    visited.insert(vkey(target, active_time));
                    std::string nid = "n" + std::to_string(result.node_count);
                    TraceNode port_node;
                    port_node.id = nid;
                    port_node.role = "alias";
                    port_node.kind = "port_boundary";
                    port_node.signal = current.signal;
                    port_node.active_time = active_time;
                    port_node.next_signal = target;
                    port_node.alias_kind = "module_port";
                    result.nodes.push_back(port_node);
                    result.selected_path.push_back(nid);
                    result.node_count++;
                    if (!current.parent_id.empty()) {
                        result.edges.push_back({
                            current.parent_id,
                            nid,
                            current.parent_relation.empty() ? "rhs_dependency" : current.parent_relation,
                            current.parent_confidence.empty() ? "high" : current.parent_confidence
                        });
                    }
                    queue.push_back({
                        target,
                        active_time,
                        current.depth + 1,
                        nid,
                        "port_connection",
                        "high"
                    });
                    continue;
                }
                if (visited.find(vkey(target, active_time)) != visited.end()) {
                    result.limitations.push_back("cycle detected: " + current.signal + " → " + target);
                } else {
                    result.truncated = true;
                    result.termination = "limit";
                    result.limitations.push_back("trace truncated by limits.max_depth at signal " + current.signal);
                    break;
                }
            }

            const bool is_external_input_boundary =
                input_port.is_input_like && input_port.target_signal.empty();
            if (!is_external_input_boundary) {
                result.limitations.push_back("active trace returned no driver evidence for " + current.signal);
            }

            std::string nid = "n" + std::to_string(result.node_count);
            TraceNode terminal_node;
            terminal_node.id = nid;
            terminal_node.role = "root";
            terminal_node.kind = is_external_input_boundary ? "primary_input" : "unknown";
            terminal_node.signal = current.signal;
            terminal_node.active_time = active_time;
            terminal_node.alias_kind = "none";
            result.nodes.push_back(terminal_node);
            result.selected_path.push_back(nid);
            result.node_count++;
            if (!current.parent_id.empty()) {
                result.edges.push_back({
                    current.parent_id,
                    nid,
                    current.parent_relation.empty() ? "rhs_dependency" : current.parent_relation,
                    current.parent_confidence.empty() ? "high" : current.parent_confidence
                });
            }
            if (is_external_input_boundary && result.root_driver.is_null()) {
                result.root_driver = {{"kind", "primary_input"}, {"file", ""}, {"line", 0}};
            }
            if (is_external_input_boundary && result.termination == "unresolved") {
                result.termination = "primary_input";
            } else if (!is_external_input_boundary) {
                result.termination = "unresolved";
            }
            continue;
        }

        
        // Process statements from active trace
        Json driver_item = nullptr;

        for (const auto& stmt : active.drvLoadStmtVec) {
            int type = stmt.useHdl ? npi_get(npiType, stmt.useHdl) : 0;
            std::string kind = statement_kind(type);

            std::string node_id = "n" + std::to_string(result.node_count);
            if (result.node_count >= limits.max_nodes) {
                result.truncated = true;
                result.termination = "limit";
                result.limitations.push_back("trace truncated by limits.max_nodes");
                break;
            }

            // Get value at active time for this node
            Json node_value = nullptr;
            if (!active.activeTime.empty()) {
                std::vector<std::string> val_signals = {current.signal};
                Json val_map = value_map(fsdb, val_signals, active.activeTime, result.limitations);
                if (val_map.contains(current.signal)) node_value = val_map[current.signal];
            }

            // Determine role
            std::string role;
            if (kind == "assignment" || kind == "force") {
                role = kind;
            } else if (is_control_kind(kind)) {
                role = "control";
            } else if (is_alias_kind(kind)) {
                role = "alias";
            } else if (kind == "event_control") {
                role = "event";
            } else {
                role = "other";
            }

            TraceNode node = trace_node_from_statement(
                stmt, node_id, role, active.activeTime, current.signal, node_value);
            if ((kind == "assignment" || kind == "port_boundary") &&
                input_port.is_input_like &&
                !input_port.target_signal.empty()) {
                node.next_signal = input_port.target_signal;
                if (std::find(node.signals.begin(), node.signals.end(),
                              input_port.target_signal) == node.signals.end()) {
                    node.signals.push_back(input_port.target_signal);
                }
            }
            result.nodes.push_back(node);
            result.selected_path.push_back(node_id);
            result.node_count++;

            // Add edge from parent if exists
            if (!current.parent_id.empty()) {
                result.edges.push_back({
                    current.parent_id,
                    node_id,
                    current.parent_relation.empty() ? "rhs_dependency" : current.parent_relation,
                    current.parent_confidence.empty() ? "high" : current.parent_confidence
                });
            }

            // Classify and decide next steps
            if (kind == "force") {
                // Force is always a terminal
                driver_item = to_json(node);
                result.termination = "force";
                result.root_driver = {
                    {"kind", "force"},
                    {"file", node.file},
                    {"line", node.line}
                };
            } else if (kind == "assignment") {
                if (driver_item.is_null()) driver_item = to_json(node);

                std::string next = node.next_signal;
                if (!next.empty()) {
                    // Pass-through: check if we should recurse.
                    // Stop at primary inputs (module boundary).
                    bool next_is_input = false;
                    PortConnectionInfo next_port = resolve_input_port_connection(next);
                    next_is_input = next_port.is_input_like;
                    npiHandle next_hdl = npi_handle_by_name(next.c_str(), nullptr);
                    if (next_hdl) {
                        next_is_input = next_is_input || is_primary_input(next_hdl);
                        npi_release_handle(next_hdl);
                    }
                    if (next_is_input) {
                        // Primary input — this assignment is the root driver
                        result.termination = "assignment";
                        result.root_driver = {
                            {"kind", "assignment"},
                            {"file", node.file},
                            {"line", node.line}
                        };
                    } else if (visited.find(vkey(next, active.activeTime)) == visited.end() && current.depth < limits.max_depth) {
                        // Pass-through: update root_driver to this assignment.
                        // If recursion stops at a primary input, this is the
                        // correct root.  If recursion finds a deeper assignment,
                        // it will be overwritten by the next pass-through hop.
                        result.root_driver = {
                            {"kind", "assignment"},
                            {"file", node.file},
                            {"line", node.line}
                        };
                        visited.insert(vkey(next, active.activeTime));
                        queue.push_back({
                            next,
                            active.activeTime,
                            current.depth + 1,
                            node_id,
                            node.next_relation.empty() ? "rhs_dependency" : node.next_relation,
                            node.next_confidence.empty() ? "high" : node.next_confidence
                        });
                    } else if (visited.find(vkey(next, active.activeTime)) != visited.end()) {
                        result.limitations.push_back("cycle detected: " + current.signal + " → " + next);
                        result.termination = result.termination == "unresolved" ? "assignment" : result.termination;
                        result.root_driver = {
                            {"kind", "assignment"},
                            {"file", node.file},
                            {"line", node.line}
                        };
                    } else {
                        // Depth limited
                        result.truncated = true;
                        result.termination = "limit";
                        result.root_driver = {
                            {"kind", "assignment"},
                            {"file", node.file},
                            {"line", node.line}
                        };
                    }
                } else {
                    // Root assignment (multi-signal RHS, expression, or constant)
                    result.termination = "assignment";
                    result.root_driver = {
                        {"kind", "assignment"},
                        {"file", node.file},
                        {"line", node.line}
                    };
                }
            } else if (is_alias_kind(kind)) {
                // For port_boundary: if the port is an input, stop here.
                // This is a module primary input; the root cause is the
                // assignment that led us here, not the port itself.
                if (kind == "port_boundary" && stmt.useHdl) {
                    int pdir = npi_get(npiDirection, stmt.useHdl);
                    if (is_input_like_direction(pdir) &&
                        input_port.is_input_like &&
                        !input_port.target_signal.empty()) {
                        std::string target = input_port.target_signal;
                        std::string next_time = active.activeTime.empty() ? current.time : active.activeTime;
                        if (visited.find(vkey(target, next_time)) == visited.end() &&
                            current.depth < limits.max_depth) {
                            visited.insert(vkey(target, next_time));
                            queue.push_back({
                                target,
                                next_time,
                                current.depth + 1,
                                node_id,
                                "port_connection",
                                "high"
                            });
                            continue;
                        }
                    }
                    if (pdir == npiInput) {
                        if (input_port.is_input_like &&
                            input_port.target_signal.empty() &&
                            current.parent_id.empty() &&
                            result.root_driver.is_null()) {
                            result.termination = "primary_input";
                            result.root_driver = {{"kind", "primary_input"}, {"file", ""}, {"line", 0}};
                        } else if (result.termination == "unresolved") {
                            result.termination = "assignment";
                        }
                        // Don't override root_driver if already set by a
                        // parent assignment that led to this boundary.
                        break;  // stop processing statements for this signal
                    }
                }

                // Try to resolve alias
                npiHandle stmt_hdl = stmt.useHdl;
                if (stmt_hdl) {
                    std::vector<AliasCandidate> candidates =
                        resolve_alias_candidates(stmt_hdl, current.signal);
                    if (candidates.size() == 1 && candidates[0].confidence == "high") {
                        std::string target = candidates[0].to;

                        if (visited.find(vkey(target, active.activeTime)) == visited.end() && current.depth < limits.max_depth) {
                            visited.insert(vkey(target, active.activeTime));
                            queue.push_back({
                                target,
                                active.activeTime,
                                current.depth + 1,
                                node_id,
                                "alias",
                                candidates[0].confidence.empty() ? "medium" : candidates[0].confidence
                            });
                        }
                    } else if (candidates.size() > 1) {
                        result.termination = "ambiguous";
                        for (const auto& c : candidates) {
                            result.alias_candidates.push_back(c);
                        }
                    } else {
                        // No candidates — mark unresolved
                        if (result.termination == "unresolved") {
                            result.termination = "unresolved";
                            result.limitations.push_back(
                                "could not resolve alias for " + current.signal +
                                " (kind: " + kind + ")");
                        }
                    }
                }
            } else if (is_control_kind(kind)) {
                result.controls.push_back(node);
            } else if (kind == "event_control") {
                result.events.push_back(node);
            }
        }

        // Set current_driver from the first assignment/force found at root level
        if (current.depth == 0 && !driver_item.is_null() && result.current_driver.is_null()) {
            result.current_driver = driver_item;
        }

        // If control_only at root
        if (current.depth == 0 && driver_item.is_null() && !result.controls.empty()) {
            result.termination = "control_only";
            result.limitations.push_back(
                "control context confirmed but NPI active evidence did not confirm specific assignment");
        }
    }

    // Post-process: keep only complete edges between materialized nodes.
    std::vector<TraceEdge> clean_edges;
    std::set<std::string> node_ids;
    for (const auto& n : result.nodes) {
        if (!n.id.empty()) node_ids.insert(n.id);
    }
    for (const auto& e : result.edges) {
        if (node_ids.count(e.from) > 0 && node_ids.count(e.to) > 0) {
            clean_edges.push_back(e);
        }
    }
    result.edges = clean_edges;

    return result;
}

} // namespace

nlohmann::ordered_json build_active_driver_payload(const Json& request,
                                                   const std::string& daidir,
                                                   const std::string& fsdb_path,
                                                   npiFsdbFileHandle fsdb,
                                                   bool include_trace) {
    (void)daidir;
    (void)fsdb_path;
    const std::string action = "trace.active_driver";
    const Json args = request.value("args", Json::object());
    const std::string signal_name = args.value("signal", std::string());
    const std::string requested_time = args.value("time", std::string());

    if (signal_name.empty() || requested_time.empty()) {
        return make_error(request, action, "MISSING_FIELD",
                          "args.signal and args.time are required");
    }
    if (!fsdb) {
        return make_error(request, action, "FSDB_NOT_OPEN", "FSDB handle is null");
    }

    ActiveTraceOptions request_options =
        parse_options(request, args, include_trace);
    NpiHandleGuard signal(npi_handle_by_name(signal_name.c_str(), nullptr));
    if (!signal) {
        return nlohmann::ordered_json{{"error","SIGNAL_NOT_FOUND"}};
    }
    trcOption_t options = trcOptionDefault;
    options.reportControl = true;

    TraceBuildResult trace_result = build_active_trace(
        fsdb, signal_name, requested_time, options,
        request_options.limits);

    std::vector<std::string> limitations = trace_result.limitations;
    std::vector<std::string> value_signals;
    value_signals.push_back(signal_name);
    for (const auto& node : trace_result.nodes) {
        if (!node.next_signal.empty()) {
            if (std::find(value_signals.begin(), value_signals.end(), node.next_signal) == value_signals.end())
                value_signals.push_back(node.next_signal);
        }
    }

    const std::string first_active_time = trace_result.nodes.empty() ? "" :
        trace_result.nodes.front().active_time;
    Json active_values = value_map(fsdb, value_signals,
        first_active_time.empty() ? requested_time : first_active_time, limitations);
    Json requested_values = value_map(fsdb, value_signals, requested_time, limitations);

    std::string driver_status = trace_result.termination;
    if (driver_status == "assignment" || driver_status == "force" || driver_status == "primary_input")
        driver_status = "resolved";
    else if (driver_status == "limit" && !trace_result.root_driver.is_null())
        driver_status = "resolved";

    nlohmann::ordered_json resp;
    resp["summary"] = {
        {"signal", signal_name},
        {"time", requested_time},
        {"requested_time", requested_time},
        {"active_time", first_active_time},
        {"time_semantics", {
            {"requested_time", "the user query time"},
            {"active_time", "the time attached to the active-driver evidence"}
        }},
        {"driver_status", driver_status},
        {"termination", trace_result.termination},
        {"termination_detail", trace_result.termination_detail.empty()
            ? nlohmann::ordered_json(trace_result.termination)
            : nlohmann::ordered_json(trace_result.termination_detail)},
        {"evidence_source", trace_result.evidence_source.empty()
            ? nlohmann::ordered_json(nullptr) : nlohmann::ordered_json(trace_result.evidence_source)},
        {"static_candidate_count", trace_result.static_candidate_count},
        {"active_check_count", trace_result.active_check_count},
        {"evidence_scope", "static_hdl_and_fsdb_active_driver"},
        {"evidence_status", trace_result.active_check_count > 0 ? "active_driver_checked" : "static_or_unavailable"},
        {"trace_node_count", trace_result.node_count},
        {"scan_complete", !trace_result.truncated},
        {"analysis_complete", !trace_result.truncated},
        {"response_truncated", false},
        {"total_count", trace_result.nodes.size()},
        {"returned_count", trace_result.nodes.size()},
        {"truncation_scopes", trace_result.truncated
            ? nlohmann::ordered_json::array({"analysis_trace"})
            : nlohmann::ordered_json::array()}
    };
    resp["driver"] = trace_result.current_driver.is_null()
        ? nlohmann::ordered_json(nullptr) : trace_result.current_driver;
    resp["root_driver"] = trace_result.root_driver.is_null()
        ? nlohmann::ordered_json(nullptr) : trace_result.root_driver;
    resp["controls"] = nodes_to_json(trace_result.controls);
    resp["events"] = nodes_to_json(trace_result.events);
    resp["values"] = {{"requested", requested_values}, {"active", active_values}};
    resp["limitations"] = strings_to_json(limitations);

    if (!trace_result.alias_candidates.empty())
        resp["alias_candidates"] = alias_candidates_to_json(trace_result.alias_candidates);

    if (request_options.include_trace) {
        resp["trace"] = {{"nodes", nodes_to_json(trace_result.nodes)},
                         {"edges", edges_to_json(trace_result.edges)},
                         {"selected_path", strings_to_json(trace_result.selected_path)},
                         {"termination", trace_result.termination},
                         {"termination_detail", trace_result.termination_detail.empty()
                             ? nlohmann::ordered_json(trace_result.termination)
                             : nlohmann::ordered_json(trace_result.termination_detail)}};
    }
    append_common_blocks_to_payload(resp);
    return resp;
}

} // namespace xdebug
