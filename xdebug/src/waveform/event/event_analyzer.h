#pragma once

#include "event_config.h"
#include "npi_fsdb.h"
#include <map>
#include <string>
#include <vector>

namespace xdebug_waveform {

struct EventRecord {
    npiFsdbTime time = 0;
    std::map<std::string, std::string> signals;
    std::map<std::string, std::string> fields;
    std::map<std::string, int> signal_widths;
    std::map<std::string, int> field_widths;
};

struct EventScanStats {
    int sample_count = 0;
    int matched_count = 0;
    npiFsdbTime first_match_time = 0;
    npiFsdbTime last_match_time = 0;
    bool sample_budget_exhausted = false;
};

struct EventQuery {
    std::string expr;
    npiFsdbTime begin = 0;
    npiFsdbTime end = 0xFFFFFFFFFFFFFFFFULL;
    int limit = -1;
    int max_samples = -1;
    bool fast_find = false;
    bool retain_last_only = false;
    EventScanStats* stats = nullptr;
};

class EventAnalyzer {
public:
    bool analyze(npiFsdbFileHandle file,
                 const EventConfig& config,
                 const EventQuery& query,
                 std::vector<EventRecord>& records,
                 std::string& error);

private:
    bool validate_config(npiFsdbFileHandle file,
                         const EventConfig& config,
                         std::vector<std::string>& ordered_aliases,
                         std::vector<std::string>& ordered_paths,
                         std::string& error);
};

} // namespace xdebug_waveform
