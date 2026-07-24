#include "axi_analyzer.h"
#include "../cache/analysis_probe.h"
#include "../cache/analysis_size_estimator.h"
#include "../common/clock_sampling.h"
#include "../common/reset_config.h"
#include "../server/fsdb_value_reader.h"
#include "../server/fsdb_scan_utils.h"
#include "npi_fsdb.h"
#include "npi_L1.h"
#include <cstdio>
#include <cstdlib>
#include <cstdint>
#include <algorithm>
#include <list>
#include <deque>
#include <map>
#include <memory>
#include <limits>
#include <set>
#include "json.hpp"

namespace xdebug_waveform {

namespace {

constexpr std::uint32_t kAxiFingerprintVersion = 2;
const char* kAxiResultTypeTag = "axi_result.v1";

int declared_width(npiFsdbFileHandle file, const std::string& signal) {
    const FsdbSignalWidth width = fsdb_signal_width(file, signal);
    return width.reliable ? width.width : 0;
}

void decorate_transaction_widths(npiFsdbFileHandle file,
                                 const AxiConfig& config,
                                 AxiTransaction& txn) {
    txn.addr_signal = txn.is_write ? config.awaddr : config.araddr;
    txn.id_signal = txn.is_write ? config.awid : config.arid;
    txn.len_signal = txn.is_write ? config.awlen : config.arlen;
    txn.size_signal = txn.is_write ? config.awsize : config.arsize;
    txn.burst_signal = txn.is_write ? config.awburst : config.arburst;
    txn.data_signal = txn.is_write ? config.wdata : config.rdata;
    txn.wstrb_signal = txn.is_write ? config.wstrb : std::string();
    txn.resp_signal = txn.is_write ? config.bresp : config.rresp;
    txn.addr_width = declared_width(file, txn.addr_signal);
    txn.id_width = declared_width(file, txn.id_signal);
    txn.len_width = declared_width(file, txn.len_signal);
    txn.size_width = declared_width(file, txn.size_signal);
    txn.burst_width = declared_width(file, txn.burst_signal);
    txn.data_width = declared_width(file, txn.data_signal);
    txn.wstrb_width = txn.wstrb_signal.empty()
        ? 0 : declared_width(file, txn.wstrb_signal);
    txn.resp_width = declared_width(file, txn.resp_signal);
}

void decorate_result_widths(npiFsdbFileHandle file,
                            const AxiConfig& config,
                            AxiResult& result) {
    auto decorate = [&](std::vector<AxiTransaction>& transactions) {
        for (auto& txn : transactions)
            decorate_transaction_widths(file, config, txn);
    };
    decorate(result.all);
    decorate(result.writes);
    decorate(result.reads);
    decorate(result.pending_writes);
    decorate(result.pending_reads);
}

std::string normalized_axi_config_semantics(const AxiConfig& c) {
    nlohmann::ordered_json j;
    j["awaddr"] = c.awaddr; j["awid"] = c.awid; j["awlen"] = c.awlen;
    j["awsize"] = c.awsize; j["awburst"] = c.awburst;
    j["awvalid"] = c.awvalid; j["awready"] = c.awready;
    j["wdata"] = c.wdata; j["wstrb"] = c.wstrb; j["wlast"] = c.wlast;
    j["wvalid"] = c.wvalid; j["wready"] = c.wready;
    j["bid"] = c.bid; j["bresp"] = c.bresp;
    j["bvalid"] = c.bvalid; j["bready"] = c.bready;
    j["araddr"] = c.araddr; j["arid"] = c.arid; j["arlen"] = c.arlen;
    j["arsize"] = c.arsize; j["arburst"] = c.arburst;
    j["arvalid"] = c.arvalid; j["arready"] = c.arready;
    j["rid"] = c.rid; j["rdata"] = c.rdata; j["rresp"] = c.rresp;
    j["rlast"] = c.rlast; j["rvalid"] = c.rvalid; j["rready"] = c.rready;
    j["clock"] = c.clock_sample.clock;
    j["edge"] = clock_edge_kind_text(c.clock_sample.edge);
    if (c.clock_sample.edge != ClockEdgeKind::Negedge)
        j["sample_point"] = clock_sample_point_text(c.clock_sample.sample_point);
    j["reset"] = reset_config_json(c.reset);
    return j.dump();
}

}  // namespace

bool AxiAnalyzer::parse_hex_value(const std::string& hex_str, uint64_t& out) {
    if (hex_str.empty()) return false;
    const char* start = hex_str.c_str();
    char* end = nullptr;
    out = strtoull(start, &end, 16);
    return end != start;
}

bool AxiAnalyzer::id_matches(const std::string& txn_id, const char* id_str) {
    if (!id_str) return true;
    uint64_t txn_id_val = 0;
    if (!parse_hex_value(txn_id, txn_id_val)) return false;
    char* end = nullptr;
    uint64_t id_val = strtoull(id_str, &end, 0);
    if (end == id_str) return false;
    return txn_id_val == id_val;
}

void AxiAnalyzer::configure_repository(AnalysisRepository* repository,
                                       const std::string& session_id,
                                       const FsdbIdentity& fsdb_identity) {
    repository_ = repository;
    session_id_ = session_id;
    fsdb_identity_ = fsdb_identity;
    keys_.clear();
    last_cache_error_ = AnalysisCacheError();
}

AnalysisCacheKey AxiAnalyzer::cache_key(const AxiConfig& config) const {
    return make_analysis_cache_key(
        "axi", session_id_, fsdb_identity_, kAxiFingerprintVersion,
        normalized_axi_config_semantics(config), AnalysisCacheScope::Full);
}

const AxiResult* AxiAnalyzer::get_result_internal(
    const std::string& name, std::uint64_t* generation) const {
    if (repository_ == nullptr) return nullptr;
    auto found = keys_.find(name);
    if (found == keys_.end()) return nullptr;
    std::shared_ptr<const AxiResult> result =
        repository_->peek_canonical<AxiResult>(found->second,
                                               kAxiResultTypeTag,
                                               generation);
    return result.get();
}

const AxiResult* AxiAnalyzer::get_result(const std::string& name) const {
    return get_result_internal(name, nullptr);
}

struct SigIdx {
    int reset = -1;
    int awaddr = -1, awid = -1, awlen = -1, awsize = -1, awburst = -1, awvalid = -1, awready = -1;
    int wdata = -1, wstrb = -1, wlast = -1, wvalid = -1, wready = -1;
    int bid = -1, bresp = -1, bvalid = -1, bready = -1;
    int araddr = -1, arid = -1, arlen = -1, arsize = -1, arburst = -1, arvalid = -1, arready = -1;
    int rid = -1, rdata = -1, rresp = -1, rlast = -1, rvalid = -1, rready = -1;
};

static void add_sig(const std::string& path, int& idx, std::vector<std::string>& signals) {
    if (!path.empty()) {
        idx = (int)signals.size();
        signals.push_back(path);
    } else {
        idx = -1;
    }
}

static bool is_active(const std::string& v) {
    return !v.empty() && v != "0" && v != "X" && v != "Z";
}

bool AxiAnalyzer::analyze(const std::string& name, npiFsdbFileHandle file,
                          const AxiConfig& config,
                          AnalysisCacheError* cache_error) {
    last_cache_error_ = AnalysisCacheError();
    if (repository_ == nullptr) {
        last_cache_error_.code = "ANALYSIS_REPOSITORY_UNAVAILABLE";
        last_cache_error_.message = "AXI analysis repository is not configured";
        if (cache_error != nullptr) *cache_error = last_cache_error_;
        return false;
    }
    const AnalysisCacheKey key = cache_key(config);
    auto previous_key = keys_.find(name);
    if (previous_key != keys_.end() && !(previous_key->second == key)) {
        repository_->erase_cursor(cursor_id(name, 0));
        repository_->erase_cursor(cursor_id(name, 1));
        repository_->erase_cursor(cursor_id(name, 2));
    }
    keys_[name] = key;
    const AnalysisAcquireStatus acquire = repository_->begin_canonical(
        key, kAxiResultTypeTag, sizeof(AxiResult), last_cache_error_);
    if (acquire == AnalysisAcquireStatus::Hit) return true;
    if (acquire != AnalysisAcquireStatus::BuildStarted) {
        if (cache_error != nullptr) *cache_error = last_cache_error_;
        return false;
    }
    auto fail_build = [&](const std::string& reason) {
        repository_->fail_canonical(key, reason);
        if (last_cache_error_.message.empty()) {
            last_cache_error_.message = "failed to build AXI analysis";
        }
        if (cache_error != nullptr) *cache_error = last_cache_error_;
        return false;
    };

    try {
    ClockSampleSpec clock_sample = config.clock_sample;
    std::string normalize_error;
    if (!normalize_clock_sample_spec(file, clock_sample, normalize_error)) {
        last_cache_error_.message = normalize_error;
        return fail_build("clock_normalization_failed");
    }

    // Build signal vector and index map
    std::vector<std::string> signals;
    signals.reserve(30);
    SigIdx idx;
    add_sig(config.reset.signal, idx.reset, signals);
    add_sig(config.awaddr,  idx.awaddr,  signals);
    add_sig(config.awid,    idx.awid,    signals);
    add_sig(config.awlen,   idx.awlen,   signals);
    add_sig(config.awsize,  idx.awsize,  signals);
    add_sig(config.awburst, idx.awburst, signals);
    add_sig(config.awvalid, idx.awvalid, signals);
    add_sig(config.awready, idx.awready, signals);
    add_sig(config.wdata,   idx.wdata,   signals);
    add_sig(config.wstrb,   idx.wstrb,   signals);
    add_sig(config.wlast,   idx.wlast,   signals);
    add_sig(config.wvalid,  idx.wvalid,  signals);
    add_sig(config.wready,  idx.wready,  signals);
    add_sig(config.bid,     idx.bid,     signals);
    add_sig(config.bresp,   idx.bresp,   signals);
    add_sig(config.bvalid,  idx.bvalid,  signals);
    add_sig(config.bready,  idx.bready,  signals);
    add_sig(config.araddr,  idx.araddr,  signals);
    add_sig(config.arid,    idx.arid,    signals);
    add_sig(config.arlen,   idx.arlen,   signals);
    add_sig(config.arsize,  idx.arsize,  signals);
    add_sig(config.arburst, idx.arburst, signals);
    add_sig(config.arvalid, idx.arvalid, signals);
    add_sig(config.arready, idx.arready, signals);
    add_sig(config.rid,     idx.rid,     signals);
    add_sig(config.rdata,   idx.rdata,   signals);
    add_sig(config.rresp,   idx.rresp,   signals);
    add_sig(config.rlast,   idx.rlast,   signals);
    add_sig(config.rvalid,  idx.rvalid,  signals);
    add_sig(config.rready,  idx.rready,  signals);

    fsdbSigVec_t sig_handles;
    for (const auto& sig_name : signals) {
        npiFsdbSigHandle sig = npi_fsdb_sig_by_name(file, sig_name.c_str(), NULL);
        if (!sig) {
            last_cache_error_.message = "AXI signal not found: " + sig_name;
            return fail_build("signal_not_found");
        }
        sig_handles.push_back(sig);
    }
    std::vector<ClockSampleSignal> sample_signals;
    for (size_t i = 0; i < signals.size(); ++i) {
        sample_signals.push_back({signals[i], signals[i], sig_handles[i]});
    }

    AxiTransactionTracker tracker;

    auto process_edge = [&](npiFsdbTime t, const std::vector<std::string>& values) {
        if (values.size() != signals.size()) return;
        AxiSample sample;
        sample.time = t;
        if (idx.reset >= 0) {
            sample.reset_active = reset_is_active(config.reset, values[idx.reset]);
        }
        sample.aw_valid = idx.awvalid >= 0 && is_active(values[idx.awvalid]);
        sample.w_valid = idx.wvalid >= 0 && is_active(values[idx.wvalid]);
        sample.ar_valid = idx.arvalid >= 0 && is_active(values[idx.arvalid]);
        sample.r_valid = idx.rvalid >= 0 && is_active(values[idx.rvalid]);
        sample.aw_handshake = idx.awvalid >= 0 && idx.awready >= 0 &&
            is_active(values[idx.awvalid]) && is_active(values[idx.awready]);
        sample.w_handshake = idx.wvalid >= 0 && idx.wready >= 0 &&
            is_active(values[idx.wvalid]) && is_active(values[idx.wready]);
        sample.b_handshake = idx.bvalid >= 0 && idx.bready >= 0 &&
            is_active(values[idx.bvalid]) && is_active(values[idx.bready]);
        sample.ar_handshake = idx.arvalid >= 0 && idx.arready >= 0 &&
            is_active(values[idx.arvalid]) && is_active(values[idx.arready]);
        sample.r_handshake = idx.rvalid >= 0 && idx.rready >= 0 &&
            is_active(values[idx.rvalid]) && is_active(values[idx.rready]);
        sample.wlast = idx.wlast >= 0 ? is_active(values[idx.wlast]) : true;
        sample.rlast = idx.rlast >= 0 ? is_active(values[idx.rlast]) : true;
        sample.awaddr = idx.awaddr >= 0 ? values[idx.awaddr] : "";
        sample.awid = idx.awid >= 0 ? values[idx.awid] : "0";
        sample.awlen = idx.awlen >= 0 ? values[idx.awlen] : "0";
        sample.awsize = idx.awsize >= 0 ? values[idx.awsize] : "";
        sample.awburst = idx.awburst >= 0 ? values[idx.awburst] : "";
        sample.wdata = idx.wdata >= 0 ? values[idx.wdata] : "";
        sample.wstrb = idx.wstrb >= 0 ? values[idx.wstrb] : "";
        sample.bid = idx.bid >= 0 ? values[idx.bid] : "0";
        sample.bresp = idx.bresp >= 0 ? values[idx.bresp] : "";
        sample.araddr = idx.araddr >= 0 ? values[idx.araddr] : "";
        sample.arid = idx.arid >= 0 ? values[idx.arid] : "0";
        sample.arlen = idx.arlen >= 0 ? values[idx.arlen] : "0";
        sample.arsize = idx.arsize >= 0 ? values[idx.arsize] : "";
        sample.arburst = idx.arburst >= 0 ? values[idx.arburst] : "";
        sample.rid = idx.rid >= 0 ? values[idx.rid] : "0";
        sample.rdata = idx.rdata >= 0 ? values[idx.rdata] : "";
        sample.rresp = idx.rresp >= 0 ? values[idx.rresp] : "";
        tracker.consume(sample);
    };

    npiFsdbTime min_time = 0;
    npiFsdbTime max_time = 0;
    npi_fsdb_min_time(file, &min_time);
    npi_fsdb_max_time(file, &max_time);

    ClockSampleScanner scanner(file, clock_sample);
    std::string scan_error;
    int sample_count = 0;
    bool truncated = false;
    analysis_probe().record(
        "scan", "axi", name,
        AnalysisProbeMetrics{repository_->stats().canonical_entry_count,
                             repository_->stats().index_count, 0, 0, 1});
    std::size_t observed_samples = 0;
    bool budget_failed = false;
    const bool scan_ok = scanner.scan(
        sample_signals, min_time, max_time, npiFsdbHexStrVal, '\0', -1,
        [&](const ClockSample& sample) -> bool {
            process_edge(sample.time, sample.values);
            ++observed_samples;
            if ((observed_samples & (observed_samples - 1)) == 0) {
                const std::uint64_t bytes =
                    tracker.estimated_working_set_bytes();
                if (!repository_->update_canonical_build_bytes(
                        key, bytes, last_cache_error_)) {
                    budget_failed = true;
                    return false;
                }
            }
            return true;
        }, scan_error, sample_count, truncated);
    if (budget_failed) {
        if (cache_error != nullptr) *cache_error = last_cache_error_;
        return false;
    }
    if (!scan_ok) {
        last_cache_error_.message = scan_error;
        return fail_build("scan_failed");
    }

    std::shared_ptr<AxiResult> result(new AxiResult(
        tracker.finish(min_time, max_time, !truncated)));
    decorate_result_widths(file, config, *result);
    result->diagnostics.full_scan_count = 1;
    const std::uint64_t resident_bytes = estimate_axi_result_bytes(*result);
    if (!repository_->update_canonical_build_bytes(
            key, resident_bytes, last_cache_error_)) {
        if (cache_error != nullptr) *cache_error = last_cache_error_;
        return false;
    }
    if (!repository_->publish_canonical<AxiResult>(
            key, kAxiResultTypeTag,
            std::static_pointer_cast<const AxiResult>(result), resident_bytes,
            last_cache_error_)) {
        if (cache_error != nullptr) *cache_error = last_cache_error_;
        return false;
    }
    return true;
    } catch (const std::bad_alloc&) {
        repository_->fail_canonical_bad_alloc(key, last_cache_error_);
        if (cache_error != nullptr) *cache_error = last_cache_error_;
        return false;
    }
}

size_t AxiAnalyzer::get_write_count(const std::string& name) const {
    const AxiResult* r = get_result(name);
    return r ? r->writes.size() : 0;
}

size_t AxiAnalyzer::get_read_count(const std::string& name) const {
    const AxiResult* r = get_result(name);
    return r ? r->reads.size() : 0;
}

bool AxiAnalyzer::ensure_address_index(const std::string& name) const {
    return numeric_index(name, "address", true) != nullptr;
}

bool AxiAnalyzer::ensure_id_index(const std::string& name) const {
    return numeric_index(name, "id", true) != nullptr;
}

std::uint64_t AxiAnalyzer::estimate_numeric_index_bytes(
    const NumericIndex& index) {
    std::uint64_t bytes = sizeof(index);
    for (const auto& bucket : index) {
        bytes += sizeof(bucket);
        bytes += bucket.second.writes.capacity() * sizeof(std::size_t);
        bytes += bucket.second.reads.capacity() * sizeof(std::size_t);
    }
    return bytes;
}

const AxiAnalyzer::NumericIndex* AxiAnalyzer::numeric_index(
    const std::string& name, const std::string& kind,
    bool record_access) const {
    last_cache_error_ = AnalysisCacheError();
    std::uint64_t generation = 0;
    const AxiResult* result = get_result_internal(name, &generation);
    auto key_it = keys_.find(name);
    if (!result || key_it == keys_.end() || repository_ == nullptr) return nullptr;
    const std::string index_kind = kind == "id" ? "id" : "address";
    const std::string type_tag = "axi_numeric_index.v1";
    if (!record_access) {
        std::shared_ptr<const NumericIndex> cached =
            repository_->peek_index<NumericIndex>(
                key_it->second, generation, index_kind, type_tag);
        if (cached) return cached.get();
    }
    const AnalysisAcquireStatus acquire = repository_->begin_index(
        key_it->second, generation, index_kind, type_tag,
        sizeof(NumericIndex), last_cache_error_);
    if (acquire == AnalysisAcquireStatus::Hit) {
        return repository_->peek_index<NumericIndex>(
            key_it->second, generation, index_kind, type_tag).get();
    }
    if (acquire != AnalysisAcquireStatus::BuildStarted) return nullptr;

    try {
    std::shared_ptr<NumericIndex> index(new NumericIndex());
    std::size_t inserted = 0;
    auto add = [&](const AxiTransaction& txn, bool write,
                   std::size_t position) -> bool {
        std::uint64_t value = 0;
        const std::string& text = kind == "id" ? txn.id : txn.addr;
        if (!parse_hex_value(text, value)) return true;
        DirectionBucket& bucket = (*index)[value];
        (write ? bucket.writes : bucket.reads).push_back(position);
        ++inserted;
        if ((inserted & (inserted - 1)) != 0) return true;
        return repository_->update_index_build_bytes(
            key_it->second, generation, index_kind,
            estimate_numeric_index_bytes(*index), last_cache_error_);
    };
    for (std::size_t i = 0; i < result->writes.size(); ++i) {
        if (!add(result->writes[i], true, i)) return nullptr;
    }
    for (std::size_t i = 0; i < result->reads.size(); ++i) {
        if (!add(result->reads[i], false, i)) return nullptr;
    }
    const std::uint64_t bytes = estimate_numeric_index_bytes(*index);
    if (!repository_->update_index_build_bytes(
            key_it->second, generation, index_kind, bytes,
            last_cache_error_)) return nullptr;
    if (!repository_->publish_index<NumericIndex>(
            key_it->second, generation, index_kind, type_tag,
            std::static_pointer_cast<const NumericIndex>(index), bytes,
            last_cache_error_)) return nullptr;
    return repository_->peek_index<NumericIndex>(
        key_it->second, generation, index_kind, type_tag).get();
    } catch (const std::bad_alloc&) {
        repository_->fail_index_bad_alloc(
            key_it->second, generation, index_kind, last_cache_error_);
        return nullptr;
    }
}

bool AxiAnalyzer::get_write_by_addr(const std::string& name, uint64_t addr,
                                    const AxiTransaction*& out) const {
    return get_write_by_addr_num(name, addr, 1, out);
}

bool AxiAnalyzer::get_write_by_addr_num(const std::string& name, uint64_t addr,
                                        size_t num,
                                        const AxiTransaction*& out) const {
    const AxiResult* result = get_result(name);
    const NumericIndex* index = numeric_index(name, "address");
    if (!result || !index || num == 0) return false;
    auto found = index->find(addr);
    if (found == index->end() || num > found->second.writes.size()) return false;
    out = &result->writes[found->second.writes[num - 1]];
    return true;
}

bool AxiAnalyzer::get_write_by_addr_last(const std::string& name, uint64_t addr,
                                         const AxiTransaction*& out) const {
    const AxiResult* result = get_result(name);
    const NumericIndex* index = numeric_index(name, "address");
    if (!result || !index) return false;
    auto found = index->find(addr);
    if (found == index->end() || found->second.writes.empty()) return false;
    out = &result->writes[found->second.writes.back()];
    return true;
}

bool AxiAnalyzer::get_write_by_num(const std::string& name, size_t num, const AxiTransaction*& out) const {
    const AxiResult* r = get_result(name);
    if (!r || num == 0 || num > r->writes.size()) return false;
    out = &r->writes[num - 1];
    return true;
}

bool AxiAnalyzer::get_write_last(const std::string& name, const AxiTransaction*& out) const {
    const AxiResult* r = get_result(name);
    if (!r || r->writes.empty()) return false;
    out = &r->writes.back();
    return true;
}

bool AxiAnalyzer::get_write_by_addr(const std::string& name, uint64_t addr,
                                    const char* id_str,
                                    const AxiTransaction*& out) const {
    return get_write_by_addr_num(name, addr, id_str, 1, out);
}

bool AxiAnalyzer::get_write_by_addr_num(const std::string& name, uint64_t addr,
                                        const char* id_str, size_t num,
                                        const AxiTransaction*& out) const {
    const AxiResult* result = get_result(name);
    const NumericIndex* index = numeric_index(name, "address");
    if (!result || !index || num == 0) return false;
    auto found = index->find(addr);
    if (found == index->end()) return false;
    std::size_t matched = 0;
    for (std::size_t position : found->second.writes) {
        const AxiTransaction& txn = result->writes[position];
        if (id_matches(txn.id, id_str) && ++matched == num) {
            out = &txn;
            return true;
        }
    }
    return false;
}

bool AxiAnalyzer::get_write_by_addr_last(const std::string& name, uint64_t addr,
                                         const char* id_str,
                                         const AxiTransaction*& out) const {
    const AxiResult* result = get_result(name);
    const NumericIndex* index = numeric_index(name, "address");
    if (!result || !index) return false;
    auto bucket = index->find(addr);
    if (bucket == index->end()) return false;
    const AxiTransaction* found = nullptr;
    for (std::size_t position : bucket->second.writes)
        if (id_matches(result->writes[position].id, id_str))
            found = &result->writes[position];
    if (!found) return false;
    out = found;
    return true;
}

bool AxiAnalyzer::get_write_by_num(const std::string& name, const char* id_str,
                                   size_t num,
                                   const AxiTransaction*& out) const {
    const AxiResult* result = get_result(name);
    const NumericIndex* index = numeric_index(name, "id");
    if (!result || !index || num == 0) return false;
    char* end = nullptr;
    const std::uint64_t id = std::strtoull(id_str, &end, 0);
    if (end == id_str) return false;
    auto found = index->find(id);
    if (found == index->end() || num > found->second.writes.size()) return false;
    out = &result->writes[found->second.writes[num - 1]];
    return true;
}

bool AxiAnalyzer::get_write_last(const std::string& name, const char* id_str,
                                 const AxiTransaction*& out) const {
    const AxiResult* result = get_result(name);
    const NumericIndex* index = numeric_index(name, "id");
    if (!result || !index) return false;
    char* end = nullptr;
    const std::uint64_t id = std::strtoull(id_str, &end, 0);
    if (end == id_str) return false;
    auto found = index->find(id);
    if (found == index->end() || found->second.writes.empty()) return false;
    out = &result->writes[found->second.writes.back()];
    return true;
}

bool AxiAnalyzer::get_read_by_addr(const std::string& name, uint64_t addr,
                                   const AxiTransaction*& out) const {
    return get_read_by_addr_num(name, addr, 1, out);
}

bool AxiAnalyzer::get_read_by_addr_num(const std::string& name, uint64_t addr,
                                       size_t num,
                                       const AxiTransaction*& out) const {
    const AxiResult* result = get_result(name);
    const NumericIndex* index = numeric_index(name, "address");
    if (!result || !index || num == 0) return false;
    auto found = index->find(addr);
    if (found == index->end() || num > found->second.reads.size()) return false;
    out = &result->reads[found->second.reads[num - 1]];
    return true;
}

bool AxiAnalyzer::get_read_by_addr_last(const std::string& name, uint64_t addr,
                                        const AxiTransaction*& out) const {
    const AxiResult* result = get_result(name);
    const NumericIndex* index = numeric_index(name, "address");
    if (!result || !index) return false;
    auto found = index->find(addr);
    if (found == index->end() || found->second.reads.empty()) return false;
    out = &result->reads[found->second.reads.back()];
    return true;
}

bool AxiAnalyzer::get_read_by_num(const std::string& name, size_t num, const AxiTransaction*& out) const {
    const AxiResult* r = get_result(name);
    if (!r || num == 0 || num > r->reads.size()) return false;
    out = &r->reads[num - 1];
    return true;
}

bool AxiAnalyzer::get_read_last(const std::string& name, const AxiTransaction*& out) const {
    const AxiResult* r = get_result(name);
    if (!r || r->reads.empty()) return false;
    out = &r->reads.back();
    return true;
}

bool AxiAnalyzer::get_read_by_addr(const std::string& name, uint64_t addr,
                                   const char* id_str,
                                   const AxiTransaction*& out) const {
    return get_read_by_addr_num(name, addr, id_str, 1, out);
}

bool AxiAnalyzer::get_read_by_addr_num(const std::string& name, uint64_t addr,
                                       const char* id_str, size_t num,
                                       const AxiTransaction*& out) const {
    const AxiResult* result = get_result(name);
    const NumericIndex* index = numeric_index(name, "address");
    if (!result || !index || num == 0) return false;
    auto found = index->find(addr);
    if (found == index->end()) return false;
    std::size_t matched = 0;
    for (std::size_t position : found->second.reads) {
        const AxiTransaction& txn = result->reads[position];
        if (id_matches(txn.id, id_str) && ++matched == num) {
            out = &txn;
            return true;
        }
    }
    return false;
}

bool AxiAnalyzer::get_read_by_addr_last(const std::string& name, uint64_t addr,
                                        const char* id_str,
                                        const AxiTransaction*& out) const {
    const AxiResult* result = get_result(name);
    const NumericIndex* index = numeric_index(name, "address");
    if (!result || !index) return false;
    auto bucket = index->find(addr);
    if (bucket == index->end()) return false;
    const AxiTransaction* found = nullptr;
    for (std::size_t position : bucket->second.reads)
        if (id_matches(result->reads[position].id, id_str))
            found = &result->reads[position];
    if (!found) return false;
    out = found;
    return true;
}

bool AxiAnalyzer::get_read_by_num(const std::string& name, const char* id_str,
                                  size_t num,
                                  const AxiTransaction*& out) const {
    const AxiResult* result = get_result(name);
    const NumericIndex* index = numeric_index(name, "id");
    if (!result || !index || num == 0) return false;
    char* end = nullptr;
    const std::uint64_t id = std::strtoull(id_str, &end, 0);
    if (end == id_str) return false;
    auto found = index->find(id);
    if (found == index->end() || num > found->second.reads.size()) return false;
    out = &result->reads[found->second.reads[num - 1]];
    return true;
}

bool AxiAnalyzer::get_read_last(const std::string& name, const char* id_str,
                                const AxiTransaction*& out) const {
    const AxiResult* result = get_result(name);
    const NumericIndex* index = numeric_index(name, "id");
    if (!result || !index) return false;
    char* end = nullptr;
    const std::uint64_t id = std::strtoull(id_str, &end, 0);
    if (end == id_str) return false;
    auto found = index->find(id);
    if (found == index->end() || found->second.reads.empty()) return false;
    out = &result->reads[found->second.reads.back()];
    return true;
}

bool AxiAnalyzer::cursor_begin(const std::string& name, int filter, const AxiTransaction*& out) {
    std::uint64_t generation = 0;
    const AxiResult* result = get_result_internal(name, &generation);
    auto key = keys_.find(name);
    if (!result || key == keys_.end() || repository_ == nullptr ||
        transaction_count(*result, filter) == 0) return false;
    GenerationCursor cursor;
    cursor.cursor_id = cursor_id(name, filter);
    cursor.key = key->second;
    cursor.generation = generation;
    cursor.direction = filter == 1 ? "write" : filter == 2 ? "read" : "all";
    cursor.position = 0;
    repository_->put_cursor(cursor);
    out = transaction_at(*result, filter, 0);
    return out != nullptr;
}

bool AxiAnalyzer::cursor_next(const std::string& name, int filter, const AxiTransaction*& out) {
    std::uint64_t generation = 0;
    const AxiResult* result = get_result_internal(name, &generation);
    auto key = keys_.find(name);
    if (!result || key == keys_.end() || repository_ == nullptr) return false;
    GenerationCursor cursor;
    if (!repository_->get_cursor(cursor_id(name, filter), cursor)) {
        cursor.cursor_id = cursor_id(name, filter);
        cursor.key = key->second;
        cursor.generation = generation;
        cursor.direction = filter == 1 ? "write" : filter == 2 ? "read" : "all";
        cursor.position = 0;
    } else if (cursor.generation != generation &&
               !repository_->resume_cursor(cursor.cursor_id, key->second,
                                            generation, cursor)) {
        return false;
    }
    if (cursor.position + 1 >= transaction_count(*result, filter)) return false;
    ++cursor.position;
    repository_->put_cursor(cursor);
    out = transaction_at(*result, filter, cursor.position);
    return out != nullptr;
}

bool AxiAnalyzer::cursor_prev(const std::string& name, int filter, const AxiTransaction*& out) {
    std::uint64_t generation = 0;
    const AxiResult* result = get_result_internal(name, &generation);
    auto key = keys_.find(name);
    GenerationCursor cursor;
    if (!result || key == keys_.end() || repository_ == nullptr ||
        !repository_->get_cursor(cursor_id(name, filter), cursor)) return false;
    if (cursor.generation != generation &&
        !repository_->resume_cursor(cursor.cursor_id, key->second,
                                    generation, cursor)) return false;
    if (cursor.position == 0) return false;
    --cursor.position;
    repository_->put_cursor(cursor);
    out = transaction_at(*result, filter, cursor.position);
    return out != nullptr;
}

bool AxiAnalyzer::cursor_last(const std::string& name, int filter, const AxiTransaction*& out) {
    std::uint64_t generation = 0;
    const AxiResult* result = get_result_internal(name, &generation);
    auto key = keys_.find(name);
    const std::size_t count = result ? transaction_count(*result, filter) : 0;
    if (!result || key == keys_.end() || repository_ == nullptr || count == 0)
        return false;
    GenerationCursor cursor;
    cursor.cursor_id = cursor_id(name, filter);
    cursor.key = key->second;
    cursor.generation = generation;
    cursor.direction = filter == 1 ? "write" : filter == 2 ? "read" : "all";
    cursor.position = count - 1;
    repository_->put_cursor(cursor);
    out = transaction_at(*result, filter, cursor.position);
    return out != nullptr;
}

bool AxiAnalyzer::cursor_state(const std::string& name, int filter,
                               size_t& one_based_index, size_t& total_count) const {
    std::uint64_t generation = 0;
    const AxiResult* result = get_result_internal(name, &generation);
    auto key = keys_.find(name);
    if (!result || key == keys_.end() || repository_ == nullptr) return false;
    total_count = transaction_count(*result, filter);
    GenerationCursor cursor;
    if (!repository_->get_cursor(cursor_id(name, filter), cursor)) {
        one_based_index = total_count == 0 ? 0 : 1;
        return true;
    }
    if (cursor.generation != generation &&
        !repository_->resume_cursor(cursor.cursor_id, key->second,
                                    generation, cursor)) return false;
    one_based_index = total_count == 0 ? 0 : cursor.position + 1;
    return true;
}

std::string AxiAnalyzer::cursor_id(const std::string& name, int filter) {
    return "axi:" + name + ":" +
           (filter == 1 ? "write" : filter == 2 ? "read" : "all");
}

std::size_t AxiAnalyzer::transaction_count(const AxiResult& result, int filter) {
    return filter == 1 ? result.writes.size()
                       : filter == 2 ? result.reads.size()
                                     : result.all.size();
}

const AxiTransaction* AxiAnalyzer::transaction_at(const AxiResult& result,
                                                  int filter,
                                                  std::size_t position) {
    if (position >= transaction_count(result, filter)) return nullptr;
    return filter == 1 ? &result.writes[position]
                       : filter == 2 ? &result.reads[position]
                                     : &result.all[position];
}

bool AxiAnalyzer::get_latency_stats(const std::string& name, bool is_write,
                                    const AxiTransaction*& max_txn,
                                    const AxiTransaction*& min_txn,
                                    double& avg_latency) const {
    const AxiResult* r = get_result(name);
    if (!r) return false;
    const auto& vec = is_write ? r->writes : r->reads;
    if (vec.empty()) return false;

    const AxiTransaction* max_t = &vec[0];
    const AxiTransaction* min_t = &vec[0];
    double total = 0.0;

    for (const auto& txn : vec) {
        double lat = static_cast<double>(txn.resp_time) - static_cast<double>(txn.addr_time);
        total += lat;
        double max_lat = static_cast<double>(max_t->resp_time) - static_cast<double>(max_t->addr_time);
        double min_lat = static_cast<double>(min_t->resp_time) - static_cast<double>(min_t->addr_time);
        if (lat > max_lat) max_t = &txn;
        if (lat < min_lat) min_t = &txn;
    }

    max_txn = max_t;
    min_txn = min_t;
    avg_latency = total / vec.size();
    return true;
}

bool AxiAnalyzer::get_latency_stats(const std::string& name, int filter, const char* id_str,
                                    AxiStatResult& out) const {
    const AxiResult* r = get_result(name);
    if (!r) return false;

    bool include_wr = (filter == 0 || filter == 1);
    bool include_rd = (filter == 0 || filter == 2);
    double total = 0.0;
    std::vector<double> latencies;
    bool seen = false;

    auto visit = [&](const AxiTransaction& txn) {
        if (!id_matches(txn.id, id_str)) return;
        double lat = static_cast<double>(txn.resp_time) - static_cast<double>(txn.addr_time);
        if (!seen) {
            out.max = lat;
            out.min = lat;
            out.max_txn = &txn;
            out.min_txn = &txn;
            seen = true;
        } else {
            if (lat > out.max) {
                out.max = lat;
                out.max_txn = &txn;
            }
            if (lat < out.min) {
                out.min = lat;
                out.min_txn = &txn;
            }
        }
        total += lat;
        latencies.push_back(lat);
        ++out.samples;
    };

    if (include_wr) {
        for (const auto& txn : r->writes) visit(txn);
    }
    if (include_rd) {
        for (const auto& txn : r->reads) visit(txn);
    }

    if (!seen || out.samples == 0) return false;
    out.avg = total / static_cast<double>(out.samples);
    std::sort(latencies.begin(), latencies.end());
    auto percentile = [&](size_t percent) {
        size_t rank = (percent * latencies.size() + 99) / 100;
        if (rank == 0) rank = 1;
        return latencies[rank - 1];
    };
    out.p50 = percentile(50);
    out.p95 = percentile(95);
    out.p99 = percentile(99);
    return true;
}

bool AxiAnalyzer::get_outstanding_stats(const std::string& name, int filter, const char* id_str,
                                        AxiStatResult& out) const {
    const AxiResult* r = get_result(name);
    if (!r || r->outstanding_samples.empty()) return false;

    bool seen = false;
    double total = 0.0;

    for (const auto& sample : r->outstanding_samples) {
        int value = 0;
        if (id_str) {
            uint64_t want = 0;
            char* end = nullptr;
            want = strtoull(id_str, &end, 0);
            if (end == id_str) return false;

            auto add_matching = [&](const std::map<std::string, int>& m) {
                for (const auto& kv : m) {
                    uint64_t id_val = 0;
                    if (parse_hex_value(kv.first, id_val) && id_val == want) {
                        value += kv.second;
                    }
                }
            };
            if (filter == 0 || filter == 1) add_matching(sample.write_by_id);
            if (filter == 0 || filter == 2) add_matching(sample.read_by_id);
        } else {
            if (filter == 0 || filter == 1) value += sample.write;
            if (filter == 0 || filter == 2) value += sample.read;
        }

        if (!seen) {
            out.max = value;
            out.min = value;
            seen = true;
        } else {
            if (value > out.max) out.max = value;
            if (value < out.min) out.min = value;
        }
        total += value;
        ++out.samples;
    }

    if (!seen || out.samples == 0) return false;
    out.avg = total / static_cast<double>(out.samples);
    return true;
}

bool AxiAnalyzer::get_transactions_in_range(const std::string& name,
                                            npiFsdbTime begin,
                                            npiFsdbTime end,
                                            std::vector<AxiContextTransaction>& out,
                                            int max_results) const {
    out.clear();
    const AxiResult* r = get_result(name);
    if (!r) return false;

    std::set<const AxiTransaction*> emitted;
    auto emit = [&](const AxiTransaction& txn, npiFsdbTime match_time) {
        if (max_results >= 0 && static_cast<int>(out.size()) >= max_results) return;
        if (!emitted.insert(&txn).second) return;
        AxiContextTransaction item;
        item.txn = &txn;
        item.match_time = match_time;
        out.push_back(item);
    };

    auto addr_it = std::lower_bound(r->all.begin(), r->all.end(), begin,
        [](const AxiTransaction& txn, npiFsdbTime t) {
            return txn.addr_time < t;
        });
    for (; addr_it != r->all.end() && addr_it->addr_time <= end; ++addr_it) {
        if (max_results >= 0 && static_cast<int>(out.size()) >= max_results) break;
        emit(*addr_it, addr_it->addr_time);
    }

    auto resp_it = std::lower_bound(r->all_by_resp_time.begin(), r->all_by_resp_time.end(), begin,
        [&](size_t idx, npiFsdbTime t) {
            return r->all[idx].resp_time < t;
        });
    for (; resp_it != r->all_by_resp_time.end(); ++resp_it) {
        if (max_results >= 0 && static_cast<int>(out.size()) >= max_results) break;
        const AxiTransaction& txn = r->all[*resp_it];
        if (txn.resp_time > end) break;
        emit(txn, txn.resp_time);
    }

    std::sort(out.begin(), out.end(), [](const AxiContextTransaction& lhs, const AxiContextTransaction& rhs) {
        return lhs.match_time < rhs.match_time;
    });
    return true;
}

std::uint64_t AxiAnalyzer::estimate_handshake_index_bytes(
    const HandshakeIndex& index) {
    return sizeof(index) +
           index.capacity() * sizeof(HandshakeIndexEntry);
}

const AxiAnalyzer::HandshakeIndex* AxiAnalyzer::handshake_index(
        const std::string& name, const std::string& channel) const {
    last_cache_error_ = AnalysisCacheError();
    std::uint64_t generation = 0;
    const AxiResult* result = get_result_internal(name, &generation);
    auto key = keys_.find(name);
    if (!result || key == keys_.end() || repository_ == nullptr) return nullptr;
    const std::string index_kind = "handshake:" + channel;
    const std::string type_tag = "axi_handshake_index.v1";
    const AnalysisAcquireStatus acquire = repository_->begin_index(
        key->second, generation, index_kind, type_tag,
        sizeof(HandshakeIndex), last_cache_error_);
    if (acquire == AnalysisAcquireStatus::Hit) {
        return repository_->peek_index<HandshakeIndex>(
            key->second, generation, index_kind, type_tag).get();
    }
    if (acquire != AnalysisAcquireStatus::BuildStarted) return nullptr;

    try {
    std::shared_ptr<HandshakeIndex> index(new HandshakeIndex());
    const bool write_channel = channel == "aw" || channel == "w" || channel == "b";
    const std::vector<AxiTransaction>& txns = write_channel ? result->writes : result->reads;
    for (std::size_t transaction_index = 0;
         transaction_index < txns.size(); ++transaction_index) {
        const AxiTransaction& txn = txns[transaction_index];
        if (channel == "aw" || channel == "ar") {
            index->push_back(
                {txn.addr_time, write_channel, transaction_index, 0});
        } else if (channel == "b") {
            index->push_back(
                {txn.resp_time, write_channel, transaction_index, 0});
        } else if (channel == "w" || channel == "r") {
            for (size_t i = 0; i < txn.data_handshake_times.size(); ++i)
                index->push_back({txn.data_handshake_times[i], write_channel,
                                  transaction_index, i + 1});
        }
    }
    std::sort(index->begin(), index->end(),
              [&](const HandshakeIndexEntry& lhs,
                  const HandshakeIndexEntry& rhs) {
        if (lhs.time != rhs.time) return lhs.time < rhs.time;
        const AxiTransaction& lhs_txn =
            (lhs.is_write ? result->writes : result->reads)[lhs.transaction_index];
        const AxiTransaction& rhs_txn =
            (rhs.is_write ? result->writes : result->reads)[rhs.transaction_index];
        if (lhs_txn.seq != rhs_txn.seq) return lhs_txn.seq < rhs_txn.seq;
        return lhs.beat_index < rhs.beat_index;
    });
    const std::uint64_t bytes = estimate_handshake_index_bytes(*index);
    if (!repository_->update_index_build_bytes(
            key->second, generation, index_kind, bytes,
            last_cache_error_)) return nullptr;
    if (!repository_->publish_index<HandshakeIndex>(
            key->second, generation, index_kind, type_tag,
            std::static_pointer_cast<const HandshakeIndex>(index), bytes,
            last_cache_error_)) return nullptr;
    return repository_->peek_index<HandshakeIndex>(
        key->second, generation, index_kind, type_tag).get();
    } catch (const std::bad_alloc&) {
        repository_->fail_index_bad_alloc(
            key->second, generation, index_kind, last_cache_error_);
        return nullptr;
    }
}

bool AxiAnalyzer::get_by_handshake(const std::string& name,
                                   const std::string& channel,
                                   npiFsdbTime handshake_time,
                                   AxiHandshakeMatch& out) const {
    out = AxiHandshakeMatch();
    if (channel != "aw" && channel != "w" && channel != "b" &&
        channel != "ar" && channel != "r") return false;
    const std::vector<HandshakeIndexEntry>* index = handshake_index(name, channel);
    if (!index) return false;
    auto it = std::lower_bound(index->begin(), index->end(), handshake_time,
        [](const HandshakeIndexEntry& item, npiFsdbTime time) {
            return item.time < time;
        });
    if (it == index->end() || it->time != handshake_time) return false;
    const AxiResult* result = get_result(name);
    if (!result) return false;
    const std::vector<AxiTransaction>& transactions =
        it->is_write ? result->writes : result->reads;
    if (it->transaction_index >= transactions.size()) return false;
    out.txn = &transactions[it->transaction_index];
    out.channel = channel;
    out.handshake_time = it->time;
    out.beat_index = it->beat_index;
    return out.txn != nullptr;
}

bool AxiAnalyzer::get_outstanding_samples_in_range(const std::string& name,
                                                   npiFsdbTime begin,
                                                   npiFsdbTime end,
                                                   std::vector<AxiOutstandingSample>& out,
                                                   int max_results) const {
    out.clear();
    const AxiResult* r = get_result(name);
    if (!r) return false;
    auto it = std::lower_bound(r->outstanding_samples.begin(), r->outstanding_samples.end(), begin,
        [](const AxiOutstandingSample& sample, npiFsdbTime t) {
            return sample.time < t;
        });
    for (; it != r->outstanding_samples.end() && it->time <= end; ++it) {
        if (max_results >= 0 && static_cast<int>(out.size()) >= max_results) break;
        out.push_back(*it);
    }
    return true;
}

bool AxiAnalyzer::summarize_outstanding_in_range(const std::string& name,
                                                  npiFsdbTime begin,
                                                  npiFsdbTime end,
                                                  int filter,
                                                  int max_change_points,
                                                  AxiOutstandingSummary& out) const {
    out = AxiOutstandingSummary();
    const AxiResult* result = get_result(name);
    if (!result) return false;
    auto it = std::lower_bound(result->outstanding_samples.begin(),
                               result->outstanding_samples.end(), begin,
        [](const AxiOutstandingSample& sample, npiFsdbTime time) {
            return sample.time < time;
        });
    int previous_read = -1;
    int previous_write = -1;
    for (; it != result->outstanding_samples.end() && it->time <= end; ++it) {
        ++out.sample_count;
        out.has_samples = true;
        out.final_read = it->read;
        out.final_write = it->write;
        if (it->read > out.peak_read) {
            out.peak_read = it->read;
            out.peak_read_time = it->time;
        }
        if (it->write > out.peak_write) {
            out.peak_write = it->write;
            out.peak_write_time = it->time;
        }
        if (!out.has_first_nonzero && (it->read > 0 || it->write > 0)) {
            out.has_first_nonzero = true;
            out.first_nonzero_time = it->time;
        }
        const int visible_read = filter == 1 ? 0 : it->read;
        const int visible_write = filter == 2 ? 0 : it->write;
        if (visible_read == previous_read && visible_write == previous_write) continue;
        ++out.change_point_count;
        if (max_change_points < 0 ||
            static_cast<int>(out.change_points.size()) < max_change_points) {
            out.change_points.push_back(*it);
        }
        previous_read = visible_read;
        previous_write = visible_write;
    }
    return true;
}

} // namespace xdebug_waveform
