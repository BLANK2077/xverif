#include "apb_analyzer.h"
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
#include <memory>
#include "json.hpp"

namespace xdebug_waveform {

namespace {

constexpr std::uint32_t kApbFingerprintVersion = 2;
const char* kApbResultTypeTag = "apb_result.v1";

std::string normalized_apb_config_semantics(const ApbConfig& config) {
    nlohmann::ordered_json value;
    value["paddr"] = config.paddr;
    value["psel"] = config.psel;
    value["penable"] = config.penable;
    value["pwrite"] = config.pwrite;
    value["pwdata"] = config.pwdata;
    value["prdata"] = config.prdata;
    value["pready"] = config.pready;
    value["pslverr"] = config.pslverr;
    value["clock"] = config.clock_sample.clock;
    value["edge"] = clock_edge_kind_text(config.clock_sample.edge);
    if (config.clock_sample.edge != ClockEdgeKind::Negedge)
        value["sample_point"] =
            clock_sample_point_text(config.clock_sample.sample_point);
    value["reset"] = reset_config_json(config.reset);
    return value.dump();
}

}  // namespace

bool ApbAnalyzer::parse_hex_value(const std::string& hex_str, uint64_t& out) {
    if (hex_str.empty()) return false;
    const char* start = hex_str.c_str();
    char* end = nullptr;
    out = strtoull(start, &end, 16);
    return end != start;
}

void ApbAnalyzer::configure_repository(AnalysisRepository* repository,
                                       const std::string& session_id,
                                       const FsdbIdentity& fsdb_identity) {
    repository_ = repository;
    session_id_ = session_id;
    fsdb_identity_ = fsdb_identity;
    keys_.clear();
    last_cache_error_ = AnalysisCacheError();
}

AnalysisCacheKey ApbAnalyzer::cache_key(const ApbConfig& config) const {
    return make_analysis_cache_key(
        "apb", session_id_, fsdb_identity_, kApbFingerprintVersion,
        normalized_apb_config_semantics(config), AnalysisCacheScope::Full);
}

const ApbResult* ApbAnalyzer::get_result_internal(
    const std::string& name, std::uint64_t* generation) const {
    if (repository_ == nullptr) return nullptr;
    auto found = keys_.find(name);
    if (found == keys_.end()) return nullptr;
    return repository_->peek_canonical<ApbResult>(
        found->second, kApbResultTypeTag, generation).get();
}

const ApbResult* ApbAnalyzer::get_result(const std::string& name) const {
    return get_result_internal(name, nullptr);
}

bool ApbAnalyzer::analyze(const std::string& name, npiFsdbFileHandle file,
                          const ApbConfig& config,
                          AnalysisCacheError* cache_error) {
    last_cache_error_ = AnalysisCacheError();
    if (repository_ == nullptr) {
        last_cache_error_.code = "ANALYSIS_REPOSITORY_UNAVAILABLE";
        last_cache_error_.message = "APB analysis repository is not configured";
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
        key, kApbResultTypeTag, sizeof(ApbResult), last_cache_error_);
    if (acquire == AnalysisAcquireStatus::Hit) return true;
    if (acquire != AnalysisAcquireStatus::BuildStarted) {
        if (cache_error != nullptr) *cache_error = last_cache_error_;
        return false;
    }
    auto fail_build = [&](const std::string& reason) {
        repository_->fail_canonical(key, reason);
        if (last_cache_error_.message.empty())
            last_cache_error_.message = "failed to build APB analysis";
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

    std::vector<std::string> signals = {
        config.reset.signal, config.psel, config.penable,
        config.pwrite, config.paddr, config.pwdata, config.prdata
    };
    int pready_index = -1;
    int pslverr_index = -1;
    // APB2 has neither signal: an access completes without a PREADY sample
    // and cannot report a slave error.  Optional APB3/APB4 signals are only
    // added to the scanner when the interface contract names them.
    if (!config.pready.empty()) {
        pready_index = static_cast<int>(signals.size());
        signals.push_back(config.pready);
    }
    if (!config.pslverr.empty()) {
        pslverr_index = static_cast<int>(signals.size());
        signals.push_back(config.pslverr);
    }
    std::vector<npiFsdbSigHandle> sig_handles;
    sig_handles.reserve(signals.size());
    for (const auto& signal : signals) {
        npiFsdbSigHandle h = npi_fsdb_sig_by_name(file, signal.c_str(), NULL);
        if (!h) {
            last_cache_error_.message = "APB signal not found: " + signal;
            return fail_build("signal_not_found");
        }
        sig_handles.push_back(h);
    }
    std::vector<ClockSampleSignal> sample_signals;
    for (size_t i = 0; i < signals.size(); ++i) {
        sample_signals.push_back({signals[i], signals[i], sig_handles[i]});
    }

    ApbResult result;
    bool completion_seen = false;
    const int paddr_width = fsdb_signal_width(sig_handles[4]).width;
    const int pwdata_width = fsdb_signal_width(sig_handles[5]).width;
    const int prdata_width = fsdb_signal_width(sig_handles[6]).width;

    auto process_edge = [&](npiFsdbTime t, const std::vector<std::string>& values) {
        if (values.size() < signals.size()) return;

        const std::string& reset_value = values[0];
        const std::string& psel_val = values[1];
        const std::string& penable_val = values[2];
        const std::string& pwrite_val = values[3];
        const std::string& paddr_val = values[4];
        const std::string& pwdata_val = values[5];
        const std::string& prdata_val = values[6];

        if (reset_is_active(config.reset, reset_value)) {
            completion_seen = false;
            return;
        }
        // Check psel == 1
        if (psel_val.empty() || psel_val == "0" || psel_val == "X" || psel_val == "Z") {
            completion_seen = false;
            return;
        }
        // Check penable == 1
        if (penable_val.empty() || penable_val == "0" || penable_val == "X" || penable_val == "Z") {
            completion_seen = false;
            return;
        }
        if (pready_index >= 0) {
            const std::string& pready_val =
                values[static_cast<size_t>(pready_index)];
            if (pready_val.empty() || pready_val == "0" ||
                pready_val == "X" || pready_val == "Z") {
                return;
            }
        }
        if (completion_seen) return;
        completion_seen = true;

        bool is_write = !(pwrite_val.empty() || pwrite_val == "0" || pwrite_val == "X" || pwrite_val == "Z");

        ApbTransaction txn;
        txn.time = t;
        txn.addr = paddr_val;
        txn.data = is_write ? pwdata_val : prdata_val;
        txn.is_write = is_write;
        txn.addr_width = paddr_width;
        txn.data_width = is_write ? pwdata_width : prdata_width;
        txn.addr_signal = config.paddr;
        txn.data_signal = is_write ? config.pwdata : config.prdata;
        txn.has_numeric_addr = parse_hex_value(txn.addr, txn.numeric_addr);
        txn.has_error = false;
        if (pslverr_index >= 0) {
            const std::string& pslverr_val =
                values[static_cast<size_t>(pslverr_index)];
            txn.has_error =
                !(pslverr_val.empty() || pslverr_val == "0" ||
                  pslverr_val == "X" || pslverr_val == "Z");
        }

        if (is_write) {
            result.writes.push_back(txn);
        } else {
            result.reads.push_back(txn);
        }
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
        "scan", "apb", name,
        AnalysisProbeMetrics{repository_->stats().canonical_entry_count,
                             repository_->stats().index_count, 0, 0, 1});
    std::size_t observed_samples = 0;
    bool budget_failed = false;
    const bool scan_ok = scanner.scan(
        sample_signals, min_time, max_time, npiFsdbHexStrVal, '\0', -1,
        [&](const ClockSample& sample) -> bool {
            process_edge(sample.time, sample.values);
            ++observed_samples;
            if ((observed_samples & (observed_samples - 1)) == 0 &&
                !repository_->update_canonical_build_bytes(
                    key, estimate_apb_result_bytes(result),
                    last_cache_error_)) {
                budget_failed = true;
                return false;
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
    result.diagnostics.sample_count = static_cast<size_t>(sample_count);
    result.diagnostics.full_scan_count = 1;
    result.diagnostics.analysis_complete = !truncated;
    result.diagnostics.scan_begin = min_time;
    result.diagnostics.scan_end = max_time;
    // Sort by time just in case (though VCT should naturally be in order)
    auto cmp = [](const ApbTransaction& a, const ApbTransaction& b) { return a.time < b.time; };
    std::sort(result.writes.begin(), result.writes.end(), cmp);
    std::sort(result.reads.begin(), result.reads.end(), cmp);
    result.all.reserve(result.writes.size() + result.reads.size());
    size_t write_index = 0;
    size_t read_index = 0;
    while (write_index < result.writes.size() || read_index < result.reads.size()) {
        if (read_index >= result.reads.size() ||
            (write_index < result.writes.size() &&
             result.writes[write_index].time <= result.reads[read_index].time)) {
            result.all.push_back(&result.writes[write_index++]);
        } else {
            result.all.push_back(&result.reads[read_index++]);
        }
    }

    std::shared_ptr<ApbResult> stored(new ApbResult(std::move(result)));
    const std::uint64_t resident_bytes = estimate_apb_result_bytes(*stored);
    if (!repository_->update_canonical_build_bytes(
            key, resident_bytes, last_cache_error_)) {
        if (cache_error != nullptr) *cache_error = last_cache_error_;
        return false;
    }
    if (!repository_->publish_canonical<ApbResult>(
            key, kApbResultTypeTag,
            std::static_pointer_cast<const ApbResult>(stored), resident_bytes,
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

size_t ApbAnalyzer::get_write_count(const std::string& name) const {
    const ApbResult* r = get_result(name);
    return r ? r->writes.size() : 0;
}

size_t ApbAnalyzer::get_read_count(const std::string& name) const {
    const ApbResult* r = get_result(name);
    return r ? r->reads.size() : 0;
}

size_t ApbAnalyzer::transaction_count(const ApbResult& result, int filter) {
    if (filter == 1) return result.writes.size();
    if (filter == 2) return result.reads.size();
    return result.all.size();
}

const ApbTransaction* ApbAnalyzer::transaction_at(
    const ApbResult& result, int filter, size_t index) {
    if (index >= transaction_count(result, filter)) return nullptr;
    if (filter == 1) return &result.writes[index];
    if (filter == 2) return &result.reads[index];
    return result.all[index];
}

size_t ApbAnalyzer::get_count(const std::string& name, int filter) const {
    const ApbResult* result = get_result(name);
    return result ? transaction_count(*result, filter) : 0;
}

bool ApbAnalyzer::ensure_address_index(const std::string& name) const {
    return address_index(name, true) != nullptr;
}

std::uint64_t ApbAnalyzer::estimate_address_index_bytes(
    const AddressIndex& index) {
    std::uint64_t bytes = sizeof(index);
    for (const auto& bucket : index) {
        bytes += sizeof(bucket);
        bytes += bucket.second.all.capacity() * sizeof(size_t);
        bytes += bucket.second.writes.capacity() * sizeof(size_t);
        bytes += bucket.second.reads.capacity() * sizeof(size_t);
    }
    return bytes;
}

const ApbAnalyzer::AddressIndex* ApbAnalyzer::address_index(
    const std::string& name, bool record_access) const {
    last_cache_error_ = AnalysisCacheError();
    std::uint64_t generation = 0;
    const ApbResult* result = get_result_internal(name, &generation);
    auto key = keys_.find(name);
    if (!result || key == keys_.end() || repository_ == nullptr) return nullptr;
    const std::string index_kind = "address";
    const std::string type_tag = "apb_address_index.v1";
    if (!record_access) {
        std::shared_ptr<const AddressIndex> cached =
            repository_->peek_index<AddressIndex>(
                key->second, generation, index_kind, type_tag);
        if (cached) return cached.get();
    }
    const AnalysisAcquireStatus acquire = repository_->begin_index(
        key->second, generation, index_kind, type_tag,
        sizeof(AddressIndex), last_cache_error_);
    if (acquire == AnalysisAcquireStatus::Hit) {
        return repository_->peek_index<AddressIndex>(
            key->second, generation, index_kind, type_tag).get();
    }
    if (acquire != AnalysisAcquireStatus::BuildStarted) return nullptr;

    try {
        std::shared_ptr<AddressIndex> index(new AddressIndex());
        std::size_t inserted = 0;
        auto update_budget = [&]() {
            ++inserted;
            return (inserted & (inserted - 1)) != 0 ||
                repository_->update_index_build_bytes(
                    key->second, generation, index_kind,
                    estimate_address_index_bytes(*index), last_cache_error_);
        };
        for (size_t i = 0; i < result->all.size(); ++i) {
            const ApbTransaction* transaction = result->all[i];
            if (transaction && transaction->has_numeric_addr) {
                (*index)[transaction->numeric_addr].all.push_back(i);
                if (!update_budget()) return nullptr;
            }
        }
        for (size_t i = 0; i < result->writes.size(); ++i) {
            const ApbTransaction& transaction = result->writes[i];
            if (transaction.has_numeric_addr) {
                (*index)[transaction.numeric_addr].writes.push_back(i);
                if (!update_budget()) return nullptr;
            }
        }
        for (size_t i = 0; i < result->reads.size(); ++i) {
            const ApbTransaction& transaction = result->reads[i];
            if (transaction.has_numeric_addr) {
                (*index)[transaction.numeric_addr].reads.push_back(i);
                if (!update_budget()) return nullptr;
            }
        }
        const std::uint64_t bytes = estimate_address_index_bytes(*index);
        if (!repository_->update_index_build_bytes(
                key->second, generation, index_kind, bytes,
                last_cache_error_)) return nullptr;
        if (!repository_->publish_index<AddressIndex>(
                key->second, generation, index_kind, type_tag,
                std::static_pointer_cast<const AddressIndex>(index), bytes,
                last_cache_error_)) return nullptr;
        return repository_->peek_index<AddressIndex>(
            key->second, generation, index_kind, type_tag).get();
    } catch (const std::bad_alloc&) {
        repository_->fail_index_bad_alloc(
            key->second, generation, index_kind, last_cache_error_);
        return nullptr;
    }
}

bool ApbAnalyzer::get_by_addr(const std::string& name, int filter, uint64_t addr,
                              const ApbTransaction*& out) const {
    return get_by_addr_num(name, filter, addr, 1, out);
}

bool ApbAnalyzer::get_by_addr_num(const std::string& name, int filter,
                                  uint64_t addr, size_t num,
                                  const ApbTransaction*& out) const {
    const ApbResult* result = get_result(name);
    const AddressIndex* index = address_index(name);
    if (!result || !index || num == 0) return false;
    auto found = index->find(addr);
    if (found == index->end()) return false;
    const std::vector<size_t>& positions = filter == 1 ? found->second.writes
        : filter == 2 ? found->second.reads : found->second.all;
    if (num > positions.size()) return false;
    out = transaction_at(*result, filter, positions[num - 1]);
    return out != nullptr;
}

bool ApbAnalyzer::get_by_addr_last(const std::string& name, int filter,
                                   uint64_t addr,
                                   const ApbTransaction*& out) const {
    const ApbResult* result = get_result(name);
    const AddressIndex* index = address_index(name);
    if (!result || !index) return false;
    auto found = index->find(addr);
    if (found == index->end()) return false;
    const std::vector<size_t>& positions = filter == 1 ? found->second.writes
        : filter == 2 ? found->second.reads : found->second.all;
    if (positions.empty()) return false;
    out = transaction_at(*result, filter, positions.back());
    return out != nullptr;
}

bool ApbAnalyzer::get_by_num(const std::string& name, int filter, size_t num,
                             const ApbTransaction*& out) const {
    if (num == 0) return false;
    const ApbResult* result = get_result(name);
    if (!result) return false;
    out = transaction_at(*result, filter, num - 1);
    return out != nullptr;
}

bool ApbAnalyzer::get_last(const std::string& name, int filter,
                           const ApbTransaction*& out) const {
    const ApbResult* result = get_result(name);
    const size_t count = result ? transaction_count(*result, filter) : 0;
    if (count == 0) return false;
    out = transaction_at(*result, filter, count - 1);
    return out != nullptr;
}

bool ApbAnalyzer::get_write_by_addr(const std::string& name, uint64_t addr, const ApbTransaction*& out) const {
    return get_by_addr(name, 1, addr, out);
}

bool ApbAnalyzer::get_write_by_addr_num(const std::string& name, uint64_t addr, size_t num, const ApbTransaction*& out) const {
    return get_by_addr_num(name, 1, addr, num, out);
}

bool ApbAnalyzer::get_write_by_addr_last(const std::string& name, uint64_t addr, const ApbTransaction*& out) const {
    return get_by_addr_last(name, 1, addr, out);
}

bool ApbAnalyzer::get_write_by_num(const std::string& name, size_t num, const ApbTransaction*& out) const {
    const ApbResult* r = get_result(name);
    if (!r || num == 0 || num > r->writes.size()) return false;
    out = &r->writes[num - 1];
    return true;
}

bool ApbAnalyzer::get_write_last(const std::string& name, const ApbTransaction*& out) const {
    const ApbResult* r = get_result(name);
    if (!r || r->writes.empty()) return false;
    out = &r->writes.back();
    return true;
}

bool ApbAnalyzer::get_read_by_addr(const std::string& name, uint64_t addr, const ApbTransaction*& out) const {
    return get_by_addr(name, 2, addr, out);
}

bool ApbAnalyzer::get_read_by_addr_num(const std::string& name, uint64_t addr, size_t num, const ApbTransaction*& out) const {
    return get_by_addr_num(name, 2, addr, num, out);
}

bool ApbAnalyzer::get_read_by_addr_last(const std::string& name, uint64_t addr, const ApbTransaction*& out) const {
    return get_by_addr_last(name, 2, addr, out);
}

bool ApbAnalyzer::get_read_by_num(const std::string& name, size_t num, const ApbTransaction*& out) const {
    const ApbResult* r = get_result(name);
    if (!r || num == 0 || num > r->reads.size()) return false;
    out = &r->reads[num - 1];
    return true;
}

bool ApbAnalyzer::get_read_last(const std::string& name, const ApbTransaction*& out) const {
    const ApbResult* r = get_result(name);
    if (!r || r->reads.empty()) return false;
    out = &r->reads.back();
    return true;
}

// Cursor operations
bool ApbAnalyzer::cursor_begin(const std::string& name, int filter, const ApbTransaction*& out) {
    std::uint64_t generation = 0;
    const ApbResult* result = get_result_internal(name, &generation);
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

bool ApbAnalyzer::cursor_next(const std::string& name, int filter, const ApbTransaction*& out) {
    std::uint64_t generation = 0;
    const ApbResult* result = get_result_internal(name, &generation);
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

bool ApbAnalyzer::cursor_prev(const std::string& name, int filter, const ApbTransaction*& out) {
    std::uint64_t generation = 0;
    const ApbResult* result = get_result_internal(name, &generation);
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

bool ApbAnalyzer::cursor_last(const std::string& name, int filter, const ApbTransaction*& out) {
    std::uint64_t generation = 0;
    const ApbResult* result = get_result_internal(name, &generation);
    auto key = keys_.find(name);
    const size_t count = result ? transaction_count(*result, filter) : 0;
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

bool ApbAnalyzer::cursor_state(const std::string& name, int filter,
                               size_t& one_based_index, size_t& total_count) const {
    std::uint64_t generation = 0;
    const ApbResult* result = get_result_internal(name, &generation);
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

std::string ApbAnalyzer::cursor_id(const std::string& name, int filter) {
    return "apb:" + name + ":" +
           (filter == 1 ? "write" : filter == 2 ? "read" : "all");
}

bool ApbAnalyzer::get_transactions_in_range(const std::string& name,
                                            npiFsdbTime begin,
                                            npiFsdbTime end,
                                            std::vector<ApbContextTransaction>& out,
                                            int max_results) const {
    out.clear();
    const ApbResult* r = get_result(name);
    if (!r) return false;

    auto it = std::lower_bound(r->all.begin(), r->all.end(), begin,
        [](const ApbTransaction* txn, npiFsdbTime t) {
            return txn->time < t;
        });
    for (; it != r->all.end() && (*it)->time <= end; ++it) {
        if (max_results >= 0 && static_cast<int>(out.size()) >= max_results) break;
        ApbContextTransaction item;
        item.txn = *it;
        out.push_back(item);
    }
    return true;
}

} // namespace xdebug_waveform
