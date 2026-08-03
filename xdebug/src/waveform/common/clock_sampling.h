#pragma once

#include "npi_fsdb.h"

#include <functional>
#include <map>
#include <string>
#include <vector>

namespace xdebug_waveform {

enum class ClockEdgeKind {
    Posedge,
    Negedge,
    Dual
};

enum class ClockSamplePointKind {
    Before,
    After
};

struct ClockSampleSpec {
    std::string clock;
    ClockEdgeKind edge = ClockEdgeKind::Negedge;
    ClockSamplePointKind sample_point = ClockSamplePointKind::Before;
    bool has_sample_point = false;
};

struct ClockSamplePoint {
    npiFsdbTime edge_time = 0;
    npiFsdbTime sample_time = 0;
    ClockEdgeKind edge_kind = ClockEdgeKind::Negedge;
};

struct ClockSampleSignal {
    ClockSampleSignal() = default;
    ClockSampleSignal(const std::string& alias_,
                      const std::string& path_,
                      npiFsdbSigHandle handle_)
        : alias(alias_), path(path_), handle(handle_) {}
    std::string alias;
    std::string path;
    npiFsdbSigHandle handle = nullptr;
};

struct ClockSample {
    npiFsdbTime time = 0;
    ClockEdgeKind edge_kind = ClockEdgeKind::Negedge;
    std::vector<std::string> values;
};

struct ClockPointSignal {
    ClockPointSignal() = default;
    ClockPointSignal(const std::string& label_,
                     const std::string& path_,
                     npiFsdbSigHandle handle_)
        : label(label_), path(path_), handle(handle_) {}
    std::string label;
    std::string path;
    npiFsdbSigHandle handle = nullptr;
};

struct ClockPointCell {
    std::string status;
    std::string raw_value;
    npiFsdbTime value_time = 0;
    bool has_value_time = false;
};

struct ClockPointRow {
    std::string label;
    std::string path;
    ClockPointCell before;
    ClockPointCell middle;
    ClockPointCell after;
};

struct ClockPointContext {
    npiFsdbTime requested_time = 0;
    bool clock_edge_hit = false;
    ClockEdgeKind clock_edge_kind = ClockEdgeKind::Negedge;
    bool has_clock_edge_kind = false;
    bool target_edge_hit = false;
    npiFsdbTime previous_sample_time = 0;
    bool has_previous_sample_time = false;
    npiFsdbTime next_sample_time = 0;
    bool has_next_sample_time = false;
    bool bracket_complete = false;
};

struct ClockPointResult {
    ClockPointContext context;
    std::vector<ClockPointRow> rows;
    std::vector<ClockPointSignal> signals;
};

const char* clock_edge_kind_text(ClockEdgeKind edge);
const char* clock_sample_point_text(ClockSamplePointKind point);
bool parse_clock_edge_kind(const std::string& text, ClockEdgeKind& edge, std::string& error);
bool parse_clock_sample_point_kind(const std::string& text,
                                   ClockSamplePointKind& point,
                                   std::string& error);
bool clock_edge_transition_matches(ClockEdgeKind requested,
                                   bool old_one,
                                   bool new_one,
                                   ClockEdgeKind* actual = nullptr);
bool normalize_clock_sample_spec(npiFsdbFileHandle fsdb,
                                 ClockSampleSpec& spec,
                                 std::string& error);
bool find_first_clock_sample(npiFsdbFileHandle fsdb,
                             const ClockSampleSpec& spec,
                             npiFsdbTime begin,
                             npiFsdbTime end,
                             ClockSamplePoint& point,
                             std::string& error);
bool resolve_clock_sample_signals(npiFsdbFileHandle fsdb,
                                  const std::vector<std::string>& aliases,
                                  const std::vector<std::string>& paths,
                                  std::vector<ClockSampleSignal>& signals,
                                  std::string& error);
std::map<std::string, std::string> clock_sample_value_map(
    const std::vector<ClockSampleSignal>& signals,
    const std::vector<std::string>& values);

class ClockValueReader {
public:
    static bool read_current(npiFsdbFileHandle fsdb,
                             npiFsdbSigHandle handle,
                             const std::string& path,
                             npiFsdbTime time,
                             npiFsdbValType format,
                             char prefix,
                             ClockPointCell& cell);
    static bool read_before(npiFsdbFileHandle fsdb,
                            npiFsdbSigHandle handle,
                            const std::string& path,
                            npiFsdbTime time,
                            npiFsdbValType format,
                            char prefix,
                            ClockPointCell& cell);
};

class ClockSampleScanner {
public:
    ClockSampleScanner(npiFsdbFileHandle fsdb, const ClockSampleSpec& spec);

