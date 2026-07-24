#pragma once

#include "apb_config.h"
#include "../cache/analysis_repository.h"
#include "npi_fsdb.h"
#include <cstdint>
#include <string>
#include <vector>
#include <map>

namespace xdebug_waveform {

struct ApbTransaction {
    npiFsdbTime time;
    std::string addr;
    std::string data;
    bool is_write;
    bool has_error = false;
    bool has_numeric_addr = false;
    uint64_t numeric_addr = 0;
    int addr_width = 0;
    int data_width = 0;
    std::string addr_signal;
    std::string data_signal;
};

struct ApbContextTransaction {
    const ApbTransaction* txn = nullptr;
};

struct ApbDiagnostics {
    size_t sample_count = 0;
    size_t full_scan_count = 0;
    bool analysis_complete = true;
    npiFsdbTime scan_begin = 0;
    npiFsdbTime scan_end = 0;
};

struct ApbResult {
    std::vector<const ApbTransaction*> all;
    std::vector<ApbTransaction> writes;
    std::vector<ApbTransaction> reads;
    ApbDiagnostics diagnostics;
};

class ApbAnalyzer {
public:
    void configure_repository(AnalysisRepository* repository,
                              const std::string& session_id,
                              const FsdbIdentity& fsdb_identity);
    bool analyze(const std::string& name, npiFsdbFileHandle file,
                 const ApbConfig& config,
                 AnalysisCacheError* cache_error = nullptr);
    const ApbResult* get_result(const std::string& name) const;
    const AnalysisCacheError& last_cache_error() const { return last_cache_error_; }
    bool ensure_address_index(const std::string& name) const;

    // Getters for wr/rd counts
    size_t get_write_count(const std::string& name) const;
    size_t get_read_count(const std::string& name) const;
    size_t get_count(const std::string& name, int filter) const;
    bool get_by_addr(const std::string& name, int filter, uint64_t addr,
                     const ApbTransaction*& out) const;
    bool get_by_addr_num(const std::string& name, int filter, uint64_t addr,
                         size_t num, const ApbTransaction*& out) const;
    bool get_by_addr_last(const std::string& name, int filter, uint64_t addr,
                          const ApbTransaction*& out) const;
    bool get_by_num(const std::string& name, int filter, size_t num,
                    const ApbTransaction*& out) const;
    bool get_last(const std::string& name, int filter,
                  const ApbTransaction*& out) const;

    // Query write by various filters
    bool get_write_by_addr(const std::string& name, uint64_t addr, const ApbTransaction*& out) const;
    bool get_write_by_addr_num(const std::string& name, uint64_t addr, size_t num, const ApbTransaction*& out) const;
    bool get_write_by_addr_last(const std::string& name, uint64_t addr, const ApbTransaction*& out) const;
    bool get_write_by_num(const std::string& name, size_t num, const ApbTransaction*& out) const;
    bool get_write_last(const std::string& name, const ApbTransaction*& out) const;

    // Query read by various filters (symmetric)
    bool get_read_by_addr(const std::string& name, uint64_t addr, const ApbTransaction*& out) const;
    bool get_read_by_addr_num(const std::string& name, uint64_t addr, size_t num, const ApbTransaction*& out) const;
    bool get_read_by_addr_last(const std::string& name, uint64_t addr, const ApbTransaction*& out) const;
    bool get_read_by_num(const std::string& name, size_t num, const ApbTransaction*& out) const;
    bool get_read_last(const std::string& name, const ApbTransaction*& out) const;

    // Cursor-based traversal
    // filter: 0=all, 1=wr only, 2=rd only
    bool cursor_begin(const std::string& name, int filter, const ApbTransaction*& out);
    bool cursor_next(const std::string& name, int filter, const ApbTransaction*& out);
    bool cursor_prev(const std::string& name, int filter, const ApbTransaction*& out);
    bool cursor_last(const std::string& name, int filter, const ApbTransaction*& out);
    bool cursor_state(const std::string& name, int filter, size_t& one_based_index,
                      size_t& total_count) const;

    bool get_transactions_in_range(const std::string& name,
                                   npiFsdbTime begin,
                                   npiFsdbTime end,
                                   std::vector<ApbContextTransaction>& out,
                                   int max_results = -1) const;

private:
    struct AddressBucket {
        std::vector<size_t> all;
        std::vector<size_t> writes;
        std::vector<size_t> reads;
    };
    using AddressIndex = std::map<uint64_t, AddressBucket>;

    AnalysisRepository* repository_ = nullptr;
    std::string session_id_;
    FsdbIdentity fsdb_identity_;
    std::map<std::string, AnalysisCacheKey> keys_;
    mutable AnalysisCacheError last_cache_error_;

    static bool parse_hex_value(const std::string& hex_str, uint64_t& out);
    AnalysisCacheKey cache_key(const ApbConfig& config) const;
    const ApbResult* get_result_internal(const std::string& name,
                                         std::uint64_t* generation) const;
    const AddressIndex* address_index(const std::string& name,
                                      bool record_access = false) const;
    static std::uint64_t estimate_address_index_bytes(
        const AddressIndex& index);
    static std::string cursor_id(const std::string& name, int filter);
    static size_t transaction_count(const ApbResult& result, int filter);
    static const ApbTransaction* transaction_at(const ApbResult& result,
                                                int filter, size_t index);
};

} // namespace xdebug_waveform
