#include "clock_sampling.h"

#include "core/npi/time_contract.h"
#include "waveform/server/fsdb_scan_utils.h"

#include "npi_L1.h"

#include <algorithm>
#include <cctype>
#include <cmath>
#include <cstdlib>
#include <limits>
#include <set>

namespace xdebug_waveform {
namespace {

std::string trim_copy(const std::string& text) {
    size_t begin = 0;
    while (begin < text.size() && std::isspace(static_cast<unsigned char>(text[begin]))) ++begin;
    size_t end = text.size();
    while (end > begin && std::isspace(static_cast<unsigned char>(text[end - 1]))) --end;
    return text.substr(begin, end - begin);
}

std::string lower_copy(std::string text) {
    for (char& c : text) c = static_cast<char>(std::tolower(static_cast<unsigned char>(c)));
    return text;
}

bool truthy_one(const std::string& value) {
    for (char c : value) {
        if (c == 'x' || c == 'X' || c == 'z' || c == 'Z') return false;
        if (c == '1') return true;
    }
    return false;
}

bool read_vct_value(npiFsdbVctHandle vct, std::string& out) {
    npiFsdbValue value;
    value.format = npiFsdbBinStrVal;
    if (!npi_fsdb_vct_value(vct, &value) || !value.value.str) return false;
    out = value.value.str;
    return true;
}

bool read_edge_at(npiFsdbSigHandle clock_handle, npiFsdbTime time, ClockEdgeKind* edge_kind) {
    if (!clock_handle) return false;
    VctHandle vct(clock_handle);
    if (!vct.valid()) return false;
    if (!npi_fsdb_goto_time(vct.get(), time)) return false;
    npiFsdbTime current_time = 0;
    if (!npi_fsdb_vct_time(vct.get(), &current_time) || current_time != time) return false;
    std::string current_value;
    if (!read_vct_value(vct.get(), current_value)) return false;
    if (!npi_fsdb_goto_prev(vct.get())) return false;
    std::string previous_value;
    if (!read_vct_value(vct.get(), previous_value)) return false;
    ClockEdgeKind actual = ClockEdgeKind::Negedge;
    if (!clock_edge_transition_matches(ClockEdgeKind::Dual,
                                       truthy_one(previous_value),
                                       truthy_one(current_value),
                                       &actual)) {
        return false;
    }
    if (edge_kind) *edge_kind = actual;
    return true;
}

} // namespace

const char* clock_edge_kind_text(ClockEdgeKind edge) {
    switch (edge) {
    case ClockEdgeKind::Posedge: return "posedge";
    case ClockEdgeKind::Negedge: return "negedge";
    case ClockEdgeKind::Dual: return "dual";
    }
    return "negedge";
}

const char* clock_sample_point_text(ClockSamplePointKind point) {
    switch (point) {
    case ClockSamplePointKind::Before: return "before";
    case ClockSamplePointKind::After: return "after";
    }
    return "before";
}

bool parse_clock_edge_kind(const std::string& text, ClockEdgeKind& edge, std::string& error) {
    std::string value = lower_copy(trim_copy(text));
    if (value.empty() || value == "negedge") {
        edge = ClockEdgeKind::Negedge;
        return true;
    }
    if (value == "posedge") {
        edge = ClockEdgeKind::Posedge;
        return true;
    }
    if (value == "dual") {
        edge = ClockEdgeKind::Dual;
        return true;
    }
    error = "invalid edge: " + text + "; expected posedge, negedge, or dual";
    return false;
}

bool parse_clock_sample_point_kind(const std::string& text,
                                   ClockSamplePointKind& point,
                                   std::string& error) {
    std::string value = lower_copy(trim_copy(text));
    if (value.empty() || value == "before") {
        point = ClockSamplePointKind::Before;
        return true;
    }
    if (value == "after") {
        point = ClockSamplePointKind::After;
        return true;
    }
    error = "invalid sample_point: " + text + "; expected before or after";
    return false;
}

bool clock_edge_transition_matches(ClockEdgeKind requested,
                                   bool old_one,
                                   bool new_one,
                                   ClockEdgeKind* actual) {
    if (!old_one && new_one) {
        if (actual) *actual = ClockEdgeKind::Posedge;
        return requested == ClockEdgeKind::Posedge || requested == ClockEdgeKind::Dual;
    }
    if (old_one && !new_one) {
        if (actual) *actual = ClockEdgeKind::Negedge;
        return requested == ClockEdgeKind::Negedge || requested == ClockEdgeKind::Dual;
    }
    return false;
}

bool normalize_clock_sample_spec(npiFsdbFileHandle fsdb,
                                 ClockSampleSpec& spec,
                                 std::string& error) {
    (void)fsdb;
    // Negedge keeps its established current-value semantics.  A supplied
    // sample_point is accepted for uniform public requests but is not applied.
    return true;
}

bool find_first_clock_sample(npiFsdbFileHandle fsdb,
                             const ClockSampleSpec& spec,
                             npiFsdbTime begin,
                             npiFsdbTime end,
                             ClockSamplePoint& point,
                             std::string& error) {
    ClockSampleTimeResolver resolver(fsdb, spec);
    if (!resolver.find_next_sample(begin, point, error)) return false;
    if (point.sample_time > end) {
        error = "no requested clock edge found in FSDB range";
        return false;
    }
    return true;
}

bool resolve_clock_sample_signals(npiFsdbFileHandle fsdb,
                                  const std::vector<std::string>& aliases,
                                  const std::vector<std::string>& paths,
                                  std::vector<ClockSampleSignal>& signals,
                                  std::string& error) {
    signals.clear();
    if (aliases.size() != paths.size()) {
        error = "clock sample aliases and paths size mismatch";
        return false;
    }
    for (size_t i = 0; i < paths.size(); ++i) {
        npiFsdbSigHandle handle = npi_fsdb_sig_by_name(fsdb, paths[i].c_str(), nullptr);
        if (!handle) {
            error = "Signal not found: " + paths[i];
            return false;
        }
        ClockSampleSignal signal;
        signal.alias = aliases[i];
        signal.path = paths[i];
        signal.handle = handle;
        signals.push_back(signal);
    }
    return true;
}

std::map<std::string, std::string> clock_sample_value_map(
    const std::vector<ClockSampleSignal>& signals,
    const std::vector<std::string>& values) {
    std::map<std::string, std::string> out;
    const size_t count = std::min(signals.size(), values.size());
    for (size_t i = 0; i < count; ++i) out[signals[i].alias] = values[i];
    return out;
}

bool ClockValueReader::read_current(npiFsdbFileHandle fsdb,
                                    npiFsdbSigHandle handle,
                                    const std::string& path,
                                    npiFsdbTime time,
                                    npiFsdbValType format,
                                    char prefix,
                                    ClockPointCell& cell) {
    if (!handle) handle = npi_fsdb_sig_by_name(fsdb, path.c_str(), nullptr);
    if (!handle) {
        cell.status = "signal_not_found";
        cell.raw_value.clear();
        return false;
    }
    fsdbSigVec_t handles;
    handles.push_back(handle);
    fsdbValVec_t values;
    if (!npi_fsdb_sig_hdl_vec_value_at(handles, time, values, format) || values.size() != 1) {
        cell.status = "missing_value";
        cell.raw_value.clear();
        return false;
    }
    cell.status = "ok";
    cell.raw_value = value_with_prefix(values[0], prefix);
    cell.value_time = time;
    cell.has_value_time = false;
    return true;
}

bool ClockValueReader::read_before(npiFsdbFileHandle fsdb,
                                   npiFsdbSigHandle handle,
                                   const std::string& path,
                                   npiFsdbTime time,
                                   npiFsdbValType format,
                                   char prefix,
                                   ClockPointCell& cell) {
    if (!handle) handle = npi_fsdb_sig_by_name(fsdb, path.c_str(), nullptr);
    if (!handle) {
        cell.status = "signal_not_found";
        cell.raw_value.clear();
        return false;
    }
    SignalChangeCursor cursor(handle, format);
    if (!cursor.valid()) {
        cell.status = "missing_value";
        cell.raw_value.clear();
        return false;
    }
    npiFsdbTime value_time = 0;
    std::string raw;
    if (!cursor.prev_before(time, value_time, raw)) {
        cell.status = "missing_value";
        cell.raw_value.clear();
        return false;
    }
    cell.status = "ok";
    cell.raw_value = value_with_prefix(raw, prefix);
    cell.value_time = value_time;
    cell.has_value_time = true;
    return true;
}

ClockSampleScanner::ClockSampleScanner(npiFsdbFileHandle fsdb, const ClockSampleSpec& spec)
    : fsdb_(fsdb), spec_(spec) {}

bool ClockSampleScanner::scan(const std::vector<ClockSampleSignal>& signals,
                              npiFsdbTime begin,
                              npiFsdbTime end,
                              npiFsdbValType format,
                              char prefix,
                              int max_samples,
                              const std::function<bool(const ClockSample&)>& callback,
                              std::string& error,
                              int& sample_count,
                              bool& truncated) const {
    sample_count = 0;
    truncated = false;
    ClockSampleSpec spec = spec_;
    if (!normalize_clock_sample_spec(fsdb_, spec, error)) return false;
    npiFsdbSigHandle clk = npi_fsdb_sig_by_name(fsdb_, spec.clock.c_str(), nullptr);
    if (!clk) {
        error = "Clock signal not found: " + spec.clock;
        return false;
    }

    fsdbSigVec_t all_handles;
    all_handles.push_back(clk);
    for (const auto& signal : signals) {
        if (!signal.handle) {
            error = "Signal handle not resolved: " + signal.path;
            return false;
        }
        all_handles.push_back(signal.handle);
    }

    fsdbValVec_t init_values;
    npiFsdbTime init_time = begin > 0 ? begin - 1 : begin;
    if (!npi_fsdb_sig_hdl_vec_value_at(all_handles, init_time, init_values, format) ||
        init_values.size() != all_handles.size()) {
        error = "Failed to read initial sampled values";
        return false;
    }
    std::string prev_clk = value_with_prefix(init_values[0], prefix);
    std::vector<std::string> values(signals.size());
    for (size_t i = 0; i < signals.size(); ++i) {
        values[i] = value_with_prefix(init_values[i + 1], prefix);
    }

    bool sample_before_edge =
        spec.edge != ClockEdgeKind::Negedge &&
        spec.sample_point == ClockSamplePointKind::Before;

    TimeBasedVcIterGuard guard;
    npiFsdbTimeBasedVcIter& iter = guard.iter();
    iter.add(clk);
    for (const auto& signal : signals) iter.add(signal.handle);
    guard.start(begin, end);

    bool have_group = false;
    bool clk_changed = false;
    bool target_edge = false;
    ClockEdgeKind edge_kind = ClockEdgeKind::Negedge;
    npiFsdbTime group_time = 0;
    std::vector<std::string> group_start_values;

    auto finish_group = [&]() -> bool {
        if (!have_group || !clk_changed || !target_edge) return true;
        ++sample_count;
        if (max_samples >= 0 && sample_count > max_samples) {
            truncated = true;
            return false;
        }
        ClockSample sample;
        sample.time = group_time;
        sample.edge_kind = edge_kind;
        sample.values = sample_before_edge ? group_start_values : values;
        return callback(sample);
    };

    npiFsdbTime curr_time = 0;
    npiFsdbSigHandle changed_sig = nullptr;
    bool keep = true;
    while (keep && iter.iter_next(curr_time, changed_sig) > 0) {
        if (!have_group) {
            have_group = true;
            group_time = curr_time;
            if (sample_before_edge) group_start_values = values;
        } else if (curr_time != group_time) {
            keep = finish_group();
            if (!keep) break;
            group_time = curr_time;
            clk_changed = false;
            target_edge = false;
            if (sample_before_edge) group_start_values = values;
        }

        npiFsdbValue val;
        val.format = format;
        if (!iter.get_value(val) || !val.value.str) continue;
        std::string v = value_with_prefix(val.value.str, prefix);
        if (changed_sig == clk) {
            ClockEdgeKind actual = ClockEdgeKind::Negedge;
            target_edge = clock_edge_transition_matches(
                spec.edge,
                truthy_one(prev_clk),
                truthy_one(v),
                &actual);
            edge_kind = actual;
            prev_clk = v;
            clk_changed = true;
        } else {
            for (size_t i = 0; i < signals.size(); ++i) {
                if (signals[i].handle == changed_sig) {
                    values[i] = v;
                    break;
                }
            }
        }
    }
    if (keep) finish_group();
    return error.empty();
}

ClockExpressionSampleScanner::ClockExpressionSampleScanner(
    npiFsdbFileHandle fsdb,
    ClockEdgeKind edge,
    ClockSamplePointKind sample_point)
    : fsdb_(fsdb), edge_(edge), sample_point_(sample_point) {}

bool ClockExpressionSampleScanner::scan(
    const std::vector<ClockSampleSignal>& clock_signals,
    const std::vector<ClockSampleSignal>& sample_signals,
    npiFsdbTime begin,
    npiFsdbTime end,
    npiFsdbValType format,
    char prefix,
    int max_samples,
    const std::function<bool(const std::map<std::string, std::string>&,
                             bool& known,
                             bool& one,
                             std::string& error)>& clock_eval,
    const std::function<bool(const ClockSample&)>& callback,
    std::string& error,
    int& sample_count,
    bool& truncated) const {
    sample_count = 0;
    truncated = false;
    if (edge_ == ClockEdgeKind::Negedge && sample_point_ == ClockSamplePointKind::Before) {
        // Negedge uses the current-value fast path; before/after is intentionally ignored.
    }
    if (clock_signals.empty()) {
        error = "clock expression has no signal dependency";
        return false;
    }

    std::vector<ClockSampleSignal> all_signals;
    std::set<npiFsdbSigHandle> clock_handles;
    auto add_unique = [&](const ClockSampleSignal& signal) {
        if (!signal.handle) {
            error = "Signal handle not resolved: " + signal.path;
            return false;
        }
        for (const auto& existing : all_signals) {
            if (existing.handle == signal.handle) return true;
        }
        all_signals.push_back(signal);
        return true;
    };
    for (const auto& signal : clock_signals) {
        clock_handles.insert(signal.handle);
        if (!add_unique(signal)) return false;
    }
    for (const auto& signal : sample_signals) if (!add_unique(signal)) return false;

    fsdbSigVec_t all_handles;
    for (const auto& signal : all_signals) all_handles.push_back(signal.handle);

    fsdbValVec_t init_values;
    npiFsdbTime init_time = begin > 0 ? begin - 1 : begin;
    if (!npi_fsdb_sig_hdl_vec_value_at(all_handles, init_time, init_values, format) ||
        init_values.size() != all_handles.size()) {
        error = "Failed to read initial expression clock values";
        return false;
    }

    std::map<npiFsdbSigHandle, std::string> current_by_handle;
    std::map<std::string, std::string> current_by_alias;
    for (size_t i = 0; i < all_signals.size(); ++i) {
        std::string value = value_with_prefix(init_values[i], prefix);
        current_by_handle[all_signals[i].handle] = value;
        current_by_alias[all_signals[i].alias] = value;
    }

    bool prev_known = false;
    bool prev_one = false;
    if (!clock_eval(current_by_alias, prev_known, prev_one, error)) return false;

    bool sample_before_edge =
        edge_ != ClockEdgeKind::Negedge &&
        sample_point_ == ClockSamplePointKind::Before;

    TimeBasedVcIterGuard guard;
    npiFsdbTimeBasedVcIter& iter = guard.iter();
    for (auto handle : all_handles) iter.add(handle);
    guard.start(begin, end);

    bool have_group = false;
    bool clock_changed = false;
    bool target_edge = false;
    ClockEdgeKind edge_kind = ClockEdgeKind::Negedge;
    npiFsdbTime group_time = 0;
    std::map<npiFsdbSigHandle, std::string> group_start_by_handle;

    auto make_sample_values = [&](const std::map<npiFsdbSigHandle, std::string>& source) {
        std::vector<std::string> out;
        out.reserve(sample_signals.size());
        for (const auto& signal : sample_signals) {
            auto it = source.find(signal.handle);
            out.push_back(it == source.end() ? std::string() : it->second);
        }
        return out;
    };

    auto finish_group = [&]() -> bool {
        if (!have_group || !clock_changed || !target_edge) return true;
        ++sample_count;
        if (max_samples >= 0 && sample_count > max_samples) {
            truncated = true;
            return false;
        }
        ClockSample sample;
        sample.time = group_time;
        sample.edge_kind = edge_kind;
        sample.values = make_sample_values(sample_before_edge ? group_start_by_handle : current_by_handle);
        return callback(sample);
    };

    npiFsdbTime curr_time = 0;
    npiFsdbSigHandle changed_sig = nullptr;
    bool keep = true;
    while (keep && iter.iter_next(curr_time, changed_sig) > 0) {
        if (!have_group) {
            have_group = true;
            group_time = curr_time;
            if (sample_before_edge) group_start_by_handle = current_by_handle;
        } else if (curr_time != group_time) {
            keep = finish_group();
            if (!keep) break;
            group_time = curr_time;
            clock_changed = false;
            target_edge = false;
            if (sample_before_edge) group_start_by_handle = current_by_handle;
        }

        npiFsdbValue val;
        val.format = format;
        if (!iter.get_value(val) || !val.value.str) continue;
        std::string value = value_with_prefix(val.value.str, prefix);
        current_by_handle[changed_sig] = value;
        for (const auto& signal : all_signals) {
            if (signal.handle == changed_sig) {
                current_by_alias[signal.alias] = value;
                break;
            }
        }

        if (clock_handles.find(changed_sig) != clock_handles.end()) {
            bool cur_known = false;
            bool cur_one = false;
            if (!clock_eval(current_by_alias, cur_known, cur_one, error)) return false;
            if (prev_known && cur_known) {
                ClockEdgeKind actual = ClockEdgeKind::Negedge;
                bool matched = clock_edge_transition_matches(edge_, prev_one, cur_one, &actual);
                if (matched) {
                    target_edge = true;
                    edge_kind = actual;
                }
                clock_changed = true;
            }
            prev_known = cur_known;
            prev_one = cur_one;
        }
    }
    if (keep) finish_group();
    return error.empty();
}

ClockPointSampler::ClockPointSampler(npiFsdbFileHandle fsdb, const ClockSampleSpec& spec)
    : fsdb_(fsdb), spec_(spec) {}

bool ClockPointSampler::sample(npiFsdbTime requested_time,
                               const std::vector<ClockPointSignal>& signals,
                               npiFsdbValType format,
                               char prefix,
                               ClockPointResult& result,
                               std::string& error) const {
    result = ClockPointResult();
    result.signals = signals;
    ClockSampleTimeResolver resolver(fsdb_, spec_);
    if (!resolver.valid(error)) return false;

    ClockEdgeKind actual_edge = ClockEdgeKind::Negedge;
    bool clock_edge_hit = resolver.is_clock_edge_at(requested_time, &actual_edge);
    ClockEdgeKind target_edge = ClockEdgeKind::Negedge;
    bool target_edge_hit = resolver.is_target_edge_at(requested_time, &target_edge);
    ClockSamplePoint prev_point;
    ClockSamplePoint next_point;
    std::string resolver_error;
    bool have_prev = resolver.find_previous_sample(requested_time, prev_point, resolver_error);
    bool have_next = resolver.find_next_sample(requested_time + 1, next_point, resolver_error);
    bool edge_sample_before =
        spec_.edge != ClockEdgeKind::Negedge &&
        spec_.sample_point == ClockSamplePointKind::Before;

    result.context.requested_time = requested_time;
    result.context.clock_edge_hit = clock_edge_hit;
    result.context.clock_edge_kind = actual_edge;
    result.context.has_clock_edge_kind = clock_edge_hit;
    result.context.target_edge_hit = target_edge_hit;
    result.context.previous_sample_time = prev_point.sample_time;
    result.context.has_previous_sample_time = have_prev;
    result.context.next_sample_time = next_point.sample_time;
    result.context.has_next_sample_time = have_next;
    result.context.bracket_complete = have_prev && have_next;

    for (const auto& signal : signals) {
        ClockPointRow row;
        row.label = signal.label.empty() ? signal.path : signal.label;
        row.path = signal.path;
        if (have_prev) {
            if (edge_sample_before) {
                ClockValueReader::read_before(fsdb_, signal.handle, signal.path,
                                              prev_point.sample_time, format, prefix, row.before);
            } else {
                ClockValueReader::read_current(fsdb_, signal.handle, signal.path,
                                               prev_point.sample_time, format, prefix, row.before);
            }
        } else {
            row.before.status = "missing_edge";
        }

        bool middle_before = target_edge_hit && edge_sample_before;
        if (middle_before) {
            ClockValueReader::read_before(fsdb_, signal.handle, signal.path,
                                          requested_time, format, prefix, row.middle);
        } else {
            ClockValueReader::read_current(fsdb_, signal.handle, signal.path,
                                           requested_time, format, prefix, row.middle);
        }

        if (have_next) {
            if (edge_sample_before) {
                ClockValueReader::read_before(fsdb_, signal.handle, signal.path,
                                              next_point.sample_time, format, prefix, row.after);
            } else {
                ClockValueReader::read_current(fsdb_, signal.handle, signal.path,
                                               next_point.sample_time, format, prefix, row.after);
            }
        } else {
            row.after.status = "missing_edge";
        }
        result.rows.push_back(row);
    }
    return true;
}

ClockSampleTimeResolver::ClockSampleTimeResolver(npiFsdbFileHandle fsdb, const ClockSampleSpec& spec)
    : fsdb_(fsdb), spec_(spec) {
    if (fsdb_ && !spec_.clock.empty()) {
        clock_handle_ = npi_fsdb_sig_by_name(fsdb_, spec_.clock.c_str(), nullptr);
    }
}

bool ClockSampleTimeResolver::valid(std::string& error) const {
    if (!fsdb_) {
        error = "FSDB handle is not available";
        return false;
    }
    if (spec_.clock.empty()) {
        error = "clock is required";
        return false;
    }
    if (!clock_handle_) {
        error = "Clock signal not found: " + spec_.clock;
        return false;
    }
    return true;
}

bool ClockSampleTimeResolver::is_clock_edge_at(npiFsdbTime time, ClockEdgeKind* edge_kind) const {
    return read_edge_at(clock_handle_, time, edge_kind);
}

bool ClockSampleTimeResolver::is_target_edge_at(npiFsdbTime time, ClockEdgeKind* edge_kind) const {
    ClockEdgeKind actual = ClockEdgeKind::Negedge;
    bool have_edge = is_clock_edge_at(time, &actual);
    bool matched = have_edge &&
        (spec_.edge == ClockEdgeKind::Dual || spec_.edge == actual);
    if (matched && edge_kind) *edge_kind = actual;
    return matched;
}

bool ClockSampleTimeResolver::previous_single_edge_sample(ClockEdgeKind edge,
                                                          npiFsdbTime anchor_time,
                                                          ClockSamplePoint& point,
                                                          std::string& error) const {
    if (!clock_handle_) {
        error = "Clock signal not found: " + spec_.clock;
        return false;
    }
    ClockEdgeCursor cursor(clock_handle_, edge == ClockEdgeKind::Posedge);
    if (!cursor.valid()) {
        error = "failed to create clock edge cursor for " + spec_.clock;
        return false;
    }
    npiFsdbTime t = 0;
    if (!cursor.prev_before(anchor_time, t)) return false;
    point.edge_time = t;
    point.sample_time = t;
    point.edge_kind = edge;
    return true;
}

bool ClockSampleTimeResolver::next_single_edge_sample(ClockEdgeKind edge,
                                                       npiFsdbTime anchor_time,
                                                       ClockSamplePoint& point,
                                                       std::string& error) const {
    npiFsdbTime start_time = anchor_time;

    SignalChangeCursor cursor(clock_handle_, npiFsdbBinStrVal);
    if (!cursor.valid()) {
        error = "failed to create clock value cursor for " + spec_.clock;
        return false;
    }

    npiFsdbTime previous_time = 0;
    std::string previous_value;
    bool have_previous = cursor.prev_before(start_time, previous_time, previous_value);

    npiFsdbTime change_time = 0;
    std::string current_value;
    if (!cursor.first_at_or_after(start_time, change_time, current_value)) return false;
    while (true) {
        if (change_time < start_time) {
            previous_value = current_value;
            have_previous = true;
        } else if (have_previous) {
            ClockEdgeKind actual = ClockEdgeKind::Negedge;
            if (clock_edge_transition_matches(edge,
                                              truthy_one(previous_value),
                                              truthy_one(current_value),
                                              &actual)) {
                point.edge_time = change_time;
                point.sample_time = change_time;
                point.edge_kind = actual;
                return true;
            }
            previous_value = current_value;
            have_previous = true;
        } else {
            previous_value = current_value;
            have_previous = true;
        }
        if (!cursor.next(change_time, current_value)) return false;
    }
}

bool ClockSampleTimeResolver::find_next_sample(npiFsdbTime anchor_time,
                                                ClockSamplePoint& point,
                                                std::string& error) const {
    if (!valid(error)) return false;
    if (spec_.edge != ClockEdgeKind::Dual) {
        return next_single_edge_sample(spec_.edge, anchor_time, point, error);
    }
    ClockSamplePoint pos;
    ClockSamplePoint neg;
    std::string pos_error;
    std::string neg_error;
    bool have_pos = next_single_edge_sample(ClockEdgeKind::Posedge, anchor_time, pos, pos_error);
    bool have_neg = next_single_edge_sample(ClockEdgeKind::Negedge, anchor_time, neg, neg_error);
    if (!have_pos && !have_neg) {
        error = pos_error.empty() ? neg_error : pos_error;
        return false;
    }
    if (!have_neg || (have_pos && pos.sample_time <= neg.sample_time)) point = pos;
    else point = neg;
    return true;
}

bool ClockSampleTimeResolver::find_previous_sample(npiFsdbTime anchor_time,
                                                   ClockSamplePoint& point,
                                                   std::string& error) const {
    if (!valid(error)) return false;
    if (spec_.edge != ClockEdgeKind::Dual) {
        return previous_single_edge_sample(spec_.edge, anchor_time, point, error);
    }
    ClockSamplePoint pos;
    ClockSamplePoint neg;
    std::string pos_error;
    std::string neg_error;
    bool have_pos = previous_single_edge_sample(ClockEdgeKind::Posedge, anchor_time, pos, pos_error);
    bool have_neg = previous_single_edge_sample(ClockEdgeKind::Negedge, anchor_time, neg, neg_error);
    if (!have_pos && !have_neg) {
        error = pos_error.empty() ? neg_error : pos_error;
        return false;
    }
    if (!have_neg || (have_pos && pos.sample_time >= neg.sample_time)) point = pos;
    else point = neg;
    return true;
}

bool ClockSampleTimeResolver::for_each_sample_time(
    npiFsdbTime begin,
    npiFsdbTime end,
    const std::function<bool(const ClockSamplePoint&)>& callback,
    std::string& error) const {
    if (!valid(error)) return false;
    npiFsdbTime anchor = begin;
    while (true) {
        ClockSamplePoint point;
        if (!find_next_sample(anchor, point, error)) return true;
        if (point.sample_time > end) return true;
        if (!callback(point)) return false;
        if (point.edge_time == std::numeric_limits<npiFsdbTime>::max() ||
            point.sample_time == std::numeric_limits<npiFsdbTime>::max()) {
            return true;
        }
        npiFsdbTime next_edge_anchor = point.edge_time + 1;
        npiFsdbTime next_sample_anchor = point.sample_time + 1;
        anchor = std::max(next_edge_anchor, next_sample_anchor);
    }
}

} // namespace xdebug_waveform
