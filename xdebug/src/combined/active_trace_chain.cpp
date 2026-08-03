#include "combined/active_trace_chain.h"
#include "combined/active_trace_common.h"
#include "api/response.h"
#include "core/ai/common_blocks.h"
#include "core/npi/time_contract.h"
#include "runtime/work_dir.h"
#include "waveform/common/clock_sampling.h"
#include "waveform/server/fsdb_value_reader.h"

#include <algorithm>
#include <set>

namespace xdebug {

namespace {

// ═══════════════════════════════════════════════════════════════════
// data types
// ═══════════════════════════════════════════════════════════════════

struct ValueEvidence {
    std::string status;
    std::string value;
    std::string value_time;
    bool known = false;
};

struct RhsSample {
    std::string signal;
    ValueEvidence before;
    ValueEvidence after;
    bool has_changed = false;
    bool changed = false;
};

struct StatementEvidence {
    std::string kind, driver, file;
    int line = 0;
    int rhs_signal_count = 0;
    int returned_rhs_signal_count = 0;
    bool complete = true;
    std::vector<RhsSample> rhs_samples;
};

struct AmbiguityEvidence {
    std::string kind, signal, active_time;
    int hop_index = 0;
    int statement_count = 0;
    int rhs_signal_count = 0;
    int returned_rhs_signal_count = 0;
    int omitted_rhs_signal_count = 0;
    bool complete = true;
    std::string truncation_scope;
    std::vector<StatementEvidence> statements;
};

struct ChainNode {
    int index = 0;
    std::string signal, time, active_time;
    std::string value_str;
    bool value_known = false;
    std::string driver_kind, driver, file;
    int line = 0;
    std::string hop;
    std::string next;
};

struct ChainStats {
    int calls = 0;
    int edgecheck_direct = 0;
    int temporal_boundaries = 0;
};

struct DepthFrontier {
    std::string signal;
    std::string time;
    std::string value;
    int stopped_after_depth = 0;
};

struct ChainResult {
    std::vector<ChainNode> chain;
    AmbiguityEvidence ambiguity_evidence;
    bool has_ambiguity_evidence = false;
    std::vector<std::string> limitations;
    std::string termination = "unresolved";
    std::string termination_detail;
    std::string evidence_source;
    int static_candidate_count = 0;
    int active_check_count = 0;
    ChainStats stats;
    bool truncated = false;
    DepthFrontier depth_frontier;
    bool has_depth_frontier = false;
};

void stop_at_depth_frontier(ChainResult& result,
                            npiFsdbFileHandle fsdb,
                            const std::string& signal,
                            const std::string& time,
                            npiFsdbTime tick,
                            int max_depth) {
    result.truncated = true;
    result.termination = "limit";
    result.termination_detail = "max_depth";
    result.depth_frontier.signal = signal;
    result.depth_frontier.time = time;
    result.depth_frontier.value = format_value(fsdb_value_at(fsdb, signal, tick));
    result.depth_frontier.stopped_after_depth = max_depth;
    result.has_depth_frontier = true;
    result.limitations.push_back(
        "trace truncated by limits.max_depth; continue from " + signal + " at " + time);
}

bool is_signal_like_rhs_type(int type) {
    return type == npiNet || type == npiNetBit ||
           type == npiReg || type == npiRegBit ||
           type == npiBitVar || type == npiPartSelect ||
           type == npiBitSelect || type == npiVarSelect ||
           type == npiNetSelect || type == 608 || type == 697;
}

std::string direct_rhs_signal_name(const drvLoadStmt_s& statement) {
    if (!statement.useHdl) return "";
    NpiHandleGuard rhs(npi_handle(npiRhs, statement.useHdl));
    if (!rhs || !is_signal_like_rhs_type(npi_get(npiType, rhs.get()))) return "";
    return npi_string(npiFullName, rhs.get());
}

std::vector<std::string> rhs_signal_names(const drvLoadStmt_s& statement,
                                          const std::string& current_signal) {
    std::vector<std::string> names;
    for (const auto& handle : statement.sigHdlVec) {
        std::string name = npi_string(npiFullName, handle);
        if (name.empty() || name == current_signal) continue;
        if (std::find(names.begin(), names.end(), name) == names.end()) names.push_back(name);
    }
    std::sort(names.begin(), names.end());
    return names;
}

ValueEvidence value_evidence(const xdebug_waveform::ClockPointCell& cell,
                             npiFsdbFileHandle fsdb,
                             const std::string& active_time,
                             bool is_before,
                             int width_hint) {
    ValueEvidence evidence;
    evidence.status = cell.status.empty() ? "missing_value" : cell.status;
    if (evidence.status != "ok") return evidence;
    const xdebug_core::LogicValue value =
        xdebug_core::logic_value_from_fsdb_raw(
            cell.raw_value, 'b', width_hint);
    evidence.value = xdebug_core::render_logic_value(value);
    evidence.known = value.known;
    evidence.value_time = is_before && cell.has_value_time
        ? xdebug_core::format_time(fsdb, cell.value_time) : active_time;
    return evidence;
}

RhsSample sample_rhs(npiFsdbFileHandle fsdb,
                     const std::string& signal,
                     npiFsdbTime active_tick,
                     const std::string& active_time) {
    RhsSample sample;
    sample.signal = signal;
    xdebug_waveform::ClockPointCell before_cell, after_cell;
    xdebug_waveform::ClockValueReader::read_before(
        fsdb, nullptr, signal, active_tick, npiFsdbBinStrVal, '\0', before_cell);
    xdebug_waveform::ClockValueReader::read_current(
        fsdb, nullptr, signal, active_tick, npiFsdbBinStrVal, '\0', after_cell);
    const xdebug_waveform::FsdbSignalWidth width =
        xdebug_waveform::fsdb_signal_width(fsdb, signal);
    const int width_hint = width.reliable ? width.width : 0;
    sample.before =
        value_evidence(before_cell, fsdb, active_time, true, width_hint);
    sample.after =
        value_evidence(after_cell, fsdb, active_time, false, width_hint);
    sample.has_changed = sample.before.status == "ok" && sample.after.status == "ok";
    sample.changed = sample.has_changed && sample.before.value != sample.after.value;
    return sample;
}

AmbiguityEvidence collect_ambiguity_evidence(
    npiFsdbFileHandle fsdb,
    const std::string& kind,
    const std::string& signal,
    const std::string& active_time,
    npiFsdbTime active_tick,
    int hop_index,
    const std::vector<drvLoadStmt_s>& statements,
    int max_trace_signals) {
    AmbiguityEvidence evidence;
    evidence.kind = kind;
    evidence.signal = signal;
    evidence.active_time = active_time;
    evidence.hop_index = hop_index;
    int remaining = max_trace_signals;
    for (const auto& statement : statements) {
        if (!is_assignment_like_statement(statement)) continue;
        StatementEvidence group;
        group.kind = statement_kind(statement.useHdl ? npi_get(npiType, statement.useHdl) : 0);
        group.driver = driver_text(statement.useHdl, group.kind);
        group.file = npi_string(npiFile, statement.useHdl);
        group.line = statement.useHdl ? npi_get(npiLineNo, statement.useHdl) : 0;
        std::vector<std::string> names = rhs_signal_names(statement, signal);
        group.rhs_signal_count = static_cast<int>(names.size());
        evidence.rhs_signal_count += group.rhs_signal_count;
        for (const auto& name : names) {
            if (remaining <= 0) break;
            group.rhs_samples.push_back(sample_rhs(fsdb, name, active_tick, active_time));
            --remaining;
        }
        group.returned_rhs_signal_count = static_cast<int>(group.rhs_samples.size());
        group.complete = group.returned_rhs_signal_count == group.rhs_signal_count;
        evidence.returned_rhs_signal_count += group.returned_rhs_signal_count;
        evidence.statements.push_back(group);
    }
    evidence.statement_count = static_cast<int>(evidence.statements.size());
    evidence.omitted_rhs_signal_count =
        evidence.rhs_signal_count - evidence.returned_rhs_signal_count;
    evidence.complete = evidence.omitted_rhs_signal_count == 0;
    if (!evidence.complete) evidence.truncation_scope = "ambiguity_rhs_samples";
    return evidence;
}

// ═══════════════════════════════════════════════════════════════════
// build_chain
// ═══════════════════════════════════════════════════════════════════

ChainResult build_chain(npiFsdbFileHandle fsdb,
                         const std::string& signal,
                         const std::string& time,
                         int max_depth, int max_nodes,
                         int max_trace_signals) {
    ChainResult result;
    auto vkey = [](const std::string& sig, const std::string& t) { return sig + "\x1f" + t; };
    std::set<std::string> visited;
    visited.insert(vkey(signal, time));

    std::string cur_sig = signal, cur_time = time;
    int depth = 0;

    trcOption_t opt = trcOptionDefault;
    opt.reportControl = true;

    while (static_cast<int>(result.chain.size()) < max_nodes) {
        // ── trace ──
        NpiHandleGuard hdl(npi_handle_by_name(cur_sig.c_str(), nullptr));
        if (!hdl) {
            result.termination = "signal_not_found";
            result.termination_detail = cur_sig.find('[') != std::string::npos
                ? "dynamic_index_boundary" : "signal_missing";
            result.limitations.push_back("signal not found: " + cur_sig);
            break;
        }
        PortConnectionInfo input_port = resolve_input_port_connection(cur_sig);

        result.stats.calls++;
        ActiveTraceResolveResult resolved = resolve_active_driver_precise(
            fsdb, hdl.get(), cur_sig, cur_time, opt);
        actTrcRes_t active = resolved.active;
        int rc = resolved.count;
        for (const auto& limitation : resolved.limitations) {
            result.limitations.push_back(limitation);
        }
        if (depth == 0) {
            result.evidence_source = resolved.evidence_source;
            result.static_candidate_count = resolved.static_candidate_count;
            result.active_check_count = resolved.active_check_count;
        }
        bool temporal = (active.activeTime != cur_time);
        if (temporal) result.stats.temporal_boundaries++;

        std::string active_time = active.activeTime.empty() ? cur_time : active.activeTime;
        npiFsdbTime active_tick = 0;
        std::string active_time_error;
        xdebug_core::TimeParseOptions active_time_options;
        active_time_options.default_unit = "ns";
        if (!xdebug_core::parse_time(fsdb, active_time, active_time_options, active_tick, active_time_error)) {
            result.termination = "unresolved";
            result.limitations.push_back("could not convert active time " + active_time);
            break;
        }

        if (resolved.ambiguous) {
            result.termination = "ambiguous";
            result.termination_detail = "multiple_active_candidates";
            result.ambiguity_evidence = collect_ambiguity_evidence(
                fsdb, result.termination_detail, cur_sig, active_time, active_tick,
                static_cast<int>(result.chain.size()), active.drvLoadStmtVec,
                max_trace_signals);
            result.has_ambiguity_evidence = true;
            if (!result.ambiguity_evidence.complete) {
                result.truncated = true;
                result.limitations.push_back(
                    "ambiguity RHS samples truncated by limits.max_trace_signals");
            }
            break;
        }

        if (rc == 0) {
            std::string raw_val = fsdb_value_at(fsdb, cur_sig, active_tick);
            ChainNode node;
            node.index = static_cast<int>(result.chain.size());
            node.signal = cur_sig;
            node.time = cur_time;
            node.active_time = active_time;
            node.value_str = format_value(raw_val);
            node.value_known = raw_val.find_first_of("xXzZ") == std::string::npos;
            node.driver_kind = "unresolved";
            node.driver = "(no driver)";

            if (input_port.is_input_like && !input_port.target_signal.empty()) {
                node.hop = temporal ? "⏱" : "→";
                node.next = input_port.target_signal;
                result.chain.push_back(node);
                if (visited.count(vkey(input_port.target_signal, active_time))) {
                    result.termination = "loop_detected";
                    result.limitations.push_back("loop: " + cur_sig + " -> " + input_port.target_signal);
                    break;
                }
                visited.insert(vkey(input_port.target_signal, active_time));
                if (depth >= max_depth) {
                    stop_at_depth_frontier(
                        result, fsdb, input_port.target_signal, active_time, active_tick,
                        max_depth);
                    break;
                }
                cur_sig = input_port.target_signal;
                cur_time = active_time;
                depth++;
                continue;
            }

            node.hop = "■";
            result.termination = input_port.is_input_like ? "primary_input" : "unresolved";
            if (!input_port.is_input_like) {
                result.limitations.push_back("active trace returned no driver evidence for " + cur_sig);
            }
            result.chain.push_back(node);
            break;
        }

        // ── classify ──
        std::string best_kind, best_driver, best_file;
        int best_line = 0;
        const drvLoadStmt_s* best_statement = nullptr;

        for (auto& stmt : active.drvLoadStmtVec) {
            int type = stmt.useHdl ? npi_get(npiType, stmt.useHdl) : 0;
            std::string kind = statement_kind(type);
            if (best_kind.empty() || kind == "assignment" || kind == "force") {
                best_kind = kind;
                best_driver = driver_text(stmt.useHdl, kind);
                best_file = npi_string(npiFile, stmt.useHdl);
                best_line = stmt.useHdl ? npi_get(npiLineNo, stmt.useHdl) : 0;
                best_statement = &stmt;
            }
        }

        std::string raw_val = fsdb_value_at(fsdb, cur_sig, active_tick);
        std::string val_disp = format_value(raw_val);
        bool known = raw_val.find_first_of("xXzZ") == std::string::npos;

        // ── record node ──
        ChainNode node;
        node.index = static_cast<int>(result.chain.size());
        node.signal = cur_sig; node.time = cur_time;
        node.active_time = active_time;
        node.value_str = val_disp; node.value_known = known;
        node.driver_kind = best_kind.empty() ? "unresolved" : best_kind;
        node.driver = best_driver.empty() ? "(no driver)" : best_driver;
        node.file = best_file; node.line = best_line;

        std::string next_signal;
        if (input_port.is_input_like && !input_port.target_signal.empty()) {
            next_signal = input_port.target_signal;
        } else if (best_kind == "force") {
            result.termination = "force";
            node.hop = "■";
            result.chain.push_back(node);
            break;
        } else if (best_kind == "assignment" && best_statement) {
            next_signal = direct_rhs_signal_name(*best_statement);
            if (next_signal == cur_sig) next_signal.clear();
            if (next_signal.empty()) {
                std::vector<std::string> rhs_signals =
                    rhs_signal_names(*best_statement, cur_sig);
                if (rhs_signals.size() > 1) {
                    result.termination = "ambiguous";
                    result.termination_detail = "multiple_rhs_sources";
                    std::vector<drvLoadStmt_s> statements{*best_statement};
                    result.ambiguity_evidence = collect_ambiguity_evidence(
                        fsdb, result.termination_detail, cur_sig, active_time,
                        active_tick, node.index, statements, max_trace_signals);
                    result.has_ambiguity_evidence = true;
                    if (!result.ambiguity_evidence.complete) {
                        result.truncated = true;
                        result.limitations.push_back(
                            "ambiguity RHS samples truncated by limits.max_trace_signals");
                    }
                } else {
                    result.termination = "assignment";
                    result.termination_detail = rhs_signals.empty()
                        ? "constant_or_no_rhs_signal" : "non_direct_rhs_expression";
                }
                node.hop = "■";
                result.chain.push_back(node);
                break;
            }
            result.stats.edgecheck_direct++;
        } else {
            result.termination = input_port.is_input_like
                ? "primary_input" : (best_kind.empty() ? "unresolved" : "control_only");
            node.hop = "■";
            result.chain.push_back(node);
            break;
        }

        node.hop = temporal ? "⏱" : "→";
        node.next = next_signal;
        result.chain.push_back(node);

        if (visited.count(vkey(next_signal, active_time))) {
            result.termination = "loop_detected";
            result.limitations.push_back("loop: " + cur_sig + " -> " + next_signal);
            break;
        }
        visited.insert(vkey(next_signal, active_time));
        if (depth >= max_depth) {
            stop_at_depth_frontier(
                result, fsdb, next_signal, active_time, active_tick, max_depth);
            break;
        }
        cur_sig = next_signal;
        cur_time = active_time;
        depth++;
    }

    if (result.termination == "unresolved"
        && static_cast<int>(result.chain.size()) >= max_nodes) {
        result.truncated = true;
        result.termination = "limit";
        result.termination_detail = "max_nodes";
        result.limitations.push_back("trace limit reached");
    }
    return result;
}

// ═══════════════════════════════════════════════════════════════════
// JSON output
// ═══════════════════════════════════════════════════════════════════

Json chain_to_json(const ChainResult& r) {
    Json arr = Json::array();
    for (auto& n : r.chain) {
        Json j;
        j["index"] = n.index; j["signal"] = n.signal;
        j["time"] = n.time; j["active_time"] = n.active_time;
        j["requested_time"] = n.time;
        j["value"] = n.value_str; j["value_known"] = n.value_known;
        j["driver_kind"] = n.driver_kind; j["driver"] = n.driver;
        j["file"] = n.file; j["line"] = n.line;
        j["hop"] = n.hop; j["next"] = n.next;
        arr.push_back(j);
    }
    Json st; st["calls"] = r.stats.calls;
    st["edgecheck_direct"] = r.stats.edgecheck_direct;
    st["temporal_boundaries"] = r.stats.temporal_boundaries;

    Json data; data["chain"] = arr;
    if (r.has_depth_frontier) {
        data["depth_frontiers"] = Json::array({{
            {"chain_id", "c0"},
            {"signal", r.depth_frontier.signal},
            {"time", r.depth_frontier.time},
            {"value", r.depth_frontier.value},
            {"stopped_after_depth", r.depth_frontier.stopped_after_depth}
        }});
    }
    if (r.has_ambiguity_evidence) {
        const auto& evidence = r.ambiguity_evidence;
        Json statements = Json::array();
        for (const auto& statement : evidence.statements) {
            Json samples = Json::array();
            for (const auto& sample : statement.rhs_samples) {
                auto value_json = [](const ValueEvidence& value) {
                    Json out;
                    out["status"] = value.status;
                    out["value"] = value.status == "ok" ? Json(value.value) : Json(nullptr);
                    out["known"] = value.status == "ok" ? Json(value.known) : Json(nullptr);
                    out["value_time"] = value.value_time.empty()
                        ? Json(nullptr) : Json(value.value_time);
                    return out;
                };
                Json item;
                item["signal"] = sample.signal;
                item["before"] = value_json(sample.before);
                item["after"] = value_json(sample.after);
                item["changed"] = sample.has_changed ? Json(sample.changed) : Json(nullptr);
                samples.push_back(item);
            }
            statements.push_back({
                {"kind", statement.kind},
                {"driver", statement.driver},
                {"file", statement.file},
                {"line", statement.line},
                {"rhs_signal_count", statement.rhs_signal_count},
                {"returned_rhs_signal_count", statement.returned_rhs_signal_count},
                {"complete", statement.complete},
                {"rhs_samples", samples}
            });
        }
        data["ambiguity_evidence"] = {
            {"kind", evidence.kind},
            {"signal", evidence.signal},
            {"active_time", evidence.active_time},
            {"hop_index", evidence.hop_index},
            {"statement_count", evidence.statement_count},
            {"rhs_signal_count", evidence.rhs_signal_count},
            {"returned_rhs_signal_count", evidence.returned_rhs_signal_count},
            {"omitted_rhs_signal_count", evidence.omitted_rhs_signal_count},
            {"analysis_complete", evidence.complete},
            {"truncation_scopes", evidence.truncation_scope.empty()
                ? Json::array() : Json::array({evidence.truncation_scope})},
            {"statements", statements}
        };
    }
    data["stats"] = st; data["limitations"] = r.limitations;
    data["evidence_source"] = r.evidence_source.empty() ? Json(nullptr) : Json(r.evidence_source);
    data["static_candidate_count"] = r.static_candidate_count;
    data["active_check_count"] = r.active_check_count;
    data["analysis_complete"] = !r.truncated;
    return data;
}

} // namespace

nlohmann::ordered_json build_active_driver_chain_payload(const Json& request,
                                                         const std::string& daidir,
                                                         const std::string& fsdb_path,
                                                         npiFsdbFileHandle fsdb) {
    (void)daidir;
    (void)fsdb_path;
    Json args = request.value("args", Json::object());
    std::string signal = args.value("signal", "");
    std::string req_time = args.value("time", "");
    if (signal.empty() || req_time.empty())
        return nlohmann::ordered_json{{"error", "MISSING_FIELD"},
            {"message", "requires args.signal and args.time"}};
    if (!fsdb)
        return nlohmann::ordered_json{{"error", "FSDB_NOT_OPEN"},
            {"message", "FSDB handle is null"}};

    Json limits_j = request.value("limits", Json::object());
    int max_depth = std::max(1, limits_j.value("max_depth", 8));
    int max_nodes = std::max(1, limits_j.value("max_nodes", 50));
    int max_trace_signals = std::max(1, limits_j.value("max_trace_signals", 64));

    NpiHandleGuard sig_hdl(npi_handle_by_name(signal.c_str(), nullptr));
    if (!sig_hdl.get())
        return nlohmann::ordered_json{{"error", "SIGNAL_NOT_FOUND"},
            {"message", "signal not found: " + signal}};

    ChainResult result = build_chain(fsdb, signal, req_time,
                                      max_depth, max_nodes, max_trace_signals);

    nlohmann::ordered_json resp;
    resp["summary"] = {
        {"signal", signal},
        {"time", req_time},
        {"requested_time", req_time},
        {"chain_length", static_cast<int>(result.chain.size())},
        {"termination", result.termination},
        {"termination_detail", result.termination_detail.empty()
            ? nlohmann::ordered_json(result.termination)
            : nlohmann::ordered_json(result.termination_detail)},
        {"evidence_source", result.evidence_source.empty()
            ? nlohmann::ordered_json(nullptr) : nlohmann::ordered_json(result.evidence_source)},
        {"static_candidate_count", result.static_candidate_count},
        {"active_check_count", result.active_check_count},
        {"evidence_scope", "static_hdl_and_fsdb_active_driver"},
        {"evidence_status", result.active_check_count > 0 ? "active_driver_checked" : "static_or_unavailable"},
        {"time_semantics", {
            {"requested_time", "the user query time"},
            {"active_time", "per-chain-node time attached to active-driver evidence"}
        }},
        {"scan_complete", !result.truncated},
        {"analysis_complete", !result.truncated},
        {"response_truncated", false},
        {"total_count", result.chain.size()},
        {"returned_count", result.chain.size()},
        {"truncation_scopes", result.truncated
            ? nlohmann::ordered_json::array({"analysis_trace"})
            : nlohmann::ordered_json::array()}
    };
    resp["chain"] = chain_to_json(result);
    if (result.has_depth_frontier) {
        Json continued_limits = limits_j;
        continued_limits["max_depth"] = max_depth;
        Json deeper_limits = limits_j;
        deeper_limits["max_depth"] = max_depth * 2;
        resp["suggested_next_actions"] = Json::array({
            {
                {"action", "trace.active_driver_chain"},
                {"reason", "continue_from_depth_frontier"},
                {"chain_id", "c0"},
                {"args", {{"signal", result.depth_frontier.signal},
                           {"time", result.depth_frontier.time}}},
                {"limits", continued_limits}
            },
            {
                {"action", "trace.active_driver_chain"},
                {"reason", "rerun_from_root_with_higher_depth"},
                {"args", {{"signal", signal}, {"time", req_time}}},
                {"limits", deeper_limits}
            }
        });
    }
    append_common_blocks_to_payload(resp);
    return resp;
}

} // namespace xdebug
