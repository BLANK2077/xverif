#pragma once

#include "apb_analyzer.h"
#include "waveform/filter/value_filter.h"
#include "json.hpp"
#include "npi_fsdb.h"

#include <cstdint>
#include <functional>
#include <string>
#include <vector>

namespace xdebug_waveform {

using Json = nlohmann::ordered_json;

struct ApbExportResult {
    std::string name;
    std::string format = "tsv";
    npiFsdbTime begin = 0;
    npiFsdbTime end = 0;
    npiFsdbTime scan_begin = 0;
    npiFsdbTime scan_end = 0;
    std::size_t scanned_transaction_count = 0;
    std::size_t in_range_count = 0;
    std::size_t unresolved_filter_count = 0;
    std::size_t write_count = 0;
    std::size_t read_count = 0;
    std::size_t sample_count = 0;
    std::size_t full_scan_count = 0;
    bool analysis_complete = true;
    bool value_width_complete = true;
    Json width_diagnostics = Json::array();
    std::vector<const ApbTransaction*> transactions;
};

class ApbExporter {
public:
    using Selector = std::function<ValueFilterMatch(const ApbTransaction&)>;
    void build(const std::string& name, const ApbResult& canonical,
               const Selector& selector, npiFsdbTime begin, npiFsdbTime end,
               ApbExportResult& result) const;

    bool write_files(const std::string& output_prefix,
                     npiFsdbFileHandle fsdb,
                     const ApbExportResult& result,
                     std::string& data_path,
                     std::string& meta_path,
                     std::uint64_t& data_bytes,
                     std::string& error) const;
};

Json apb_export_transaction_json(npiFsdbFileHandle fsdb,
                                 const ApbTransaction& transaction);

}  // namespace xdebug_waveform
