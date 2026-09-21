#pragma once

#include "axi_config.h"
#include "axi_transaction_tracker.h"
#include "npi_fsdb.h"
#include "json.hpp"

#include <cstdint>
#include <map>
#include <string>
#include <vector>

namespace xdebug_waveform {

using Json = nlohmann::ordered_json;

struct AxiExportTransaction {
    uint64_t seq = 0;
    bool is_write = false;
    npiFsdbTime addr_time = 0;
    npiFsdbTime first_data_time = 0;
    npiFsdbTime last_data_time = 0;
    npiFsdbTime completion_time = 0;
    std::string id;
    std::string addr;
    std::string len;
    std::string size;
    std::string burst;
    std::string resp;
    size_t beat_count = 0;
    size_t expected_beat_count = 0;
    std::string phase_order;
    bool response_dependency_violation = false;
};

struct AxiExportResult {
    std::string name;
    std::string format;
    npiFsdbTime begin = 0;
    npiFsdbTime end = 0;
    npiFsdbTime scan_begin = 0;
    npiFsdbTime scan_end = 0;
    std::vector<AxiExportTransaction> writes;
    std::vector<AxiExportTransaction> reads;
    std::map<std::string, int> write_count_by_id;
    std::map<std::string, int> read_count_by_id;
    std::map<std::string, int> max_write_outstanding_by_id;
    std::map<std::string, int> max_read_outstanding_by_id;
    int max_total_write_outstanding = 0;
    int max_total_read_outstanding = 0;
    std::map<std::string, int> burst_histogram;
    int beat_count_mismatch_count = 0;
    int incomplete_write_count = 0;
    int incomplete_read_count = 0;
    int reset_cleared_write_count = 0;
    int reset_cleared_read_count = 0;
    int orphan_b_count = 0;
    int orphan_r_beat_count = 0;
    int buffered_w_beat_count = 0;
    int buffered_w_burst_count = 0;
    int orphan_w_beat_count = 0;
    int response_dependency_violation_count = 0;
    size_t sample_count = 0;
    size_t full_scan_count = 0;
    bool analysis_complete = true;
};

class AxiExporter {
public:
    void build(const AxiResult& canonical,
               const AxiConfig& config,
               npiFsdbTime begin,
               npiFsdbTime end,
               AxiExportResult& result) const;

    bool write_files(const std::string& output_prefix,
                     const AxiExportResult& result,
                     std::string& write_file,
                     std::string& read_file,
                     std::string& meta_file,
                     std::string& error) const;
};

Json axi_export_meta_json(const AxiExportResult& result,
                          const std::string& write_file,
                          const std::string& read_file,
                          const std::string& meta_file);

} // namespace xdebug_waveform
