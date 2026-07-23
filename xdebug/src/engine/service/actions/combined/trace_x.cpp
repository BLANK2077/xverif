#include "service/engine_action_handler.h"
#include "service/engine_globals.h"
#include "service/trace_source_path_formatter.h"

#include "combined/active_trace_common.h"
#include "core/npi/time_contract.h"
#include "waveform/server/fsdb_scan_utils.h"
#include "waveform/value/logic_value.h"

#include "npi.h"
#include "npi_fsdb.h"
#include "npi_hdl.h"

#include <algorithm>
#include <map>
#include <memory>
#include <set>
#include <string>
#include <vector>

namespace xdebug_design {
namespace {

using xdebug::ActiveTraceResolveResult;
using xdebug::NpiHandleGuard;
using xdebug::PortConnectionInfo;
using xdebug::driver_text;
using xdebug::npi_string;
using xdebug::resolve_active_driver_precise;
using xdebug::resolve_input_port_connection;
using xdebug::statement_kind;

bool has_x_bit(const std::string& bits) {
    return bits.find_first_of("xX") != std::string::npos;
}

std::string x_mask_from_bits(const std::string& bits) {
    std::string mask;
    mask.reserve(bits.size());
    for (char bit : bits) mask.push_back(bit == 'x' || bit == 'X' ? '1' : '0');
    return "'b" + mask;
}

bool is_control_kind(const std::string& kind) {
    return kind == "if" || kind == "if_else" ||
           kind == "case" || kind == "case_item";
}

bool is_port_kind(const std::string& kind) {
    return kind == "port_boundary" || kind == "modport_port" || kind == "ref_obj";
}

std::string normalized_signal_name(npiHandle handle) {
    if (!handle) return std::string();
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

struct XPoint {
    std::string signal;
    std::string time;
    npiFsdbTime tick = 0;
    xdebug_waveform::LogicValue value;
    bool at_fsdb_start = false;
};

Json point_json(const XPoint& point, const char* time_field) {
    return {
        {"signal", point.signal},
        {time_field, point.time},
        {"value", xdebug_waveform::logic_value_json(point.value)},
        {"x_mask", x_mask_from_bits(point.value.bits)}
    };
}

bool read_point(npiFsdbFileHandle fsdb,
                const std::string& signal,
                npiFsdbTime tick,
                XPoint& point) {
    npiFsdbSigHandle handle = npi_fsdb_sig_by_name(fsdb, signal.c_str(), nullptr);
    if (!handle) return false;
    std::string raw;
    if (!npi_fsdb_sig_hdl_value_at(handle, tick, raw, npiFsdbBinStrVal)) return false;
    point.signal = signal;
    point.tick = tick;
    point.time = xdebug_core::format_time(fsdb, tick);
    point.value = xdebug_waveform::logic_value_from_fsdb_raw(raw, 'b');
    return point.value.valid;
}

bool find_x_onset(npiFsdbFileHandle fsdb,
                  const std::string& signal,
                  npiFsdbTime anchor_tick,
                  XPoint& point) {
    XPoint anchor;
    if (!read_point(fsdb, signal, anchor_tick, anchor) || !anchor.value.has_x) return false;

    npiFsdbSigHandle handle = npi_fsdb_sig_by_name(fsdb, signal.c_str(), nullptr);
    if (!handle) return false;
    xdebug_waveform::SignalChangeCursor cursor(handle, npiFsdbBinStrVal);
    if (!cursor.valid()) {
        point = anchor;
        return true;
    }

    npiFsdbTime onset_tick = anchor_tick;
    npiFsdbTime current_tick = 0;
    std::string current_raw;
    if (cursor.first_at_or_after(anchor_tick, current_tick, current_raw) &&
        current_tick <= anchor_tick && has_x_bit(current_raw)) {
        onset_tick = current_tick;
    }

    bool found_previous = false;
    while (onset_tick > 0) {
        npiFsdbTime previous_tick = 0;
        std::string previous_raw;
        if (!cursor.prev_before(onset_tick, previous_tick, previous_raw)) break;
        found_previous = true;
        if (!has_x_bit(previous_raw)) break;
        if (previous_tick >= onset_tick) break;
        onset_tick = previous_tick;
    }

    if (!read_point(fsdb, signal, onset_tick, point)) point = anchor;
    point.at_fsdb_start = !found_previous;
    return point.value.has_x;
}

struct Dependency {
    std::string signal;
    std::set<std::string> relations;
    std::string file;
    int line = 0;
};

std::string relation_text(const Dependency& dependency) {
    std::string text;
    for (const auto& relation : dependency.relations) {
        if (!text.empty()) text += "+";
        text += relation;
    }
    return text.empty() ? "rhs" : text;
}

void add_dependency(std::map<std::string, Dependency>& dependencies,
                    const std::string& signal,
                    const std::string& relation,
                    const std::string& current_signal,
                    const std::string& file,
                    int line) {
    if (signal.empty() || signal == current_signal) return;
    Dependency& dependency = dependencies[signal];
    dependency.signal = signal;
    dependency.relations.insert(relation);
    if (dependency.file.empty() && !file.empty()) {
        dependency.file = file;
        dependency.line = line;
    }
}

struct DependencyResult {
    std::vector<Dependency> dependencies;
    std::string active_time;
    std::string file;
    int line = 0;
    std::string driver_kind;
    bool force = false;
    bool dynamic_select = false;
    bool external_input = false;
    bool had_driver_evidence = false;
};

DependencyResult collect_dependencies(npiFsdbFileHandle fsdb,
                                      const XPoint& point,
                                      std::vector<std::string>& limitations) {
    DependencyResult result;
    result.active_time = point.time;
    std::map<std::string, Dependency> dependencies;

    NpiHandleGuard signal_handle(npi_handle_by_name(point.signal.c_str(), nullptr));
    PortConnectionInfo input_port = resolve_input_port_connection(point.signal);
    if (input_port.is_input_like && !input_port.target_signal.empty()) {
        add_dependency(dependencies, input_port.target_signal, "port", point.signal, "", 0);
    } else if (input_port.is_input_like) {
        result.external_input = true;
    }

    if (!signal_handle) {
        limitations.push_back("design signal not found while tracing " + point.signal);
    } else {
        trcOption_t options = trcOptionDefault;
        options.reportControl = true;
        ActiveTraceResolveResult resolved = resolve_active_driver_precise(
            fsdb, signal_handle.get(), point.signal, point.time, options);
        for (const auto& limitation : resolved.limitations) limitations.push_back(limitation);
        if (!resolved.active.activeTime.empty()) result.active_time = resolved.active.activeTime;

        bool has_active_assignment = false;
        bool has_active_control = false;
        std::set<npiHandle> active_statement_handles;
        auto collect_statement = [&](const drvLoadStmt_s& statement,
                                     bool active_statement) {
            if (!statement.useHdl) return;
            std::string kind = statement_kind(npi_get(npiType, statement.useHdl));
            std::string file = npi_string(npiFile, statement.useHdl);
            int line = npi_get(npiLineNo, statement.useHdl);
            if (!result.had_driver_evidence || kind == "assignment" || kind == "force") {
                result.file = file;
                result.line = line;
                result.driver_kind = kind;
            }
            result.had_driver_evidence = true;
            if (active_statement && kind == "force") result.force = true;
            if (active_statement && kind == "assignment") has_active_assignment = true;
            if (active_statement && is_control_kind(kind)) has_active_control = true;
            if (kind == "assignment" && driver_text(statement.useHdl, kind).find('[') != std::string::npos) {
                result.dynamic_select = true;
            }

            std::string relation;
            if (is_control_kind(kind)) relation = "control";
            else if (kind == "assignment") relation = "rhs";
            else if (is_port_kind(kind)) relation = "port";
            else return;

            for (const auto& handle : statement.sigHdlVec) {
                add_dependency(dependencies, normalized_signal_name(handle), relation,
                               point.signal, file, line);
            }
        };

        for (const auto& statement : resolved.active.drvLoadStmtVec) {
            if (statement.useHdl) active_statement_handles.insert(statement.useHdl);
            collect_statement(statement, true);
        }

        // Under tmerge an unknown control can evaluate multiple assignment
        // branches while active trace reports only the control context.  In
        // that precise case, complete the dependency set from NPI's static
        // driver candidates and still require the waveform dependency itself
        // to be X before creating a branch.
        if (has_active_control && !has_active_assignment) {
            drvLoadStmtVec_t static_candidates;
            int static_rc = npi_trace_driver_by_hdl2(
                signal_handle.get(), static_candidates, true, nullptr, options);
            if (static_rc > 0) {
                for (const auto& statement : static_candidates) {
                    if (!statement.useHdl || active_statement_handles.count(statement.useHdl)) continue;
                    std::string kind = statement_kind(npi_get(npiType, statement.useHdl));
                    if (kind == "assignment") collect_statement(statement, false);
                }
            }
        }
    }

    for (const auto& entry : dependencies) result.dependencies.push_back(entry.second);
    std::sort(result.dependencies.begin(), result.dependencies.end(),
              [](const Dependency& lhs, const Dependency& rhs) {
                  if (lhs.file != rhs.file) return lhs.file < rhs.file;
                  if (lhs.line != rhs.line) return lhs.line < rhs.line;
                  return lhs.signal < rhs.signal;
              });
    return result;
}

struct ChildDependency {
    Dependency dependency;
    XPoint onset;
    XPoint sample;
};

struct ChainState {
    std::string chain_id;
    std::string status = "pending";
    std::string termination_detail;
    bool complete = true;
    bool finished = false;
    int depth = 0;
    XPoint current;
    std::string relation = "root";
    Json hops = Json::array();
    Json origin = nullptr;
    Json pending_x_dependencies = Json::array();
    Json branch_events = Json::array();
    std::set<std::string> visited;
};

std::string visit_key(const XPoint& point) {
    return point.signal + "\x1f" + point.time;
}

void stop_chain(ChainState& chain,
                const std::string& status,
                const std::string& detail,
                bool complete) {
    chain.status = status;
    chain.termination_detail = detail;
    chain.complete = chain.complete && complete;
    chain.finished = true;
}

Json chain_json(const ChainState& chain) {
    Json out = {
        {"chain_id", chain.chain_id},
        {"status", chain.status},
        {"termination_detail", chain.termination_detail},
        {"complete", chain.complete},
        {"current", point_json(chain.current, "x_onset_time")},
        {"hops", chain.hops}
    };
    if (!chain.origin.is_null()) out["origin"] = chain.origin;
    if (!chain.pending_x_dependencies.empty()) {
        out["pending_x_dependencies"] = chain.pending_x_dependencies;
    }
    if (!chain.branch_events.empty()) out["branch_events"] = chain.branch_events;
    return out;
}

class TraceXHandler : public EngineActionHandler {
public:
    const char* action_name() const override { return "trace.x"; }
    bool needs_design() const override { return true; }
    bool needs_waveform() const override { return true; }

    Json run(const Json& request, EngineActionContext&) const override {
        const Json args = request.value("args", Json::object());
        const std::string signal = args.value("signal", std::string());
        const std::string requested_time = args.value("time", std::string());
        if (signal.empty() || requested_time.empty()) {
            return make_handler_error(
                "MISSING_FIELD", "args.signal and args.time are required",
                {{"invalid_arg", signal.empty() ? "args.signal" : "args.time"}});
        }

        npiFsdbTime requested_tick = 0;
        std::string time_error;
        xdebug_core::TimeParseOptions time_options;
        time_options.default_unit = "ns";
        if (!xdebug_core::parse_time(
                g_fsdb_file, requested_time, time_options, requested_tick, time_error)) {
            return make_handler_error("INVALID_TIME", time_error, {{"invalid_arg", "args.time"}});
        }

        XPoint query_point;
        if (!read_point(g_fsdb_file, signal, requested_tick, query_point)) {
            npiFsdbSigHandle handle = npi_fsdb_sig_by_name(g_fsdb_file, signal.c_str(), nullptr);
            return make_handler_error(
                handle ? "VALUE_NOT_AVAILABLE" : "SIGNAL_NOT_FOUND",
                handle ? "failed to read signal at requested time" : "signal not found: " + signal,
                {{"signal", signal}, {"time", xdebug_core::format_time(g_fsdb_file, requested_tick)}});
        }

        Json query = point_json(query_point, "query_time");
        if (!query_point.value.has_x) {
            return {
                {"summary", {{"signal", signal}, {"query_time", query_point.time},
                              {"termination", "not_x_at_query_time"},
                              {"evidence_status", "proven"}, {"chain_count", 0},
                              {"completed_chain_count", 0}, {"limited_chain_count", 0},
                              {"hop_count", 0}, {"origin_count", 0},
                              {"truncated", false}}},
                {"query", query}, {"chains", Json::array()},
                {"limitations", Json::array()}, {"truncated", false}
            };
        }

        XPoint root;
        if (!find_x_onset(g_fsdb_file, signal, requested_tick, root)) root = query_point;

        Json limits_json = request.value("limits", Json::object());
        const int max_depth = std::max(1, limits_json.value("max_depth", 8));
        const int max_nodes = std::max(1, limits_json.value("max_nodes", 50));
        const int max_time_steps = std::max(1, limits_json.value("max_time_steps", 128));
        const int max_trace_signals = std::max(1, limits_json.value("max_trace_signals", 64));
        const int max_chains = std::max(1, limits_json.value("max_chains", 8));

        std::vector<ChainState> chains;
        ChainState initial;
        initial.chain_id = "c0";
        initial.current = root;
        initial.visited.insert(visit_key(root));
        chains.push_back(initial);
        std::vector<size_t> stack{0};
        std::set<std::string> visited_times;
        std::vector<std::string> limitations;
        int processed_nodes = 0;
        int next_chain_id = 1;

        auto stop_remaining = [&](const std::string& detail) {
            for (size_t index : stack) {
                if (index < chains.size() && !chains[index].finished)
                    stop_chain(chains[index], "limit", detail, false);
            }
            stack.clear();
        };

        while (!stack.empty()) {
            size_t index = stack.back();
            stack.pop_back();
            if (index >= chains.size() || chains[index].finished) continue;
            ChainState chain = chains[index];

            if (chain.depth > max_depth) {
                stop_chain(chain, "limit", "max_depth", false);
                chains[index] = chain;
                continue;
            }
            if (processed_nodes >= max_nodes) {
                limitations.push_back("trace truncated by limits.max_nodes");
                stop_chain(chain, "limit", "max_nodes", false);
                chains[index] = chain;
                stop_remaining("max_nodes");
                break;
            }
            if (visited_times.insert(chain.current.time).second &&
                static_cast<int>(visited_times.size()) > max_time_steps) {
                limitations.push_back("trace truncated by limits.max_time_steps");
                stop_chain(chain, "limit", "max_time_steps", false);
                chains[index] = chain;
                stop_remaining("max_time_steps");
                break;
            }

            DependencyResult dependency_result =
                collect_dependencies(g_fsdb_file, chain.current, limitations);
            Json hop = {
                {"index", static_cast<int>(chain.hops.size())},
                {"chain_id", chain.chain_id},
                {"signal", chain.current.signal},
                {"x_onset_time", chain.current.time},
                {"active_time", dependency_result.active_time},
                {"value", xdebug_waveform::logic_value_json(chain.current.value)},
                {"x_mask", x_mask_from_bits(chain.current.value.bits)},
                {"relation", chain.relation},
                {"file", dependency_result.file},
                {"line", dependency_result.line},
                {"signal_path", Json::array({chain.current.signal})}
            };
            chain.hops.push_back(hop);
            processed_nodes++;

            if (dependency_result.force) {
                chain.origin = {{"signal", chain.current.signal},
                                {"x_onset_time", chain.current.time},
                                {"kind", "force"}, {"reason", "force_x"},
                                {"evidence_status", "proven"},
                                {"file", dependency_result.file}, {"line", dependency_result.line}};
                stop_chain(chain, "origin_found", "force_x", true);
                chains[index] = chain;
                continue;
            }

            std::vector<Dependency> considered = dependency_result.dependencies;
            if (static_cast<int>(considered.size()) > max_trace_signals) {
                for (size_t i = max_trace_signals; i < considered.size(); ++i) {
                    chain.pending_x_dependencies.push_back({
                        {"signal", considered[i].signal},
                        {"relation", relation_text(considered[i])},
                        {"reason", "max_trace_signals"}
                    });
                }
                limitations.push_back("dependency enumeration truncated by limits.max_trace_signals at " +
                                      chain.current.signal);
                chain.complete = false;
                considered.resize(max_trace_signals);
            }

            std::vector<ChildDependency> children;
            int unreadable_dependencies = 0;
            for (const auto& dependency : considered) {
                XPoint sample;
                if (!read_point(g_fsdb_file, dependency.signal, chain.current.tick, sample)) {
                    unreadable_dependencies++;
                    continue;
                }
                if (!sample.value.has_x) continue;
                XPoint onset;
                if (!find_x_onset(g_fsdb_file, dependency.signal, chain.current.tick, onset)) {
                    onset = sample;
                }
                children.push_back({dependency, onset, sample});
            }

            if (children.empty()) {
                std::string detail;
                std::string kind;
                std::string evidence = "best_effort";
                if (chain.current.at_fsdb_start) {
                    detail = "x_present_at_fsdb_start";
                    kind = "fsdb_boundary";
                    evidence = "proven";
                } else if (dependency_result.external_input) {
                    detail = "primary_input_x";
                    kind = "primary_input";
                    evidence = "proven";
                } else if (unreadable_dependencies > 0) {
                    detail = "undumped_boundary";
                    kind = "undumped_dependency";
                } else if (!dependency_result.dependencies.empty()) {
                    detail = "x_not_observable_upstream";
                    kind = "observability_boundary";
                } else if (dependency_result.dynamic_select) {
                    detail = "dynamic_select_x";
                    kind = "dynamic_select";
                } else {
                    detail = dependency_result.had_driver_evidence
                        ? "candidate_x_source" : "x_not_observable_upstream";
                    kind = dependency_result.driver_kind.empty()
                        ? "unknown" : dependency_result.driver_kind;
                }
                chain.origin = {{"signal", chain.current.signal},
                                {"x_onset_time", chain.current.time},
                                {"kind", kind}, {"reason", detail},
                                {"evidence_status", evidence},
                                {"file", dependency_result.file}, {"line", dependency_result.line}};
                stop_chain(chain,
                           detail == "x_not_observable_upstream" ? detail : "origin_found",
                           detail, true);
                chains[index] = chain;
                continue;
            }

            const int available_children =
                1 + std::max(0, max_chains - static_cast<int>(chains.size()));
            const int kept_children = std::min(static_cast<int>(children.size()), available_children);
            if (kept_children < static_cast<int>(children.size())) {
                Json pending = Json::array();
                for (size_t i = kept_children; i < children.size(); ++i) {
                    Json item = point_json(children[i].sample, "sample_time");
                    item["relation"] = relation_text(children[i].dependency);
                    item["x_onset_time"] = children[i].onset.time;
                    pending.push_back(item);
                    chain.pending_x_dependencies.push_back(item);
                }
                chain.branch_events.push_back({
                    {"hop_index", static_cast<int>(chain.hops.size()) - 1},
                    {"reason", "max_chains"},
                    {"x_dependency_count", static_cast<int>(children.size())},
                    {"returned_x_dependency_count", kept_children},
                    {"omitted_x_dependency_count", static_cast<int>(children.size()) - kept_children},
                    {"pending_x_dependencies", pending}
                });
                chain.complete = false;
                limitations.push_back("X branches truncated by limits.max_chains at " +
                                      chain.current.signal);
            }

            std::vector<size_t> child_indexes;
            for (int child_index = 0; child_index < kept_children; ++child_index) {
                ChainState child = chain;
                if (child_index > 0) {
                    child.chain_id = "c" + std::to_string(next_chain_id++);
                    for (auto& prior_hop : child.hops) prior_hop["chain_id"] = child.chain_id;
                    child.pending_x_dependencies = Json::array();
                    child.branch_events = Json::array();
                    child.complete = true;
                }
                child.current = children[child_index].onset;
                child.relation = relation_text(children[child_index].dependency);
                child.depth = chain.depth + 1;
                std::string key = visit_key(child.current);
                if (child.visited.count(key)) {
                    stop_chain(child, "loop_detected", "loop_detected", true);
                } else {
                    child.visited.insert(key);
                    child.finished = false;
                    child.status = "pending";
                    child.termination_detail.clear();
                    if (child.depth > max_depth) {
                        stop_chain(child, "limit", "max_depth", false);
                    }
                }

                if (child_index == 0) {
                    chains[index] = child;
                    child_indexes.push_back(index);
                } else {
                    chains.push_back(child);
                    child_indexes.push_back(chains.size() - 1);
                }
            }
            for (auto it = child_indexes.rbegin(); it != child_indexes.rend(); ++it) {
                if (!chains[*it].finished) stack.push_back(*it);
            }
        }

        Json chain_array = Json::array();
        Json depth_frontiers = Json::array();
        Json suggested_next_actions = Json::array();
        int completed_count = 0;
        int limited_count = 0;
        int hop_count = 0;
        int origin_count = 0;
        bool best_effort = false;
        for (const auto& chain : chains) {
            chain_array.push_back(chain_json(chain));
            hop_count += static_cast<int>(chain.hops.size());
            if (!chain.origin.is_null()) {
                origin_count++;
                if (chain.origin.value("evidence_status", "best_effort") != "proven") best_effort = true;
            }
            if (chain.status == "limit" || !chain.complete) limited_count++;
            else completed_count++;
            if (chain.status == "limit" && chain.termination_detail == "max_depth") {
                Json frontier = point_json(chain.current, "continue_time");
                frontier["chain_id"] = chain.chain_id;
                frontier["stopped_after_depth"] = max_depth;
                depth_frontiers.push_back(frontier);

                Json continued_limits = limits_json;
                continued_limits["max_depth"] = max_depth;
                continued_limits["max_chains"] = max_chains;
                suggested_next_actions.push_back({
                    {"action", "trace.x"},
                    {"reason", "continue_from_depth_frontier"},
                    {"chain_id", chain.chain_id},
                    {"args", {{"signal", chain.current.signal}, {"time", chain.current.time},
                               {"value_format", args.value("value_format", "hex")}}},
                    {"limits", continued_limits}
                });
            }
        }
        if (!depth_frontiers.empty()) {
            Json deeper_limits = limits_json;
            deeper_limits["max_depth"] = max_depth * 2;
            deeper_limits["max_chains"] = max_chains;
            suggested_next_actions.push_back({
                {"action", "trace.x"},
                {"reason", "rerun_from_root_with_higher_depth"},
                {"args", {{"signal", signal}, {"time", query_point.time},
                           {"value_format", args.value("value_format", "hex")}}},
                {"limits", deeper_limits}
            });
        }

        std::string termination;
        if (limited_count > 0 && completed_count > 0) termination = "partial";
        else if (limited_count > 0) termination = "limit";
        else if (origin_count > 0) termination = "origin_found";
        else termination = chains.empty() ? "x_not_observable_upstream" : chains.front().status;
        const bool truncated = limited_count > 0;

        Json result = {
            {"summary", {{"signal", signal}, {"query_time", query_point.time},
                          {"termination", termination},
                          {"evidence_status", origin_count == 0 ? "unresolved" :
                              (best_effort ? "best_effort" : "proven")},
                          {"chain_count", static_cast<int>(chains.size())},
                          {"completed_chain_count", completed_count},
                          {"limited_chain_count", limited_count},
                          {"hop_count", hop_count}, {"origin_count", origin_count},
                          {"truncated", truncated}}},
            {"query", query},
            {"chains", chain_array},
            {"limitations", limitations},
            {"truncated", truncated}
        };
        if (!depth_frontiers.empty()) result["depth_frontiers"] = depth_frontiers;
        if (!suggested_next_actions.empty()) {
            result["suggested_next_actions"] = suggested_next_actions;
        }
        return result;
    }

private:
    std::string render_xout(const Json& response) const override {
        return render_source_path_xout(action_name(), response);
    }
};

} // namespace

std::unique_ptr<EngineActionHandler> make_trace_x_handler() {
    return std::unique_ptr<EngineActionHandler>(new TraceXHandler);
}

} // namespace xdebug_design
