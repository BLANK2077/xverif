#pragma once

#include "npi_fsdb.h"

#include <cstdint>
#include <deque>
#include <map>
#include <string>
#include <vector>

namespace xdebug_waveform {

struct AxiTransaction {
    uint64_t seq = 0;
    npiFsdbTime addr_valid_begin_time = 0;
    npiFsdbTime addr_time = 0;       // AW/AR handshake time
    npiFsdbTime first_data_valid_begin_time = 0;
    npiFsdbTime first_data_time = 0; // first W/R beat handshake time
    npiFsdbTime last_data_time = 0;  // WLAST/RLAST handshake time
    npiFsdbTime resp_time = 0;       // B handshake time or RLAST handshake time
    std::string addr;
    std::string id;
    std::string len;
    std::string size;
    std::string burst;
    std::vector<std::string> data;
    std::vector<std::string> wstrb;
    std::vector<std::string> data_resp;
    std::vector<npiFsdbTime> data_handshake_times;
    std::vector<bool> data_last;
    std::string resp;
    int addr_width = 0;
    int id_width = 0;
    int len_width = 0;
    int size_width = 0;
    int burst_width = 0;
    int data_width = 0;
    int wstrb_width = 0;
    int resp_width = 0;
    std::string addr_signal;
    std::string id_signal;
    std::string len_signal;
    std::string size_signal;
    std::string burst_signal;
    std::string data_signal;
    std::string wstrb_signal;
    std::string resp_signal;
    bool is_write = false;
    bool has_addr_valid_begin_time = false;
    bool has_first_data_valid_begin_time = false;
    bool is_out_of_order = false;
    bool data_complete = false;
    bool response_dependency_violation = false;
    size_t expected_beat_count = 0;
    std::string phase_order;
};

struct AxiOutstandingSample {
    npiFsdbTime time = 0;
    int read = 0;
    int write = 0;
    std::map<std::string, int> read_by_id;
    std::map<std::string, int> write_by_id;
};

struct AxiChannelCounts {
    size_t aw = 0;
    size_t w = 0;
    size_t b = 0;
    size_t ar = 0;
    size_t r = 0;
};

struct AxiDiagnostics {
    AxiChannelCounts handshakes;
    size_t sample_count = 0;
    size_t full_scan_count = 0;
    size_t incomplete_write_count = 0;
    size_t incomplete_read_count = 0;
    size_t buffered_w_beat_count = 0;
    size_t buffered_w_burst_count = 0;
    size_t orphan_w_beat_count = 0;
    size_t orphan_b_count = 0;
    size_t orphan_r_beat_count = 0;
    size_t beat_count_mismatch_count = 0;
    size_t response_dependency_violation_count = 0;
    size_t reset_cleared_write_count = 0;
    size_t reset_cleared_read_count = 0;
    size_t reset_cleared_w_beat_count = 0;
    int final_write_outstanding = 0;
    int final_read_outstanding = 0;
    int max_total_write_outstanding = 0;
    int max_total_read_outstanding = 0;
    std::map<std::string, int> max_write_outstanding_by_id;
    std::map<std::string, int> max_read_outstanding_by_id;
    bool analysis_complete = true;
    npiFsdbTime scan_begin = 0;
    npiFsdbTime scan_end = 0;
};

struct AxiResult {
    std::vector<AxiTransaction> all;
    std::vector<AxiTransaction> writes;
    std::vector<AxiTransaction> reads;
    std::vector<AxiTransaction> pending_writes;
    std::vector<AxiTransaction> pending_reads;
    std::vector<AxiOutstandingSample> outstanding_samples;
    std::vector<size_t> all_by_resp_time;
    AxiDiagnostics diagnostics;
};

struct AxiLatencyOutlierSelection {
    std::vector<const AxiTransaction*> transactions;
    size_t candidate_count = 0;
    size_t matched_outlier_count = 0;
};

struct AxiSample {
    npiFsdbTime time = 0;
    bool reset_active = false;
    bool aw_valid = false;
    bool w_valid = false;
    bool ar_valid = false;
    bool r_valid = false;
    bool aw_handshake = false;
    bool w_handshake = false;
    bool b_handshake = false;
    bool ar_handshake = false;
    bool r_handshake = false;
    bool wlast = false;
    bool rlast = false;
    std::string awaddr;
    std::string awid;
    std::string awlen;
    std::string awsize;
    std::string awburst;
    std::string wdata;
    std::string wstrb;
    std::string bid;
    std::string bresp;
    std::string araddr;
    std::string arid;
    std::string arlen;
    std::string arsize;
    std::string arburst;
    std::string rid;
    std::string rdata;
    std::string rresp;
};

class AxiTransactionTracker {
public:
    void consume(const AxiSample& sample);
    AxiResult finish(npiFsdbTime scan_begin, npiFsdbTime scan_end,
                     bool analysis_complete = true);
    const AxiResult& in_progress_result() const { return result_; }
    std::size_t estimated_working_set_bytes() const;

private:
    struct WBeat {
        npiFsdbTime valid_begin_time = 0;
        npiFsdbTime time = 0;
        bool has_valid_begin_time = false;
        std::string data;
        std::string strb;
        bool last = false;
    };

    void clear_for_reset();
    void drain_w_beats();
    void snapshot(npiFsdbTime time);
    void complete_write(const AxiSample& sample);
    void complete_read(const AxiSample& sample);

    AxiResult result_;
    std::deque<WBeat> w_beats_;
    std::deque<AxiTransaction> pending_writes_;
    std::map<std::string, std::deque<AxiTransaction>> pending_reads_;
    int write_outstanding_ = 0;
    int read_outstanding_ = 0;
    std::map<std::string, int> write_outstanding_by_id_;
    std::map<std::string, int> read_outstanding_by_id_;
    uint64_t next_seq_ = 0;
    npiFsdbTime aw_valid_begin_time_ = 0;
    npiFsdbTime w_valid_begin_time_ = 0;
    npiFsdbTime ar_valid_begin_time_ = 0;
    npiFsdbTime r_valid_begin_time_ = 0;
    bool aw_valid_active_ = false;
    bool w_valid_active_ = false;
    bool ar_valid_active_ = false;
    bool r_valid_active_ = false;
    bool finished_ = false;
};

size_t axi_expected_beats(const std::string& len);
std::string axi_write_phase_order(const AxiTransaction& txn);
AxiLatencyOutlierSelection select_axi_latency_outliers(
    const std::vector<AxiTransaction>& transactions,
    npiFsdbTime begin,
    npiFsdbTime end,
    int direction_filter,
    bool threshold_mode,
    npiFsdbTime threshold,
    size_t top_n,
    size_t retained_limit);

} // namespace xdebug_waveform