    bool scan(const std::vector<ClockSampleSignal>& signals,
              npiFsdbTime begin,
              npiFsdbTime end,
              npiFsdbValType format,
              char prefix,
              int max_samples,
              const std::function<bool(const ClockSample&)>& callback,
              std::string& error,
              int& sample_count,
              bool& truncated) const;

private:
    npiFsdbFileHandle fsdb_ = nullptr;
    ClockSampleSpec spec_;
};

class ClockExpressionSampleScanner {
public:
    ClockExpressionSampleScanner(npiFsdbFileHandle fsdb,
                                 ClockEdgeKind edge,
                                 ClockSamplePointKind sample_point);

    bool scan(const std::vector<ClockSampleSignal>& clock_signals,
              const std::vector<ClockSampleSignal>& sample_signals,
              npiFsdbTime begin,
              npiFsdbTime end,
              npiFsdbValType format,
              char prefix,
              int max_samples,
              const std::function<bool(const std::map<std::string, std::string>&,
                                       bool& known,
                                       bool& one,
                                       std::string& error)>& clock_eval,
              const std::function<bool(const ClockSample&)>& callback,
              std::string& error,
              int& sample_count,
              bool& truncated) const;

private:
    npiFsdbFileHandle fsdb_ = nullptr;
    ClockEdgeKind edge_ = ClockEdgeKind::Negedge;
    ClockSamplePointKind sample_point_ = ClockSamplePointKind::Before;
};

class ClockPointSampler {
public:
    ClockPointSampler(npiFsdbFileHandle fsdb, const ClockSampleSpec& spec);

    bool sample(npiFsdbTime requested_time,
                const std::vector<ClockPointSignal>& signals,
                npiFsdbValType format,
                char prefix,
                ClockPointResult& result,
                std::string& error) const;

private:
    npiFsdbFileHandle fsdb_ = nullptr;
    ClockSampleSpec spec_;
};

class ClockSampleTimeResolver {
public:
    ClockSampleTimeResolver(npiFsdbFileHandle fsdb, const ClockSampleSpec& spec);

    bool valid(std::string& error) const;
    bool is_clock_edge_at(npiFsdbTime time, ClockEdgeKind* edge_kind = nullptr) const;
    bool is_target_edge_at(npiFsdbTime time, ClockEdgeKind* edge_kind = nullptr) const;
    bool find_previous_sample(npiFsdbTime anchor_time,
                              ClockSamplePoint& point,
                              std::string& error) const;
    bool find_next_sample(npiFsdbTime anchor_time,
                          ClockSamplePoint& point,
                          std::string& error) const;
    bool for_each_sample_time(npiFsdbTime begin,
                              npiFsdbTime end,
                              const std::function<bool(const ClockSamplePoint&)>& callback,
                              std::string& error) const;

private:
    bool previous_single_edge_sample(ClockEdgeKind edge,
                                     npiFsdbTime anchor_time,
                                     ClockSamplePoint& point,
                                     std::string& error) const;
    bool next_single_edge_sample(ClockEdgeKind edge,
                                 npiFsdbTime anchor_time,
                                 ClockSamplePoint& point,
                                 std::string& error) const;

    npiFsdbFileHandle fsdb_ = nullptr;
    ClockSampleSpec spec_;
    npiFsdbSigHandle clock_handle_ = nullptr;
};

} // namespace xdebug_waveform
