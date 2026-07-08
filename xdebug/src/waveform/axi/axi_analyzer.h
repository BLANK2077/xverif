#pragma once

#include "axi_config.h"
#include <cstdint>
#include "npi_fsdb.h"
#include <string>
#include <vector>
#include <map>

namespace xdebug_waveform {

struct AxiTransaction {
    npiFsdbTime addr_time = 0;       // AW/AR handshake time
    npiFsdbTime first_data_time = 0; // first W/R beat handshake time
    npiFsdbTime last_data_time = 0;  // WLAST / RLAST handshake time
    npiFsdbTime resp_time = 0;       // B handshake time (write) or RLAST time (read)
    std::string addr;
    std::string id;
    std::string len;
    std::string size;
    std::string burst;
    std::vector<std::string> data;   // per-beat data
    std::vector<std::string> wstrb;  // per-beat wstrb (write only)
    std::string resp;
    bool is_write = false;
    bool is_out_of_order = false;
};

struct AxiContextTransaction {
    const AxiTransaction* txn = nullptr;
    npiFsdbTime match_time = 0;
};

struct AxiOutstandingSample {
    npiFsdbTime time = 0;
    int read = 0;
    int write = 0;
    std::map<std::string, int> read_by_id;
    std::map<std::string, int> write_by_id;
};

struct AxiResult {
    std::vector<AxiTransaction> all;
    std::vector<AxiTransaction> writes;
    std::vector<AxiTransaction> reads;
    std::vector<AxiOutstandingSample> outstanding_samples;
    std::vector<size_t> all_by_resp_time;
};

struct AxiCursor {
    size_t all_idx = 0;
    size_t wr_idx = 0;
    size_t rd_idx = 0;
};

struct AxiStatResult {
    double max = 0.0;
    double min = 0.0;
    double avg = 0.0;
    size_t samples = 0;
    const AxiTransaction* max_txn = nullptr;
    const AxiTransaction* min_txn = nullptr;
};

class AxiAnalyzer {
public:
    // Analyze and cache result for the given config name.
    // If already cached, returns cached result.
    bool analyze(const std::string& name, npiFsdbFileHandle file, const AxiConfig& config);

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

    bool get_outstanding_samples_in_range(const std::string& name,
                                          npiFsdbTime begin,
                                          npiFsdbTime end,
                                          std::vector<AxiOutstandingSample>& out,
                                          int max_results = -1) const;

private:
    std::map<std::string, AxiResult> results_;
    std::map<std::string, AxiCursor> cursors_;

    const AxiResult* get_result(const std::string& name) const;
    AxiResult* get_result_mut(const std::string& name);
    AxiCursor* get_cursor_mut(const std::string& name);

    static bool parse_hex_value(const std::string& hex_str, uint64_t& out);
    static bool id_matches(const std::string& txn_id, const char* id_str);
};

} // namespace xdebug_waveform
