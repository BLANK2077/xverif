#pragma once

#include "apb_config.h"
#include <cstdint>
#include "npi_fsdb.h"
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
};

struct ApbContextTransaction {
    const ApbTransaction* txn = nullptr;
};

struct ApbResult {
    std::vector<ApbTransaction> all;
    std::vector<ApbTransaction> writes;
    std::vector<ApbTransaction> reads;
};

struct ApbCursor {
    size_t all_idx = 0;
    size_t wr_idx = 0;
    size_t rd_idx = 0;
};

class ApbAnalyzer {
public:
    // Analyze and cache result for the given config name.
    // If already cached, returns cached result.
    bool analyze(const std::string& name, npiFsdbFileHandle file, const ApbConfig& config);

    // Getters for wr/rd counts
    size_t get_write_count(const std::string& name) const;
    size_t get_read_count(const std::string& name) const;

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

    bool get_transactions_in_range(const std::string& name,
                                   npiFsdbTime begin,
                                   npiFsdbTime end,
                                   std::vector<ApbContextTransaction>& out,
                                   int max_results = -1) const;

private:
    std::map<std::string, ApbResult> results_;
    std::map<std::string, ApbCursor> cursors_;

    const ApbResult* get_result(const std::string& name) const;
    ApbResult* get_result_mut(const std::string& name);
    ApbCursor* get_cursor_mut(const std::string& name);

    static bool parse_hex_value(const std::string& hex_str, uint64_t& out);
};

} // namespace xdebug_waveform
