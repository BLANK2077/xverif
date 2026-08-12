#pragma once

#include "axi_config.h"
#include "axi_transaction_tracker.h"
#include "../cache/analysis_repository.h"
#include "npi_fsdb.h"
#include <string>
#include <vector>
#include <map>

namespace xdebug_waveform {

struct AxiContextTransaction {
    const AxiTransaction* txn = nullptr;
    npiFsdbTime match_time = 0;
};

struct AxiHandshakeMatch {
    const AxiTransaction* txn = nullptr;
    std::string channel;
    npiFsdbTime handshake_time = 0;
    size_t beat_index = 0;
};

struct AxiOutstandingSummary {
    size_t sample_count = 0;
    size_t change_point_count = 0;
    std::vector<AxiOutstandingSample> change_points;
    int peak_read = 0;
    int peak_write = 0;
    npiFsdbTime peak_read_time = 0;
    npiFsdbTime peak_write_time = 0;
    npiFsdbTime first_nonzero_time = 0;
    bool has_first_nonzero = false;
    int final_read = 0;
    int final_write = 0;
    bool has_samples = false;
};

struct AxiStatResult {
    double max = 0.0;
    double min = 0.0;
    double avg = 0.0;
    double p50 = 0.0;
    double p95 = 0.0;
    double p99 = 0.0;
    size_t samples = 0;
    const AxiTransaction* max_txn = nullptr;
    const AxiTransaction* min_txn = nullptr;
};

class AxiAnalyzer {
public:
    void configure_repository(AnalysisRepository* repository,
                              const std::string& session_id,
                              const FsdbIdentity& fsdb_identity);
    bool analyze(const std::string& name, npiFsdbFileHandle file,
                 const AxiConfig& config,
                 AnalysisCacheError* cache_error = nullptr);
    const AxiResult* get_result(const std::string& name) const;
    const AnalysisCacheError& last_cache_error() const { return last_cache_error_; }
    bool ensure_address_index(const std::string& name) const;
    bool ensure_id_index(const std::string& name) const;

    // Getters for wr/rd counts
    size_t get_write_count(const std::string& name) const;
    size_t get_read_count(const std::string& name) const;

    // Query write by various filters
    bool get_write_by_addr(const std::string& name, uint64_t addr, const AxiTransaction*& out) const;
    bool get_write_by_addr_num(const std::string& name, uint64_t addr, size_t num, const AxiTransaction*& out) const;
    bool get_write_by_addr_last(const std::string& name, uint64_t addr, const AxiTransaction*& out) const;
    bool get_write_by_num(const std::string& name, size_t num, const AxiTransaction*& out) const;
    bool get_write_last(const std::string& name, const AxiTransaction*& out) const;
    bool get_write_by_addr(const std::string& name, uint64_t addr, const char* id_str, const AxiTransaction*& out) const;
    bool get_write_by_addr_num(const std::string& name, uint64_t addr, const char* id_str, size_t num, const AxiTransaction*& out) const;
    bool get_write_by_addr_last(const std::string& name, uint64_t addr, const char* id_str, const AxiTransaction*& out) const;
    bool get_write_by_num(const std::string& name, const char* id_str, size_t num, const AxiTransaction*& out) const;
    bool get_write_last(const std::string& name, const char* id_str, const AxiTransaction*& out) const;

    // Query read by various filters (symmetric)
    bool get_read_by_addr(const std::string& name, uint64_t addr, const AxiTransaction*& out) const;
    bool get_read_by_addr_num(const std::string& name, uint64_t addr, size_t num, const AxiTransaction*& out) const;
    bool get_read_by_addr_last(const std::string& name, uint64_t addr, const AxiTransaction*& out) const;
    bool get_read_by_num(const std::string& name, size_t num, const AxiTransaction*& out) const;
    bool get_read_last(const std::string& name, const AxiTransaction*& out) const;
    bool get_read_by_addr(const std::string& name, uint64_t addr, const char* id_str, const AxiTransaction*& out) const;
    bool get_read_by_addr_num(const std::string& name, uint64_t addr, const char* id_str, size_t num, const AxiTransaction*& out) const;
    bool get_read_by_addr_last(const std::string& name, uint64_t addr, const char* id_str, const AxiTransaction*& out) const;
    bool get_read_by_num(const std::string& name, const char* id_str, size_t num, const AxiTransaction*& out) const;
    bool get_read_last(const std::string& name, const char* id_str, const AxiTransaction*& out) const;

