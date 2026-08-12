#include "fsdb_scan_utils.h"

#include "core/session/request_deadline.h"
#include "npi_L1.h"

#include <cctype>
#include <sstream>

namespace xdebug_waveform {

std::string value_with_prefix(const std::string& value, char prefix) {
    if (prefix == '\0') return value;
    if (value.size() >= 2 && value[0] == '\'') return value;
    char p = static_cast<char>(std::tolower(static_cast<unsigned char>(prefix)));
    return std::string("'") + p + value;
}

VctHandle::VctHandle(npiFsdbSigHandle sig) {
    if (sig) vct_ = npi_fsdb_create_vct(sig);
}

VctHandle::~VctHandle() {
    if (vct_) {
        npi_fsdb_release_vct(vct_);
        vct_ = nullptr;
    }
}

ClockEdgeCursor::ClockEdgeCursor(npiFsdbSigHandle clk, bool posedge)
    : vct_(clk),
      edge_(posedge ? npiFsdbL1PositiveEdge : npiFsdbL1NegativeEdge) {}

bool ClockEdgeCursor::first_at_or_after(npiFsdbTime time, npiFsdbTime& out_time) {
    xdebug_core::request_deadline_checkpoint();
    if (!vct_.valid()) return false;
    if (!npi_fsdb_goto_time_edge(vct_.get(), time, edge_)) return false;
    return npi_fsdb_vct_time(vct_.get(), &out_time) != 0;
}

bool ClockEdgeCursor::next(npiFsdbTime& out_time) {
    xdebug_core::request_deadline_checkpoint();
    if (!vct_.valid()) return false;
    if (!npi_fsdb_goto_next_edge(vct_.get(), edge_)) return false;
    return npi_fsdb_vct_time(vct_.get(), &out_time) != 0;
}

bool ClockEdgeCursor::prev_before(npiFsdbTime time, npiFsdbTime& out_time) {
    xdebug_core::request_deadline_checkpoint();
    if (!vct_.valid()) return false;
    if (!npi_fsdb_goto_time_edge(vct_.get(), time, edge_)) return false;
    npiFsdbTime current = 0;
    if (!npi_fsdb_vct_time(vct_.get(), &current)) return false;
    if (current < time) {
        out_time = current;
        return true;
    }
    if (!npi_fsdb_goto_prev_edge(vct_.get(), edge_)) return false;
    return npi_fsdb_vct_time(vct_.get(), &out_time) != 0;
}

SignalChangeCursor::SignalChangeCursor(npiFsdbSigHandle sig, npiFsdbValType format)
    : vct_(sig), format_(format) {}

bool SignalChangeCursor::read_current(npiFsdbTime& out_time, std::string& out_value) {
    xdebug_core::request_deadline_checkpoint();
    if (!vct_.valid()) return false;
    npiFsdbValue value;
    value.format = format_;
    if (!npi_fsdb_vct_time(vct_.get(), &out_time)) return false;
    if (!npi_fsdb_vct_value(vct_.get(), &value) || !value.value.str) return false;
    out_value = value.value.str;
    return true;
}

bool SignalChangeCursor::first_at_or_after(npiFsdbTime time,
                                           npiFsdbTime& out_time,
                                           std::string& out_value) {
    xdebug_core::request_deadline_checkpoint();
    if (!vct_.valid()) return false;
    if (!npi_fsdb_goto_time(vct_.get(), time)) return false;
    return read_current(out_time, out_value);
}

bool SignalChangeCursor::next(npiFsdbTime& out_time, std::string& out_value) {
    xdebug_core::request_deadline_checkpoint();
    if (!vct_.valid()) return false;
    if (!npi_fsdb_goto_next(vct_.get())) return false;
    return read_current(out_time, out_value);
}

bool SignalChangeCursor::prev_before(npiFsdbTime time,
                                     npiFsdbTime& out_time,
                                     std::string& out_value) {
    xdebug_core::request_deadline_checkpoint();
    if (!vct_.valid()) return false;
    if (!npi_fsdb_goto_time(vct_.get(), time)) return false;
    npiFsdbTime current = 0;
    if (!npi_fsdb_vct_time(vct_.get(), &current)) return false;
    if (current < time) return read_current(out_time, out_value);
    if (!npi_fsdb_goto_prev(vct_.get())) return false;
    return read_current(out_time, out_value);
}

TimeBasedVcIterGuard::~TimeBasedVcIterGuard() {
    stop();
}

void TimeBasedVcIterGuard::start(npiFsdbTime begin, npiFsdbTime end) {
    xdebug_core::request_deadline_checkpoint();
    iter_.iter_start(begin, end);
    started_ = true;
}

void TimeBasedVcIterGuard::stop() {
    if (started_) {
        iter_.iter_stop();
        started_ = false;
    }
}

bool SampleCache::read(const std::vector<npiFsdbSigHandle>& handles,
                       npiFsdbTime time,
                       npiFsdbValType format,
                       std::vector<std::string>& out_values) {
    xdebug_core::request_deadline_checkpoint();
    std::ostringstream key;
    key << time << ':' << static_cast<int>(format);
    for (auto h : handles) key << ':' << h;
    const std::string key_s = key.str();
    auto it = cache_.find(key_s);
    if (it != cache_.end()) {
        out_values = it->second;
        return true;
    }
    fsdbValVec_t raw;
    if (!npi_fsdb_sig_hdl_vec_value_at(handles, time, raw, format) || raw.size() != handles.size()) {
        return false;
    }
    out_values.assign(raw.begin(), raw.end());
    cache_[key_s] = out_values;
    return true;
}

void SampleCache::clear() {
    cache_.clear();
}

} // namespace xdebug_waveform