    // Cursor-based traversal
    // filter: 0=all, 1=wr only, 2=rd only
    bool cursor_begin(const std::string& name, int filter, const AxiTransaction*& out);
    bool cursor_next(const std::string& name, int filter, const AxiTransaction*& out);
    bool cursor_prev(const std::string& name, int filter, const AxiTransaction*& out);
    bool cursor_last(const std::string& name, int filter, const AxiTransaction*& out);
    bool cursor_state(const std::string& name, int filter, size_t& one_based_index,
                      size_t& total_count) const;

    // Latency stats helpers
    bool get_latency_stats(const std::string& name, bool is_write,
                           const AxiTransaction*& max_txn,
                           const AxiTransaction*& min_txn,
                           double& avg_latency) const;
    bool get_latency_stats(const std::string& name, int filter, const char* id_str,
                           AxiStatResult& out) const;
    bool get_outstanding_stats(const std::string& name, int filter, const char* id_str,
                               AxiStatResult& out) const;

    bool get_transactions_in_range(const std::string& name,
                                   npiFsdbTime begin,
                                   npiFsdbTime end,
                                   std::vector<AxiContextTransaction>& out,
                                   int max_results = -1) const;
    bool get_latency_outliers_in_range(
        const std::string& name,
        npiFsdbTime begin,
        npiFsdbTime end,
        int direction_filter,
        bool threshold_mode,
        npiFsdbTime threshold,
        std::size_t top_n,
        int max_results,
        std::vector<AxiContextTransaction>& out,
        std::size_t& candidate_count,
        std::size_t& matched_outlier_count) const;
    bool get_by_handshake(const std::string& name,
                          const std::string& channel,
                          npiFsdbTime handshake_time,
                          AxiHandshakeMatch& out) const;

    bool get_outstanding_samples_in_range(const std::string& name,
                                          npiFsdbTime begin,
                                          npiFsdbTime end,
                                          std::vector<AxiOutstandingSample>& out,
                                          int max_results = -1) const;
    bool summarize_outstanding_in_range(const std::string& name,
                                        npiFsdbTime begin,
                                        npiFsdbTime end,
                                        int filter,
                                        int max_change_points,
                                        AxiOutstandingSummary& out) const;

private:
    struct DirectionBucket {
        std::vector<size_t> writes;
        std::vector<size_t> reads;
    };
    using NumericIndex = std::map<uint64_t, DirectionBucket>;
    struct HandshakeIndexEntry {
        npiFsdbTime time = 0;
        bool is_write = false;
        size_t transaction_index = 0;
        size_t beat_index = 0;
        HandshakeIndexEntry() = default;
        HandshakeIndexEntry(npiFsdbTime value_time,
                            bool value_is_write,
                            size_t value_transaction_index,
                            size_t value_beat_index)
            : time(value_time), is_write(value_is_write),
              transaction_index(value_transaction_index),
              beat_index(value_beat_index) {}
    };
    using HandshakeIndex = std::vector<HandshakeIndexEntry>;

    AnalysisRepository* repository_ = nullptr;
    std::string session_id_;
    FsdbIdentity fsdb_identity_;
    std::map<std::string, AnalysisCacheKey> keys_;
    mutable AnalysisCacheError last_cache_error_;

    static bool parse_hex_value(const std::string& hex_str, uint64_t& out);
    static bool id_matches(const std::string& txn_id, const char* id_str);
    AnalysisCacheKey cache_key(const AxiConfig& config) const;
    const AxiResult* get_result_internal(const std::string& name,
                                         std::uint64_t* generation) const;
    const NumericIndex* numeric_index(const std::string& name,
                                      const std::string& kind,
                                      bool record_access = false) const;
    const HandshakeIndex* handshake_index(
        const std::string& name, const std::string& channel) const;
    static std::uint64_t estimate_numeric_index_bytes(const NumericIndex& index);
    static std::uint64_t estimate_handshake_index_bytes(
        const HandshakeIndex& index);
    static std::string cursor_id(const std::string& name, int filter);
    static const AxiTransaction* transaction_at(const AxiResult& result,
                                                int filter,
                                                std::size_t position);
    static std::size_t transaction_count(const AxiResult& result, int filter);
};

} // namespace xdebug_waveform
